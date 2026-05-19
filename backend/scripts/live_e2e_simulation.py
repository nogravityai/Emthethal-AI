import httpx
import asyncio
import json

BASE_URL = "http://localhost:8000/api/v1"

async def run_live_simulation():
    async with httpx.AsyncClient(timeout=30.0) as client:
        print("🎬 Starting Live E2E Simulation: The 'Sovereign Protocol' Test\n")

        # --- STEP 1: QA Approval ---
        template_id = 2 # The Defibrillator template we just generated
        print(f"🛠️ Step 1: Approving Template ID {template_id}...")
        
        # Using a valid UUID v4
        approval_res = await client.put(
            f"{BASE_URL}/templates/{template_id}/review",
            json={
                "qa_manager_id": "550e8400-e29b-41d4-a716-446655440000", 
                "action": "approve", 
                "review_notes": "Approved for live hospital use."
            }
        )
        if approval_res.status_code == 200:
            print("✅ Template approved and deployed to edge nodes.")
        else:
            print(f"❌ Approval failed: {approval_res.text}")
            return

        # --- STEP 2: Failed Inspection Submission ---
        # We target the device 'SN-DEFIB-990' (ID 1 from seeding)
        device_id = 1
        print(f"\n🕵️ Step 2: Inspector submitting a FAILED inspection for Device {device_id}...")
        inspection_payload = {
            "device_id": device_id,
            "template_id": template_id,
            "inspector_name": "Eng. Ahmed",
            "inspection_data": {
                "cable_check": "fail", # FATAL FAILURE
                "battery_level": 95,
                "pad_check": "pass",
                "emergency_switch_check": "pass"
            }
        }
        
        inspection_res = await client.post(f"{BASE_URL}/inspections/", json=inspection_payload)
        inspection_data = inspection_res.json()
        
        if "log_id" in inspection_data:
            print(f"📩 Inspection submitted. Log ID: {inspection_data['log_id']}")
        else:
            print(f"❌ Inspection submission failed: {inspection_data}")
            return

        # --- STEP 3: Verify Sovereign Interceptor Action ---
        print("\n🛡️ Step 3: Verifying Sovereign Interceptor action...")
        # Give a small delay for background tasks
        await asyncio.sleep(2)
        
        device_res = await client.get(f"{BASE_URL}/devices/{device_id}")
        device_status = device_res.json()["status"]
        
        if device_status == "Frozen":
            print("🚨 ALERT: Sovereign Interceptor detected FATAL failure!")
            print(f"🛑 Device '{device_res.json()['name']}' is now FROZEN and locked.")
        else:
            print(f"⚠️ Warning: Device status is '{device_status}'. Expected 'Frozen'.")

        # --- STEP 4: Executive KPI Impact ---
        print("\n📊 Step 4: Checking Hospital KPI Impact...")
        kpi_res = await client.get(f"{BASE_URL}/kpis/hospital-overview")
        kpis = kpi_res.json()
        
        # Correctly accessing nested metrics from the API response
        metrics = kpis.get("metrics", {})
        icu_impact = metrics.get("icu_impact", {})
        
        print(f"📉 Equipment Failure Rate: {metrics.get('failure_rate', 0)}%")
        print(f"🏥 ICU Capacity Impact: {icu_impact.get('capacity_lost_pct', 0)}% reduction in safety margin")
        print(f"📅 Inspections Today: {metrics.get('total_inspected_today', 0)}")
        
        print("\n✨ Simulation Complete: The loop is closed. Emthethal AI is operational.")

if __name__ == "__main__":
    asyncio.run(run_live_simulation())
