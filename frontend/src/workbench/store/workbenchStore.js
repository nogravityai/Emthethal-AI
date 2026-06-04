import { create } from 'zustand';
import { immer } from 'zustand/middleware/immer';

// Default layer visibility: conflict/hitl off to reduce noise on first load
const defaultLayers = {
  ocr:       true,
  geometry:  true,
  coordinate_space: true,
  shapes:    true,
  topology:  true,
  zones:     true,
  formGraph: true,
  alignment: false,
  conflict:  false,
  orphan:    false,
  hitl:      false,
  fusion:    true,
  minimap:   true,
  coord_tooltip: true,
};

const defaultOpacities = {
  ocr:       0.85,
  geometry:  0.85,
  coordinate_space: 0.25,
  shapes:    0.7,
  topology:  0.4,
  zones:     0.75,
  formGraph: 0.75,
  alignment: 0.6,
  conflict:  0.8,
  orphan:    0.7,
  hitl:      0.7,
  fusion:    0.9,
  minimap:   1.0,
  coord_tooltip: 1.0,
};

const defaultRenderModes = {
  shapes: 'contour', // 'contour' | 'centroid' | 'saliency'
  coordinate_space: 'grid_axis', // 'grid_axis' | 'grid_only' | 'axis_only'
  alignment: 'semantic', // 'semantic' | 'gradient'
};

// Layer visual config — matches backend AlignmentType values + stage names
export const LAYER_META = {
  ocr:              { label: 'OCR Tokens',        color: '#10B981', shortcut: '1', stageKey: 'ocr_evidence' },
  geometry:         { label: 'Geometry Regions',  color: '#3B82F6', shortcut: '2', stageKey: 'geometry_evidence' },
  coordinate_space: { label: 'Coordinate Spaces', color: '#06B6D4', shortcut: '3', stageKey: 'coordinate_space_evidence' },
  shapes:           { label: 'Primitive Contours',color: '#F59E0B', shortcut: '4', stageKey: 'shape_evidence' },
  topology:         { label: 'Table Topology',    color: '#FBBF24', shortcut: '5', stageKey: 'topology_evidence' },
  zones:            { label: 'Semantic Zones',    color: '#F43F5E', shortcut: 'z', stageKey: 'topology_evidence' },
  formGraph:        { label: 'Form Graph',        color: '#A855F7', shortcut: 'g', stageKey: 'topology_evidence' },
  alignment:        { label: 'Alignment Edges',   color: '#EC4899', shortcut: '6', stageKey: 'alignment_evidence' },
  conflict:         { label: 'Conflict Edges',    color: '#EF4444', shortcut: '7', stageKey: 'alignment_evidence' },
  orphan:           { label: 'Orphan Tokens',     color: '#F97316', shortcut: '8', stageKey: 'alignment_evidence' },
  hitl:             { label: 'HITL Operations',   color: '#A78BFA', shortcut: '9', stageKey: 'patched_evidence' },
  fusion:           { label: 'Resolved Fields',   color: '#8B5CF6', shortcut: '0', stageKey: 'resolved_fields' },
};

// Backend AlignmentType enum values (from alignment/models.py)
export const ALIGNMENT_TYPES = {
  TOKEN_INSIDE_REGION:    'token_inside_region',
  TOKEN_CROSSES_BOUNDARY: 'token_crosses_boundary',
  TOKEN_TOUCHING_REGION:  'token_touching_region',
};
export const IR_STAGE_LAYERS = {
  raw_geometry:     ['shapes', 'geometry'],
  structural:       ['shapes', 'geometry', 'topology', 'zones', 'formGraph'],
  coordinate:       ['coordinate_space', 'shapes'],
  cognitive:        ['ocr', 'geometry', 'alignment', 'fusion', 'zones', 'formGraph'],
  reasoning:        ['fusion', 'topology', 'zones', 'formGraph'],
};

