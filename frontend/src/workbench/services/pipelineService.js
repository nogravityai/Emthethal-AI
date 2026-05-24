import axios from 'axios';

const API = axios.create({ baseURL: '' });

// ── Real Phase 3 Route Prefixes ──────────────────────────────────────────────
const V3_PIPELINE = '/api/cfis/v3/pipeline';
const V3_HITL = '/api/cfis/v3/hitl';
const V1_GEO = '/api/cfis/v1/debug/geometry'; // Phase 2 geometry debug (still v1)

// ============================================================================
//  PIPELINE SERVICE — TASK-P3-11 contracts
// ============================================================================

export const pipelineService = {
  /**
   * POST /v3/pipeline/run
   * Requires: { document_id, input_type: 'fixture', fixture_ocr, fixture_geometry }
   * Returns: { run_id, status, document_id, artifacts: { artifact_type → artifact_id } }
   */
  run: async (payload) => {
    const { data } = await API.post(`${V3_PIPELINE}/run`, payload);
    return data; // PipelineRunResponse
  },

  /**
   * POST /v3/pipeline/replay
   * TASK-P3-11B — replay from a stage (without HITL operations)
   * from_stage: 'alignment' | 'alignment_fusion'
   * Returns: { run_id, replayed_from, artifacts, determinism_ok }
   */
  replay: async (run_id, from_stage = 'alignment') => {
    const { data } = await API.post(`${V3_PIPELINE}/replay`, { run_id, from_stage });
    return data; // ReplayResponse
  },

  /**
   * GET /v3/pipeline/debug/{run_id}/{stage}
   * stage: 'ocr' | 'geometry' | 'alignment' | 'fusion'
   * Returns stage-specific snapshot with real stable_ids
   */
  getSnapshot: async (run_id, stage) => {
    const { data } = await API.get(`${V3_PIPELINE}/debug/${run_id}/${stage}`);
    return data;
  },

  /** Fetch all 7 snapshots in parallel */
  getAllSnapshots: async (run_id) => {
    const [ocr, geometry, topology, alignment, fusion, coordinate_space, shapes] = await Promise.allSettled([
      pipelineService.getSnapshot(run_id, 'ocr'),
      pipelineService.getSnapshot(run_id, 'geometry'),
      pipelineService.getSnapshot(run_id, 'topology'),
      pipelineService.getSnapshot(run_id, 'alignment'),
      pipelineService.getSnapshot(run_id, 'fusion'),
      pipelineService.getSnapshot(run_id, 'coordinate_space'),
      pipelineService.getSnapshot(run_id, 'shapes'),
    ]);
    return {
      ocr: ocr.status === 'fulfilled' ? ocr.value : null,
      geometry: geometry.status === 'fulfilled' ? geometry.value : null,
      topology: topology.status === 'fulfilled' ? topology.value : null,
      alignment: alignment.status === 'fulfilled' ? alignment.value : null,
      fusion: fusion.status === 'fulfilled' ? fusion.value : null,
      coordinate_space: coordinate_space.status === 'fulfilled' ? coordinate_space.value : null,
      shapes: shapes.status === 'fulfilled' ? shapes.value : null,
    };
  },

  /**
   * GET /v3/pipeline/export/{run_id}
   * Returns: { canonical_document, formio_schema }
   */
  getExport: async (run_id) => {
    const { data } = await API.get(`${V3_PIPELINE}/export/${run_id}`);
    return data;
  },

  /**
   * GET /v3/pipeline/runs/{run_id}/timeline
   * Returns: { run_id, document_id, stages: [{stage_name, output_type, artifact_id}], human_operations: [] }
   */
  getTimeline: async (run_id) => {
    const { data } = await API.get(`${V3_PIPELINE}/runs/${run_id}/timeline`);
    return data;
  },

  /**
   * GET /v3/pipeline/artifacts/{artifact_id}
   * TASK-P3-11C — artifact inspection (metadata + summary, no raw payload)
   */
  inspectArtifact: async (artifact_id) => {
    const { data } = await API.get(`${V3_PIPELINE}/artifacts/${artifact_id}`);
    return data;
  },
};

