import asyncio
import os
import sys
from sqlalchemy import select

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.database import async_session
from app.models import DocumentChunk

async def check():
    async with async_session() as session:
        stmt = select(DocumentChunk.content).where(
            DocumentChunk.metadata_payload['source'].astext == 'الملف-الطبي-اليمني-الموحد- (1).pdf'
        ).limit(10)
        result = await session.execute(stmt)
        for content in result.scalars():
            print(f"--- CHUNK START ---")
            print(content[:500])
            print(f"--- CHUNK END ---\n")

if __name__ == "__main__":
    asyncio.run(check())
