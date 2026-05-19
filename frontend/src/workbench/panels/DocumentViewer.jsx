/**
 * Document Viewer — Canvas with Evidence Layer Overlays
 * 
 * Renders all Phase 3 snapshot data as pixel-accurate overlays.
 * Each layer maps to a specific backend artifact_type:
 *   ocr layer       → ocr_evidence tokens    (token.id = stable_id SHA-256)
 *   geometry layer  → geometry_evidence regions
 *   alignment layer → alignment_evidence (type: AlignmentType enum)
 *   fusion layer    → resolved_fields
 * 
 * The viewer is READ-ONLY. Clicking an element triggers selection only.
 * Mutations happen via the HITL panel → API → new snapshot.
 */
import React, { useRef, useState, useCallback, useEffect } from 'react';
import { useWorkbenchStore, LAYER_META, ALIGNMENT_TYPES } from '../store/workbenchStore.js';

const C = {
  bg: '#05080F', border: '#1A2438', muted: '#64748B', text: '#E2E8F0',
  green: '#10B981', blue: '#3B82F6', pink: '#EC4899', purple: '#A78BFA',
  red: '#EF4444', orange: '#F97316', yellow: '#F59E0B', accent: '#0EA5E9',
};

// AlignmentType → color mapping (matches backend AlignmentType enum)
const ALIGNMENT_COLORS = {
  [ALIGNMENT_TYPES.TOKEN_INSIDE_REGION]:    C.green,
  [ALIGNMENT_TYPES.TOKEN_CROSSES_BOUNDARY]: C.red,
  [ALIGNMENT_TYPES.TOKEN_TOUCHING_REGION]:  C.yellow,
};

const MAX_DISPLAY_W = 860;