// ============================================================================
//  HITL SERVICE — TASK-P3-12 contracts
// ============================================================================

/**
 * All HITL operation types as defined in backend/app/services/hitl/models.py
 * These are the ONLY valid operation_type values.
 */
export const HITL_OP_TYPES = {
  LINE_REJECTION: 'line_rejection',       // HumanLineRejection
  LINE_APPROVAL: 'line_approval',         // HumanLineApproval
  REGION_MERGE: 'region_merge',          // HumanRegionMerge — needs source_regions[]
  REGION_SPLIT: 'region_split',          // HumanRegionSplit — needs split_coordinates{}
  TOKEN_REASSIGNMENT: 'token_reassignment',    // HumanTokenReassignment — needs token_id + new_region_id
  CHECKBOX_CORRECTION: 'checkbox_correction',   // HumanCheckboxCorrection — needs region_id + new_state
};

export const hitlService = {
  /**
   * POST /v3/hitl/operations
   * Logs an operation into the immutable ledger. Does NOT trigger rerun.
   * Returns: { status: "logged", operation_id: "..." }
   */
  submitOperation: async ({ operation_type, run_id, operator_id, target_evidence_ids, payload = {} }) => {
    const { data } = await API.post(`${V3_HITL}/operations`, {
      operation_type,
      run_id,
      operator_id,
      target_evidence_ids,
      payload,
    });
    return data;
  },

  /**
   * POST /v3/hitl/rerun
   * TASK-P3-12F — triggers rerun from evidence_patching stage onwards.
   * This is the CORRECT endpoint after HITL ops (not /pipeline/replay).
   * Returns: ReplayResponse { run_id, replayed_from, artifacts, determinism_ok }
   */
  rerun: async (run_id) => {
    const { data } = await API.post(`${V3_HITL}/rerun`, { run_id });
    return data;
  },

  /**
   * GET /v3/hitl/runs/{run_id}/operations
   * Returns the full ledger of human operations for a run.
   */
  getOperations: async (run_id) => {
    const { data } = await API.get(`${V3_HITL}/runs/${run_id}/operations`);
    return data; // { run_id, operations: HumanOperation[] }
  },
};

// ============================================================================
//  GEOMETRY DEBUG SERVICE — Phase 2 v1 (for PDF → page image + fixture data)
// ============================================================================

export const geometryDebugService = {
  /**
   * POST /api/cfis/v1/debug/geometry
   * Extracts page image (base64) + geometry boxes from uploaded PDF.
   * Used to build a fixture_geometry payload for Phase 3 pipeline.
   */
  extractFromPdf: async (file, params = {}) => {
    const form = new FormData();
    form.append('file', file);
    const { data } = await API.post(V1_GEO, form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      params: {
        page_number: 0,
        dpi: 150,
        layers: 'lines,boxes,anchors',
        run_inference: true,
        run_merger: true,
        run_radio: true,
        ...params,
      },
    });
    return data; // { page_image_b64, layers: { boxes, lines }, border_audit }
  },
};

// ============================================================================
//  ORCHESTRATION — Full pipeline run + HITL → rerun flows
// ============================================================================

/** Run fixture pipeline and retrieve all artifacts in one call */
export async function runFixturePipeline(fixturePayload) {
  const runResult = await pipelineService.run(fixturePayload);
  const run_id = runResult.run_id;

  const [snapshots, timeline, schema] = await Promise.allSettled([
    pipelineService.getAllSnapshots(run_id),
    pipelineService.getTimeline(run_id),
    pipelineService.getExport(run_id),
  ]);

  return {
    run_id,
    artifacts: runResult.artifacts,
    snapshots: snapshots.status === 'fulfilled' ? snapshots.value
      : { ocr: null, geometry: null, topology: null, alignment: null, fusion: null, coordinate_space: null, shapes: null },
    timeline: timeline.status === 'fulfilled' ? timeline.value : null,
    schema: schema.status === 'fulfilled' ? schema.value : null,
  };
}

/**
 * HITL Workflow:
 * 1. Submit operation → logged in ledger
 * 2. Trigger rerun from evidence_patching (not pipeline/replay)
 * 3. Re-fetch all snapshots
 */
