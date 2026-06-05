from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional, Tuple, Union
from pydantic import BaseModel, Field, field_validator, model_validator

# ────────────────────────────────────────────────────────────
# SECTION 1: PRIMITIVES AND GEOMETRY
# ────────────────────────────────────────────────────────────

class BoundingBox(BaseModel):
    """Axis-aligned bounding box. All coordinates in pixels relative to single page bounds."""
    x_min: int = Field(..., ge=0)
    y_min: int = Field(..., ge=0)
    x_max: int = Field(..., gt=0)
    y_max: int = Field(..., gt=0)

    @model_validator(mode="after")
    def validate_bounds(self) -> BoundingBox:
        if self.x_max <= self.x_min:
            raise ValueError("x_max must be greater than x_min")
        if self.y_max <= self.y_min:
            raise ValueError("y_max must be greater than y_min")
        return self

    @property
    def center(self) -> Tuple[float, float]:
        return ((self.x_min + self.x_max) / 2.0, (self.y_min + self.y_max) / 2.0)

    def area(self) -> int:
        return (self.x_max - self.x_min) * (self.y_max - self.y_min)

    def contains(self, other: BoundingBox) -> bool:
        return (self.x_min <= other.x_min and self.x_max >= other.x_max and
                self.y_min <= other.y_min and self.y_max >= other.y_max)

    def intersection_area(self, other: BoundingBox) -> int:
        x_overlap = max(0, min(self.x_max, other.x_max) - max(self.x_min, other.x_min))
        y_overlap = max(0, min(self.y_max, other.y_max) - max(self.y_min, other.y_min))
        return x_overlap * y_overlap

    def iou(self, other: BoundingBox) -> float:
        inter = self.intersection_area(other)
        union = self.area() + other.area() - inter
        return inter / union if union > 0 else 0.0

class AffineMatrix(BaseModel):
    """2D affine transformation for deskewing and template alignment."""
    a: float
    b: float
    c: float
    d: float
    tx: float
    ty: float

    def transform_point(self, x: float, y: float) -> Tuple[float, float]:
        return (self.a * x + self.b * y + self.tx,
                self.c * x + self.d * y + self.ty)

class PrimitiveType(str, Enum):
    CHECKBOX = "checkbox"
    RADIO_BUTTON = "radio_button"
    UNDERLINE_FIELD = "underline_field"
    TEXTLINE = "textline"
    SIGNATURE_LINE = "signature_line"
    DATE_SLOTS = "date_slots"
    TABLE_CELL = "table_cell"
    DROPDOWN_INDICATOR = "dropdown_indicator"
    NUMERIC_BOX = "numeric_box"

class ZoneType(str, Enum):
    PATIENT_INFO = "patient_info"
    SECTION_HEADER = "section_header"
    TABLE = "table"
    CHECKBOX_GROUP = "checkbox_group"
    FREE_TEXT = "free_text"
    SIGNATURE_BLOCK = "signature_block"
    FOOTER = "footer"
    UNKNOWN = "unknown"

# ────────────────────────────────────────────────────────────
# SECTION 2: PAGE METADATA [CLOSES Gap#1, Gap#22]
# ────────────────────────────────────────────────────────────

class PageMetadata(BaseModel):
    """Established at pipeline entry. NEVER changes during processing."""
    page_id: str  # globally unique identifier (UUID)
    document_id: str  # parent document identifier
    page_number: int = Field(..., ge=1)  # 1-based page index within the document
    width_px: int = Field(..., gt=0)
    height_px: int = Field(..., gt=0)
    dpi: int = Field(default=300, gt=0)
    file_hash: str  # SHA-256 of the original page image bytes
    upload_timestamp: datetime
    pipeline_version: str  # e.g. "CFIS-P5.2"
    source_document_path: Optional[str] = None
    rotation_degrees: float = 0.0  # detected rotation before deskew (for audit)

# ────────────────────────────────────────────────────────────
# SECTION 3: PROVENANCE [CLOSES Gap#19]
# ────────────────────────────────────────────────────────────

class Provenance(BaseModel):
    """
    Attached to every extracted value. Satisfies RULE 8 audit trail requirement.
    Never omit this. Missing provenance is a pipeline integrity violation.
    """
    source_engine: str  # e.g. "ParentChildLinkerEngine"
    confidence: float = Field(..., ge=0.0, le=1.0)
    evidence_refs: List[str]  # word_ids, primitive_ids, zone_ids contributing to this value
    creation_timestamp: datetime
    template_id: Optional[str] = None  # set if value was assisted by a template

# ────────────────────────────────────────────────────────────
# SECTION 4: OCR EVIDENCE (IMMUTABLE after Perception)
# ────────────────────────────────────────────────────────────

class OCRWord(BaseModel):
    word_id: str
    text: str
    bbox: BoundingBox
    confidence: float = Field(..., ge=0.0, le=1.0)
    language: Optional[str] = None
    direction: Literal["LTR", "RTL"] = "LTR"
    direction_per_word: Literal["LTR", "RTL"] = "LTR"

class OCREvidence(BaseModel):
    """Immutable OCR output for a single page. Produced by Perception stage."""
    words: List[OCRWord]
    ocr_engine: str
    extraction_timestamp: datetime
    page_language: Optional[str] = None
    page_direction: Literal["LTR", "RTL"] = "LTR"
    errors: List[str] = Field(default_factory=list)

