import asyncio
import sys
import os

# Add the app directory to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.database import async_session
from app.services.batch_orchestrator import orchestrator
from sqlalchemy import select
from app.models import Department, Device

async def run_simulation_ingestion():
    async with async_session() as session:
        print("🧠 Starting AI Ingestion Simulation (Maestro Orchestrator)...")
        
        # Fetch the seeded data
        device_result = await session.execute(select(Device).limit(1))
        device = device_result.scalar_one()
        
        dept_result = await session.execute(select(Department).where(Department.id == device.department_id))
        dept = dept_result.scalar_one()

        # Read the mock manual text
        with open("ahsan_defib_manual.txt", "r", encoding="utf-8") as f:
            raw_text = f.read()

        # Construct the item payload
        item = {
            "raw_text": raw_text,
            "device_id": device.id,
            "device_name": device.name,
            "department_id": dept.id,
            "department_name": dept.name,
            "ahsan_ref_code": dept.ahsan_ref_code
        }

        # Run the Maestro (Correct method name is process_single_item)
        template_id = await orchestrator.process_single_item(db=session, item=item)
        
        print(f"✨ SUCCESS: AI extracted the checklist and stored vectors for '{device.name}'.")
        print(f"📑 Template ID: {template_id} is now in 'Pending_QA_Review' status.")
        print("\nNext Step: Go to the QA Dashboard and Approve this template.")

if __name__ == "__main__":
    asyncio.run(run_simulation_ingestion())