export async function submitHitlAndRerun({ operation_type, run_id, operator_id, target_evidence_ids, payload = {} }) {
  // Step 1: Log the operation
  const opResult = await hitlService.submitOperation({
    operation_type, run_id, operator_id, target_evidence_ids, payload,
  });

  // Step 2: Rerun from evidence_patching (applies all ledger ops)
  const rerunResult = await hitlService.rerun(run_id);

  // Step 3: Re-fetch updated snapshots
  const [snapshots, timeline, schema] = await Promise.allSettled([
    pipelineService.getAllSnapshots(run_id),
    pipelineService.getTimeline(run_id),
    pipelineService.getExport(run_id),
  ]);

  return {
    operation_id: opResult.operation_id,
    determinism_ok: rerunResult.determinism_ok,
    replayed_from: rerunResult.replayed_from,
    snapshots: snapshots.status === 'fulfilled' ? snapshots.value : null,
    timeline: timeline.status === 'fulfilled' ? timeline.value : null,
    schema: schema.status === 'fulfilled' ? schema.value : null,
  };
}

/**
 * Extract PDF via Phase 2 geometry debug, then run Phase 3 fixture pipeline.
 * Bridges Phase 2 (real geometry) → Phase 3 (evidence pipeline).
 */
export async function processPdfThroughPipeline(file) {
  // Phase 2 extraction
  const geoData = await geometryDebugService.extractFromPdf(file);

  const pageW = geoData.page_width ?? 1000;
  const pageH = geoData.page_height ?? 1000;

  const rawGeo = geoData.raw_geometry || { tokens: [], lines: [], boxes: [] };

  const fixturePayload = {
    document_id: `pdf_${Date.now().toString(36)}`,
    input_type: 'fixture',
    pipeline_version: '3.0.0',
    fixture_ocr: {
      source_engine: 'hybrid_phase2',
      engine_version: 'phase2_geometry',
      page_width: pageW,
      page_height: pageH,
      page_number: 0,
      tokens: rawGeo.tokens.map(t => {
        let coords = [0, 0, 0, 0];
        if (Array.isArray(t.bbox)) {
          coords = t.bbox;
        } else if (t.bbox && typeof t.bbox === 'object') {
          coords = [t.bbox.x1, t.bbox.y1, t.bbox.x2, t.bbox.y2];
        } else if (Array.isArray(t.box_2d)) {
          coords = t.box_2d;
        }
        return {
          bbox: coords,
          text: t.ocr_raw_text || t.text || t.text_content || '—',
          confidence: t.confidence || 0.9,
          space: 'page_pixels',
        };
      }),
    },
    fixture_geometry: {
      meta: {
        opencv_version: '4.10.0',
        kernel_signature: 'morph_rect',
        dpi_normalization: 'identity',
        original_space: 'page_pixels',
        page_width: pageW,
        page_height: pageH,
      },
      lines: rawGeo.lines.map(l => {
        let coords = [0, 0, 0, 0];
        if (Array.isArray(l.bbox)) {
          coords = l.bbox;
        } else if (l.x1 !== undefined && l.y1 !== undefined) {
          coords = [l.x1, l.y1, l.x2, l.y2];
        }
        return {
          bbox: coords,
          x1: coords[0], y1: coords[1], x2: coords[2], y2: coords[3],
          orientation: l.orientation || 'horizontal',
          thickness: l.thickness || 1,
        };
      }),
      boxes: rawGeo.boxes.map(b => {
        let coords = [0, 0, 0, 0];
        if (Array.isArray(b.bbox)) {
          coords = b.bbox;
        } else if (b.bbox && typeof b.bbox === 'object') {
          coords = [b.bbox.x1, b.bbox.y1, b.bbox.x2, b.bbox.y2];
        }
        return {
          bbox: coords,
          confidence: b.confidence || 0.9,
          box_type: b.box_type || 'unknown'
        };
      }),
    },
  };

  const result = await runFixturePipeline(fixturePayload);
  return {
    ...result,
    pageImage: geoData.page_image_b64 ? `data:image/png;base64,${geoData.page_image_b64}` : null,
    pageW,
    pageH,
  };
}