# ────────────────────────────────────────────────────────────
# SECTION 5: VISUAL PRIMITIVE EVIDENCE (IMMUTABLE after Perception)
# ────────────────────────────────────────────────────────────

class DetectionMetadata(BaseModel):
    """
    Typed metadata produced by PrimitiveShapeDetectorEngine.
    Closes Gap#2: previously Dict[str, Any], now fully typed.
    """
    edge_density: Optional[float] = None  # Canny edge density in bbox region
    fill_ratio: Optional[float] = None  # filled area / total bbox area
    contour_area: float = 0.0
    aspect_ratio: float = 0.0
    num_hough_lines: int = 0  # lines detected inside bbox
    is_filled: bool = False  # for checkboxes: tick/fill detected
    contains_ocr_words: bool = False  # True if OCRWords overlap this primitive
    # underline_field disambiguation (closes Gap#36):
    # underline_field is only assigned when contains_ocr_words is False.
    # If a horizontal line's bbox overlaps OCRWords with confidence > 0.5,
    # it is classified as TEXTLINE, not UNDERLINE_FIELD.
    disambiguation_applied: bool = False

class VisualPrimitiveEvidence(BaseModel):
    """Immutable. Produced by PrimitiveShapeDetectorEngine."""
    primitive_id: str
    primitive_type: PrimitiveType
    bbox: BoundingBox
    confidence: float = Field(..., ge=0.0, le=1.0)
    shape_features: Dict[str, float] = Field(default_factory=dict)
    associated_text_ids: List[str] = Field(default_factory=list)
    detection_metadata: DetectionMetadata = Field(default_factory=DetectionMetadata)

# ────────────────────────────────────────────────────────────
# SECTION 6: SEMANTIC ZONE PROPOSAL [CLOSES Gap#3]
# ────────────────────────────────────────────────────────────

class ZoneProposalSource(str, Enum):
    GEOMETRIC_DETECTION = "GEOMETRIC_DETECTION"
    LAYOUTLMV3_SUGGESTION = "LAYOUTLMV3_SUGGESTION"
    TEMPLATE_PROJECTED = "TEMPLATE_PROJECTED"

class VisualFeatures(BaseModel):
    """Typed visual features used by ZoneProposalMergerEngine for comparison."""
    has_border: bool = False
    has_background_shading: bool = False
    vertical_gap_above_px: float = 0.0
    vertical_gap_below_px: float = 0.0
    density: float = 0.0  # text/primitive density within proposed zone
    has_grid_lines: bool = False
    dominant_color: Optional[str] = None  # hex, for shading detection

class SemanticZoneProposal(BaseModel):
    """
    Produced by SemanticZoneProposalEngine (geometric) and LayoutLMv3 integration.
    Resolved by ZoneProposalMergerEngine before ZoneGraphCompilerEngine.
    Closes Gap#3.
    """
    proposal_id: str
    zone_type: ZoneType
    zone_label: str
    bbox: BoundingBox
    confidence: float = Field(..., ge=0.0, le=1.0)
    source: ZoneProposalSource
    parent_proposal_id: Optional[str] = None
    contained_primitive_ids: List[str] = Field(default_factory=list)
    contained_text_ids: List[str] = Field(default_factory=list)
    visual_features: VisualFeatures = Field(default_factory=VisualFeatures)
    conflict_log: List[str] = Field(default_factory=list)  # losing proposal_ids

# ────────────────────────────────────────────────────────────
# SECTION 7: FIELD GROUP CANDIDATE [CLOSES Gap#4]
# ────────────────────────────────────────────────────────────

class AnchorCandidate(BaseModel):
    primitive_id: Optional[str] = None
    text_ids: List[str] = Field(default_factory=list)
    bbox: BoundingBox
    anchor_text: Optional[str] = None

class ValueCandidate(BaseModel):
    primitive_id: Optional[str] = None
    text_ids: List[str] = Field(default_factory=list)
    bbox: BoundingBox
    candidate_type: PrimitiveType

class FieldGroupStructuralType(str, Enum):
    LABEL_VALUE_HORIZONTAL = "label_value_horizontal"  # label left, value right
    LABEL_VALUE_VERTICAL = "label_value_vertical"  # label above, value below
    CHECKBOX_WITH_LABEL = "checkbox_with_label"
    TABLE_CELL_PAIR = "table_cell_pair"
    STANDALONE_PRIMITIVE = "standalone_primitive"

class FieldGroupCandidate(BaseModel):
    """
    Produced by StructuralGroupingEngine.
    Groups related visual elements into field candidates.
    These are CANDIDATES only — not final fields.
    Closes Gap#4.
    """
    group_id: str
    zone_proposal_id: str
    anchor_candidates: List[AnchorCandidate]
    value_candidates: List[ValueCandidate]
    structural_type: FieldGroupStructuralType
    confidence: float = Field(..., ge=0.0, le=1.0)

# ────────────────────────────────────────────────────────────
# SECTION 8: LAYOUT GRAMMAR MODELS
# ────────────────────────────────────────────────────────────

