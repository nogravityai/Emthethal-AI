import { create } from 'zustand';
import { immer } from 'zustand/middleware/immer';

// Default layer visibility: conflict/hitl off to reduce noise on first load
const defaultLayers = {
  ocr:       true,
  geometry:  true,
  alignment: false,
  conflict:  false,
  orphan:    false,
  hitl:      false,
  fusion:    true,
};

// Layer visual config — matches backend AlignmentType values + stage names
export const LAYER_META = {
  ocr:       { label: 'OCR Tokens',        color: '#10B981', shortcut: '1', stageKey: 'ocr_evidence' },
  geometry:  { label: 'Geometry Regions',  color: '#3B82F6', shortcut: '2', stageKey: 'geometry_evidence' },
  alignment: { label: 'Alignment Edges',   color: '#EC4899', shortcut: '3', stageKey: 'alignment_evidence' },
  conflict:  { label: 'Conflict Edges',    color: '#EF4444', shortcut: '4', stageKey: 'alignment_evidence' },
  orphan:    { label: 'Orphan Tokens',     color: '#F97316', shortcut: '5', stageKey: 'alignment_evidence' },
  hitl:      { label: 'HITL Operations',   color: '#A78BFA', shortcut: '6', stageKey: 'patched_evidence' },
  fusion:    { label: 'Resolved Fields',   color: '#8B5CF6', shortcut: '7', stageKey: 'resolved_fields' },
};

// Backend AlignmentType enum values (from alignment/models.py)
export const ALIGNMENT_TYPES = {
  TOKEN_INSIDE_REGION:    'token_inside_region',
  TOKEN_CROSSES_BOUNDARY: 'token_crosses_boundary',
  TOKEN_TOUCHING_REGION:  'token_touching_region',
};

// Backend HITL stage names (from orchestration.py pipeline stages)
export const PIPELINE_STAGES = [
  { name: 'raw_ocr_input',     type: 'raw_ocr_dicts',       label: 'OCR Input' },
  { name: 'raw_cv2_data',      type: 'raw_cv2_dicts',        label: 'CV2 Geometry' },
  { name: 'ocr_adapter',       type: 'ocr_evidence',         label: 'OCR Adapter' },
  { name: 'geometry',          type: 'geometry_evidence',    label: 'Geometry Adapter' },
  { name: 'evidence_patching', type: 'patched_evidence',     label: 'Evidence Patch (HITL)' },
  { name: 'alignment',         type: 'alignment_evidence',   label: 'Alignment Engine' },
  { name: 'alignment_fusion',  type: 'resolved_fields',      label: 'Fusion Engine' },
];

