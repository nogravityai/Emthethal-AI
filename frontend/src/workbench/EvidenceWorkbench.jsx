/**
 * CFIS Phase 4 — Evidence Intelligence Workbench
 * 
 * Architecture: Stateless Replay Client
 * - Never mutates backend results directly
 * - All edits = HumanOperation → /hitl/operations → /hitl/rerun → new snapshot
 * - Every field maps to a real Phase 3 backend model
 */
import React, { useEffect, useCallback, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useWorkbenchStore, LAYER_META, PIPELINE_STAGES } from './store/workbenchStore.js';
import {
  runFixturePipeline,
  processPdfThroughPipeline,
  submitHitlAndRerun,
  pipelineService,
  hitlService,
  HITL_OP_TYPES,
} from './services/pipelineService.js';

// ── Sub-panels (lazy-split for bundle size) ──────────────────────────────────
import TopBar        from './panels/TopBar.jsx';
import LeftPanel     from './panels/LeftPanel.jsx';
import DocumentViewer from './panels/DocumentViewer.jsx';
import RightPanel    from './panels/RightPanel.jsx';
import BottomPanel   from './panels/BottomPanel.jsx';

// Demo fixture — real Phase 3 API payload shape
const DEMO_FIXTURE = {
  document_id: `demo_${Date.now().toString(36)}`,
  input_type: 'fixture',
  pipeline_version: '3.0.0',
  fixture_ocr: {
    source_engine: 'paddleocr',
    engine_version: '2.6.0',
    page_width: 1000,
    page_height: 1200,
    page_number: 1,
    tokens: [
      { bbox: [50, 50, 260, 80],  text: 'اسم المريض:',    confidence: 0.99, space: 'page_pixels' },
      { bbox: [270, 50, 480, 80], text: 'محمد أحمد علي',  confidence: 0.96, space: 'page_pixels' },
      { bbox: [50, 110, 160, 138], text: 'العمر:',         confidence: 0.98, space: 'page_pixels' },
      { bbox: [170, 110, 230, 138], text: '42 سنة',        confidence: 0.95, space: 'page_pixels' },
      { bbox: [50, 170, 210, 198], text: 'التشخيص:',      confidence: 0.97, space: 'page_pixels' },
      { bbox: [220, 170, 520, 198], text: 'حالة مستقرة',   confidence: 0.89, space: 'page_pixels' },
      { bbox: [50, 230, 80, 258],  text: '☑',              confidence: 0.99, space: 'page_pixels' },
      { bbox: [95, 230, 300, 258], text: 'موافق على العلاج', confidence: 0.94, space: 'page_pixels' },
      { bbox: [50, 290, 80, 318],  text: '☐',              confidence: 0.92, space: 'page_pixels' },
      { bbox: [95, 290, 290, 318], text: 'رفض العلاج',     confidence: 0.91, space: 'page_pixels' },
    ],
  },
  fixture_geometry: {
    meta: {
      opencv_version: '4.10.0',
      kernel_signature: 'morph_rect',
      dpi_normalization: 'identity',
      original_space: 'page_pixels',
      page_width: 1000,
      page_height: 1200,
    },
    lines: [],
    boxes: [
      { bbox: [40, 40, 500, 92],  confidence: 0.97 },
      { bbox: [40, 100, 260, 150], confidence: 0.96 },
      { bbox: [40, 160, 540, 210], confidence: 0.93 },
      { bbox: [40, 220, 320, 270], confidence: 0.91 },
      { bbox: [40, 280, 310, 330], confidence: 0.88 },
    ],
  },
};