class OptionElement(BaseModel):
    primitive_id: str
    bbox: BoundingBox
    # OptionElement label resolution (closes Gap#37):
    # label_text is resolved by searching OCRWords within a 20px horizontal
    # margin to the right (LTR) or left (RTL) of the primitive bbox.
    # The nearest word cluster not overlapping another primitive is assigned.
    label_text: Optional[str] = None
    label_word_ids: List[str] = Field(default_factory=list)

class OptionGroup(BaseModel):
    group_id: str
    question_anchor_id: Optional[str]
    option_elements: List[OptionElement]
    layout_type: Literal["HORIZONTAL", "VERTICAL", "GRID"]
    confidence: float = Field(..., ge=0.0, le=1.0)

class GridCell(BaseModel):
    row_index: int
    col_index: int
    primitive_id: Optional[str] = None
    text_ids: List[str] = Field(default_factory=list)
    bbox: BoundingBox
    is_empty: bool = False
    colspan: int = 1
    rowspan: int = 1

class MergedCellRegion(BaseModel):
    start_row: int
    start_col: int
    end_row: int
    end_col: int
    primary_cell_row: int
    primary_cell_col: int

class InferredGrid(BaseModel):
    grid_id: str
    row_count: int
    col_count: int
    cells: List[GridCell]
    header_row: Optional[List[str]] = None
    header_col: Optional[List[str]] = None
    merged_cells: List[MergedCellRegion] = Field(default_factory=list)

class RowGroup(BaseModel):
    row_index: int
    y_band_min: int
    y_band_max: int
    element_ids: List[str]

class PatternInstance(BaseModel):
    instance_index: int
    element_ids: List[str]

class RepeatedFieldPattern(BaseModel):
    pattern_id: str
    template_fields: List[str]
    instances: List[PatternInstance]

class LayoutGrammarGraph(BaseModel):
    rows: List[RowGroup] = Field(default_factory=list)
    option_groups: List[OptionGroup] = Field(default_factory=list)
    grids: List[InferredGrid] = Field(default_factory=list)
    patterns: List[RepeatedFieldPattern] = Field(default_factory=list)

# ────────────────────────────────────────────────────────────
# SECTION 9: READING ORDER [CLOSES Gap#8]
# ────────────────────────────────────────────────────────────

class ReadingOrderEntry(BaseModel):
    word_id: str
    line_index: int
    position_in_line: int  # 0-based position within the line
    resolved_direction: Literal["LTR", "RTL"]
    zone_id: str

class ReadingOrderSequence(BaseModel):
    """
    Produced by ReadingOrderEngine.
    Defines the deterministic word reading order across all zones on the page.
    Closes Gap#8.
    """
    entries: List[ReadingOrderEntry]
    page_id: str
    computed_at: datetime

    def words_in_zone(self, zone_id: str) -> List[ReadingOrderEntry]:
        return sorted(
            [e for e in self.entries if e.zone_id == zone_id],
            key=lambda e: (e.line_index, e.position_in_line)
        )

# ────────────────────────────────────────────────────────────
# SECTION 10: HIERARCHICAL FIELD PAIR [CLOSES Gap#6, Gap#7]
# ────────────────────────────────────────────────────────────

class LinkStatus(str, Enum):
    LINK_CONFIRMED = "LINK_CONFIRMED"  # final_score >= 0.70
    LINK_TENTATIVE = "LINK_TENTATIVE"  # 0.50 <= score < 0.70 → HITL queue
    NO_LINK = "NO_LINK"  # score < 0.50

class SignalScores(BaseModel):
    """All six linker signal scores recorded for audit and calibration."""
    spatial_proximity: float = 0.0
    alignment_vector: float = 0.0
    reading_order_adjacency: float = 0.0
    zone_membership: float = 0.0
    layout_grammar_structure: float = 0.0
    primitive_association: float = 0.0
    final_score: float = 0.0

class HierarchicalFieldPair(BaseModel):
    """
    The core output of ParentChildLinkerEngine.
    Links a question anchor to its answer node.
    signal_scores are embedded here (not in TentativeLinkBatch) to
    maintain a single source of truth. Closes Gap#6 and Gap#7.
    """
    pair_id: str
    question_anchor_id: str  # element_id of the question label
    answer_node_id: str  # primitive_id or text group id
    status: LinkStatus
    signal_scores: SignalScores
    zone_id: str
    alternative_answer_ids: List[str] = Field(default_factory=list)
    provenance: Provenance

# ────────────────────────────────────────────────────────────
# SECTION 11: SEMANTIC ZONE (COMPLETED) [CLOSES Gap#5]
# ────────────────────────────────────────────────────────────

class SpatialTransform(BaseModel):
    """Cached affine transform for the zone. Do NOT cache across pages."""
    affine: AffineMatrix
    computed_at: datetime
    page_id: str  # invalidation guard