export const useWorkbenchStore = create(
  immer((set, _get) => ({

    // ── Run state ─────────────────────────────────────────────────────────────
    runId: null,
    pipelineVersion: '3.0.0',
    determinismOk: true,
    driftScore: 0,
    artifacts: {},    // { artifact_type → artifact_id } from PipelineRunResponse

    // ── Snapshots (keyed by stage) ────────────────────────────────────────────
    // Each snapshot shape matches the backend debug response exactly:
    //   ocr:       { tokens: [{id, text, confidence, bbox}] }
    //   geometry:  { regions: [{id, bbox, confidence}] }
    //   alignment: { alignments: [{id, type, score, token, region}] }
    //   fusion:    { fields: [{id, field_type, confidence, ocr_tokens, alignment_edges}] }
    snapshots: { ocr: null, geometry: null, alignment: null, fusion: null },

    // ── Run history ───────────────────────────────────────────────────────────
    runs: [],           // Array of { run_id, timestamp, stages[], human_operations[], determinism_ok }
    activeRunIndex: 0,

    // ── HITL ledger ───────────────────────────────────────────────────────────
    // Local mirror of backend ledger (fetched via GET /hitl/runs/{run_id}/operations)
    hitlLedger: [],

    // ── Timeline ──────────────────────────────────────────────────────────────
    // Matches: { run_id, document_id, stages: [{stage_name, output_type, artifact_id}] }
    timeline: null,

    // ── Schema export ─────────────────────────────────────────────────────────
    // Matches: { canonical_document: {...}, formio_schema: { components: [...] } }
    schema: null,

    // ── Compare mode ─────────────────────────────────────────────────────────
    compareMode: false,
    compareSnapshots: { ocr: null, geometry: null, alignment: null, fusion: null },
    compareRunId: null,

    // ── Canvas / viewer state ─────────────────────────────────────────────────
    pageImage: null,
    pageW: 1000,
    pageH: 1000,
    zoom: 1.0,
    panOffset: { x: 0, y: 0 },

    // ── UI state ──────────────────────────────────────────────────────────────
    layers: { ...defaultLayers },
    selected: null,     // { type: 'token'|'region'|'alignment'|'field', data: {...} }
    loading: false,
    status: '',
    activeTab: 'json',  // bottom panel: 'json' | 'formio' | 'raw' | 'diff'

    // =========================================================================
    //  Actions
    // =========================================================================

    setLoading: (loading, status = '') =>
      set(s => { s.loading = loading; s.status = status; }),

    setStatus: (status) =>
      set(s => { s.status = status; }),

    /** Called after a successful /run or /hitl/rerun */
    applyRunResult: ({ run_id, artifacts, snapshots, timeline, schema, determinism_ok = true }) =>
      set(s => {
        s.runId = run_id;
        s.artifacts = artifacts ?? {};
        s.snapshots = snapshots ?? { ocr: null, geometry: null, alignment: null, fusion: null };
        s.timeline = timeline;
        s.schema = schema;
        s.determinismOk = determinism_ok;
        s.loading = false;
        s.status = '';

        // Push to run history — timeline stages already have stage_name/artifact_id
        const runRecord = {
          run_id,
          timestamp: new Date().toISOString(),
          determinism_ok,
          orphan_count: 0, // computed from snapshots when available
          stages: timeline?.stages ?? [],
          is_hitl_rerun: false,
        };
        s.runs.unshift(runRecord);
        s.activeRunIndex = 0;
      }),

    /** Called after HITL rerun — marks the run record */
    applyHitlRerun: ({ run_id, determinism_ok, snapshots, timeline, schema }) =>
      set(s => {
        s.snapshots = snapshots ?? s.snapshots;
        s.timeline = timeline ?? s.timeline;
        s.schema = schema ?? s.schema;
        s.determinismOk = determinism_ok;
        s.loading = false;
        s.status = determinism_ok ? 'Replay complete — determinism verified' : '⚠ DETERMINISM BREACH detected';

        // Update the top run record
        if (s.runs.length > 0) {
          s.runs[0].determinism_ok = determinism_ok;
          s.runs[0].stages = timeline?.stages ?? s.runs[0].stages;
          s.runs[0].is_hitl_rerun = true;
        }
      }),

    setPageCanvas: ({ pageImage, pageW, pageH }) =>
      set(s => { s.pageImage = pageImage; s.pageW = pageW; s.pageH = pageH; }),

    setSelected: (selected) =>
      set(s => { s.selected = selected; }),

    clearSelected: () =>
      set(s => { s.selected = null; }),

    toggleLayer: (key) =>
      set(s => { s.layers[key] = !s.layers[key]; }),

    setLayerVisible: (key, visible) =>
      set(s => { s.layers[key] = visible; }),

    setZoom: (zoom) =>
      set(s => { s.zoom = Math.max(0.2, Math.min(5, zoom)); }),

    adjustZoom: (delta) =>
      set(s => { s.zoom = Math.max(0.2, Math.min(5, s.zoom + delta)); }),

    setPan: (offset) =>
      set(s => { s.panOffset = offset; }),

    resetView: () =>
      set(s => { s.zoom = 1; s.panOffset = { x: 0, y: 0 }; }),

    setCompareMode: (on) =>
      set(s => {
        s.compareMode = on;
        if (!on) { s.compareRunId = null; s.compareSnapshots = { ocr: null, geometry: null, alignment: null, fusion: null }; }
      }),

    setCompareSnapshots: ({ run_id, snapshots }) =>
      set(s => { s.compareRunId = run_id; s.compareSnapshots = snapshots; }),

    setActiveTab: (tab) =>
      set(s => { s.activeTab = tab; }),

    setHitlLedger: (ops) =>
      set(s => { s.hitlLedger = ops; }),

    addToLedger: (op) =>
      set(s => { s.hitlLedger.push(op); }),

    resetWorkbench: () =>
      set(s => {
        s.runId = null; s.artifacts = {}; s.runs = []; s.activeRunIndex = 0;
        s.snapshots = { ocr: null, geometry: null, alignment: null, fusion: null };
        s.compareSnapshots = { ocr: null, geometry: null, alignment: null, fusion: null };
        s.timeline = null; s.schema = null; s.selected = null;
        s.loading = false; s.status = ''; s.compareMode = false; s.compareRunId = null;
        s.layers = { ...defaultLayers }; s.zoom = 1; s.panOffset = { x: 0, y: 0 };
        s.pageImage = null; s.pageW = 1000; s.pageH = 1000;
        s.hitlLedger = []; s.determinismOk = true;
      }),
  }))
);
