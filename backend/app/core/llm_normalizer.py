"""
core/llm_normalizer.py — Emthethal AI
Lightweight AI Layer for KPI Label Normalization.

CRITICAL RULES:
1. The LLM is used ONLY for controlled KPI normalization:
   - Label standardization
   - Synonym mapping (e.g., "infection rate" = "معدل العدوى")
2. The LLM MUST NOT infer structure, layout, relationships, or table logic.
3. All structural understanding comes exclusively from the Geometry Engine
   and native parsers.
4. The LLM is a semantic assistant, NOT a structural parser.
"""

import json
import logging
import os
import re
from typing import Dict, List, Optional, Any

import httpx

from ..ingestion_models.schemas import DocumentOutput, StructureBlock, TableRow, ExtractedCell

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = os.getenv("OLLAMA_URL", "http://ollama:11434")
MODEL_NAME = "llama3:8b-instruct-q4_K_M"

# ─── Known KPI Synonyms (Static Mapping — LLM Supplements This) ──────────────

STATIC_SYNONYM_MAP: Dict[str, str] = {
    # English → Canonical
    "infection rate": "infection_rate",
    "mortality rate": "mortality_rate",
    "hand hygiene compliance": "hand_hygiene_compliance",
    "bed occupancy rate": "bed_occupancy_rate",
    "patient satisfaction": "patient_satisfaction_score",
    "readmission rate": "readmission_rate",
    "medication error rate": "medication_error_rate",
    "fall rate": "fall_rate",
    "pressure ulcer rate": "pressure_ulcer_rate",
    "surgical site infection": "ssi_rate",
    "central line infection": "clabsi_rate",
    "ventilator pneumonia": "vap_rate",
    "catheter infection": "cauti_rate",
    "sterilization compliance": "sterilization_compliance",
    "equipment failure rate": "equipment_failure_rate",
    # Arabic → Canonical
    "معدل العدوى": "infection_rate",
    "معدل الوفيات": "mortality_rate",
    "نظافة اليدين": "hand_hygiene_compliance",
    "نسبة إشغال الأسرة": "bed_occupancy_rate",
    "رضا المرضى": "patient_satisfaction_score",
    "معدل إعادة الدخول": "readmission_rate",
    "أخطاء الأدوية": "medication_error_rate",
    "معدل السقوط": "fall_rate",
    "قرحة الضغط": "pressure_ulcer_rate",
    "عدوى الموقع الجراحي": "ssi_rate",
    "عدوى القسطرة المركزية": "clabsi_rate",
    "التهاب رئوي مرتبط بالتنفس": "vap_rate",
    "عدوى القسطرة البولية": "cauti_rate",
    "امتثال التعقيم": "sterilization_compliance",
    "معدل فشل المعدات": "equipment_failure_rate",
}


# ─── LLM Normalizer ──────────────────────────────────────────────────────────

class LLMNormalizer:
    """
    Normalizes KPI labels and synonyms in extracted data.
    Uses a static mapping first, then LLM for unknown labels.
    NEVER infers structure or layout.
    """

    def __init__(self, base_url: str = OLLAMA_BASE_URL):
        self.api_url = f"{base_url.rstrip('/')}/api/generate"
        self.synonym_cache: Dict[str, str] = dict(STATIC_SYNONYM_MAP)

    async def normalize_document(
        self, doc: DocumentOutput
    ) -> DocumentOutput:
        """
        Normalize all cell values in a DocumentOutput.
        1. Apply static synonym mapping to cell text
        2. For unrecognized labels, batch-query the LLM
        3. Set the `value` field on each cell with the canonical form
        """
        unknown_labels: List[str] = []

        # Pass 1: Apply static mapping, collect unknowns
        for page in doc.pages:
            for block in page.blocks:
                for row in block.rows:
                    for cell in row.cells:
                        normalized = self._static_normalize(cell.text)
                        if normalized:
                            cell.value = normalized
                        elif cell.text.strip() and len(cell.text.strip()) > 2:
                            unknown_labels.append(cell.text.strip())

        # Pass 2: LLM batch normalization for unknowns
        if unknown_labels:
            # Deduplicate
            unique_unknowns = list(set(unknown_labels))[:50]  # Cap at 50

            try:
                llm_mappings = await self._llm_normalize_batch(unique_unknowns)
                # Cache results
                self.synonym_cache.update(llm_mappings)

                # Apply LLM results back to cells
                for page in doc.pages:
                    for block in page.blocks:
                        for row in block.rows:
                            for cell in row.cells:
                                if cell.value is None and cell.text.strip() in llm_mappings:
                                    cell.value = llm_mappings[cell.text.strip()]

            except Exception as e:
                logger.warning(f"LLM normalization failed (non-critical): {e}")
                # Non-critical: document proceeds without LLM normalization

        return doc

    def _static_normalize(self, text: str) -> Optional[str]:
        """Apply static synonym mapping (case-insensitive)."""
        clean = text.strip().lower()
        # Exact match
        if clean in self.synonym_cache:
            return self.synonym_cache[clean]
        # Partial match (text contains a known synonym)
        for synonym, canonical in self.synonym_cache.items():
            if synonym.lower() in clean:
                return canonical
        return None

    async def _llm_normalize_batch(
        self, labels: List[str]
    ) -> Dict[str, str]:
        """
        Use LLM ONLY for label standardization.
        The prompt is strictly constrained to prevent structural inference.
        """
        labels_text = "\n".join(f"- {label}" for label in labels)

        system_prompt = """You are a medical terminology standardization assistant.
Your ONLY job is to map medical/healthcare labels to their canonical English key form.

RULES:
1. ONLY standardize label names (e.g., "معدل العدوى" → "infection_rate")
2. Return snake_case canonical keys
3. DO NOT infer any table structure, layout, or relationships
4. DO NOT add information that is not in the input
5. If you cannot confidently map a label, return it as-is in snake_case
6. Output ONLY valid JSON

OUTPUT FORMAT:
{"original_label": "canonical_key", ...}"""

        user_prompt = f"""Standardize these medical/healthcare labels to canonical snake_case keys:

{labels_text}

Return a JSON mapping of each label to its canonical form."""

        payload = {
            "model": MODEL_NAME,
            "system": system_prompt,
            "prompt": user_prompt,
            "stream": False,
            "format": "json",
            "options": {
                "num_ctx": 4096,
                "temperature": 0.05,  # Near-deterministic for standardization
                "num_predict": 2048,
            },
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            try:
                response = await client.post(self.api_url, json=payload)
                response.raise_for_status()
                raw = response.json().get("response", "{}")

                mappings = json.loads(raw)
                if isinstance(mappings, dict):
                    # Validate: only string→string mappings
                    result = {}
                    for k, v in mappings.items():
                        if isinstance(k, str) and isinstance(v, str):
                            result[k.strip()] = v.strip()
                    logger.info(f"LLM normalized {len(result)} labels")
                    return result
                else:
                    logger.warning("LLM returned non-dict response for normalization")
                    return {}

            except json.JSONDecodeError:
                logger.warning("LLM returned invalid JSON for normalization")
                return {}
            except Exception as e:
                logger.error(f"LLM normalization request failed: {e}")
                raise

    async def normalize_single(self, text: str) -> str:
        """Normalize a single label. Uses cache first, then LLM."""
        cached = self._static_normalize(text)
        if cached:
            return cached

        try:
            mappings = await self._llm_normalize_batch([text])
            return mappings.get(text.strip(), text.strip())
        except Exception:
            return text.strip()


# ─── Module-Level Instance ────────────────────────────────────────────────────

llm_normalizer = LLMNormalizer()