class SemanticZone(BaseModel):
    """
    Final compiled zone. Produced by ZoneGraphCompilerEngine.
    Closes Gap#5: now includes compiled_fields, validation_rules,
    spatial_transform, and metadata.

    Smart Discovery extensions:
    - is_dynamic: True when the zone was auto-discovered by SmartZoneDiscoveryEngine
      rather than projected from a static template.
    - anchors_refs: word_ids of anchor tokens used to calibrate coordinate drift for
      this zone. Populated by AnchorCalibrationEngine; empty on template-projected zones.
    - detection_confidence: confidence score of the automatic zone classification;
      mirrors SemanticZoneProposal.confidence but persisted on the final zone for
      downstream audit. Always 1.0 for manually created zones.
    - coordinate_drift: (dx, dy) pixel offset applied during anchor calibration.
      Stored so re-runs can reproduce the same adjustment deterministically.
    """
    zone_id: str
    zone_type: ZoneType
    zone_label: str
    bbox: BoundingBox
    parent_zone_id: Optional[str] = None
    child_zone_ids: List[str] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)
    compiled_fields: List[str] = Field(default_factory=list)  # HierarchicalFieldPair.pair_ids
    validation_rules: Dict[str, Any] = Field(default_factory=dict)
    spatial_transform: Optional[SpatialTransform] = None  # set once, reused within zone
    metadata: Dict[str, Any] = Field(default_factory=dict)
    median_line_height_px: Optional[float] = None  # computed by ReadingOrderEngine; used for tolerances
    # ── Smart Discovery fields ──────────────────────────────
    is_dynamic: bool = False  # True → discovered automatically, False → template-projected / manual
    anchors_refs: List[str] = Field(default_factory=list)  # word_ids of calibration anchor tokens
    detection_confidence: float = Field(default=1.0, ge=0.0, le=1.0)  # auto-classification confidence
    coordinate_drift: Optional[Tuple[float, float]] = None  # (dx, dy) applied by AnchorCalibrationEngine

# ────────────────────────────────────────────────────────────
# SECTION 12: FIELD TYPE INFERENCE
# ────────────────────────────────────────────────────────────

class FieldType(str, Enum):
    TEXT = "text"
    NUMBER = "number"
    DATE = "date"
    BOOLEAN = "boolean"
    ENUM = "enum"
    MULTI_SELECT = "multi_select"
    SIGNATURE = "signature"
    TABLE = "table"
    TIME = "time"
    PHONE = "phone"
    EMAIL = "email"
    IDENTIFIER = "identifier"
    COMPOSITE_CONTAINER = "composite_container"
    ENUM_WITH_FREETEXT_OPTION = "enum_with_freetext_option"
    DATE_STRUCTURED = "date_structured"

class SnapResult(str, Enum):
    EXACT = "exact"  # match within primary radius
    LOW_CONFIDENCE = "low_confidence"  # match within expanded radius
    UNBOUND = "unbound"  # no match; routed to HITL

class FieldTypeInference(BaseModel):
    pair_id: str
    inferred_type: FieldType
    confidence: float = Field(..., ge=0.0, le=1.0)
    snap_result: Optional[SnapResult] = None
    snap_radius_used_px: Optional[float] = None
    provenance: Provenance

# ────────────────────────────────────────────────────────────
# SECTION 13: COMPOSITE FIELD CONTAINER
# ────────────────────────────────────────────────────────────

class ContainerValidationStatus(str, Enum):
    VALID = "VALID"
    PARTIAL = "PARTIAL"
    INVALID = "INVALID"

class ContainerInstance(BaseModel):
    instance_index: int  # 0-based
    fields: List[str]  # HierarchicalFieldPair.pair_ids
    validation_status: ContainerValidationStatus

class CompositeFieldContainer(BaseModel):
    container_id: str
    canonical_tag: str  # e.g. "patient.medications"
    is_repeatable: bool
    instances: List[ContainerInstance]
    instance_count: int

# ────────────────────────────────────────────────────────────
# SECTION 14: CANONICAL SCHEMA MAPPING
# ────────────────────────────────────────────────────────────

class CanonicalFieldMapping(BaseModel):
    pair_id: str
    canonical_tag: str  # e.g. "patient.name" or "patient.medications[0].dose"
    schema_version: str
    mapping_confidence: float = Field(..., ge=0.0, le=1.0)
    is_unmapped: bool = False  # True → assigned "unknown.field_{n}"
    provenance: Provenance

# ────────────────────────────────────────────────────────────
# SECTION 15: CONSTRAINT CONDITION [CLOSES Gap#9]
# ────────────────────────────────────────────────────────────

class ComparisonOperator(str, Enum):
    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    CONTAINS = "contains"
    MATCHES_REGEX = "matches_regex"
    IS_PRESENT = "is_present"
    IS_ABSENT = "is_absent"
    IS_NUMERIC = "is_numeric"

class ComparisonCondition(BaseModel):
    """Simple field-to-value or field-to-field comparison."""
    type: Literal["comparison"] = "comparison"
    field_path: str  # dot-path with wildcard support: "medications[*].dose"
    operator: ComparisonOperator
    value: Optional[Any] = None  # None for IS_PRESENT / IS_ABSENT

class LogicalCondition(BaseModel):
    """Composite AND / OR / NOT over sub-conditions."""
    type: Literal["logical"] = "logical"
    logical_operator: Literal["AND", "OR", "NOT"]
    operands: List[ConstraintCondition]

class PathExistenceCondition(BaseModel):
    """Checks whether a field path resolves to at least one value in PageCompilationState."""
    type: Literal["path_existence"] = "path_existence"
    field_path: str
    must_exist: bool = True

ConstraintCondition = Union[ComparisonCondition, LogicalCondition, PathExistenceCondition]

# Resolve forward references in LogicalCondition
LogicalCondition.model_rebuild()

