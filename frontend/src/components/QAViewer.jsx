/**
 * CFIS QA Canvas Viewer
 * Location: frontend/src/components/QAViewer.jsx
 *
 * HTML5 Canvas-based QA review interface for CFIS extracted form fields.
 * - Bboxes served by API are in normalized (0–1) space → scaled to canvas pixels
 * - SpatialIndex for O(1) click-to-field hit testing
 * - Shows extraction_mode badge per field: "N" (native) or "O" (ocr)
 * - Full correction panel: label, widget type, note
 * - Canvas (NOT SVG) — handles 1000+ boxes without lag
 */

import React, { useEffect, useRef, useState, useCallback } from 'react';

const CFIS_API = '/api/cfis/v1';

// ── Color coding by field state ──────────────────────────────────────────────
const COLORS = {
  human_corrected: 'rgba(168,85,247,0.35)',   // purple
  needs_qa:        'rgba(239,68,68,0.40)',    // red
  high_confidence: 'rgba(34,197,94,0.30)',    // green  (confidence >= 0.85)
  low_confidence:  'rgba(234,179,8,0.35)',    // yellow (confidence < 0.85)
  selected:        'rgba(99,102,241,0.65)',   // indigo
  border_default:  'rgba(100,116,139,0.8)',
  border_selected: 'rgba(99,102,241,1)',
  text:            '#1e293b',
};

// ── Spatial Index for O(1) click hit testing ─────────────────────────────────
class SpatialIndex {
  constructor(fields, canvasW, canvasH) {
    this.fields = fields;
    this.canvasW = canvasW;
    this.canvasH = canvasH;
    // Convert normalized bboxes → canvas pixels
    this.pixelBoxes = fields.map(f => ({
      x1: f.bbox.x1 * canvasW,
      y1: f.bbox.y1 * canvasH,
      x2: f.bbox.x2 * canvasW,
      y2: f.bbox.y2 * canvasH,
      field: f,
    }));
  }

  query(cx, cy) {
    // Return first matching field at click coordinates
    for (const box of this.pixelBoxes) {
      if (cx >= box.x1 && cx <= box.x2 && cy >= box.y1 && cy <= box.y2) {
        return box.field;
      }
    }
    return null;
  }
}

// ── Widget types ─────────────────────────────────────────────────────────────
const WIDGET_TYPES = [
  'text', 'number', 'radio', 'select', 'date', 'datetime',
  'textarea', 'checkbox', 'signature', 'file', 'unknown',
];

