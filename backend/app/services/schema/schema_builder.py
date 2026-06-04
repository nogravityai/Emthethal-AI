"""
CFIS v5.2 — Schema Builder  [Zone-Aware Rebuild]

Converts ResolvedFields + SemanticZones into a CanonicalDocument.

Algorithm:
  1. Detect form_title zone → CanonicalDocument.title
  2. For each zone → CanonicalSection
       - Find ResolvedFields whose bbox center lies inside zone bbox
       - Classify each field type via FieldTypeClassifier
       - Attach nearby OCR label as field_name
  3. Collect unzoned fields → "Unclassified" fallback section
  4. Fallback (no zones): old flat behavior — all fields in "Main Content"
"""
from typing import List, Optional, Tuple, Any, Dict
import uuid
import logging

from app.services.fusion.models import ResolvedField
from app.services.schema.models import (
    CanonicalDocument, CanonicalPage, CanonicalSection,
    CanonicalField, CanonicalCheckbox, FieldType,
)
from app.services.schema.field_type_classifier import (
    classify_field_type, extract_nearby_label
)

logger = logging.getLogger(__name__)

# Zone types that should be excluded from form exports
_EXCLUDED_ZONE_TYPES = {"section_header", "footer", "form_title"}


# ── Geometry Helpers ───────────────────────────────────────────────────────────

def _bbox_to_list(bbox) -> Optional[List[int]]:
    """Convert BoundingBox object or list to [x1, y1, x2, y2] int list."""
    if bbox is None:
        return None
    if isinstance(bbox, (list, tuple)):
        return [int(v) for v in bbox]
    try:
        return [int(bbox.x1), int(bbox.y1), int(bbox.x2), int(bbox.y2)]
    except AttributeError:
        return None


def _center_inside_zone(field_bbox: List[int], zone_bbox: List[int]) -> bool:
    """True if the center of field_bbox lies inside zone_bbox."""
    if not field_bbox or not zone_bbox:
        return False
    fx1, fy1, fx2, fy2 = field_bbox
    zx1, zy1, zx2, zy2 = zone_bbox
    cx = (fx1 + fx2) / 2
    cy = (fy1 + fy2) / 2
    return zx1 <= cx <= zx2 and zy1 <= cy <= zy2


def _get_zone_bbox(zone: Any) -> Optional[List[int]]:
    """Extract bbox from a zone dict or object."""
    if isinstance(zone, dict):
        raw = zone.get("bbox")
    else:
        raw = getattr(zone, "bbox", None)
    return _bbox_to_list(raw) if raw is not None else None


def _get_zone_attr(zone: Any, key: str, default=None):
    """Get attribute from a zone dict or object."""
    if isinstance(zone, dict):
        return zone.get(key, default)
    return getattr(zone, key, default)


# ── Field Builder ──────────────────────────────────────────────────────────────

def _build_canonical_field(
    rf: ResolvedField,
    zone_id: Optional[str],
    include_in_form: bool,
    ocr_tokens: List,
    corrections: Optional[Dict[str, Any]] = None,
) -> CanonicalField:
    """Build a CanonicalField from a ResolvedField, applying human corrections if any."""
    bbox_list = _bbox_to_list(getattr(rf, "bbox", None))

    # Extract label from nearby OCR tokens
    label = ""
    if ocr_tokens and bbox_list:
        label = extract_nearby_label(ocr_tokens, bbox_list)

    # Fall back to field_id-based name
    field_name = label.strip() or f"Field_{rf.field_id[:8]}"

    # Classify type
    raw_value = str(rf.value or "")
    primitive_hint = getattr(rf, "field_type", None)
    field_type = classify_field_type(raw_value, nearby_label=label, primitive_type=primitive_hint)

    # Apply human corrections if any
    if corrections and rf.field_id in corrections:
        corr = corrections[rf.field_id]
        corr_type = corr.get("corrected_type") or corr.get("type")
        corr_label = corr.get("corrected_label") or corr.get("label")
        if corr_type:
            try:
                field_type = FieldType(corr_type)
            except ValueError:
                pass
        if corr_label:
            field_name = corr_label

    confidence = 0.0
    try:
        confidence = rf.confidence_breakdown.final_score
    except AttributeError:
        pass

    # Special Checkbox construction
    if field_type == FieldType.CHECKBOX:
        val_str = raw_value.strip().lower()
        is_checked = val_str in {"[x]", "[v]", "true", "checked", "yes", "☑", "✓"}
        return CanonicalCheckbox(
            field_id=rf.field_id,
            field_name=field_name,
            value=is_checked,
            confidence_score=confidence,
            provenance_ref=rf.field_id,
            bbox=bbox_list,
            zone_id=zone_id,
            include_in_form=include_in_form,
        )

    return CanonicalField(
        field_id=rf.field_id,
        field_name=field_name,
        value=rf.value,
        confidence_score=confidence,
        field_type=field_type.value if isinstance(field_type, FieldType) else str(field_type),
        provenance_ref=rf.field_id,
        bbox=bbox_list,
        zone_id=zone_id,
        include_in_form=include_in_form,
    )


# ── Main Builder ───────────────────────────────────────────────────────────────