# ────────────────────────────────────────────────────────────
# SECTION 16: CROSS-FIELD CONSTRAINT GRAPH [CLOSES Gap#10]
# ────────────────────────────────────────────────────────────

class ConstraintScope(str, Enum):
    FLAT = "flat"  # applies to top-level fields
    EACH_INSTANCE = "each_instance"  # constraint checked per container instance
    ANY_INSTANCE = "any_instance"  # constraint satisfied if ANY instance complies

class ViolationAction(str, Enum):
    LOWER_CONFIDENCE = "lower_confidence"
    FLAG_HITL = "flag_hitl"
    BLOCK_COMMIT = "block_commit"

class ViolationSeverity(str, Enum):
    WARNING = "warning"
    ERROR = "error"

class CrossFieldConstraint(BaseModel):
    constraint_id: str
    constraint_type: Literal["IMPLICATION", "EXCLUSION", "DEPENDENCY", "RANGE_RELATION", "INSTANCE_REQUIRED"]
    field_a_tag: str  # supports path expressions with [*] wildcard
    field_b_tag: str
    scope: ConstraintScope
    condition: ConstraintCondition
    violation_action: ViolationAction
    severity: ViolationSeverity
    valid_from_schema_version: str  # e.g. "healthcare.patient.v1"
    deprecated_in_schema_version: Optional[str] = None

class ConstraintGraph(BaseModel):
    """
    Closes Gap#10: now has version and namespace.
    Loaded from versioned ConstraintRegistry at startup.
    Supports hot-reload (see Gap#28 / SECTION 28).
    """
    graph_version: str
    namespace: str  # e.g. "healthcare.patient"
    constraints: List[CrossFieldConstraint]
    loaded_at: datetime

# ────────────────────────────────────────────────────────────
# SECTION 17: VALIDATION REPORT AND TENTATIVE LINK BATCH [CLOSES Gap#7]
# ────────────────────────────────────────────────────────────

class TentativeLinkBatch(BaseModel):
    """
    Simplified: signal_scores are now inside HierarchicalFieldPair.
    TentativeLinkBatch only groups tentative pair_ids by zone for HITL review.
    Closes Gap#7.
    """
    zone_id: str
    tentative_pair_ids: List[str]  # HierarchicalFieldPair.pair_ids with LINK_TENTATIVE

class FieldViolation(BaseModel):
    pair_id: str
    canonical_tag: str
    violation_type: str
    message: str
    severity: ViolationSeverity

class ConstraintViolation(BaseModel):
    constraint_id: str
    field_a_tag: str
    field_b_tag: str
    instance_index: Optional[int] = None
    field_a_value: Any
    field_b_value: Any
    severity: ViolationSeverity
    action_taken: ViolationAction

class ValidationReport(BaseModel):
    field_violations: List[FieldViolation] = Field(default_factory=list)
    constraint_violations: List[ConstraintViolation] = Field(default_factory=list)
    tentative_link_batches: List[TentativeLinkBatch] = Field(default_factory=list)
    hitl_flags: List[Any] = Field(default_factory=list)
    overall_confidence: float = 1.0
    commit_blocked: bool = False

# ────────────────────────────────────────────────────────────
# SECTION 18: LEDGER OPERATIONS [CLOSES Gap#13, Gap#14]
# ────────────────────────────────────────────────────────────

class BaseLedgerOperation(BaseModel):
    """
    Base class for all ledger operations.
    All operation types inherit from this. Closes Gap#13.
    Common fields validated once, not duplicated across subtypes.
    """
    operation_id: str  # UUID
    ledger_sequence_number: int  # strictly monotonic; enforced by LedgerOperationEngine
    timestamp: datetime
    operator_id: str  # user or system agent issuing this operation
    operation_type: str  # discriminator; set by subclasses
    previous_state: Dict[str, Any] = Field(default_factory=dict)  # for rollback

class ZoneOperation(BaseLedgerOperation):
    operation_type: Literal[
        "RESIZE_ZONE", "RENAME_ZONE", "MERGE_ZONES",
        "SPLIT_ZONE", "ASSIGN_PARENT", "DELETE_ZONE",
        "CREATE_ZONE",
        # Smart-discovery operations (Phase-3 additions)
        "UPDATE_ZONE_ANCHOR",       # attach / replace anchor_refs for a zone
        "CALIBRATE_COORDINATES",    # record drift correction (dx, dy) applied to a zone
    ] = "CREATE_ZONE"
    target_zone_id: str
    parameters: Dict[str, Any]

class FieldOperation(BaseLedgerOperation):
    operation_type: Literal["OVERRIDE_FIELD_TYPE", "EDIT_VALUE", "REASSIGN_ZONE",
                            "ADD_FIELD", "DELETE_FIELD", "LINK_FIELD", "UNLINK_FIELD"] = "ADD_FIELD"
    target_field_id: str
    parameters: Dict[str, Any]

class RelationshipOperation(BaseLedgerOperation):
    operation_type: Literal["CREATE_LINK", "DELETE_LINK", "ADJUST_CONFIDENCE"] = "CREATE_LINK"
    question_anchor_id: str
    answer_node_id: str
    parameters: Dict[str, Any]

class ContainerOperation(BaseLedgerOperation):
    operation_type: Literal["ADD_INSTANCE", "REMOVE_INSTANCE", "REORDER_INSTANCES"] = "ADD_INSTANCE"
    container_id: str
    instance_index: Optional[int] = None
    parameters: Dict[str, Any]