export default function EvidenceWorkbench() {
  const {
    runId, loading, status,
    applyRunResult, applyHitlRerun,
    setLoading, setStatus,
    setPageCanvas, setHitlLedger,
    resetWorkbench,
    workspaceMode, isLeftCollapsed, isRightCollapsed,
    setLeftCollapsed, setRightCollapsed,
  } = useWorkbenchStore();

  const fileRef = useRef();

  // ── Keyboard shortcuts ──────────────────────────────────────────────────────
  useEffect(() => {
    const handler = (e) => {
      if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

      // Layer toggles: 1–8
      if (e.key >= '1' && e.key <= '8') {
        const layerKeys = Object.keys(LAYER_META);
        const idx = parseInt(e.key, 10) - 1;
        if (layerKeys[idx]) useWorkbenchStore.getState().toggleLayer(layerKeys[idx]);
      }
      // Zoom
      if (e.key === '=' || e.key === '+') useWorkbenchStore.getState().adjustZoom(0.15);
      if (e.key === '-')                   useWorkbenchStore.getState().adjustZoom(-0.15);
      if (e.key === '0')                   useWorkbenchStore.getState().resetView();
      // Escape = deselect
      if (e.key === 'Escape')              useWorkbenchStore.getState().clearSelected();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  // ── Run demo fixture ────────────────────────────────────────────────────────
  const handleRunDemo = useCallback(async () => {
    setLoading(true, 'Sending fixture to /api/cfis/v3/pipeline/run…');
    try {
      // Use a fresh document_id each time
      const payload = {
        ...DEMO_FIXTURE,
        document_id: `demo_${Date.now().toString(36)}`,
      };
      const result = await runFixturePipeline(payload);
      applyRunResult(result);
    } catch (err) {
      setLoading(false, `Error: ${err.response?.data?.detail ?? err.message}`);
    }
  }, [setLoading, applyRunResult]);

  // ── Upload PDF ──────────────────────────────────────────────────────────────
  const handleFileUpload = useCallback(async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      setStatus('Only PDF files accepted');
      return;
    }
    setLoading(true, `Extracting geometry from ${file.name} via Phase 2…`);
    try {
      const result = await processPdfThroughPipeline(file);
      if (result.pageImage) {
        setPageCanvas({ pageImage: result.pageImage, pageW: result.pageW, pageH: result.pageH });
      }
      applyRunResult(result);
    } catch (err) {
      setLoading(false, `Error: ${err.response?.data?.detail ?? err.message}`);
    }
  }, [setLoading, setPageCanvas, applyRunResult]);

  // ── HITL operation dispatch ────────────────────────────────────────────────
  // This function is exposed globally via store so child panels can call it
  const handleHitlOperation = useCallback(async ({
    operation_type, target_evidence_ids, payload = {},
  }) => {
    if (!runId) return;
    setLoading(true, `Logging ${operation_type} → /api/cfis/v3/hitl/operations…`);
    try {
      const result = await submitHitlAndRerun({
        operation_type,
        run_id: runId,
        operator_id: 'operator_console_v3',
        target_evidence_ids,
        payload,
      });
      // Refresh ledger
      try {
        const ledger = await hitlService.getOperations(runId);
        setHitlLedger(ledger.operations ?? []);
      } catch (_) {}

      applyHitlRerun(result);
    } catch (err) {
      setLoading(false, `HITL error: ${err.response?.data?.detail ?? err.message}`);
    }
  }, [runId, setLoading, applyHitlRerun, setHitlLedger]);

  // ── Expose handleHitlOperation on window for panels that can't use hooks ──
  useEffect(() => {
    window.__cfisHitl = handleHitlOperation;
    return () => { delete window.__cfisHitl; };
  }, [handleHitlOperation]);

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        background: '#05080F',
        color: '#E2E8F0',
        fontFamily: "'Inter', 'Segoe UI', sans-serif",
        overflow: 'hidden',
        position: 'relative',
      }}
    >
      {/* ── TOP BAR ─────────────────────────────────────────────────── */}
      <TopBar
        onRunDemo={handleRunDemo}
        onUploadClick={() => fileRef.current?.click()}
      />

      <input
        ref={fileRef}
        type="file"
        style={{ display: 'none' }}
        accept="application/pdf"
        onChange={handleFileUpload}
      />

      {/* ── MAIN 3-COLUMN AREA ─────────────────────────────────────── */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0, position: 'relative' }}>
        {workspaceMode !== 'inspect' && !isLeftCollapsed && (
          <LeftPanel onHitlOp={handleHitlOperation} />
        )}

        {workspaceMode !== 'inspect' && (
          <button
            onClick={() => setLeftCollapsed(!isLeftCollapsed)}
            style={{
              width: 10,
              background: '#0B1120',
              border: 'none',
              borderRight: '1px solid #1A2438',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justify: 'center',
              color: '#64748B',
              fontSize: 8,
              padding: 0,
              zIndex: 10,
            }}
            title={isLeftCollapsed ? "Expand Left Panel" : "Collapse Left Panel"}
          >
            {isLeftCollapsed ? '▶' : '◀'}
          </button>
        )}

        <DocumentViewer />

        {workspaceMode !== 'inspect' && (
          <button
            onClick={() => setRightCollapsed(!isRightCollapsed)}
            style={{
              width: 10,
              background: '#0B1120',
              border: 'none',
              borderLeft: '1px solid #1A2438',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justify: 'center',
              color: '#64748B',
              fontSize: 8,
              padding: 0,
              zIndex: 10,
            }}
            title={isRightCollapsed ? "Expand Right Panel" : "Collapse Right Panel"}
          >
            {isRightCollapsed ? '◀' : '▶'}
          </button>
        )}

        {workspaceMode !== 'inspect' && !isRightCollapsed && (
          <RightPanel />
        )}
      </div>

      {/* ── BOTTOM PANEL ────────────────────────────────────────────── */}
      {workspaceMode !== 'inspect' && (
        <BottomPanel />
      )}

      {/* ── GLOBAL LOADING OVERLAY ────────────────────────────────── */}
      <AnimatePresence>
        {loading && (
          <motion.div
            key="loader"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            style={{
              position: 'absolute', inset: 0,
              background: 'rgba(5,8,15,0.82)',
              display: 'flex', flexDirection: 'column',
              alignItems: 'center', justifyContent: 'center',
              zIndex: 100, backdropFilter: 'blur(6px)',
            }}
          >
            <div style={{
              width: 52, height: 52,
              border: '3px solid rgba(59,130,246,0.2)',
              borderTopColor: '#3B82F6',
              borderRadius: '50%',
              animation: 'cfis-spin 0.8s linear infinite',
              marginBottom: 20,
            }} />
            <div style={{ color: '#3B82F6', fontFamily: 'monospace', fontSize: 13, letterSpacing: '0.08em' }}>
              {status || 'PROCESSING…'}
            </div>
            <div style={{ color: '#475569', fontSize: 10, marginTop: 8, letterSpacing: '0.1em' }}>
              CFIS-P3 · DETERMINISTIC PIPELINE
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <style>{`
        @keyframes cfis-spin { to { transform: rotate(360deg); } }
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 4px; height: 4px; }
        ::-webkit-scrollbar-track { background: #05080F; }
        ::-webkit-scrollbar-thumb { background: #1A2438; border-radius: 2px; }
        ::-webkit-scrollbar-thumb:hover { background: #2D3D58; }
      `}</style>
    </div>
  );
}