// Backend HITL stage names (from orchestration.py pipeline stages)
export const PIPELINE_STAGES = [
  { name: 'raw_ocr_input',     type: 'raw_ocr_dicts',       label: 'OCR Input' },
  { name: 'raw_cv2_data',      type: 'raw_cv2_dicts',        label: 'CV2 Geometry' },
  { name: 'perception',        type: 'perception_data',      label: 'Perception Stage (3-Layer)' },
  { name: 'evidence_patching', type: 'patched_evidence',     label: 'Evidence Patch (HITL)' },
  { name: 'topology_reconstruction', type: 'topology_evidence', label: 'Topology Reconstruction' },
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
    //   ocr:       { tokens: [{id, text, confidence, bbox}] }
    //   geometry:  { regions: [{id, bbox, confidence}] }
    //   topology:  { tables: [], hierarchy: [], linked_checkboxes: {} }
    //   alignment: { alignments: [{id, type, score, token, region}] }
    //   fusion:    { fields: [{id, field_type, confidence, ocr_tokens, alignment_edges}] }
    //   coordinate_space: { coordinate_space: {...} }
    //   shapes:    { shapes: [...] }
    snapshots: { ocr: null, geometry: null, topology: null, alignment: null, fusion: null, coordinate_space: null, shapes: null },

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
    compareSnapshots: { ocr: null, geometry: null, topology: null, alignment: null, fusion: null, coordinate_space: null, shapes: null },
    compareRunId: null,

    // ── Canvas / viewer state ─────────────────────────────────────────────────
    pageImage: null,
    pageW: 1000,
    pageH: 1000,
    zoom: 1.0,
    panOffset: { x: 0, y: 0 },

    // ── UI state ──────────────────────────────────────────────────────────────
    layers: { ...defaultLayers },
    layerOpacities: { ...defaultOpacities },
    layerRenderModes: { ...defaultRenderModes },
    irLevel: 'cognitive',
    selected: null,     // { type: 'token'|'region'|'alignment'|'field', data: {...} }
    loading: false,
    status: '',
    activeTab: 'json',  // bottom panel: 'json' | 'formio' | 'raw' | 'diff'
    
    // ── Spatial IDE additions ──
    workspaceMode: 'debug', // 'debug' | 'inspect' | 'replay' | 'chart'
    drawingMode: false,     // Drawing new zones mode
    isBottomCollapsed: false,
    isLeftCollapsed: false,
    isRightCollapsed: false,

    // ── Zone field corrections (local overrides before API call) ────────────
    // { [zoneId]: { [fieldId]: { type: string, label: string } } }
    zoneFieldCorrections: {},

    // ── Smart Calibration (SmartZoneDiscoveryEngine) ─────────────────────────
    // When enabled: every zone resize/drag in the canvas emits CALIBRATE_COORDINATES
    // via the HITL ledger, and the backend applies drift correction on rerun.
    smartCalibrationEnabled: false,
    // { [zone_id]: { dx: number, dy: number, anchor_word_ids: string[] } }
    calibrationVectors: {},

    // =========================================================================
    //  Actions
    // =========================================================================

    setDrawingMode: (mode) =>
      set(s => { s.drawingMode = mode; }),

    setWorkspaceMode: (mode) =>
      set(s => { s.workspaceMode = mode; }),

    setBottomCollapsed: (collapsed) =>
      set(s => { s.isBottomCollapsed = collapsed; }),

    setLeftCollapsed: (collapsed) =>
      set(s => { s.isLeftCollapsed = collapsed; }),

    setRightCollapsed: (collapsed) =>
      set(s => { s.isRightCollapsed = collapsed; }),

    // ── Zone field correction actions ────────────────────────────────────────
    setZoneFieldCorrection: (zoneId, fieldId, correction) =>
      set(s => {
        if (!s.zoneFieldCorrections[zoneId]) s.zoneFieldCorrections[zoneId] = {};
        s.zoneFieldCorrections[zoneId][fieldId] = { ...correction };
      }),

    clearZoneCorrections: (zoneId) =>
      set(s => {
        if (zoneId) {
          delete s.zoneFieldCorrections[zoneId];
        } else {
          s.zoneFieldCorrections = {};
        }
      }),

    // ── Smart Calibration actions ─────────────────────────────────────────────
    toggleSmartCalibration: () =>
      set(s => { s.smartCalibrationEnabled = !s.smartCalibrationEnabled; }),

    setCalibrationVector: (zoneId, vector) =>
      set(s => { s.calibrationVectors[zoneId] = vector; }),

    clearCalibrationVectors: () =>
      set(s => { s.calibrationVectors = {}; }),

    setLoading: (loading, status = '') =>
      set(s => { s.loading = loading; s.status = status; }),

    setStatus: (status) =>
      set(s => { s.status = status; }),

    /** Called after a successful /run or /hitl/rerun */
    applyRunResult: ({ run_id, artifacts, snapshots, timeline, schema, determinism_ok = true }) =>
      set(s => {
        s.runId = run_id;
        s.artifacts = artifacts ?? {};
        s.snapshots = snapshots ?? { ocr: null, geometry: null, topology: null, alignment: null, fusion: null, coordinate_space: null, shapes: null };
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

    setLayerOpacity: (key, val) =>
      set(s => { s.layerOpacities[key] = Math.max(0, Math.min(1, val)); }),

    setLayerRenderMode: (key, mode) =>
      set(s => { s.layerRenderModes[key] = mode; }),

    setIrLevel: (level) =>
      set(s => {
        s.irLevel = level;
        const active = IR_STAGE_LAYERS[level];
        if (active) {
          Object.keys(s.layers).forEach(k => {
            s.layers[k] = active.includes(k);
          });
        }
      }),

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
        if (!on) { s.compareRunId = null; s.compareSnapshots = { ocr: null, geometry: null, topology: null, alignment: null, fusion: null, coordinate_space: null, shapes: null }; }
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
        s.snapshots = { ocr: null, geometry: null, topology: null, alignment: null, fusion: null, coordinate_space: null, shapes: null };
        s.compareSnapshots = { ocr: null, geometry: null, topology: null, alignment: null, fusion: null, coordinate_space: null, shapes: null };
        s.timeline = null; s.schema = null; s.selected = null;
        s.loading = false; s.status = ''; s.compareMode = false; s.compareRunId = null;
        s.layers = { ...defaultLayers };
        s.layerOpacities = { ...defaultOpacities };
        s.layerRenderModes = { ...defaultRenderModes };
        s.irLevel = 'cognitive';
        s.zoom = 1; s.panOffset = { x: 0, y: 0 };
        s.pageImage = null; s.pageW = 1000; s.pageH = 1000;
        s.hitlLedger = []; s.determinismOk = true;
        s.workspaceMode = 'debug';
        s.isBottomCollapsed = false;
        s.isLeftCollapsed = false;
        s.isRightCollapsed = false;
        s.zoneFieldCorrections = {};
        s.smartCalibrationEnabled = false;
        s.calibrationVectors = {};
      }),
  }))
);
