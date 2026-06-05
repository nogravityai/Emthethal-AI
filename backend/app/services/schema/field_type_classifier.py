"""
CFIS v5.2 — Field Type Classifier

Rule-based intelligent field type detection.
Analyzes OCR text + nearby label hints + spatial context to determine
the semantic FieldType of a resolved field.

Mirror: frontend/src/workbench/services/fieldTypeDetector.js
Both must implement identical classification logic.
"""
import re
from typing import Optional, List

from app.services.schema.models import FieldType

# ── Patterns ───────────────────────────────────────────────────────────────────
_DATE_RE   = re.compile(r'\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}')
_EMAIL_RE  = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
_PHONE_RE  = re.compile(r'[\+]?[\d\s\-\(\)]{8,15}$')
_NUM_RE    = re.compile(r'^\d+([.,]\d+)?$')

# ── Arabic Normalization ───────────────────────────────────────────────────────
def _normalize_arabic(text: str) -> str:
    """
    Normalize Arabic text for robust hint matching:
    1. Remove diacritics and tatweel.
    2. Normalize Alif forms (أ إ آ ٱ → ا).
    3. Normalize Taa Marbuta (ة → ه).
    """
    text = re.sub(r'[\u064B-\u065F\u0670\u0640]', '', text)
    text = re.sub(r'[أإآٱ]', 'ا', text)
    text = text.replace('ة', 'ه')
    return text


# ── Keyword Sets ───────────────────────────────────────────────────────────────
_CHECKBOX_CHARS = {'☑', '☐', '□', '✓', '✗'}
_CHECKBOX_TEXTS = {'[x]', '[X]', '[v]', '[V]', '[ ]'}

_DATE_HINTS    = {'تاريخ', 'date', 'يوم', 'شهر', 'سنة', 'birth', 'ميلاد', 'التاريخ', 'yy', 'yyyy'}
_NAME_HINTS    = {'اسم', 'الاسم', 'المريض', 'الطبيب', 'المراجع', 'name', 'patient', 'doctor'}
_HEADER_HINTS  = {'القسم', 'قسم', 'section', 'معلومات', 'information', 'بيانات', 'data'}
_PHONE_HINTS   = {'هاتف', 'جوال', 'phone', 'mobile', 'tel', 'رقم الهاتف'}
_EMAIL_HINTS   = {'بريد', 'email', 'إيميل', 'ايميل'}
_SIG_HINTS     = {'توقيع', 'signature', 'ختم', 'stamp', 'الإمضاء'}
_DROPDOWN_HINTS = {'اختر', 'select', 'choose', 'قائمة', 'dropdown'}

# Numeric field label hints (pre-normalized for fast matching)
_NUM_HINTS_RAW = {'عمر', 'عدد', 'رقم', 'سن', 'العمر', 'عمره', 'عمرها'}
_NUM_HINTS = {_normalize_arabic(h) for h in _NUM_HINTS_RAW}


