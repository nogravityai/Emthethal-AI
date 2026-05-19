"""
extract_structure.py — Emthethal AI
Queries pgvector and extracts the full document structure:
  { department → { device_name → [form_types] } }
Writes output to ingestion_queue/structure.json for the frontend dropdown.
Usage: docker exec -it emthethal_backend python scripts/extract_structure.py
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from collections import defaultdict

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import select
from app.database import async_session
from app.models import DocumentChunk

OUTPUT_PATH = Path(__file__).parent.parent / "ingestion_queue" / "structure.json"


async def extract():
    print("🔍 Querying vector DB for document structure...\n")

    async with async_session() as session:
        result = await session.execute(
            select(
                DocumentChunk.metadata_payload['department'].astext.label('dept'),
                DocumentChunk.metadata_payload['device_name'].astext.label('device'),
                DocumentChunk.metadata_payload['form_type'].astext.label('form_type'),
                DocumentChunk.metadata_payload['source'].astext.label('source'),
            ).distinct()
        )
        rows = result.all()

    # Build nested structure
    # structure[dept][device] = { form_types: set, sources: set }
    structure = defaultdict(lambda: defaultdict(lambda: {"form_types": set(), "sources": set()}))

    for row in rows:
        dept      = row.dept      or "General"
        device    = row.device    or "General"
        form_type = row.form_type or "General"
        source    = row.source    or "unknown"

        if dept in ("None", "null"):
            continue

        structure[dept][device]["form_types"].add(form_type)
        structure[dept][device]["sources"].add(source)

    # Convert sets → sorted lists for JSON serialization
    output = {}
    for dept, devices in sorted(structure.items()):
        output[dept] = {}
        for device, meta in sorted(devices.items()):
            output[dept][device] = {
                "form_types": sorted(meta["form_types"]),
                "sources": sorted(meta["sources"]),
            }

    # Print summary
    print(f"{'Department':<30} {'Device':<30} {'Form Types'}")
    print("-" * 85)
    total_form_types = 0
    for dept, devices in output.items():
        for device, meta in devices.items():
            for ft in meta["form_types"]:
                print(f"{dept:<30} {device:<30} {ft}")
                total_form_types += 1

    print(f"\n📊 Total: {len(output)} departments | {sum(len(v) for v in output.values())} devices | {total_form_types} form types")

    # Save JSON
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ Structure saved to: {OUTPUT_PATH}")
    return output


if __name__ == "__main__":
    asyncio.run(extract())
