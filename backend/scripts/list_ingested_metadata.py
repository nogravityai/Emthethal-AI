import asyncio
import os
import sys
from sqlalchemy import select, func

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.database import async_session
from app.models import DocumentChunk

async def list_sources():
    async with async_session() as session:
        # Get unique source and device_name pairs
        stmt = select(
            DocumentChunk.metadata_payload['source'].astext.label('source'),
            DocumentChunk.metadata_payload['department'].astext.label('dept'),
            DocumentChunk.metadata_payload['device_name'].astext.label('device')
        ).distinct()
        
        result = await session.execute(stmt)
        rows = result.all()
        
        print(f"{'Source':<40} | {'Dept':<20} | {'Device':<20}")
        print("-" * 85)
        for row in rows:
            print(f"{str(row.source):<40} | {str(row.dept):<20} | {str(row.device):<20}")

if __name__ == "__main__":
    asyncio.run(list_sources())
