import asyncio
import os
import sys
import json
import httpx
import logging
from typing import List, Dict, Any

# Add project root to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from langchain_text_splitters import MarkdownHeaderTextSplitter
from app.database import async_session
from app.models import DocumentChunk
from sqlalchemy import select

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
EMBED_MODEL = "nomic-embed-text"

async def get_embedding(text: str) -> List[float]:
    """Fetch embedding from local Ollama/LM Studio instance."""
    base_url = OLLAMA_BASE_URL.rstrip('/')
    is_openai = "/v1" in base_url or "1234" in base_url
    
    if is_openai:
        url = f"{base_url}/embeddings" if "/v1" in base_url else f"{base_url}/v1/embeddings"
        payload = {"model": EMBED_MODEL, "input": text}
    else:
        url = f"{base_url}/api/embeddings"
        payload = {"model": EMBED_MODEL, "prompt": text}
        
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        res_data = response.json()
        if is_openai:
            return res_data["data"][0]["embedding"]
        else:
            return res_data["embedding"]

async def ingest_markdown_manual(file_path: str):
    if not os.path.exists(file_path):
        logger.error(f"File not found: {file_path}")
        return

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Phase 1: Hierarchical Splitting
    # We define headers mapping: H1 is Department, H2 is Device Name
    headers_to_split_on = [
        ("#", "department"),
        ("##", "device_name"),
    ]

    markdown_splitter = MarkdownHeaderTextSplitter(headers_to_split_on=headers_to_split_on)
    md_header_splits = markdown_splitter.split_text(content)

    logger.info(f"Split manual into {len(md_header_splits)} hierarchical chunks.")

    async with async_session() as session:
        for chunk in md_header_splits:
            text_content = chunk.page_content
            metadata = chunk.metadata
            
            # Ensure metadata has required fields or defaults
            dept = metadata.get("department", "General")
            device = metadata.get("device_name", "General")
            
            # Phase 2: Metadata Injection
            payload_metadata = {
                "department": dept,
                "device_name": device,
                "chunk_type": "inspection_guidelines",
                "source": os.path.basename(file_path)
            }

            logger.info(f"Processing chunk for Device: {device} in Dept: {dept}")

            # Phase 3: Vectorization
            try:
                embedding = await get_embedding(text_content)
                
                # Phase 4: Storage in pgvector
                db_chunk = DocumentChunk(
                    content=text_content,
                    embedding=embedding,
                    metadata_payload=payload_metadata
                )
                session.add(db_chunk)
                
            except Exception as e:
                logger.error(f"Failed to process chunk: {e}")

        await session.commit()
        logger.info("✅ Ingestion Complete. Manual stored in pgvector.")

if __name__ == "__main__":
    # Sample usage: python ingest_manual.py path/to/manual.md
    target_file = sys.argv[1] if len(sys.argv) > 1 else "manual_sample.md"
    
    # Create a sample file if it doesn't exist for testing
    if not os.path.exists(target_file):
        with open(target_file, "w", encoding="utf-8") as f:
            f.write("""# ICU
## Defibrillator
Inspection Guidelines:
1. Check power cable for any physical damage.
2. Verify battery charge levels are above 90%.
3. Ensure pads are within expiration date.

## Ventilator
Inspection Guidelines:
1. Perform O2 sensor calibration.
2. Check circuit integrity and filters.
3. Test backup battery operation.

# Radiology
## X-Ray Machine
Inspection Guidelines:
1. Verify lead apron availability.
2. Check exposure switch functionality.
3. Inspect collimator alignment.
""")
        logger.info(f"Created sample manual: {target_file}")

    asyncio.run(ingest_markdown_manual(target_file))