class TentativeLinkResolutionOperation(BaseLedgerOperation):
    """Operator decision on a tentative link from TentativeLinkReviewEngine."""
    operation_type: Literal["TENTATIVE_LINK_RESOLVED"] = "TENTATIVE_LINK_RESOLVED"
    pair_id: str
    decision: Literal["CONFIRM", "REJECT"]

class CompensateOperation(BaseLedgerOperation):
    """
    Compensating operation for rollback. Closes Gap#14.
    Appended to ledger; NEVER deletes previous entries.
    Replay applies it in sequence like any other operation.
    """
    operation_type: Literal["COMPENSATE"] = "COMPENSATE"
    target_operation_id: str  # the operation being rolled back
    previous_state_snapshot: Dict[str, Any]  # taken from target operation's previous_state
    # Cascading compensations (e.g. rolling back a ContainerOp that added an instance):
    # cascaded_operation_ids lists all FieldOperation.operation_ids referencing the
    # removed instance_index. These are also compensated in reverse chronological order.
    # Operator must confirm cascading compensations before commit.
    cascaded_operation_ids: List[str] = Field(default_factory=list)
    operator_confirmed_cascade: bool = False

class DraftOperation(BaseModel):
    """
    Closes Gap#24: draft lifecycle for MacroHITLEditorEngine.
    A DraftOperation is NOT appended to the ledger until the operator commits.
    DISCARD_DRAFT removes all accumulated drafts for the session.
    """
    draft_id: str
    session_id: str
    accumulated_operations: List[Dict[str, Any]]  # serialized BaseLedgerOperation subtypes
    created_at: datetime
    status: Literal["PENDING", "COMMITTED", "DISCARDED"] = "PENDING"

LedgerOperation = Union[
    ZoneOperation, FieldOperation, RelationshipOperation,
    ContainerOperation, TentativeLinkResolutionOperation, CompensateOperation
]

# ────────────────────────────────────────────────────────────
# SECTION 19: COMPILED SNAPSHOT [CLOSES Gap#11, Gap#12, Gap#34]
# ────────────────────────────────────────────────────────────

class CompiledSnapshot(BaseModel):
    """
    Closes Gap#11: compiled_fields and composite_containers explicitly typed.
    Closes Gap#34: snapshots list in PageCompilationState holds IDs only;
    actual blobs live in SnapshotStore (external persistent storage).
    """
    snapshot_id: str
    page_id: str
    ledger_sequence_number: int
    compiled_zones: List[SemanticZone]
    compiled_fields: List[HierarchicalFieldPair]  # explicit type
    composite_containers: List[CompositeFieldContainer]  # explicit type
    schema_version: str
    created_at: datetime
    supersedes_snapshot_id: Optional[str] = None

class SchemaMigrationAdapter(BaseModel):
    """
    Closes Gap#12: protocol for migrating stale snapshots when schema version changes.
    Applied at snapshot load time if snapshot.schema_version != current schema_version.
    """
    from_version: str
    to_version: str
    # migration_steps: ordered list of field remapping rules.
    # Each step is {"action": "rename" | "drop" | "default",
    # "field_tag": "old.tag", "new_tag": "new.tag" (for rename),
    # "default_value": any (for default)}
    migration_steps: List[Dict[str, Any]]
    migration_script_ref: Optional[str] = None  # path to Python migration script if complex

# ────────────────────────────────────────────────────────────
# SECTION 20: ERROR AND ALERT MODELS [CLOSES Gap#25, Gap#32]
# ────────────────────────────────────────────────────────────

class ProcessingSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

class ProcessingError(BaseModel):
    """
    Stored in PageCompilationState.error_log.
    Closes Gap#32.
    """
    error_id: str
    error_code: str  # e.g. "OCR_PARTIAL_FAILURE", "ZONE_TREE_CYCLE"
    message: str
    engine_name: str  # which engine raised this error
    timestamp: datetime
    severity: ProcessingSeverity
    related_entity_id: Optional[str] = None  # zone_id, pair_id, primitive_id, etc.
    stack_trace: Optional[str] = None

class SnapshotRaceConditionError(BaseModel):
    """
    Raised by SnapshotCompilerEngine when an out-of-order snapshot write is attempted.
    Closes Gap#25.
    """
    error_type: Literal["SNAPSHOT_RACE_CONDITION"] = "SNAPSHOT_RACE_CONDITION"
    incoming_sequence_number: int
    cached_sequence_number: int
    page_id: str
    timestamp: datetime

class DeterminismViolationAlert(BaseModel):
    """
    Raised by ReplayEngine or LedgerOperationEngine on state_hash mismatch.
    Closes Gap#25 and Gap#20.
    """
    alert_type: Literal["DETERMINISM_VIOLATION"] = "DETERMINISM_VIOLATION"
    expected_hash: str
    actual_hash: str
    page_id: str
    ledger_sequence_number: int
    timestamp: datetime

# ────────────────────────────────────────────────────────────
# SECTION 21: TEMPLATE MODELS [CLOSES Gap#15, Gap#39, Gap#40]
# ────────────────────────────────────────────────────────────

