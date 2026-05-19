import logging
from typing import Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from .llm_extractor import extractor
from .vector_loader import vector_loader
from ..models import ChecklistTemplate, TemplateStatus

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class BatchOrchestrator:
    async def run_batch_ingestion_pipeline(
        self, 
        db: AsyncSession, 
        raw_texts: List[Dict[str, Any]]
    ):
        """
        Processes a list of raw manual texts and their metadata.
        Expected item format: 
        {
            "raw_text": str,
            "device_id": int,
            "device_name": str,
            "department_id": int,
            "department_name": str,
            "ahsan_ref_code": str
        }
        """
        results = []
        for item in raw_texts:
            try:
                template_id = await self.process_single_item(db, item)
                results.append({"status": "success", "device": item['device_name'], "template_id": template_id})
            except Exception as e:
                results.append({"status": "error", "device": item['device_name'], "error": str(e)})
        
        return results

    async def process_single_item(
        self, 
        db: AsyncSession, 
        item: Dict[str, Any]
    ):
        logger.info(f"Starting orchestration for device: {item['device_name']}")

        # 1. Extract structured JSON using llama3:8b-instruct-q4_K_M
        template_data = await extractor.generate_checklist(
            item['device_name'], 
            item['department_name'], 
            item['raw_text']
        )
        
        # 2. Save the template to the relational DB
        db_template = ChecklistTemplate(
            title=template_data['title'],
            department_id=item['department_id'],
            form_schema=template_data['form_schema'],
            criteria=template_data['criteria'],
            status=TemplateStatus.Pending_QA_Review
        )
        db.add(db_template)
        await db.flush()
        
        # 3. Generate embeddings using nomic-embed-text
        metadata = {
            "device_id": item['device_id'],
            "device_name": item['device_name'],
            "department_id": item['department_id'],
            "department_name": item['department_name'],
            "ahsan_ref_code": item['ahsan_ref_code'],
            "template_id": db_template.id
        }
        
        await vector_loader.store_template_vectors(db, template_data, metadata)
        await db.commit()
        
        return db_template.id

# Global instance
orchestrator = BatchOrchestrator()
