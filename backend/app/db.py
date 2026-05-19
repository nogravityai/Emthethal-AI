# ============================================================
# CFIS Database Layer
# Location: backend/app/db.py
# Async PostgreSQL via asyncpg.
# ALL functions referenced in router.py are defined here.
# Tables created on startup via init_db().
# ============================================================

from __future__ import annotations
import json
import logging
import os
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

import asyncpg

from app.models.schemas import DocumentOutput, QACorrection, FormField

logger = logging.getLogger(__name__)

_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        dsn = os.environ["DATABASE_URL"]
        if dsn.startswith("postgresql+asyncpg://"):
            dsn = dsn.replace("postgresql+asyncpg://", "postgresql://", 1)
        _pool = await asyncpg.create_pool(
            dsn=dsn,
            min_size=2,
            max_size=10,
            command_timeout=30,
        )
    return _pool


async def init_db() -> None:
    """Create all CFIS tables if they don't exist. Called on startup."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS cfis_documents (
                document_id       TEXT PRIMARY KEY,
                source_file       TEXT NOT NULL,
                processed_at      TIMESTAMPTZ NOT NULL,
                qa_status         TEXT NOT NULL DEFAULT 'pending',
                primary_language  TEXT NOT NULL DEFAULT 'ar',
                total_pages       INTEGER NOT NULL DEFAULT 0,
                qa_issues_count   INTEGER NOT NULL DEFAULT 0,
                failed_pages      JSONB NOT NULL DEFAULT '[]',
                extraction_stats  JSONB NOT NULL DEFAULT '{}',
                approved_at       TIMESTAMPTZ,
                approved_by       TEXT,
                data              JSONB NOT NULL,
                created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS cfis_corrections (
                correction_id  TEXT PRIMARY KEY,
                document_id    TEXT NOT NULL REFERENCES cfis_documents(document_id),
                field_id       TEXT NOT NULL,
                layout_hash    TEXT NOT NULL,
                row_index      INTEGER NOT NULL DEFAULT 0,
                column_index   INTEGER NOT NULL DEFAULT 0,
                page_number    INTEGER NOT NULL DEFAULT 0,
                data           JSONB NOT NULL,
                corrected_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS cfis_formio_schemas (
                document_id  TEXT PRIMARY KEY REFERENCES cfis_documents(document_id),
                schema_json  JSONB NOT NULL,
                generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );

            CREATE TABLE IF NOT EXISTS cfis_page_images (
                document_id  TEXT NOT NULL,
                page_number  INTEGER NOT NULL,
                image_data   BYTEA NOT NULL,
                width_px     INTEGER,
                height_px    INTEGER,
                PRIMARY KEY (document_id, page_number)
            );

            CREATE INDEX IF NOT EXISTS idx_cfis_documents_qa_status
                ON cfis_documents (qa_status);
            CREATE INDEX IF NOT EXISTS idx_cfis_corrections_document_id
                ON cfis_corrections (document_id);
            CREATE INDEX IF NOT EXISTS idx_cfis_corrections_layout_hash
                ON cfis_corrections (layout_hash);
        """)
    logger.info("CFIS database tables initialized.")