def build_canonical_document(
    document_id: str,
    resolved_fields: List[ResolvedField],
    zones: Optional[List] = None,
    ocr_tokens: Optional[List] = None,
    field_type_corrections: Optional[Dict[str, Any]] = None,
) -> CanonicalDocument:
    """
    Groups ResolvedFields into a zone-aware CanonicalDocument.

    Args:
        document_id:     Unique document identifier.
        resolved_fields: List of ResolvedField from FusionStage.
        zones:           List of zone dicts/objects from TopologyStage.
        ocr_tokens:      List of OCR token objects for label extraction.
        field_type_corrections: Dict of human type/label corrections.

    Returns:
        CanonicalDocument structured by zones.
    """
    ocr_tokens = ocr_tokens or []
    zones = zones or []

    # ── 1. Extract form title from form_title zone ───────────────────────────
    title = "Untitled Form"
    for zone in zones:
        if _get_zone_attr(zone, "zone_type") == "form_title":
            candidate = _get_zone_attr(zone, "zone_label", "")
            if candidate:
                title = candidate
            break

    # ── 2. Build sections from zones ─────────────────────────────────────────
    if zones:
        assigned_field_ids = set()
        sections: List[CanonicalSection] = []

        for zone in zones:
            zone_type = _get_zone_attr(zone, "zone_type", "unknown")

            # form_title zones are not sections — they provide the document title
            if zone_type == "form_title":
                continue

            zone_id   = _get_zone_attr(zone, "zone_id", str(uuid.uuid4()))
            zone_label = _get_zone_attr(zone, "zone_label", zone_id)
            zone_bbox  = _get_zone_bbox(zone)
            include    = zone_type not in _EXCLUDED_ZONE_TYPES
            # Honour explicit include_in_form override if set on the zone
            explicit_include = _get_zone_attr(zone, "include_in_form", None)
            if explicit_include is not None:
                include = explicit_include

            # Find ResolvedFields whose center lies inside this zone
            zone_fields: List[CanonicalField] = []
            for rf in resolved_fields:
                if rf.field_id in assigned_field_ids:
                    continue
                rf_bbox = _bbox_to_list(getattr(rf, "bbox", None))
                if rf_bbox and _center_inside_zone(rf_bbox, zone_bbox or []):
                    cf = _build_canonical_field(rf, zone_id, include, ocr_tokens, corrections=field_type_corrections)
                    zone_fields.append(cf)
                    assigned_field_ids.add(rf.field_id)

            sections.append(CanonicalSection(
                section_id=zone_id,
                title=zone_label,
                zone_type=zone_type,
                include_in_form=include,
                fields=zone_fields,
            ))

        # ── 3. Collect unzoned fields ────────────────────────────────────────
        unzoned = [
            rf for rf in resolved_fields
            if rf.field_id not in assigned_field_ids
        ]
        if unzoned:
            unzoned_fields = [
                _build_canonical_field(rf, None, True, ocr_tokens, corrections=field_type_corrections)
                for rf in unzoned
            ]
            sections.append(CanonicalSection(
                section_id="unzoned_" + str(uuid.uuid4())[:8],
                title="Unclassified Fields",
                zone_type="unknown",
                include_in_form=True,
                fields=unzoned_fields,
            ))

        page = CanonicalPage(page_number=1, sections=sections)

    else:
        # ── Fallback: no zones — flat single section (backward compat) ───────
        logger.warning("build_canonical_document: no zones provided — using flat fallback")
        fields = []
        for rf in resolved_fields:
            # Check corrections
            corr_type = None
            corr_label = None
            if field_type_corrections and rf.field_id in field_type_corrections:
                corr = field_type_corrections[rf.field_id]
                corr_type = corr.get("corrected_type") or corr.get("type")
                corr_label = corr.get("corrected_label") or corr.get("label")

            raw_value = str(rf.value or "").strip().lower()
            field_name = corr_label or f"Field_{rf.field_id[:8]}"

            # Determine type
            ftype = corr_type
            if not ftype:
                if raw_value in ("[x]", "[v]", "checked", "true"):
                    ftype = FieldType.CHECKBOX
                elif raw_value in ("[ ]", "unchecked", "false"):
                    ftype = FieldType.CHECKBOX
                else:
                    ftype = FieldType.TEXT

            if ftype == FieldType.CHECKBOX or ftype == "checkbox":
                is_checked = raw_value in {"[x]", "[v]", "true", "checked", "yes", "☑", "✓"}
                cf = CanonicalCheckbox(
                    field_id=rf.field_id,
                    field_name=field_name,
                    value=is_checked,
                    confidence_score=getattr(rf.confidence_breakdown, "final_score", 0.0),
                    provenance_ref=rf.field_id,
                )
            else:
                cf = CanonicalField(
                    field_id=rf.field_id,
                    field_name=field_name,
                    value=rf.value,
                    confidence_score=getattr(rf.confidence_breakdown, "final_score", 0.0),
                    field_type=ftype.value if isinstance(ftype, FieldType) else str(ftype),
                    provenance_ref=rf.field_id,
                )
            fields.append(cf)

        main_section = CanonicalSection(
            section_id=str(uuid.uuid4()),
            title="Main Content",
            fields=fields,
        )
        page = CanonicalPage(page_number=1, sections=[main_section])

    return CanonicalDocument(
        document_id=document_id,
        title=title,
        pages=[page],
    )