class VisualAnchorPoint(BaseModel):
    anchor_id: str
    description: str
    # Closes Gap#40: large descriptors (> 256 floats total) stored externally.
    # If descriptor_blob_id is set, load from DescriptorBlobStore; feature_descriptor is empty.
    feature_descriptor: List[List[float]] = Field(default_factory=list)
    descriptor_blob_id: Optional[str] = None  # reference to external blob store
    approximate_bbox: BoundingBox
    confidence_threshold: float = 0.75

    def get_descriptor_as_array(self) -> Any:
        """Convert to np.array at call site only. Never store ndarray in this model."""
        import numpy as np
        return np.array(self.feature_descriptor, dtype=np.float32)

class RelativePosition(BaseModel):
    anchor_reference: str
    offset_x: float  # pixels
    offset_y: float  # pixels
    width: float  # pixels
    height: float  # pixels

class ZoneTemplate(BaseModel):
    zone_template_id: str
    zone_type: ZoneType
    zone_label: str
    relative_position: RelativePosition
    parent_zone_template_id: Optional[str] = None
    child_zone_template_ids: List[str] = Field(default_factory=list)
    expected_field_count: int
    validation_rules: Dict[str, Any] = Field(default_factory=dict)

class FieldTemplate(BaseModel):
    field_template_id: str
    canonical_tag: str
    field_type: str
    zone_template_id: str
    relative_position: RelativePosition
    expected_primitive_type: PrimitiveType
    validation_rules: Dict[str, Any] = Field(default_factory=dict)

class FormTemplate(BaseModel):
    template_id: str
    template_name: str
    template_version: str
    anchor_keypoints: List[VisualAnchorPoint]
    zone_templates: List[ZoneTemplate]
    field_templates: List[FieldTemplate]
    canonical_schema_version: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

class TemplateFailureLog(BaseModel):
    """
    Closes Gap#15. Stored in MetricsStore (dedicated table: template_failure_log).
    Queried before each template match attempt using (template_id, page_id) index.
    """
    log_id: str
    template_id: str
    page_id: str
    failure_reason: str  # e.g. "INSUFFICIENT_INLIERS", "CONFIDENCE_BELOW_THRESHOLD"
    timestamp: datetime
    retry_blocked_until: datetime  # = timestamp + 7 days

# ────────────────────────────────────────────────────────────
# SECTION 22: MULTI-PAGE ORCHESTRATION CONTRACT [CLOSES Gap#23]
# ────────────────────────────────────────────────────────────

class PageExtractionResult(BaseModel):
    """Summary output per page, produced after OperationalStage completes."""
    page_id: str
    page_number: int
    document_id: str
    compiled_zones: List[str]  # zone_ids
    compiled_fields: List[str]  # pair_ids
    composite_containers: List[str]  # container_ids
    schema_version: str
    overall_confidence: float
    commit_blocked: bool
    error_count: int

class OrchestrationContract(BaseModel):
    """
    Closes Gap#23.
    The Orchestration layer collects PageExtractionResult per page and aggregates.
    Cross-page references (e.g. field in page 1 refers to table in page 3) are
    NOT resolved by this system — they are flagged as CROSS_PAGE_REFERENCE in
    canonical_tag metadata and resolved by the downstream consumer application.
    This is by design: CFIS is single-page atomic.
    """
    document_id: str
    total_pages: int
    page_results: List[PageExtractionResult]
    aggregated_schema_version: str
    pipeline_version: str
    aggregation_timestamp: datetime
    # cross_page_flags: canonical_tags that could not be resolved within their page
    # and may reference data on another page. Downstream consumer resolves.
    cross_page_flags: List[str] = Field(default_factory=list)

# ────────────────────────────────────────────────────────────
# SECTION 22.5: TYPED STRUCTURAL FORM GRAPH
# ────────────────────────────────────────────────────────────

class FormElementType(str, Enum):
    ATOMIC_FIELD = "atomic_field"
    ENUM_GROUP = "enum_group"
    COMPOSITE_FIELD = "composite_field"
    MATRIX_FIELD = "matrix_field"
    CONDITIONAL_BRANCH = "conditional_branch"
    REPEATING_CLUSTER = "repeating_cluster"

class LayoutTopologyType(str, Enum):
    ROW_MAJOR = "row_major"
    COLUMN_MAJOR = "column_major"
    GRID = "grid"
    FREEFORM = "freeform"

class StructuralRelationType(str, Enum):
    CONTAINS = "contains"
    OPTION_OF = "option_of"
    CONDITIONAL_TRIGGER = "conditional_trigger"
    MATRIX_CELL = "matrix_cell"
    ROW_MEMBER = "row_member"
    COLUMN_MEMBER = "column_member"
    CHILD_REASON = "child_reason"
    ACTIVATES = "activates"

class StructuralEdge(BaseModel):
    source_id: str
    target_id: str
    relation_type: StructuralRelationType
    confidence: float
    provenance: Provenance
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ConstraintType(str, Enum):
    MAX_SELECTED = "max_selected"
    MUTUALLY_EXCLUSIVE = "mutually_exclusive"
    REQUIRED_IF_PARENT_ACTIVE = "required_if_parent_active"
    REQUIRES_CHILD_IF_SELECTED = "requires_child_if_selected"

class StructuralConstraint(BaseModel):
    constraint_id: str
    constraint_type: ConstraintType
    target_element_ids: List[str]
    parameters: Dict[str, Any] = Field(default_factory=dict)

