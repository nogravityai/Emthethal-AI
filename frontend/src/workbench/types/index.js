// CFIS Phase 4 — Domain Types
// All backend contract models live here. UI never mutates these directly.

/** @typedef {{ x1: number, y1: number, x2: number, y2: number }} BBox */

/**
 * @typedef {Object} OcrToken
 * @property {string} id
 * @property {number[]} bbox  [x1,y1,x2,y2]
 * @property {string}  text
 * @property {number}  confidence
 * @property {string}  space
 * @property {string}  [source_engine]
 * @property {string}  [schema_version]
 */

/**
 * @typedef {Object} GeometryRegion
 * @property {string}  id
 * @property {number[]} bbox
 * @property {number}  confidence
 * @property {string}  [region_type]
 * @property {string}  [source_engine]
 * @property {boolean} [rejected]
 */

/**
 * @typedef {Object} AlignmentEdge
 * @property {string} id
 * @property {string} token
 * @property {string} region
 * @property {string} type
 * @property {number} score
 */

/**
 * @typedef {Object} FusionField
 * @property {string}   id
 * @property {string}   field_name
 * @property {string}   [value]
 * @property {number}   confidence
 * @property {string[]} ocr_tokens
 * @property {string[]} [alignment_edges]
 * @property {{ geometry_score: number, assignment_score: number, text_score: number, conflict_penalty: number, human_override_score: number, final_score: number }} [confidence_breakdown]
 */

/**
 * @typedef {Object} PipelineSnapshot
 * @property {{ tokens: OcrToken[] }}                    ocr
 * @property {{ regions: GeometryRegion[] }}             geometry
 * @property {{ alignments: AlignmentEdge[] }}           alignment
 * @property {{ fields: FusionField[], resolved_fields: FusionField[], orphans: any[], conflict_edges: any[] }} fusion
 */

/**
 * @typedef {Object} TimelineStage
 * @property {string} stage_name
 * @property {string} artifact_id
 * @property {number} [duration_ms]
 * @property {boolean} [deterministic]
 */

/**
 * @typedef {Object} PipelineRun
 * @property {string}          run_id
 * @property {string}          timestamp
 * @property {boolean}         deterministic
 * @property {number}          drift_score
 * @property {number}          orphan_count
 * @property {TimelineStage[]} stages
 */

/**
 * @typedef {Object} HitlOperation
 * @property {'reject_region'|'approve_region'|'merge_regions'|'split_region'|'reassign_token'|'ignore_token'|'approve_ocr'|'reject_ocr'} operation_type
 * @property {string}   run_id
 * @property {string}   operator_id
 * @property {string[]} target_evidence_ids
 * @property {Object}   [parameters]
 */

/**
 * @typedef {'ocr'|'geometry'|'alignment'|'conflict'|'orphan'|'hitl'|'fusion'} LayerKey
 */

/**
 * @typedef {Object} SelectedElement
 * @property {'token'|'region'|'alignment'|'field'|'orphan'|'conflict'} type
 * @property {OcrToken|GeometryRegion|AlignmentEdge|FusionField} data
 */

/**
 * @typedef {Object} CompareRun
 * @property {string}           run_id
 * @property {PipelineSnapshot} snapshot
 */

export const OP_TYPES = {
  REJECT_REGION:    'reject_region',
  APPROVE_REGION:   'approve_region',
  MERGE_REGIONS:    'merge_regions',
  SPLIT_REGION:     'split_region',
  REASSIGN_TOKEN:   'reassign_token',
  IGNORE_TOKEN:     'ignore_token',
  APPROVE_OCR:      'approve_ocr',
  REJECT_OCR:       'reject_ocr',
};

export const LAYER_KEYS = ['ocr','geometry','alignment','conflict','orphan','hitl','fusion'];

export const LAYER_META = {
  ocr:       { label: 'OCR Tokens',       color: '#10B981', shortcut: '1' },
  geometry:  { label: 'Geometry Regions', color: '#3B82F6', shortcut: '2' },
  alignment: { label: 'Alignment Edges',  color: '#EC4899', shortcut: '3' },
  conflict:  { label: 'Conflicts',         color: '#EF4444', shortcut: '4' },
  orphan:    { label: 'Orphans',           color: '#F97316', shortcut: '5' },
  hitl:      { label: 'HITL Operations',  color: '#A78BFA', shortcut: '6' },
  fusion:    { label: 'Resolved Fields',  color: '#8B5CF6', shortcut: '7' },
};