def classify_field_type(
    text: str,
    nearby_label: str = "",
    primitive_type: Optional[str] = None,
) -> str:
    """
    Determine the FieldType for a resolved field.

    Args:
        text:          The raw OCR value / field content.
        nearby_label:  The closest label token (from adjacent OCR tokens).
        primitive_type: hint from the fusion/topology stage (optional).

    Returns:
        FieldType enum value (string).
    """
    t = (text or "").strip()
    t_lower = t.lower()
    label = (nearby_label or "").strip().lower()
    combined = f"{t_lower} {label}"
    # Normalize Arabic for hint matching
    normalized_label = _normalize_arabic(label)

    # ── 1. Checkbox — highest priority (visual indicators) ───────────────────
    if any(ch in t for ch in _CHECKBOX_CHARS):
        return FieldType.CHECKBOX
    if any(tx in t for tx in _CHECKBOX_TEXTS):
        return FieldType.CHECKBOX

    # ── 2. Date — value or label match ──────────────────────────────────────
    if _DATE_RE.search(t):
        return FieldType.DATE
    if any(hint in combined for hint in _DATE_HINTS):
        return FieldType.DATE

    # ── 3. Email ─────────────────────────────────────────────────────────────
    if _EMAIL_RE.search(t):
        return FieldType.EMAIL
    if any(hint in combined for hint in _EMAIL_HINTS):
        return FieldType.EMAIL

    # ── 4. Phone ─────────────────────────────────────────────────────────────
    if t and _PHONE_RE.match(t) and len(re.sub(r'\D', '', t)) >= 7:
        return FieldType.PHONE
    if any(hint in combined for hint in _PHONE_HINTS):
        return FieldType.PHONE

    # ── 5. Signature ─────────────────────────────────────────────────────────
    if any(hint in combined for hint in _SIG_HINTS):
        return FieldType.SIGNATURE

    # ── 6. Dropdown / Select ─────────────────────────────────────────────────
    if any(hint in combined for hint in _DROPDOWN_HINTS):
        return FieldType.DROPDOWN

    # ── 7. Name ──────────────────────────────────────────────────────────────
    if any(hint in combined for hint in _NAME_HINTS):
        return FieldType.NAME

    # ── 8. Section Header (short text, no value, label matches) ─────────────
    if len(t.split()) <= 5 and any(hint in combined for hint in _HEADER_HINTS):
        return FieldType.HEADER

    # ── 9. Pure Number ────────────────────────────────────────────────────────
    if t and _NUM_RE.match(t):
        return FieldType.NUMBER

    # ── 9b. Number inferred from label when field is empty ──────────────────
    if not t and any(hint in normalized_label for hint in _NUM_HINTS):
        return FieldType.NUMBER

    # ── 10. Propagate primitive_type hint from topology ──────────────────────
    if primitive_type:
        pl = primitive_type.lower()
        if pl in ("checkbox", "check"):   return FieldType.CHECKBOX
        if pl == "date":                  return FieldType.DATE
        if pl in ("radio", "select"):     return FieldType.RADIO
        if pl == "signature":             return FieldType.SIGNATURE

    # ── Default ───────────────────────────────────────────────────────────────
    return FieldType.TEXT


def extract_nearby_label(
    ocr_tokens: List,
    field_bbox: list,
    max_y_gap: int = 35,
    max_above: int = 80,
) -> str:
    """
    Find the closest OCR label token to a field bbox.
    For Arabic/RTL forms, the label is typically to the right of the value.

    Args:
        ocr_tokens:  List of OCR token objects with .bbox and .text
        field_bbox:  [x1, y1, x2, y2] of the field region
        max_y_gap:   Max vertical distance (pixels) to consider same row

    Returns:
        Combined text of the closest label token(s).
    """
    if not ocr_tokens or not field_bbox:
        return ""

    fx1, fy1, fx2, fy2 = field_bbox
    f_cy = (fy1 + fy2) / 2

    candidates = []
    for tok in ocr_tokens:
        bx1, by1, bx2, by2 = (
            tok.bbox.x1, tok.bbox.y1, tok.bbox.x2, tok.bbox.y2
        ) if hasattr(tok.bbox, 'x1') else tok.bbox

        t_cy = (by1 + by2) / 2
        tok_text = tok.text if hasattr(tok, 'text') else ""

        if abs(t_cy - f_cy) <= max_y_gap:
            # Same-row candidate — handled below in the existing logic
            pass
        elif fy1 >= by2 and (fy1 - by2) <= max_above:
            # Column-header: label is directly above the field with horizontal overlap
            h_overlap = max(0, min(fx2, bx2) - max(fx1, bx1))
            if h_overlap > 0:
                dist = fy1 - by2
                candidates.append((dist + 1000, tok_text))  # lower priority than same-row
            continue
        else:
            continue

        # Prefer tokens to the RIGHT (Arabic label convention)
        if bx1 > fx2:
            dist = bx1 - fx2
        elif bx2 < fx1:
            dist = fx1 - bx2
        else:
            continue  # overlapping — skip

        candidates.append((dist, tok.text if hasattr(tok, 'text') else ""))

    if not candidates:
        return ""

    # Sort by distance and take the two closest
    candidates.sort(key=lambda x: x[0])
    return " ".join(t for _, t in candidates[:2])
