import asyncio
import sys
import os

# Add the app directory to sys.path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.database import async_session
from app.models import Department, Device, DeviceStatus
from sqlalchemy import select

async def seed_demo_data():
    async with async_session() as session:
        print("🚀 Seeding Foundation Data for Emthethal AI Demo...")

        # 1. Check if Department exists
        stmt = select(Department).where(Department.ahsan_ref_code == "AHSAN-DEPT-001")
        result = await session.execute(stmt)
        icu = result.scalar_one_or_none()

        if not icu:
            icu = Department(
                name="العناية المركزة (ICU)",
                ahsan_ref_code="AHSAN-DEPT-001"
            )
            session.add(icu)
            await session.flush()
            print(f"✅ Created Department: {icu.name}")
        else:
            print(f"ℹ️ Department '{icu.name}' already exists.")

        # 2. Check if Device exists
        stmt = select(Device).where(Device.serial_number == "SN-DEFIB-990")
        result = await session.execute(stmt)
        defibrillator = result.scalar_one_or_none()

        if not defibrillator:
            defibrillator = Device(
                name="جهاز صدمات قلبية (Zoll R Series)",
                serial_number="SN-DEFIB-990",
                department_id=icu.id,
                is_life_support=True,
                status=DeviceStatus.Active
            )
            session.add(defibrillator)
            await session.commit()
            print(f"✅ Created Device: {defibrillator.name}")
        else:
            print(f"ℹ️ Device '{defibrillator.name}' already exists.")
        
        # 3. Always rewrite the Mock Ahsan Text for Ingestion (to ensure it's on the host volume)
        ahsan_text = """
        دليل أحسن - المعايير الوطنية للسلامة (الرعاية المركزة):
        جهاز الصدمات الكهربائية (Defibrillator):
        1. فحص كابل الطاقة (Power Cable): يجب أن يكون الكابل سليماً ولا يحتوي على أي قطع أو تعرية. (بند حرج جداً - Fatal).
        2. فحص الأقطاب (Pads/Paddles): يجب التأكد من تاريخ الصلاحية ووجود الجل الموصل.
        3. اختبار التفريغ (Discharge Test): يجب إجراء اختبار تفريغ يومي للتأكد من قدرة الجهاز على إعطاء الصدمة. (بند حرج - Fatal).
        4. شحن البطارية: يجب أن يظهر مؤشر البطارية حالة الشحن الكامل.
        """
        
        # Save this text to a temporary file
        with open("ahsan_defib_manual.txt", "w", encoding="utf-8") as f:
            f.write(ahsan_text)
        
        print("📄 Mock Ahsan Manual saved/updated in 'ahsan_defib_manual.txt'.")
        print("\nReady for Step 2: Running the Batch Ingestion Pipeline.")

if __name__ == "__main__":
    asyncio.run(seed_demo_data())