class TopologySignature(BaseModel):
    alignment_group: str
    indentation_level: int = 0
    row_index: Optional[int] = None
    column_index: Optional[int] = None
    lane_id: Optional[str] = None

class FormElement(BaseModel):
    element_id: str  # Deterministic (quantized coords + normalized label hash)
    element_type: FormElementType
    label: str
    bbox: BoundingBox
    field_pairs: List[str] = Field(default_factory=list)
    child_element_ids: List[str] = Field(default_factory=list)
    topology_signature: Optional[TopologySignature] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class FormSection(BaseModel):
    section_id: str
    label: str
    bbox: BoundingBox
    element_ids: List[str] = Field(default_factory=list)
    layout_topology: LayoutTopologyType = LayoutTopologyType.FREEFORM

class FormGraph(BaseModel):
    page_id: str
    graph_version: str = "1.0"
    compiler_version: str = "CFIS-C1.0"
    normalization_version: str = "CFIS-N1.0"
    elements: Dict[str, FormElement] = Field(default_factory=dict)
    sections: List[FormSection] = Field(default_factory=list)
    edges: List[StructuralEdge] = Field(default_factory=list)
    constraints: List[StructuralConstraint] = Field(default_factory=list)

# ────────────────────────────────────────────────────────────
# SECTION 23: UNIFIED RUNTIME STATE
# ────────────────────────────────────────────────────────────

class PageCompilationState(BaseModel):
    """
    SINGLE source of truth during pipeline execution.
    Passed between all engines. No engine communicates through any other channel.
    """
    page_metadata: PageMetadata  # NEVER changes after entry
    ocr_evidence: Optional[OCREvidence] = None  # IMMUTABLE after Perception
    visual_primitives: List[VisualPrimitiveEvidence] = Field(default_factory=list)  # IMMUTABLE after Perception
    zone_proposals: List[SemanticZoneProposal] = Field(default_factory=list)  # IMMUTABLE after Perception; replaced by merger
    field_group_candidates: List[FieldGroupCandidate] = Field(default_factory=list)  # IMMUTABLE after Perception
    layout_grammar: Optional[LayoutGrammarGraph] = None
    compiled_zones: List[SemanticZone] = Field(default_factory=list)
    reading_order: Optional[ReadingOrderSequence] = None
    linked_fields: List[HierarchicalFieldPair] = Field(default_factory=list)
    inferred_types: List[FieldTypeInference] = Field(default_factory=list)
    canonical_mappings: List[CanonicalFieldMapping] = Field(default_factory=list)
    composite_containers: List[CompositeFieldContainer] = Field(default_factory=list)
    validation_results: Optional[ValidationReport] = None
    ledger_operations: List[LedgerOperation] = Field(default_factory=list)  # last 1000 in-memory
    snapshots: List[str] = Field(default_factory=list)  # snapshot_ids only; blobs in SnapshotStore
    metrics: Dict[str, Any] = Field(default_factory=dict)
    error_log: List[ProcessingError] = Field(default_factory=list)
    state_hash: Optional[str] = None  # recomputed after every LedgerOperationEngine commit (closes Gap#20)
    draft_operations: List[DraftOperation] = Field(default_factory=list)  # uncommitted HITL drafts (closes Gap#24)
    form_graph: Optional[FormGraph] = None
    semantic_form_graph: Optional[SemanticFormGraph] = None


# ────────────────────────────────────────────────────────────
# SEMANTIC FORM GRAPH  — Phase 2 Form Understanding Layer
# ────────────────────────────────────────────────────────────

class SemanticField(BaseModel):
    """
    A single field in the Semantic Form Graph.
    Produced by SemanticFormGraphBuilder from BoundQuestions and LogicalTable cells.
    The label is the raw Arabic/English string as it appears on the form.
    """
    field_id: str
    label: str                          # Arabic label as-is (e.g. "عمر المتوفاة")
    field_type: str                     # "text" | "number" | "enum" | "date" | "signature"
    options: List[str] = Field(default_factory=list)  # for enum fields
    bbox: BoundingBox
    section_id: Optional[str] = None
    source: str = "unknown"             # "bound_question" | "table_cell" | "free_field"


class SemanticSection(BaseModel):
    """
    A logical section grouping SemanticFields.
    Derived from FormGraph sections detected by ZoneTypeClassifierEngine.
    """
    section_id: str
    label: str
    fields: List[SemanticField] = Field(default_factory=list)
    bbox: BoundingBox
    zone_type: str = "unknown"
    include_in_form: bool = True


class SemanticFormGraph(BaseModel):
    """
    The Single Source of Truth for the Schema Builder in Phase 2.

    Produced by SemanticFormGraphBuilder by combining:
      - FormGraph sections (from StructuralSemanticCompilerEngine)
      - BoundQuestions (from QuestionControlBinder)
      - LogicalTable cells (from GridTableStructureBuilder)

    SemanticFormGraph is persisted as a named artifact (type="semantic_form_graph")
    in the ArtifactStore for debugging, regression testing, and model evaluation.
    It is NOT stored only transiently on PageCompilationState.
    """
    page_id: str
    sections: List[SemanticSection] = Field(default_factory=list)
    unassigned_fields: List[SemanticField] = Field(default_factory=list)
