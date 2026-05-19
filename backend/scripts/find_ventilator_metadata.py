import asyncio
import os
import sys
from sqlalchemy import select

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.database import async_session
from app.models import DocumentChunk

async def check():
    async with async_session() as session:
        stmt = select(DocumentChunk).where(
            DocumentChunk.content.like('%جهاز التنفس الصناعي%')
        )
        result = await session.execute(stmt)
        for chunk in result.scalars():
            print(f"Metadata: {chunk.metadata_payload}")
            print(f"Content: {chunk.content[:100]}...")
            print("-" * 20)

if __name__ == "__main__":
    asyncio.run(check())
