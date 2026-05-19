"""
tasks/analytics_task.py — Emthethal AI
========================================
RQ worker task: KPI analytics recomputation.

Triggered after:
  - Every new InspectionLog submission
  - On schedule (daily summary)
  - Manually via /api/v1/avni/sync/trigger (analytics variant)

Computes and caches:
  - Pass/fail rates by department + device (rolling 30 days)
  - Fatal failure frequency by criteria key
  - Submission volume by source
  - Schema version distribution across submissions

Rule: Analytics are read-only queries. No business decisions here.
      Results stored in analytics_cache table (to be added) or Redis cache.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict

logger = logging.getLogger(__name__)


def refresh_kpi_analytics() -> Dict[str, Any]:
    """
    Recompute KPI analytics from inspection_logs.
    Uses synchronous DB access (psycopg2) since this runs in an RQ worker.

    Returns a summary dict written to Redis for status polling.
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    sync_url = os.getenv("DATABASE_URL", "").replace("+asyncpg", "")
    engine   = create_engine(sync_url)
    Session  = sessionmaker(bind=engine)

    results: Dict[str, Any] = {"computed_at": datetime.utcnow().isoformat()}

    with Session() as session:

        # ── 1. Overall pass/fail rates (last 30 days) ─────────────────────────
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        total_q = session.execute(text("""
            SELECT COUNT(*) as total,
                   SUM(CASE WHEN has_fatal_failure THEN 1 ELSE 0 END) as fatal_count
            FROM inspection_logs
            WHERE created_at >= :since
        """), {"since": thirty_days_ago}).fetchone()

        total       = total_q.total or 0
        fatal_count = total_q.fatal_count or 0
        results["last_30_days"] = {
            "total_submissions": total,
            "fatal_failures":    fatal_count,
            "pass_rate":         round((total - fatal_count) / total, 4) if total else 0.0,
        }

        # ── 2. Submission breakdown by source ──────────────────────────────────
        source_rows = session.execute(text("""
            SELECT submission_source, COUNT(*) as cnt
            FROM inspection_logs
            WHERE created_at >= :since
            GROUP BY submission_source
        """), {"since": thirty_days_ago}).fetchall()

        results["by_source"] = {r.submission_source: r.cnt for r in source_rows}

        # ── 3. Schema version distribution ────────────────────────────────────
        version_rows = session.execute(text("""
            SELECT schema_version, COUNT(*) as cnt
            FROM inspection_logs
            WHERE schema_version IS NOT NULL
            GROUP BY schema_version
            ORDER BY cnt DESC
        """)).fetchall()

        results["schema_versions"] = {r.schema_version: r.cnt for r in version_rows}

        # ── 4. Top failing criteria (across all submissions) ──────────────────
        # inspection_data is JSONB: {criteria_key: "pass"/"fail"}
        # This query extracts key-value pairs and counts failures
        failing_rows = session.execute(text("""
            SELECT key, COUNT(*) as fail_count
            FROM inspection_logs,
                 jsonb_each_text(inspection_data) AS d(key, value)
            WHERE value = 'fail'
              AND created_at >= :since
            GROUP BY key
            ORDER BY fail_count DESC
            LIMIT 10
        """), {"since": thirty_days_ago}).fetchall()

        results["top_failing_criteria"] = [
            {"key": r.key, "fail_count": r.fail_count}
            for r in failing_rows
        ]


    logger.info(
        f"[analytics] Refreshed: total={results['last_30_days']['total_submissions']} "
        f"fatal={results['last_30_days']['fatal_failures']} "
        f"pass_rate={results['last_30_days']['pass_rate']:.1%}"
    )
    return results