export default function DocumentViewer() {
  const {
    runId, snapshots, layers, selected, setSelected,
    pageImage, pageW, pageH, zoom, panOffset, setPan,
  } = useWorkbenchStore();

  const containerRef = useRef();
  const isDragging = useRef(false);
  const dragStart = useRef({ x: 0, y: 0, px: 0, py: 0 });

  // Display dimensions — canvas size in CSS pixels
  const baseW = Math.min(pageW, MAX_DISPLAY_W);
  const baseH = Math.round(baseW * (pageH / pageW));
  const displayW = Math.round(baseW * zoom);
  const displayH = Math.round(baseH * zoom);

  // Scale a backend bbox [x1,y1,x2,y2] (page_pixels) → display pixels
  const scale = useCallback((bbox) => {
    const sx = displayW / pageW;
    const sy = displayH / pageH;
    return [bbox[0] * sx, bbox[1] * sy, bbox[2] * sx, bbox[3] * sy];
  }, [displayW, displayH, pageW, pageH]);

  const downloadAsImage = () => {
    if (!pageImage) return;

    const canvas = document.createElement('canvas');
    canvas.width = pageW;
    canvas.height = pageH;
    const ctx = canvas.getContext('2d');

    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.src = pageImage;
    img.onload = () => {
      // 1. Draw original document page image
      ctx.drawImage(img, 0, 0, pageW, pageH);

      // 2. Draw Geometry Layer
      if (layers.geometry && snapshots.geometry?.regions) {
        ctx.lineWidth = 3;
        ctx.strokeStyle = '#3B82F6';
        snapshots.geometry.regions.forEach(r => {
          const [x1, y1, x2, y2] = r.bbox;
          ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
          if (selected?.data?.id === r.id) {
            ctx.fillStyle = 'rgba(59, 130, 246, 0.15)';
            ctx.fillRect(x1, y1, x2 - x1, y2 - y1);
          }
        });
      }

      // 3. Draw OCR Token Layer
      if (layers.ocr && snapshots.ocr?.tokens) {
        ctx.lineWidth = 2;
        ctx.strokeStyle = '#10B981';
        snapshots.ocr.tokens.forEach(t => {
          const [x1, y1, x2, y2] = t.bbox;
          ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
          ctx.fillStyle = selected?.data?.id === t.id ? 'rgba(16, 185, 129, 0.25)' : 'rgba(16, 185, 129, 0.08)';
          ctx.fillRect(x1, y1, x2 - x1, y2 - y1);

          const fontSize = Math.max(9, (y2 - y1) * 0.45);
          ctx.font = `bold ${fontSize}px sans-serif`;
          ctx.fillStyle = '#064E3B';
          ctx.textBaseline = 'middle';
          ctx.fillText(t.text || '', x1 + 2, y1 + (y2 - y1) / 2);
        });
      }

      // 4. Draw Alignment Layer
      if (layers.alignment && snapshots.alignment?.alignments) {
        ctx.lineWidth = 1.5;
        ctx.setLineDash([5, 3]);
        snapshots.alignment.alignments.forEach(a => {
          const tok = snapshots.ocr?.tokens?.find(t => t.id === a.token);
          const reg = snapshots.geometry?.regions?.find(r => r.id === a.region);
          if (!tok || !reg) return;

          const [tx1, ty1, tx2, ty2] = tok.bbox;
          const [rx1, ry1, rx2, ry2] = reg.bbox;
          const tx = (tx1 + tx2) / 2, ty = (ty1 + ty2) / 2;
          const rx = (rx1 + rx2) / 2, ry = (ry1 + ry2) / 2;

          ctx.strokeStyle = ALIGNMENT_COLORS[a.type] ?? '#EC4899';
          ctx.beginPath();
          ctx.moveTo(tx, ty);
          ctx.lineTo(rx, ry);
          ctx.stroke();
        });
        ctx.setLineDash([]);
      }

      // 5. Draw Fusion Layer
      if (layers.fusion && snapshots.fusion?.fields) {
        ctx.font = 'bold 10px monospace';
        snapshots.fusion.fields.forEach(f => {
          const tok = snapshots.ocr?.tokens?.find(t => f.ocr_tokens?.includes(t.id));
          if (!tok) return;
          const [, y1, x2] = tok.bbox;
          const score = f.confidence ?? 0;
          const color = score > 0.85 ? '#10B981' : score > 0.6 ? '#F59E0B' : '#EF4444';

          ctx.fillStyle = '#0B1120';
          ctx.strokeStyle = color;
          ctx.lineWidth = 1;

          const text = `${(score * 100).toFixed(0)}%`;
          const textW = ctx.measureText(text).width;
          ctx.fillRect(x2 + 3, y1, textW + 12, 14);
          ctx.strokeRect(x2 + 3, y1, textW + 12, 14);

          ctx.fillStyle = color;
          ctx.fillText(text, x2 + 9, y1 + 7);
        });
      }

      try {
        const dataUrl = canvas.toDataURL('image/png');
        const link = document.createElement('a');
        link.download = `evidence_workbench_${runId || 'extract'}.png`;
        link.href = dataUrl;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
      } catch (err) {
        console.error('Failed to download composite image:', err);
      }
    };
  };

  // Pan drag
  const onMouseDown = (e) => {
    // Allow dragging from the container or the background wrapper
    isDragging.current = true;
    dragStart.current = { x: e.clientX, y: e.clientY, px: panOffset.x, py: panOffset.y };
    if (containerRef.current) containerRef.current.style.cursor = 'grabbing';
  };
  const onMouseMove = (e) => {
    if (!isDragging.current) return;
    setPan({ x: dragStart.current.px + e.clientX - dragStart.current.x, y: dragStart.current.py + e.clientY - dragStart.current.y });
  };
  const onMouseUp = () => {
    isDragging.current = false;
    if (containerRef.current) containerRef.current.style.cursor = 'grab';
  };

  // Wheel zoom
  const onWheel = useCallback((e) => {
    e.preventDefault();
    const delta = e.deltaY > 0 ? -0.1 : 0.1;
    useWorkbenchStore.getState().adjustZoom(delta);
  }, []);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [onWheel]);

  if (!runId) {
    return (
      <div style={{
        flex: 1, display: 'flex', flexDirection: 'column',
        alignItems: 'center', justifyContent: 'center',
        background: `radial-gradient(ellipse at 50% 30%, #0D1F3C 0%, ${C.bg} 70%)`,
        color: C.muted, userSelect: 'none',
      }}>
        <div style={{ fontSize: 72, marginBottom: 20, opacity: 0.12 }}>🧬</div>
        <div style={{ fontSize: 18, fontWeight: 300, letterSpacing: '0.25em', textTransform: 'uppercase', marginBottom: 8 }}>
          Awaiting Document
        </div>
        <div style={{ fontSize: 11, opacity: 0.5 }}>Upload a PDF or run the demo fixture to begin</div>
        <div style={{ marginTop: 24, display: 'flex', gap: 16, fontSize: 9, color: C.muted, letterSpacing: '0.08em', textTransform: 'uppercase', fontWeight: 700 }}>
          <span>1–7 · Toggle Layers</span>
          <span>+/− · Zoom</span>
          <span>0 · Reset View</span>
          <span>Esc · Deselect</span>
        </div>
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      onMouseDown={onMouseDown}
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
      onMouseLeave={onMouseUp}
      style={{
        flex: 1,
        overflow: 'hidden',
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'flex-start',
        background: `radial-gradient(ellipse at 50% 30%, #0D1F3C 0%, ${C.bg} 70%)`,
        cursor: 'grab',
        position: 'relative',
      }}
    >
      {/* Scrollable inner area */}
      <div style={{
        transform: `translate(${panOffset.x}px, ${panOffset.y}px)`,
        transformOrigin: '0 0',
        padding: 40,
        userSelect: 'none',
        pointerEvents: 'none', // container doesn't capture clicks, canvas elements do
      }}>
        {/* Document canvas */}
        <div style={{
          position: 'relative',
          width: displayW,
          height: displayH,
          background: '#FAFAFA',
          boxShadow: '0 4px 60px rgba(0,0,0,0.8)',
          borderRadius: 2,
          overflow: 'hidden',
          flexShrink: 0,
          pointerEvents: 'auto',
        }}>
          {/* Page image */}
          {pageImage
            ? <img draggable={false} src={pageImage} alt="Document page" width={displayW} height={displayH} style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'fill', pointerEvents: 'none', userSelect: 'none' }} />
            : <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <span style={{ fontSize: 10, color: '#94a3b8', textAlign: 'center' }}>Demo Fixture Mode<br />Upload a PDF to see the real document</span>
              </div>
          }

          {/* ── GEOMETRY LAYER ────────────────────────────────────── */}
          {layers.geometry && snapshots.geometry?.regions?.map(r => {
            const [x1, y1, x2, y2] = scale(r.bbox);
            const isSel = selected?.data?.id === r.id;
            return (
              <div
                key={r.id}
                onClick={(e) => { e.stopPropagation(); setSelected({ type: 'region', data: r }); }}
                title={`Region · ${(r.confidence * 100).toFixed(0)}% · ${r.id?.slice(0, 12)}…`}
                style={{
                  position: 'absolute',
                  left: x1, top: y1, width: x2 - x1, height: y2 - y1,
                  border: `2px solid ${isSel ? C.blue : C.blue + '80'}`,
                  background: isSel ? `${C.blue}28` : `${C.blue}0F`,
                  cursor: 'pointer', zIndex: 1,
                  boxShadow: isSel ? `0 0 0 2px ${C.blue}, 0 0 16px ${C.blue}50` : 'none',
                  transition: 'box-shadow 0.15s',
                }}
              />
            );
          })}

          {/* ── OCR TOKEN LAYER ───────────────────────────────────── */}
          {layers.ocr && snapshots.ocr?.tokens?.map(t => {
            const [x1, y1, x2, y2] = scale(t.bbox);
            const isSel = selected?.data?.id === t.id;
            const alpha = Math.round(t.confidence * 80 + 30).toString(16).padStart(2, '0');
            return (
              <div
                key={t.id}
                onClick={(e) => { e.stopPropagation(); setSelected({ type: 'token', data: t }); }}
                title={`"${t.text}" · ${(t.confidence * 100).toFixed(0)}% · ${t.id?.slice(0, 12)}…`}
                style={{
                  position: 'absolute',
                  left: x1, top: y1, width: x2 - x1, height: y2 - y1,
                  border: `1.5px solid ${C.green}${isSel ? '' : '80'}`,
                  background: isSel ? `${C.green}35` : `${C.green}18`,
                  cursor: 'pointer', zIndex: 3,
                  display: 'flex', alignItems: 'center', overflow: 'hidden',
                  boxShadow: isSel ? `0 0 0 2px ${C.green}, 0 0 12px ${C.green}50` : 'none',
                  transition: 'box-shadow 0.15s',
                }}
              >
                <span style={{
                  fontSize: Math.max(7, (y2 - y1) * 0.45),
                  color: '#064E3B', fontWeight: 700,
                  padding: '0 2px', direction: 'rtl',
                  width: '100%', overflow: 'hidden', whiteSpace: 'nowrap',
                  pointerEvents: 'none',
                }}>{t.text}</span>
              </div>
            );
          })}

          {/* ── ALIGNMENT LAYER (SVG arrows) ──────────────────────── */}
          {layers.alignment && snapshots.alignment?.alignments && (
            <svg
              style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none', zIndex: 4 }}
              aria-hidden="true"
            >
              {snapshots.alignment.alignments.map(a => {
                const tok = snapshots.ocr?.tokens?.find(t => t.id === a.token);
                const reg = snapshots.geometry?.regions?.find(r => r.id === a.region);
                if (!tok || !reg) return null;
                const [tx1, ty1, tx2, ty2] = scale(tok.bbox);
                const [rx1, ry1, rx2, ry2] = scale(reg.bbox);
                const tx = (tx1 + tx2) / 2, ty = (ty1 + ty2) / 2;
                const rx = (rx1 + rx2) / 2, ry = (ry1 + ry2) / 2;
                const color = ALIGNMENT_COLORS[a.type] ?? C.pink;
                return (
                  <line
                    key={a.id}
                    x1={tx} y1={ty} x2={rx} y2={ry}
                    stroke={color} strokeWidth={1.5} strokeDasharray="5 3" opacity={0.65}
                  />
                );
              })}
            </svg>
          )}

          {/* ── FUSION FIELD LAYER ────────────────────────────────── */}
          {layers.fusion && snapshots.fusion?.fields?.map((f, idx) => {
            const tok = snapshots.ocr?.tokens?.find(t => f.ocr_tokens?.includes(t.id));
            if (!tok) return null;
            const [, y1, x2] = scale(tok.bbox);
            const score = f.confidence ?? 0;
            const color = score > 0.85 ? C.green : score > 0.6 ? C.yellow : C.red;
            const isSel = selected?.data?.id === f.id || selected?.data?.field_id === f.id;
            return (
              <div
                key={f.id ?? idx}
                onClick={(e) => { e.stopPropagation(); setSelected({ type: 'field', data: f }); }}
                title={`Field · ${(score * 100).toFixed(0)}% · ${f.field_type ?? 'inferred'}`}
                style={{
                  position: 'absolute',
                  left: x2 + 3, top: y1,
                  padding: '2px 6px', borderRadius: 4,
                  background: '#0B1120', border: `1px solid ${color}`,
                  fontSize: 8, fontFamily: 'monospace', color, zIndex: 5,
                  cursor: 'pointer', whiteSpace: 'nowrap',
                  boxShadow: isSel ? `0 0 6px ${color}60` : 'none',
                }}
              >
                {(score * 100).toFixed(0)}%
              </div>
            );
          })}

          {/* ── ORPHAN LAYER ──────────────────────────────────────── */}
          {layers.orphan && snapshots.fusion?.orphans?.map((o, i) => {
            const tok = snapshots.ocr?.tokens?.find(t => t.id === (o.token_id ?? o.id));
            if (!tok) return null;
            const [x1, y1, x2, y2] = scale(tok.bbox);
            return (
              <div
                key={o.id ?? i}
                title="Orphan token — no alignment to any region"
                style={{
                  position: 'absolute', left: x1, top: y1,
                  width: x2 - x1, height: y2 - y1,
                  border: `2px dashed ${C.orange}`, background: `${C.orange}18`,
                  zIndex: 2, pointerEvents: 'none',
                }}
              />
            );
          })}

          {/* ── CONFLICT LAYER ────────────────────────────────────── */}
          {layers.conflict && snapshots.fusion?.conflict_edges?.map((ce, i) => (
            <div
              key={i}
              title="Conflict edge — disputed evidence"
              style={{ position: 'absolute', left: 4, top: 4, zIndex: 6 }}
            />
          ))}
        </div>
      </div>

      {/* Download Canvas Image Button */}
      <button
        onClick={downloadAsImage}
        style={{
          position: 'absolute',
          bottom: 16,
          left: 16,
          background: 'rgba(16, 185, 129, 0.15)',
          border: '1px solid #10B981',
          borderRadius: 6,
          padding: '6px 12px',
          color: '#E2E8F0',
          fontSize: 10,
          fontWeight: 600,
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          backdropFilter: 'blur(4px)',
          transition: 'all 0.2s',
          zIndex: 100,
        }}
        onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(16, 185, 129, 0.3)'; }}
        onMouseLeave={(e) => { e.currentTarget.style.background = 'rgba(16, 185, 129, 0.15)'; }}
      >
        <span>📸</span>
        <span>حفظ الاستمارة كصورة</span>
      </button>

      {/* Zoom indicator */}
      <div style={{
        position: 'absolute', bottom: 16, right: 16,
        fontSize: 9, fontFamily: 'monospace', color: C.muted,
        background: 'rgba(5,8,15,0.7)', padding: '4px 10px',
        borderRadius: 5, border: `1px solid ${C.border}`,
        backdropFilter: 'blur(4px)',
        pointerEvents: 'none',
      }}>
        {Math.round(zoom * 100)}% · {pageW}×{pageH}px
      </div>
    </div>
  );
}