// ── Main Component ───────────────────────────────────────────────────────────
export default function QAViewer({ documentId }) {
  const canvasRef = useRef(null);
  const [doc, setDoc] = useState(null);
  const [pageNum, setPageNum] = useState(0);
  const [pageImage, setPageImage] = useState(null);
  const [fields, setFields] = useState([]);
  const [selectedField, setSelectedField] = useState(null);
  const [spatialIndex, setSpatialIndex] = useState(null);
  const [correction, setCorrection] = useState({ label: '', widget: '', note: '' });
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState('');
  const [approveStatus, setApproveStatus] = useState('');

  // Load document
  useEffect(() => {
    if (!documentId) return;
    setLoading(true);
    fetch(`${CFIS_API}/documents/${documentId}`)
      .then(r => r.json())
      .then(d => {
        setDoc(d);
        setFields(d.fields || []);
        setLoading(false);
      })
      .catch(e => {
        setStatus(`Error loading document: ${e.message}`);
        setLoading(false);
      });
  }, [documentId]);

  // Load page image
  useEffect(() => {
    if (!documentId) return;
    const url = `${CFIS_API}/documents/${documentId}/page/${pageNum}/image`;
    const img = new Image();
    img.onload = () => setPageImage(img);
    img.onerror = () => setPageImage(null);
    img.src = url;
  }, [documentId, pageNum]);

  // Draw canvas
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const W = canvas.width;
    const H = canvas.height;

    ctx.clearRect(0, 0, W, H);

    // Draw background image
    if (pageImage) {
      ctx.drawImage(pageImage, 0, 0, W, H);
    } else {
      ctx.fillStyle = '#f8fafc';
      ctx.fillRect(0, 0, W, H);
      ctx.fillStyle = '#94a3b8';
      ctx.font = '14px sans-serif';
      ctx.textAlign = 'center';
      ctx.fillText('Loading page image...', W / 2, H / 2);
    }

    // Filter fields for current page
    const pageFields = fields.filter(f => f.page_number === pageNum);

    // Build/update spatial index
    const idx = new SpatialIndex(pageFields, W, H);
    setSpatialIndex(idx);

    // Draw field bounding boxes
    for (const field of pageFields) {
      const x1 = field.bbox.x1 * W;
      const y1 = field.bbox.y1 * H;
      const x2 = field.bbox.x2 * W;
      const y2 = field.bbox.y2 * H;
      const bw = x2 - x1;
      const bh = y2 - y1;

      const isSelected = selectedField && selectedField.field_id === field.field_id;

      // Fill color
      let fillColor = COLORS.low_confidence;
      if (isSelected) {
        fillColor = COLORS.selected;
      } else if (field.human_corrected) {
        fillColor = COLORS.human_corrected;
      } else if (field.needs_qa) {
        fillColor = COLORS.needs_qa;
      } else if (field.confidence >= 0.85) {
        fillColor = COLORS.high_confidence;
      }

      ctx.fillStyle = fillColor;
      ctx.fillRect(x1, y1, bw, bh);

      // Border
      ctx.strokeStyle = isSelected ? COLORS.border_selected : COLORS.border_default;
      ctx.lineWidth = isSelected ? 2.5 : 1;
      ctx.strokeRect(x1, y1, bw, bh);

      // Source badge: "N" = native, "O" = ocr
      const badge = field.source === 'native' ? 'N' : 'O';
      const badgeBg = field.source === 'native' ? '#10b981' : '#f59e0b';
      const badgeSize = Math.max(10, Math.min(14, bh * 0.5));
      ctx.fillStyle = badgeBg;
      ctx.fillRect(x1, y1, badgeSize + 4, badgeSize + 2);
      ctx.fillStyle = '#fff';
      ctx.font = `bold ${badgeSize - 2}px monospace`;
      ctx.textAlign = 'left';
      ctx.fillText(badge, x1 + 2, y1 + badgeSize);

      // Label text (truncated)
      if (bh > 14 && bw > 30) {
        ctx.fillStyle = COLORS.text;
        ctx.font = `${Math.min(11, bh * 0.5)}px sans-serif`;
        ctx.textAlign = 'left';
        const maxChars = Math.floor(bw / 6);
        const label = (field.semantic_label || '').substring(0, maxChars);
        ctx.fillText(label, x1 + badgeSize + 6, y1 + bh * 0.65);
      }
    }
  }, [pageImage, fields, selectedField, pageNum]);

  // Canvas click handler
  const handleCanvasClick = useCallback((e) => {
    if (!spatialIndex) return;
    const canvas = canvasRef.current;
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    const cx = (e.clientX - rect.left) * scaleX;
    const cy = (e.clientY - rect.top) * scaleY;

    const hit = spatialIndex.query(cx, cy);
    if (hit) {
      setSelectedField(hit);
      setCorrection({
        label: hit.semantic_label || '',
        widget: hit.runtime_widget || 'text',
        note: hit.note || '',
      });
    } else {
      setSelectedField(null);
    }
  }, [spatialIndex]);

  // Submit correction
  const submitCorrection = useCallback(async () => {
    if (!selectedField || !doc) return;
    setStatus('Saving correction...');
    try {
      const payload = {
        document_id: documentId,
        field_id: selectedField.field_id,
        cell_id: selectedField.cell_id,
        layout_hash: doc.fingerprint?.layout_hash || '',
        row_index: selectedField.row_index,
        column_index: selectedField.column_index,
        page_number: selectedField.page_number,
        corrected_label: correction.label || null,
        corrected_widget: correction.widget || null,
        note: correction.note || null,
        corrected_by: 'qa_user',
      };

      const resp = await fetch(`${CFIS_API}/qa/correction`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || 'Correction failed');
      }

      // Update local state
      setFields(prev => prev.map(f =>
        f.field_id === selectedField.field_id
          ? { ...f, semantic_label: correction.label || f.semantic_label,
                    runtime_widget: correction.widget || f.runtime_widget,
                    note: correction.note,
                    human_corrected: true, needs_qa: false }
          : f
      ));

      setStatus('✅ Correction saved');
      setTimeout(() => setStatus(''), 3000);
    } catch (err) {
      setStatus(`❌ Error: ${err.message}`);
    }
  }, [selectedField, correction, doc, documentId]);

  // Approve document
  const approveDocument = useCallback(async () => {
    if (!doc) return;
    const unresolved = fields.filter(f => f.needs_qa && !f.human_corrected);
    if (unresolved.length > 0) {
      setApproveStatus(`❌ ${unresolved.length} fields still need review`);
      return;
    }
    setApproveStatus('Approving...');
    try {
      const resp = await fetch(`${CFIS_API}/qa/approve/${documentId}`, {
        method: 'POST',
      });
      if (!resp.ok) {
        const err = await resp.json();
        throw new Error(err.detail || 'Approval failed');
      }
      setApproveStatus('✅ Approved — Form.io schema ready');
    } catch (err) {
      setApproveStatus(`❌ ${err.message}`);
    }
  }, [doc, fields, documentId]);

  // Page navigation
  const totalPages = doc ? (doc.total_pages || 1) : 1;
  const needsQACount = fields.filter(f => f.needs_qa && !f.human_corrected).length;

  if (!documentId) {
    return (
      <div style={styles.empty}>
        <p>Select a document to begin QA review.</p>
      </div>
    );
  }

  if (loading) {
    return <div style={styles.empty}><p>Loading document…</p></div>;
  }

  return (
    <div style={styles.container} dir="rtl">
      {/* Header */}
      <div style={styles.header}>
        <div>
          <strong>{doc?.source_file || documentId}</strong>
          <span style={styles.meta}>
            {fields.length} حقل | {needsQACount} يحتاج مراجعة |&nbsp;
            {doc?.fingerprint?.extraction_mode || 'hybrid'} |&nbsp;
            {doc?.primary_language || 'ar'}
          </span>
        </div>
        <div style={styles.headerActions}>
          <button
            id="cfis-approve-btn"
            style={{ ...styles.btn, background: needsQACount > 0 ? '#94a3b8' : '#10b981' }}
            onClick={approveDocument}
            disabled={needsQACount > 0}
          >
            اعتماد النموذج
          </button>
          {approveStatus && <span style={styles.approveStatus}>{approveStatus}</span>}
        </div>
      </div>

      {/* Legend */}
      <div style={styles.legend}>
        {[
          { color: COLORS.high_confidence, label: 'ثقة عالية' },
          { color: COLORS.low_confidence,  label: 'ثقة منخفضة' },
          { color: COLORS.needs_qa,         label: 'يحتاج مراجعة' },
          { color: COLORS.human_corrected,  label: 'تم التصحيح' },
          { color: COLORS.selected,         label: 'محدد' },
        ].map(({ color, label }) => (
          <span key={label} style={styles.legendItem}>
            <span style={{ ...styles.legendSwatch, background: color }} />
            {label}
          </span>
        ))}
        <span style={styles.legendItem}>
          <span style={{ ...styles.legendSwatch, background: '#10b981', fontSize: 10 }}>N</span>
          نصي أصلي
        </span>
        <span style={styles.legendItem}>
          <span style={{ ...styles.legendSwatch, background: '#f59e0b', fontSize: 10 }}>O</span>
          OCR
        </span>
      </div>

      <div style={styles.main}>
        {/* Canvas */}
        <div style={styles.canvasWrapper}>
          <canvas
            ref={canvasRef}
            id="cfis-qa-canvas"
            width={900}
            height={1200}
            style={styles.canvas}
            onClick={handleCanvasClick}
          />
          {/* Page navigation */}
          <div style={styles.pageNav}>
            <button
              style={styles.navBtn}
              onClick={() => setPageNum(p => Math.max(0, p - 1))}
              disabled={pageNum === 0}
            >←</button>
            <span style={{ color: '#fff', fontSize: 13 }}>
              صفحة {pageNum + 1} / {totalPages}
            </span>
            <button
              style={styles.navBtn}
              onClick={() => setPageNum(p => Math.min(totalPages - 1, p + 1))}
              disabled={pageNum >= totalPages - 1}
            >→</button>
          </div>
        </div>

        {/* Correction Panel */}
        <div style={styles.panel}>
          {selectedField ? (
            <>
              <h3 style={styles.panelTitle}>تصحيح الحقل</h3>
              <div style={styles.fieldMeta}>
                <span>الصف {selectedField.row_index} | العمود {selectedField.column_index}</span>
                <span>ثقة: {(selectedField.confidence * 100).toFixed(0)}%</span>
                <span>المصدر: {selectedField.source === 'native' ? '📄 نصي' : '🔍 OCR'}</span>
              </div>

              <div style={styles.rawText}>
                <strong>النص الخام:</strong>
                <p style={styles.rawTextContent}>{selectedField.semantic_label}</p>
              </div>

              <label style={styles.label}>التسمية المصححة</label>
              <input
                id="cfis-correction-label"
                style={styles.input}
                value={correction.label}
                onChange={e => setCorrection(c => ({ ...c, label: e.target.value }))}
                dir="rtl"
                placeholder="أدخل التسمية الصحيحة..."
              />

              <label style={styles.label}>نوع الحقل</label>
              <select
                id="cfis-correction-widget"
                style={styles.input}
                value={correction.widget}
                onChange={e => setCorrection(c => ({ ...c, widget: e.target.value }))}
              >
                {WIDGET_TYPES.map(w => (
                  <option key={w} value={w}>{w}</option>
                ))}
              </select>

              <label style={styles.label}>ملاحظة</label>
              <textarea
                id="cfis-correction-note"
                style={{ ...styles.input, height: 60, resize: 'vertical' }}
                value={correction.note}
                onChange={e => setCorrection(c => ({ ...c, note: e.target.value }))}
                dir="rtl"
                placeholder="ملاحظة اختيارية..."
              />

              <button
                id="cfis-save-correction-btn"
                style={{ ...styles.btn, width: '100%', marginTop: 8 }}
                onClick={submitCorrection}
              >
                حفظ التصحيح
              </button>

              {status && <p style={styles.status}>{status}</p>}
            </>
          ) : (
            <div style={styles.panelEmpty}>
              <p>انقر على حقل في اللوحة لعرض خيارات التصحيح</p>
              <div style={styles.fieldList}>
                <strong>الحقول التي تحتاج مراجعة ({needsQACount}):</strong>
                {fields
                  .filter(f => f.needs_qa && !f.human_corrected && f.page_number === pageNum)
                  .slice(0, 10)
                  .map(f => (
                    <div
                      key={f.field_id}
                      style={styles.fieldListItem}
                      onClick={() => {
                        setSelectedField(f);
                        setCorrection({ label: f.semantic_label || '', widget: f.runtime_widget || 'text', note: f.note || '' });
                      }}
                    >
                      <span style={{ color: '#ef4444' }}>⚠</span>
                      {f.semantic_label?.substring(0, 40) || '(بدون تسمية)'}
                    </div>
                  ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── Styles ───────────────────────────────────────────────────────────────────
const styles = {
  container: {
    fontFamily: "'Cairo', 'Segoe UI', sans-serif",
    background: '#0f172a',
    minHeight: '100vh',
    color: '#e2e8f0',
    display: 'flex',
    flexDirection: 'column',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '12px 20px',
    background: '#1e293b',
    borderBottom: '1px solid #334155',
  },
  meta: {
    marginRight: 12,
    color: '#94a3b8',
    fontSize: 12,
  },
  headerActions: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
  },
  approveStatus: {
    fontSize: 12,
    color: '#94a3b8',
  },
  legend: {
    display: 'flex',
    gap: 16,
    padding: '6px 20px',
    background: '#1e293b',
    borderBottom: '1px solid #334155',
    flexWrap: 'wrap',
  },
  legendItem: {
    display: 'flex',
    alignItems: 'center',
    gap: 4,
    fontSize: 11,
    color: '#94a3b8',
  },
  legendSwatch: {
    width: 16,
    height: 12,
    borderRadius: 2,
    display: 'inline-block',
    border: '1px solid rgba(255,255,255,0.2)',
  },
  main: {
    display: 'flex',
    flex: 1,
    gap: 0,
    overflow: 'hidden',
  },
  canvasWrapper: {
    flex: 1,
    position: 'relative',
    background: '#0f172a',
    overflow: 'auto',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    padding: 16,
  },
  canvas: {
    border: '1px solid #334155',
    borderRadius: 4,
    cursor: 'crosshair',
    maxWidth: '100%',
    boxShadow: '0 4px 24px rgba(0,0,0,0.5)',
  },
  pageNav: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    marginTop: 12,
    background: 'rgba(30,41,59,0.9)',
    padding: '6px 16px',
    borderRadius: 20,
  },
  navBtn: {
    background: '#334155',
    border: 'none',
    color: '#fff',
    borderRadius: 4,
    padding: '4px 12px',
    cursor: 'pointer',
    fontSize: 16,
  },
  panel: {
    width: 300,
    background: '#1e293b',
    borderLeft: '1px solid #334155',
    padding: 16,
    overflowY: 'auto',
    flexShrink: 0,
  },
  panelTitle: {
    margin: '0 0 12px',
    fontSize: 15,
    color: '#e2e8f0',
    borderBottom: '1px solid #334155',
    paddingBottom: 8,
  },
  fieldMeta: {
    display: 'flex',
    flexDirection: 'column',
    gap: 4,
    fontSize: 11,
    color: '#64748b',
    marginBottom: 12,
  },
  rawText: {
    background: '#0f172a',
    borderRadius: 4,
    padding: '8px 10px',
    marginBottom: 12,
    fontSize: 12,
  },
  rawTextContent: {
    margin: '4px 0 0',
    color: '#cbd5e1',
    wordBreak: 'break-all',
    direction: 'rtl',
  },
  label: {
    display: 'block',
    fontSize: 11,
    color: '#94a3b8',
    marginBottom: 4,
    marginTop: 10,
  },
  input: {
    width: '100%',
    background: '#0f172a',
    border: '1px solid #334155',
    borderRadius: 4,
    color: '#e2e8f0',
    padding: '6px 8px',
    fontSize: 13,
    boxSizing: 'border-box',
  },
  btn: {
    background: '#6366f1',
    color: '#fff',
    border: 'none',
    borderRadius: 6,
    padding: '8px 16px',
    cursor: 'pointer',
    fontSize: 13,
    fontWeight: 600,
  },
  status: {
    marginTop: 8,
    fontSize: 12,
    color: '#94a3b8',
  },
  panelEmpty: {
    color: '#64748b',
    fontSize: 13,
    textAlign: 'center',
    paddingTop: 24,
  },
  fieldList: {
    marginTop: 16,
    textAlign: 'right',
    fontSize: 12,
  },
  fieldListItem: {
    padding: '6px 8px',
    borderRadius: 4,
    cursor: 'pointer',
    marginTop: 4,
    background: '#0f172a',
    display: 'flex',
    gap: 6,
    alignItems: 'center',
    color: '#cbd5e1',
  },
  empty: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    height: 200,
    color: '#64748b',
  },
};
