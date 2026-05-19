import httpx
import json
import logging
import os
import re
import hashlib
from typing import Dict, Any
from ..schemas import AIGeneratedTemplate

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
MODEL_NAME = "llama3:8b-instruct-q4_K_M"

# ─── Prompt ───────────────────────────────────────────────────────────────────

def build_system_prompt(device_name: str, department: str) -> str:
    return f"""You are a medical compliance expert building an inspection checklist for "{device_name}" in the "{department}" department.

TASK: Read the REFERENCE TEXT and extract ALL items. 
Distinguish between "Inspection Checks" and "Data Fields".

FIELD TYPES:
1. "radio": Use for items that need verification (Pass/Fail). Example: "Is the site marked?", "Consent obtained?".
2. "textfield": Use for items that require data entry. Example: "Patient Name", "Age", "Physician Notes", "Serial Number".

OUTPUT FORMAT (strict JSON):
{{
  "title": "{device_name} Inspection Checklist",
  "form_schema": {{
    "display": "form",
    "components": [
      {{
        "type": "textfield", 
        "key": "patient_name", 
        "label": "Patient Name", 
        "placeholder": "Enter name..."
      }},
      {{
        "type": "radio", 
        "key": "consent_check", 
        "label": "Is consent signed?", 
        "values": [{{"label": "Pass", "value": "pass"}}, {{"label": "Fail", "value": "fail"}}]
      }}
    ]
  }},
  "criteria": [
    {{"key": "consent_check", "label": "Is consent signed?", "is_fatal": true}}
  ]
}}

STRICT RULES:
1. Extract ALL fields found in the text. Minimum 10 items.
2. Use "textfield" for ANY field that isn't a simple yes/no or pass/fail check.
3. Mark is_fatal=true ONLY for critical safety/life-support checks. Data fields are NEVER fatal.
4. Output ONLY JSON."""


def build_user_prompt(device_name: str, department: str, raw_text: str, extra: str = "") -> str:
    prompt = f"""REFERENCE TEXT (extract ALL fields from this):
---
{raw_text}
---

Generate a comprehensive inspection checklist for "{device_name}" covering EVERY item in the reference text above."""
    if extra:
        prompt += f"\n\nAdditional focus: {extra}"
    return prompt


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _slug(text: str) -> str:
    text = re.sub(r'[^a-zA-Z0-9\u0600-\u06FF]+', '_', text.lower())
    h = hashlib.md5(text.encode()).hexdigest()[:4]
    return (text[:30].strip('_') or h) + '_' + h


def _find_canonical(obj) -> dict | None:
    if isinstance(obj, dict):
        if all(k in obj for k in ["title", "form_schema", "criteria"]):
            return obj
        for v in obj.values():
            found = _find_canonical(v)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_canonical(item)
            if found:
                return found
    return None


def _build_from_any(data: dict, device_name: str, department: str) -> dict:
    """Harvest any label-like strings from whatever structure the LLM returned."""
    labels = []

    def harvest(obj, depth=0):
        if depth > 6:
            return
        if isinstance(obj, dict):
            for key in ("label", "name", "title", "check", "item", "field", "description", "text"):
                val = obj.get(key)
                if isinstance(val, str) and 3 < len(val) < 120:
                    fatal = bool(obj.get("is_fatal") or obj.get("fatal") or obj.get("critical") or obj.get("required"))
                    labels.append((val, fatal))
            for v in obj.values():
                harvest(v, depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                harvest(item, depth + 1)
        elif isinstance(obj, str) and 3 < len(obj) < 120 and obj not in ("pass", "fail", "Pass", "Fail"):
            labels.append((obj, False))

    harvest(data)

    # Deduplicate preserving order
    seen, unique = set(), []
    for label, fatal in labels:
        if label not in seen:
            seen.add(label)
            unique.append((label, fatal))

    if not unique:
        unique = [("General safety check", False), ("Documentation completeness", False)]

    components, criteria = [], []
    for label, fatal in unique:
        key = _slug(label)
        components.append({
            "type": "radio", "key": key, "label": label,
            "values": [{"label": "Pass", "value": "pass"}, {"label": "Fail", "value": "fail"}]
        })
        criteria.append({"key": key, "label": label, "is_fatal": fatal})

    return {
        "title": f"{device_name} Inspection Checklist — {department}",
        "form_schema": {"display": "form", "components": components},
        "criteria": criteria,
    }


def _ensure_unique_keys(data: dict) -> dict:
    """Fix duplicate keys in form_schema.components and align criteria."""
    components = data.get("form_schema", {}).get("components", [])
    seen_keys: dict[str, int] = {}
    for comp in components:
        k = comp.get("key", "item")
        if k in seen_keys:
            seen_keys[k] += 1
            comp["key"] = f"{k}_{seen_keys[k]}"
        else:
            seen_keys[k] = 0

    # Re-align criteria keys to components
    comp_map = {c["label"]: c["key"] for c in components}
    for crit in data.get("criteria", []):
        if crit["label"] in comp_map:
            crit["key"] = comp_map[crit["label"]]

    return data


# ─── LLM Extractor ────────────────────────────────────────────────────────────

class LLMExtractor:
    def __init__(self, base_url: str = OLLAMA_BASE_URL):
        self.api_url = f"{base_url.rstrip('/')}/api/generate"

    async def generate_checklist(
        self, device_name: str, department_name: str, raw_text: str = ""
    ) -> Dict[str, Any]:

        payload = {
            "model": MODEL_NAME,
            "system": build_system_prompt(device_name, department_name),
            "prompt": build_user_prompt(device_name, department_name, raw_text[:3500]),
            "stream": False,
            "format": "json",
            "options": {
                "num_ctx": 8192,
                "temperature": 0.1,   # low temperature = more deterministic/faithful
                "num_predict": 4096,  # allow longer output for comprehensive lists
            },
        }

        logger.info(f"Generating checklist: device='{device_name}' dept='{department_name}' context={len(raw_text)} chars")

        async with httpx.AsyncClient(timeout=180.0) as client:
            response = await client.post(self.api_url, json=payload)
            response.raise_for_status()
            raw = response.json().get("response", "{}")

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Try to extract JSON from within the response
            match = re.search(r'\{.*\}', raw, re.DOTALL)
            if match:
                data = json.loads(match.group())
            else:
                logger.error("Could not parse JSON from LLM response")
                raise ValueError("Invalid JSON from LLM")

        # Stage 1: try canonical structure
        canonical = _find_canonical(data)
        if canonical:
            components = canonical.get("form_schema", {}).get("components", [])
            logger.info(f"✅ Canonical structure found with {len(components)} components")
            data = canonical
        else:
            logger.warning("⚠️ Non-standard LLM output — applying fallback harvester")
            data = _build_from_any(data, device_name, department_name)

        # Stage 2: fix duplicate keys
        data = _ensure_unique_keys(data)

        # Stage 3: inject submit button
        components = data["form_schema"]["components"]
        if not any(c.get("type") == "button" and c.get("action") == "submit" for c in components):
            components.append({
                "type": "button", "label": "Submit Inspection / إرسال التفتيش",
                "key": "submit_btn", "size": "md", "block": True,
                "action": "submit", "disableOnInvalid": True, "theme": "primary"
            })

        validated = AIGeneratedTemplate(**data)
        result = validated.model_dump()
        logger.info(f"✅ Final checklist: {len(result['criteria'])} checks, {sum(1 for c in result['criteria'] if c['is_fatal'])} critical")
        return result


# Global instance
extractor = LLMExtractor()
