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
import { useWorkbenchStore, LAYER_META, ALIGNMENT_TYPES, IR_STAGE_LAYERS } from '../store/workbenchStore.js';
import { globalCoordinateRegistry } from '../services/coordinateTransformRegistry.js';

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
    layerOpacities, layerRenderModes, irLevel,
    workspaceMode, runs, compareMode, compareSnapshots, compareRunId,
    toggleLayer, setLayerVisible,
  } = useWorkbenchStore();

  const containerRef = useRef();
  const [containerSize, setContainerSize] = useState({ w: 800, h: 600 });

  useEffect(() => {
    if (!containerRef.current) return;
    const resizeObserver = new ResizeObserver(entries => {
      for (let entry of entries) {
        setContainerSize({ w: entry.contentRect.width, h: entry.contentRect.height });
      }
    });
    resizeObserver.observe(containerRef.current);
    return () => resizeObserver.disconnect();
  }, []);

  const getIsRelated = useCallback((layerType, item) => {
    if (!selected) return true;
    
    const selType = selected.type;
    const selData = selected.data;

    if (selType === 'token') {
      if (layerType === 'ocr' && item.id === selData.id) return true;
      if (layerType === 'alignment' && item.token === selData.id) return true;
      if (layerType === 'fusion' && selData.id && item.ocr_tokens?.includes(selData.id)) return true;
      if (layerType === 'geometry') {
        const linkedRegs = snapshots.alignment?.alignments
          ?.filter(a => a.token === selData.id)
          ?.map(a => a.region);
        if (linkedRegs?.includes(item.id)) return true;
      }
    }
    if (selType === 'region') {
      if (layerType === 'geometry' && item.id === selData.id) return true;
      if (layerType === 'alignment' && item.region === selData.id) return true;
      if (layerType === 'ocr') {
        const linkedTokens = snapshots.alignment?.alignments
          ?.filter(a => a.region === selData.id)
          ?.map(a => a.token);
        if (linkedTokens?.includes(item.id)) return true;
      }
      if (layerType === 'fusion') {
        if (item.resolved_provenance?.geometry_regions?.includes(selData.id)) return true;
      }
    }
    if (selType === 'field') {
      if (layerType === 'fusion' && item.id === selData.id) return true;
      if (layerType === 'ocr' && selData.ocr_tokens?.includes(item.id)) return true;
      if (layerType === 'alignment' && selData.ocr_tokens?.includes(item.token)) return true;
      if (layerType === 'geometry') {
        const linkedRegions = snapshots.alignment?.alignments
          ?.filter(a => selData.ocr_tokens?.includes(a.token))
          ?.map(a => a.region);
        if (linkedRegions?.includes(item.id)) return true;
      }
    }
    if (selType === 'shape') {
      if (layerType === 'shapes' && item.centroid?.[0] === selData.centroid?.[0] && item.centroid?.[1] === selData.centroid?.[1]) return true;
      if (layerType === 'geometry') {
        const boxCenter = [(item.bbox[0] + item.bbox[2])/2, (item.bbox[1] + item.bbox[3])/2];
        const dist = Math.hypot(boxCenter[0] - selData.centroid[0], boxCenter[1] - selData.centroid[1]);
        if (dist < 12) return true;
      }
    }
    if (selType === 'cell' || selType === 'table') {
      if (layerType === 'topology') return true;
    }
    return false;
  }, [selected, snapshots]);

  const getLayerOpacityVal = useCallback((layerKey, item) => {
    // 1. Base opacity from store
    const baseOpacity = layerOpacities?.[layerKey] ?? 1.0;
    
    // 2. Focus mode modifier
    const isRelated = getIsRelated(layerKey, item);
    const focusModifier = (selected && !isRelated) ? 0.45 : 1.0;

    // 3. IR Level Filter Modifier
    let irModifier = 1.0;
    if (irLevel === 'raw_geometry') {
      // Only show geometry and ocr raw contents
      if (layerKey !== 'geometry' && layerKey !== 'ocr') {
        irModifier = 0.0;
      }
    } else if (irLevel === 'structural') {
      // Show geometry, ocr, alignment, and shapes. Hide coordinate grid and fusion/topology.
      if (layerKey === 'coordinate_space' || layerKey === 'fusion' || layerKey === 'topology' || layerKey === 'orphan') {
        irModifier = 0.0;
      }
    } else if (irLevel === 'coordinate') {
      // Show coordinate grid, geometry, ocr, shapes, alignment. Dim fusion/topology.
      if (layerKey === 'fusion' || layerKey === 'topology') {
        irModifier = 0.25;
      }
    } else if (irLevel === 'cognitive') {
      // Filter out low confidence nodes to focus on high confidence ones (salient filters)
      if (item && item.confidence !== undefined && item.confidence < 0.85) {
        irModifier = 0.15; // Dim low confidence items
      }
    } else if (irLevel === 'reasoning') {
      // Dim raw inputs, focus on resolved fusion / topology cells
      if (layerKey === 'geometry' || layerKey === 'ocr' || layerKey === 'shapes') {
        irModifier = 0.25;
      }
    }
    
    return baseOpacity * focusModifier * irModifier;
  }, [layerOpacities, selected, getIsRelated, irLevel]);

  const isDragging = useRef(false);
  const dragStart = useRef({ x: 0, y: 0, px: 0, py: 0 });

  const [hoverCoords, setHoverCoords] = useState(null);

  // Display dimensions — canvas size in CSS pixels
  const baseW = Math.min(pageW, MAX_DISPLAY_W);
  const baseH = Math.round(baseW * (pageH / pageW));
  const displayW = Math.round(baseW * zoom);
  const displayH = Math.round(baseH * zoom);

  // Sync dimensions and calibration details to coordinate transform registry
  useEffect(() => {
    globalCoordinateRegistry.updatePageDimensions(pageW, pageH);
  }, [pageW, pageH]);

  useEffect(() => {
    if (snapshots.coordinate_space?.coordinate_space) {
      globalCoordinateRegistry.updateDpi(72, snapshots.coordinate_space.detected_dpi || 150);
      if (snapshots.coordinate_space.calibration) {
        globalCoordinateRegistry.setChartCalibration(snapshots.coordinate_space.calibration);
      }
    } else {
      globalCoordinateRegistry.setChartCalibration(null);
    }
  }, [snapshots.coordinate_space]);

  // Minimap calculations
  const MINIMAP_W = 85;
  const minimapH = Math.round(MINIMAP_W * (pageH / pageW));

  const handleMinimapInteraction = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;

    const pctX = mx / MINIMAP_W;
    const pctY = my / minimapH;

    const docX = displayW * pctX;
    const docY = displayH * pctY;

    setPan({
      x: containerSize.w / 2 - docX,
      y: containerSize.h / 2 - docY,
    });
  };

  const [isMinimapDragging, setIsMinimapDragging] = useState(false);

  const onMinimapMouseDown = (e) => {
    setIsMinimapDragging(true);
    handleMinimapInteraction(e);
  };

  const onMinimapMouseMove = (e) => {
    if (!isMinimapDragging) return;
    handleMinimapInteraction(e);
  };

  const onMinimapMouseUp = () => {
    setIsMinimapDragging(false);
  };

  useEffect(() => {
    if (isMinimapDragging) {
      window.addEventListener('mouseup', onMinimapMouseUp);
      return () => window.removeEventListener('mouseup', onMinimapMouseUp);
    }
  }, [isMinimapDragging]);

  // Viewport rect coordinates on minimap
  const rectX = Math.max(0, Math.min(MINIMAP_W, -panOffset.x * (MINIMAP_W / displayW)));
  const rectY = Math.max(0, Math.min(minimapH, -panOffset.y * (minimapH / displayH)));
  const rectW = Math.max(10, Math.min(MINIMAP_W - rectX, containerSize.w * (MINIMAP_W / displayW)));
  const rectH = Math.max(10, Math.min(minimapH - rectY, containerSize.h * (minimapH / displayH)));

  const onCanvasMouseMove = useCallback((e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    
    // Scale back to original page coordinates
    const pageX = Math.round((x / displayW) * pageW);
    const pageY = Math.round((y / displayH) * pageH);
    
    if (pageX >= 0 && pageX <= pageW && pageY >= 0 && pageY <= pageH) {
      setHoverCoords({ x: pageX, y: pageY });
    } else {
      setHoverCoords(null);
    }
  }, [displayW, displayH, pageW, pageH]);

  const onCanvasMouseLeave = useCallback(() => {
    setHoverCoords(null);
  }, []);


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
      ctx.globalAlpha = 1.0;
      ctx.drawImage(img, 0, 0, pageW, pageH);

      // 2. Draw Geometry Layer
      if (layers.geometry && snapshots.geometry?.regions) {
        snapshots.geometry.regions.forEach(r => {
          const op = getLayerOpacityVal('geometry', r);
          ctx.globalAlpha = op;
          ctx.lineWidth = 3;
          const isSel = selected?.data?.id === r.id;
          ctx.strokeStyle = isSel ? '#3B82F6' : 'rgba(59, 130, 246, 0.5)';
          const [x1, y1, x2, y2] = r.bbox;
          ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
          if (isSel) {
            ctx.fillStyle = 'rgba(59, 130, 246, 0.15)';
            ctx.fillRect(x1, y1, x2 - x1, y2 - y1);
          }
        });
      }

      // 3. Draw OCR Token Layer
      if (layers.ocr && snapshots.ocr?.tokens) {
        snapshots.ocr.tokens.forEach(t => {
          const op = getLayerOpacityVal('ocr', t);
          ctx.globalAlpha = op;
          ctx.lineWidth = 2;
          const isSel = selected?.data?.id === t.id;
          ctx.strokeStyle = isSel ? '#10B981' : 'rgba(16, 185, 129, 0.5)';
          const [x1, y1, x2, y2] = t.bbox;
          ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
          ctx.fillStyle = isSel ? 'rgba(16, 185, 129, 0.25)' : 'rgba(16, 185, 129, 0.08)';
          ctx.fillRect(x1, y1, x2 - x1, y2 - y1);

          if (isSel) {
            const fontSize = Math.max(9, (y2 - y1) * 0.45);
            ctx.font = `bold ${fontSize}px sans-serif`;
            ctx.fillStyle = '#064E3B';
            ctx.textBaseline = 'middle';
            ctx.fillText(t.text || '', x1 + 2, y1 + (y2 - y1) / 2);
          }
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

          const op = getLayerOpacityVal('alignment', a);
          ctx.globalAlpha = op;

          let strokeColor = ALIGNMENT_COLORS[a.type] ?? '#EC4899';
          if (layerRenderModes.alignment === 'gradient') {
            const score = a.alignment_score ?? 1.0;
            strokeColor = score > 0.8 ? '#10B981' : score > 0.5 ? '#FBBF24' : '#EF4444';
          }

          ctx.strokeStyle = strokeColor;
          ctx.beginPath();
          ctx.moveTo(tx, ty);
          ctx.lineTo(rx, ry);
          ctx.stroke();
        });
        ctx.setLineDash([]);
      }

      // 4.5. Draw Topology Layer
      if (layers.topology && snapshots.topology?.tables) {
        snapshots.topology.tables.forEach(table => {
          const opTable = getLayerOpacityVal('topology', table);
          ctx.globalAlpha = opTable;
          ctx.lineWidth = 2;
          ctx.strokeStyle = '#F59E0B'; // Yellow
          const [tx1, ty1, tx2, ty2] = table.bbox;
          ctx.strokeRect(tx1, ty1, tx2 - tx1, ty2 - ty1);
          
          ctx.font = 'bold 10px sans-serif';
          ctx.fillStyle = '#F59E0B';
          ctx.fillText(`Table ${table.table_id}`, tx1 + 4, ty1 + 12);

          table.cells.forEach(cell => {
            const opCell = getLayerOpacityVal('topology', cell);
            ctx.globalAlpha = opCell;
            const [cx1, cy1, cx2, cy2] = cell.bbox;
            ctx.strokeStyle = 'rgba(245, 158, 11, 0.4)';
            ctx.strokeRect(cx1, cy1, cx2 - cx1, cy2 - cy1);
          });
        });
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

          const op = getLayerOpacityVal('fusion', f);
          ctx.globalAlpha = op;

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

      // 6. Draw Coordinate Space Grid
      if (layers.coordinate_space) {
        const op = getLayerOpacityVal('coordinate_space', null);
        ctx.globalAlpha = op;
        ctx.strokeStyle = 'rgba(6, 182, 212, 0.08)';
        ctx.lineWidth = 1;
        ctx.setLineDash([3, 3]);
        ctx.font = '8px monospace';
        ctx.fillStyle = '#06B6D4';
        
        const showLine = layerRenderModes.coordinate_space !== 'axis_only';
        const showText = layerRenderModes.coordinate_space !== 'grid_only';

        // Vertical lines
        for (let i = 0; i < 9; i++) {
          const pct = (i + 1) * 0.1;
          const x = pageW * pct;
          if (showLine) {
            ctx.beginPath();
            ctx.moveTo(x, 0);
            ctx.lineTo(x, pageH);
            ctx.stroke();
          }
          if (showText) {
            ctx.fillText(Math.round(x).toString(), x + 4, 15);
          }
        }
        
        // Horizontal lines
        for (let i = 0; i < 9; i++) {
          const pct = (i + 1) * 0.1;
          const y = pageH * pct;
          if (showLine) {
            ctx.beginPath();
            ctx.moveTo(0, y);
            ctx.lineTo(pageW, y);
            ctx.stroke();
          }
          if (showText) {
            ctx.fillText(Math.round(y).toString(), 4, y - 4);
          }
        }
        ctx.setLineDash([]);
      }

      // 7. Draw Orphan Tokens
      if (layers.orphan && snapshots.fusion?.orphans) {
        snapshots.fusion.orphans.forEach(o => {
          const tok = snapshots.ocr?.tokens?.find(t => t.id === (o.token_id ?? o.id));
          if (!tok) return;
          const op = getLayerOpacityVal('orphan', o);
          ctx.globalAlpha = op;
          ctx.lineWidth = 2;
          ctx.strokeStyle = '#F97316'; // Orange
          ctx.setLineDash([4, 4]);
          const [x1, y1, x2, y2] = tok.bbox;
          ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
          ctx.fillStyle = 'rgba(249, 115, 22, 0.09)';
          ctx.fillRect(x1, y1, x2 - x1, y2 - y1);
        });
        ctx.setLineDash([]);
      }

      // 8. Draw Primitive Shapes Layer
      if (layers.shapes && snapshots.shapes?.shapes) {
        snapshots.shapes.shapes.forEach((s, idx) => {
          const matchedRegion = snapshots.geometry?.regions?.find(r => {
            const boxCenter = [(r.bbox[0] + r.bbox[2])/2, (r.bbox[1] + r.bbox[3])/2];
            const dist = Math.hypot(boxCenter[0] - s.centroid[0], boxCenter[1] - s.centroid[1]);
            return dist < 12;
          });
          
          const cx = s.centroid[0];
          const cy = s.centroid[1];
          const isSel = selected?.type === 'shape' && selected?.data?.centroid?.[0] === s.centroid[0] && selected?.data?.centroid?.[1] === s.centroid[1];
          const op = getLayerOpacityVal('shapes', s);
          ctx.globalAlpha = op;
          
          const showBorder = layerRenderModes.shapes !== 'centroid';
          const showSaliency = layerRenderModes.shapes === 'saliency';

          // Draw Centroid Target
          ctx.beginPath();
          ctx.arc(cx, cy, 6, 0, 2 * Math.PI);
          ctx.fillStyle = isSel ? '#F59E0B' : '#FBBF24';
          ctx.fill();
          ctx.lineWidth = 2;
          ctx.strokeStyle = '#FFFFFF';
          ctx.stroke();

          // Draw boundary
          if (showBorder) {
            let bbox = matchedRegion ? matchedRegion.bbox : [s.centroid[0] - 20, s.centroid[1] - 20, s.centroid[0] + 20, s.centroid[1] + 20];
            const [x1, y1, x2, y2] = bbox;
            ctx.strokeStyle = isSel ? '#F59E0B' : 'rgba(245, 158, 11, 0.65)';
            ctx.fillStyle = showSaliency ? 'rgba(245, 158, 11, 0.15)' : 'rgba(0,0,0,0)';
            ctx.lineWidth = 1.5;
            ctx.setLineDash([4, 4]);
            ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
            if (showSaliency) {
              ctx.fillRect(x1, y1, x2 - x1, y2 - y1);
            }
            ctx.setLineDash([]);

            // Draw text label
            if (isSel) {
              ctx.font = '7px sans-serif';
              ctx.fillStyle = 'rgba(15, 23, 42, 0.85)';
              const text = `AR: ${s.aspect_ratio.toFixed(2)} | Hu0: ${s.hu_moments[0].toFixed(4)}`;
              const textW = ctx.measureText(text).width;
              ctx.fillRect(x1, y2, textW + 8, 12);
              ctx.lineWidth = 1;
              ctx.strokeStyle = '#F59E0B';
              ctx.strokeRect(x1, y2, textW + 8, 12);
              ctx.fillStyle = '#FBBF24';
              ctx.fillText(text, x1 + 4, y2 + 8);
            }
          }
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

  const renderCanvas = (targetSnapshots, isCurrent = true) => {
    if (!targetSnapshots) return null;
    return (
      <div
        onMouseMove={onCanvasMouseMove}
        onMouseLeave={onCanvasMouseLeave}
        style={{
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
        {layers.geometry && targetSnapshots.geometry?.regions?.map(r => {
          const [x1, y1, x2, y2] = scale(r.bbox);
          const isSel = selected?.data?.id === r.id;
          const op = getLayerOpacityVal('geometry', r);
          return (
            <div
              key={r.id}
              onClick={(e) => { e.stopPropagation(); if (isCurrent) setSelected({ type: 'region', data: r }); }}
              title={`Region · ${(r.confidence * 100).toFixed(0)}% · ${r.id?.slice(0, 12)}…`}
              onMouseEnter={(e) => { if (!isSel) e.currentTarget.style.background = 'rgba(59, 130, 246, 0.35)'; }}
              onMouseLeave={(e) => { if (!isSel) e.currentTarget.style.background = 'rgba(59, 130, 246, 0.15)'; }}
              style={{
                position: 'absolute',
                left: x1, top: y1, width: x2 - x1, height: y2 - y1,
                border: `2px solid ${isSel ? '#2563EB' : 'rgba(59, 130, 246, 0.85)'}`,
                background: isSel ? 'rgba(59, 130, 246, 0.35)' : 'rgba(59, 130, 246, 0.15)',
                cursor: 'pointer', zIndex: 1,
                boxShadow: isSel ? `0 0 0 2px #2563EB, 0 0 16px rgba(37, 99, 235, 0.5)` : 'none',
                transition: 'all 0.15s',
                opacity: op,
              }}
            />
          );
        })}

        {/* ── OCR TOKEN LAYER ───────────────────────────────────── */}
        {layers.ocr && targetSnapshots.ocr?.tokens?.map(t => {
          const [x1, y1, x2, y2] = scale(t.bbox);
          const isSel = selected?.data?.id === t.id;
          const op = getLayerOpacityVal('ocr', t);
          return (
            <div
              key={t.id}
              className="ocr-token-box"
              onClick={(e) => { e.stopPropagation(); if (isCurrent) setSelected({ type: 'token', data: t }); }}
              title={`"${t.text}" · ${(t.confidence * 100).toFixed(0)}% · ${t.id?.slice(0, 12)}…`}
              onMouseEnter={(e) => { if (!isSel) e.currentTarget.style.background = `${C.green}30`; }}
              onMouseLeave={(e) => { if (!isSel) e.currentTarget.style.background = `${C.green}18`; }}
              style={{
                position: 'absolute',
                left: x1, top: y1, width: x2 - x1, height: y2 - y1,
                border: `1.5px solid ${C.green}${isSel ? '' : '80'}`,
                background: isSel ? `${C.green}35` : `${C.green}18`,
                cursor: 'pointer', zIndex: 3,
                display: 'flex', alignItems: 'center', overflow: 'hidden',
                boxShadow: isSel ? `0 0 0 2px ${C.green}, 0 0 12px ${C.green}50` : 'none',
                transition: 'all 0.15s',
                opacity: op,
              }}
            >
              <span style={{
                fontSize: Math.max(7, (y2 - y1) * 0.45),
                color: '#064E3B', fontWeight: 700,
                padding: '0 2px', direction: 'rtl',
                width: '100%', overflow: 'hidden', whiteSpace: 'nowrap',
                pointerEvents: 'none',
                opacity: isSel ? 1 : undefined,
              }}>{t.text}</span>
            </div>
          );
        })}

        {/* ── ALIGNMENT LAYER (SVG arrows) ──────────────────────── */}
        {layers.alignment && targetSnapshots.alignment?.alignments && (
          <svg
            style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none', zIndex: 4 }}
            aria-hidden="true"
          >
            {targetSnapshots.alignment.alignments.map(a => {
              const tok = targetSnapshots.ocr?.tokens?.find(t => t.id === a.token);
              const reg = targetSnapshots.geometry?.regions?.find(r => r.id === a.region);
              if (!tok || !reg) return null;
              const [tx1, ty1, tx2, ty2] = scale(tok.bbox);
              const [rx1, ry1, rx2, ry2] = scale(reg.bbox);
              const tx = (tx1 + tx2) / 2, ty = (ty1 + ty2) / 2;
              const rx = (rx1 + rx2) / 2, ry = (ry1 + ry2) / 2;
              const op = getLayerOpacityVal('alignment', a);
              
              let strokeColor = ALIGNMENT_COLORS[a.type] ?? C.pink;
              if (layerRenderModes.alignment === 'gradient') {
                const score = a.alignment_score ?? 1.0;
                strokeColor = score > 0.8 ? C.green : score > 0.5 ? C.yellow : C.red;
              }

              return (
                <line
                  key={a.id}
                  x1={tx} y1={ty} x2={rx} y2={ry}
                  stroke={strokeColor} strokeWidth={1.5} strokeDasharray="5 3"
                  opacity={op}
                />
              );
            })}
          </svg>
        )}

        {/* ── FUSION FIELD LAYER ────────────────────────────────── */}
        {layers.fusion && targetSnapshots.fusion?.fields?.map((f, idx) => {
          const tok = targetSnapshots.ocr?.tokens?.find(t => f.ocr_tokens?.includes(t.id));
          if (!tok) return null;
          const [, y1, x2] = scale(tok.bbox);
          const score = f.confidence ?? 0;
          const color = score > 0.85 ? C.green : score > 0.6 ? C.yellow : C.red;
          const isSel = selected?.data?.id === f.id || selected?.data?.field_id === f.id;
          const op = getLayerOpacityVal('fusion', f);
          return (
            <div
              key={f.id ?? idx}
              onClick={(e) => { e.stopPropagation(); if (isCurrent) setSelected({ type: 'field', data: f }); }}
              title={`Field · ${(score * 100).toFixed(0)}% · ${f.field_type ?? 'inferred'}`}
              style={{
                position: 'absolute',
                left: x2 + 3, top: y1,
                padding: '2px 6px', borderRadius: 4,
                background: '#0B1120', border: `1px solid ${color}`,
                fontSize: 8, fontFamily: 'monospace', color, zIndex: 5,
                cursor: 'pointer', whiteSpace: 'nowrap',
                boxShadow: isSel ? `0 0 6px ${color}60` : 'none',
                opacity: op,
              }}
            >
              {(score * 100).toFixed(0)}%
            </div>
          );
        })}

        {/* ── ORPHAN LAYER ──────────────────────────────────────── */}
        {layers.orphan && targetSnapshots.fusion?.orphans?.map((o, i) => {
          const tok = targetSnapshots.ocr?.tokens?.find(t => t.id === (o.token_id ?? o.id));
          if (!tok) return null;
          const [x1, y1, x2, y2] = scale(tok.bbox);
          const op = getLayerOpacityVal('orphan', o);
          return (
            <div
              key={o.id ?? i}
              title="Orphan token — no alignment to any region"
              style={{
                position: 'absolute', left: x1, top: y1,
                width: x2 - x1, height: y2 - y1,
                border: `2px dashed ${C.orange}`, background: `${C.orange}18`,
                zIndex: 2, pointerEvents: 'none',
                opacity: op,
              }}
            />
          );
        })}

        {/* ── TOPOLOGY LAYER ────────────────────────────────────── */}
        {layers.topology && targetSnapshots.topology?.tables?.map(table => {
          const [tx1, ty1, tx2, ty2] = scale(table.bbox);
          const opTable = getLayerOpacityVal('topology', table);
          return (
            <React.Fragment key={table.table_id}>
              <div
                onClick={(e) => { e.stopPropagation(); if (isCurrent) setSelected({ type: 'table', data: table }); }}
                title={`Table · ${table.table_id} (${table.rows_count}x${table.cols_count})`}
                style={{
                  position: 'absolute',
                  left: tx1, top: ty1, width: tx2 - tx1, height: ty2 - ty1,
                  border: `2px dashed ${C.yellow}`,
                  background: `${C.yellow}0F`,
                  cursor: 'pointer', zIndex: 10,
                  opacity: opTable,
                }}
              >
                <div style={{
                  position: 'absolute', top: -18, left: 0,
                  background: C.yellow, color: '#000000',
                  fontSize: 8, fontWeight: 700, padding: '2px 4px',
                  borderRadius: 2, whiteSpace: 'nowrap'
                }}>
                  📊 {table.table_id} ({table.rows_count}x{table.cols_count})
                </div>
              </div>

              {table.cells?.map(cell => {
                const [cx1, cy1, cx2, cy2] = scale(cell.bbox);
                const opCell = getLayerOpacityVal('topology', cell);
                return (
                  <div
                    key={cell.cell_id}
                    onClick={(e) => { e.stopPropagation(); if (isCurrent) setSelected({ type: 'cell', data: cell }); }}
                    title={`Cell · Row ${cell.row_index}, Col ${cell.column_index}`}
                    style={{
                      position: 'absolute',
                      left: cx1, top: cy1, width: cx2 - cx1, height: cy2 - cy1,
                      border: `1px solid ${C.yellow}40`,
                      background: `${C.yellow}05`,
                      cursor: 'pointer', zIndex: 11,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      opacity: opCell,
                    }}
                  >
                    <span style={{ fontSize: 7, color: C.yellow, opacity: 0.6, pointerEvents: 'none' }}>
                      R{cell.row_index} C{cell.column_index}
                    </span>
                  </div>
                );
              })}
            </React.Fragment>
          );
        })}

        {/* ── COORDINATE SPACE GRID LAYER ───────────────────────── */}
        {layers.coordinate_space && (
          <svg
            style={{
              position: 'absolute', inset: 0, width: '100%', height: '100%',
              pointerEvents: 'none', zIndex: 5,
              opacity: getLayerOpacityVal('coordinate_space', null)
            }}
          >
            {Array.from({ length: 9 }).map((_, i) => {
              const pct = (i + 1) * 0.1;
              const x = displayW * pct;
              const labelX = Math.round(pageW * pct);
              const showLine = layerRenderModes.coordinate_space !== 'axis_only';
              const showText = layerRenderModes.coordinate_space !== 'grid_only';
              return (
                <React.Fragment key={`v-${i}`}>
                  {showLine && <line x1={x} y1={0} x2={x} y2={displayH} stroke="rgba(6, 182, 212, 0.08)" strokeWidth={1} strokeDasharray="3 3" />}
                  {showText && (
                    <text x={x + 4} y={15} fill="#06B6D4" fontSize={8} opacity={0.7} fontFamily="monospace">
                      {labelX}
                    </text>
                  )}
                </React.Fragment>
              );
            })}
            {Array.from({ length: 9 }).map((_, i) => {
              const pct = (i + 1) * 0.1;
              const y = displayH * pct;
              const labelY = Math.round(pageH * pct);
              const showLine = layerRenderModes.coordinate_space !== 'axis_only';
              const showText = layerRenderModes.coordinate_space !== 'grid_only';
              return (
                <React.Fragment key={`h-${i}`}>
                  {showLine && <line x1={0} y1={y} x2={displayW} y2={y} stroke="rgba(6, 182, 212, 0.08)" strokeWidth={1} strokeDasharray="3 3" />}
                  {showText && (
                    <text x={4} y={y - 4} fill="#06B6D4" fontSize={8} opacity={0.7} fontFamily="monospace">
                      {labelY}
                    </text>
                  )}
                </React.Fragment>
              );
            })}
          </svg>
        )}

        {/* ── COORDINATE SPACE CURSOR OVERLAY ──────────────────── */}
        {layers.coordinate_space && hoverCoords && isCurrent && layers.coord_tooltip && (
          <React.Fragment>
            <div style={{
              position: 'absolute', left: hoverCoords.x * (displayW / pageW), top: 0,
              width: 1, height: displayH, borderLeft: '1px dashed rgba(6, 182, 212, 0.35)',
              pointerEvents: 'none', zIndex: 49, opacity: getLayerOpacityVal('coordinate_space', null)
            }} />
            <div style={{
              position: 'absolute', left: 0, top: hoverCoords.y * (displayH / pageH),
              width: displayW, height: 1, borderTop: '1px dashed rgba(6, 182, 212, 0.35)',
              pointerEvents: 'none', zIndex: 49, opacity: getLayerOpacityVal('coordinate_space', null)
            }} />
            <div style={{
              position: 'absolute',
              left: Math.min(displayW - 130, (hoverCoords.x * (displayW / pageW)) + 12),
              top: Math.min(displayH - 30, (hoverCoords.y * (displayH / pageH)) + 12),
              background: 'rgba(11, 17, 32, 0.95)', border: '1px solid #06B6D4', borderRadius: 3,
              padding: '2px 5px', fontSize: 8, fontFamily: 'monospace', color: '#06B6D4',
              zIndex: 50, pointerEvents: 'none', whiteSpace: 'nowrap',
              boxShadow: '0 2px 8px rgba(0,0,0,0.5)', opacity: getLayerOpacityVal('coordinate_space', null),
              backdropFilter: 'blur(4px)',
            }}>
              px: {hoverCoords.x}, {hoverCoords.y} | mm: {globalCoordinateRegistry.pixelToReal(hoverCoords.x, hoverCoords.y).x.toFixed(1)}, {globalCoordinateRegistry.pixelToReal(hoverCoords.x, hoverCoords.y).y.toFixed(1)}
            </div>
          </React.Fragment>
        )}

        {/* ── PRIMITIVE SHAPES LAYER ───────────────────────────── */}
        {layers.shapes && targetSnapshots.shapes?.shapes?.map((s, idx) => {
          const matchedRegion = targetSnapshots.geometry?.regions?.find(r => {
            const boxCenter = [(r.bbox[0] + r.bbox[2])/2, (r.bbox[1] + r.bbox[3])/2];
            const dist = Math.hypot(boxCenter[0] - s.centroid[0], boxCenter[1] - s.centroid[1]);
            return dist < 12;
          });
          const cx = s.centroid[0] * (displayW / pageW);
          const cy = s.centroid[1] * (displayH / pageH);
          let bbox = matchedRegion ? matchedRegion.bbox : [s.centroid[0] - 20, s.centroid[1] - 20, s.centroid[0] + 20, s.centroid[1] + 20];
          const [x1, y1, x2, y2] = scale(bbox);
          const isSel = selected?.type === 'shape' && selected?.data?.centroid?.[0] === s.centroid[0] && selected?.data?.centroid?.[1] === s.centroid[1];
          const op = getLayerOpacityVal('shapes', s);
          const showBorder = layerRenderModes.shapes !== 'centroid';
          const showSaliency = layerRenderModes.shapes === 'saliency';
          return (
            <React.Fragment key={`shape-${idx}`}>
              <div
                onClick={(e) => { e.stopPropagation(); if (isCurrent) setSelected({ type: 'shape', data: s }); }}
                style={{
                  position: 'absolute', left: cx - 6, top: cy - 6, width: 12, height: 12, borderRadius: '50%',
                  background: isSel ? '#F59E0B' : '#FBBF24', border: '2px solid #FFFFFF',
                  cursor: 'pointer', zIndex: 12, boxShadow: '0 0 10px rgba(0,0,0,0.5)', opacity: op,
                }}
              />
              {showBorder && (
                <div style={{
                  position: 'absolute', left: x1, top: y1, width: x2 - x1, height: y2 - y1,
                  border: `1.5px dashed ${isSel ? '#F59E0B' : 'rgba(245, 158, 11, 0.65)'}`,
                  background: showSaliency ? 'rgba(245, 158, 11, 0.15)' : 'none',
                  pointerEvents: 'none', zIndex: 10, opacity: op,
                }}>
                  {isSel && (
                    <div style={{
                      position: 'absolute', bottom: -14, left: 0,
                      background: 'rgba(15, 23, 42, 0.9)', border: '1px solid #F59E0B',
                      borderRadius: 3, padding: '1px 4px', fontSize: 7, color: '#FBBF24',
                      whiteSpace: 'nowrap', zIndex: 100,
                    }}>
                      AR: {s.aspect_ratio.toFixed(2)} | Hu0: {s.hu_moments[0].toFixed(4)}
                    </div>
                  )}
                </div>
              )}
            </React.Fragment>
          );
        })}
      </div>
    );
  };

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
          <span>1–8 · Toggle Layers</span>
          <span>+/− · Zoom</span>
          <span>0 · Reset View</span>
          <span>Esc · Deselect</span>
        </div>
      </div>
    );
  }

  const isReplaySplit = workspaceMode === 'replay' && compareMode && compareSnapshots?.ocr;

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
      <style dangerouslySetInnerHTML={{ __html: `
        .ocr-token-box span {
          opacity: 0;
          transition: opacity 0.12s ease-in-out;
        }
        .ocr-token-box:hover span {
          opacity: 1;
        }
        @keyframes pulse {
          0% { opacity: 0.4; }
          50% { opacity: 1; }
          100% { opacity: 0.4; }
        }
      `}} />

      {/* Main Canvas Container */}
      <div style={{
        transform: `translate(${panOffset.x}px, ${panOffset.y}px)`,
        transformOrigin: '0 0',
        padding: 40,
        userSelect: 'none',
        pointerEvents: 'none',
        display: 'flex',
        flexDirection: 'row',
        gap: 80,
      }}>
        {isReplaySplit ? (
          <>
            {/* Left Side: Reference Run */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div style={{
                fontSize: 10, fontWeight: 700, color: C.blue,
                background: 'rgba(59, 130, 246, 0.12)', border: `1px solid rgba(59, 130, 246, 0.3)`,
                padding: '6px 12px', borderRadius: 6, display: 'flex', alignItems: 'center', gap: 8,
                backdropFilter: 'blur(4px)'
              }}>
                <span style={{ animation: 'pulse 2s infinite' }}>🔵</span>
                <span>REFERENCE RUN: {runId?.slice(0, 16)}...</span>
              </div>
              {renderCanvas(snapshots, true)}
            </div>

            {/* Right Side: Compare Run */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div style={{
                fontSize: 10, fontWeight: 700, color: C.pink,
                background: 'rgba(236, 72, 153, 0.12)', border: `1px solid rgba(236, 72, 153, 0.3)`,
                padding: '6px 12px', borderRadius: 6, display: 'flex', alignItems: 'center', gap: 8,
                backdropFilter: 'blur(4px)'
              }}>
                <span>💗</span>
                <span>COMPARE RUN: {compareRunId?.slice(0, 16)}...</span>
              </div>
              {renderCanvas(compareSnapshots, false)}
            </div>
          </>
        ) : (
          renderCanvas(snapshots, true)
        )}
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

      {/* Viewport Minimap Tracker */}
      {layers.minimap && (
        <div
          onMouseDown={onMinimapMouseDown}
          onMouseMove={onMinimapMouseMove}
          style={{
            position: 'absolute',
            top: 16,
            right: 16,
            width: MINIMAP_W,
            height: minimapH,
            background: 'rgba(5, 8, 15, 0.85)',
            border: `1px solid ${C.border}`,
            borderRadius: 8,
            overflow: 'hidden',
            cursor: 'crosshair',
            zIndex: 100,
            backdropFilter: 'blur(8px)',
            boxShadow: '0 4px 20px rgba(0,0,0,0.6)',
            userSelect: 'none',
          }}
        >
          {pageImage ? (
            <img
              draggable={false}
              src={pageImage}
              alt="minimap"
              style={{ width: '100%', height: '100%', objectFit: 'fill', opacity: 0.35, pointerEvents: 'none' }}
            />
          ) : (
            <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', opacity: 0.2 }}>
              📄
            </div>
          )}
          <div style={{
            position: 'absolute',
            left: rectX,
            top: rectY,
            width: rectW,
            height: rectH,
            border: '1.5px solid #0EA5E9',
            background: 'rgba(14, 165, 233, 0.15)',
            borderRadius: 2,
            pointerEvents: 'none',
            boxShadow: '0 0 8px rgba(14, 165, 233, 0.5)',
          }} />

          {/* Dismiss button */}
          <button
            onClick={(e) => { e.stopPropagation(); setLayerVisible('minimap', false); }}
            style={{
              position: 'absolute', top: 2, right: 2,
              width: 14, height: 14, borderRadius: '50%',
              background: 'rgba(15, 23, 42, 0.8)', border: 'none',
              color: '#FFFFFF', fontSize: 9, cursor: 'pointer',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontWeight: 'bold', zIndex: 101,
            }}
            title="إغلاق الخريطة"
          >
            ×
          </button>
        </div>
      )}

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