async def save_document(doc: DocumentOutput) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO cfis_documents
                (document_id, source_file, processed_at, qa_status,
                 primary_language, total_pages, qa_issues_count, failed_pages,
                 extraction_stats, data)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (document_id) DO UPDATE SET
                qa_status        = EXCLUDED.qa_status,
                qa_issues_count  = EXCLUDED.qa_issues_count,
                failed_pages     = EXCLUDED.failed_pages,
                extraction_stats = EXCLUDED.extraction_stats,
                data             = EXCLUDED.data
        """,
            doc.document_id,
            doc.source_file,
            doc.processed_at,
            doc.qa_status,
            doc.primary_language,
            doc.total_pages,
            doc.qa_issues_count,
            json.dumps(doc.failed_pages),
            json.dumps(doc.extraction_stats),
            doc.model_dump_json(),
        )


async def get_document(document_id: str) -> Optional[DocumentOutput]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT data FROM cfis_documents WHERE document_id = $1",
            document_id,
        )
    if not row:
        return None
    return DocumentOutput.model_validate_json(row["data"])


async def list_documents(qa_status: Optional[str] = None) -> List[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        if qa_status:
            rows = await conn.fetch(
                """SELECT document_id, source_file, qa_status, primary_language,
                          total_pages, qa_issues_count, processed_at
                   FROM cfis_documents WHERE qa_status = $1
                   ORDER BY processed_at DESC LIMIT 200""",
                qa_status,
            )
        else:
            rows = await conn.fetch(
                """SELECT document_id, source_file, qa_status, primary_language,
                          total_pages, qa_issues_count, processed_at
                   FROM cfis_documents
                   ORDER BY processed_at DESC LIMIT 200"""
            )
    return [dict(r) for r in rows]


async def save_correction(correction: QACorrection) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO cfis_corrections
                (correction_id, document_id, field_id, layout_hash,
                 row_index, column_index, page_number, data)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (correction_id) DO UPDATE SET data = EXCLUDED.data
        """,
            correction.correction_id,
            correction.document_id,
            correction.field_id,
            correction.layout_hash,
            correction.row_index,
            correction.column_index,
            correction.page_number,
            correction.model_dump_json(),
        )


async def apply_correction(document_id: str, correction: QACorrection) -> None:
    """
    Apply a QACorrection to the stored DocumentOutput.
    Matches by (row_index, column_index, page_number) — geometric identity, not ephemeral field_id.
    """
    doc = await get_document(document_id)
    if not doc:
        logger.warning(f"apply_correction: document {document_id} not found")
        return

    updated = False
    for field in doc.fields:
        if (field.row_index == correction.row_index
                and field.column_index == correction.column_index
                and field.page_number == correction.page_number):
            if correction.corrected_label:
                field.semantic_label = correction.corrected_label
                field.semantic_label_ar = correction.corrected_label
            if correction.corrected_widget:
                field.runtime_widget = correction.corrected_widget
            if correction.note:
                field.note = correction.note
            field.human_corrected = True
            field.needs_qa = False
            updated = True
            break

    if updated:
        doc.qa_issues_count = sum(1 for f in doc.fields if f.needs_qa)
        await save_document(doc)
    else:
        logger.warning(
            f"apply_correction: no field matched "
            f"(row={correction.row_index}, col={correction.column_index}, "
            f"page={correction.page_number}) in {document_id}"
        )


async def approve_document(document_id: str, approved_by: str = "anonymous") -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            UPDATE cfis_documents
            SET qa_status = 'approved', approved_at = NOW(), approved_by = $2
            WHERE document_id = $1
        """, document_id, approved_by)

    # Also update the cached DocumentOutput
    doc = await get_document(document_id)
    if doc:
        doc.qa_status = "approved"
        doc.approved_at = datetime.now(timezone.utc)
        doc.approved_by = approved_by
        await save_document(doc)


async def save_formio_schema(document_id: str, schema: dict) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO cfis_formio_schemas (document_id, schema_json)
            VALUES ($1, $2)
            ON CONFLICT (document_id) DO UPDATE SET
                schema_json  = EXCLUDED.schema_json,
                generated_at = NOW()
        """, document_id, json.dumps(schema))


async def get_formio_schema(document_id: str) -> Optional[dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT schema_json FROM cfis_formio_schemas WHERE document_id = $1",
            document_id,
        )
    if not row:
        return None
    return json.loads(row["schema_json"])


async def save_page_image(
    document_id: str, page_number: int, image_data: bytes,
    width_px: int, height_px: int
) -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO cfis_page_images
                (document_id, page_number, image_data, width_px, height_px)
            VALUES ($1, $2, $3, $4, $5)
            ON CONFLICT (document_id, page_number) DO UPDATE SET
                image_data = EXCLUDED.image_data,
                width_px   = EXCLUDED.width_px,
                height_px  = EXCLUDED.height_px
        """, document_id, page_number, image_data, width_px, height_px)


async def get_page_image(document_id: str, page_number: int) -> Optional[bytes]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT image_data FROM cfis_page_images WHERE document_id=$1 AND page_number=$2",
            document_id, page_number,
        )
    return bytes(row["image_data"]) if row else None
