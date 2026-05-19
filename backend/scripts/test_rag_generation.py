import httpx
import asyncio
import json

async def test_generation():
    # Inside the container, we call localhost:8000
    url = "http://localhost:8000/api/v1/forms/generate"
    
    payload = {
        "department": "الملف الطبي الموحد",
        "device_name": "General",
        "optional_extra_prompt": "بناءً على معايير أحسن لـ 'جهاز التنفس الصناعي' (Ventilator) المذكورة في النص، قم بتوليد قائمة تحقق JSON تتضمن فحص معايرة الأكسجين وحالة الدوائر التنفسية وفلاتر البكتيريا."
    }
    
    print(f"🚀 Sending Generation Request for: {payload['device_name']} in {payload['department']}...")
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        try:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
            
            print("\n✨ Generation Successful!")
            print(f"📑 Template ID: {data['template_id']}")
            print("\n📦 Generated JSON Schema:")
            print(json.dumps(data['generated_form'], indent=2, ensure_ascii=False))
            
        except Exception as e:
            print(f"❌ Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_generation())
