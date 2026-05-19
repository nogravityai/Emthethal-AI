import React, { useState, useRef, useCallback, useEffect } from 'react';

const API = '/api/cfis/v1/debug/geometry';

// ── Color constants ────────────────────────────────────────────────────────
const C = {
  bg:       '#0a0f1a',
  card:     '#111827',
  border:   '#1e293b',
  accent:   '#0ea5e9',
  purple:   '#6366f1',
  green:    '#10b981',
  yellow:   '#f59e0b',
  red:      '#ef4444',
  orange:   '#f97316',
  text:     '#e2e8f0',
  muted:    '#64748b',
  indigo:   '#818cf8',
};

// ── Stat Badge ─────────────────────────────────────────────────────────────
const Badge = ({ label, value, color = C.accent }) => (
  <div style={{
    background: `${color}15`, border: `1px solid ${color}30`,
    borderRadius: 10, padding: '6px 14px', display: 'flex',
    flexDirection: 'column', alignItems: 'center', minWidth: 70,
  }}>
    <span style={{ fontSize: 18, fontWeight: 800, color }}>{value ?? '—'}</span>
    <span style={{ fontSize: 10, color: C.muted, marginTop: 2 }}>{label}</span>
  </div>
);

// ── Layer toggle button ────────────────────────────────────────────────────
const LayerBtn = ({ id, label, active, onClick, color }) => (
  <button onClick={onClick} style={{
    padding: '5px 12px', borderRadius: 8, cursor: 'pointer', fontSize: 12,
    border: `1px solid ${active ? color : C.border}`,
    background: active ? `${color}18` : C.card,
    color: active ? color : C.muted,
    fontWeight: active ? 700 : 400,
    transition: 'all .15s',
    fontFamily: "'Cairo', sans-serif",
  }}>{label}</button>
);

// ── Audit row ──────────────────────────────────────────────────────────────
const AuditRow = ({ rec }) => {
  const accepted = rec.accepted;
  const score = (rec.alignment_score * 100).toFixed(0);
  return (
    <div style={{
      display: 'flex', gap: 8, alignItems: 'center',
      padding: '5px 10px', borderRadius: 6, marginBottom: 3,
      background: accepted ? '#10b98110' : '#ef444410',
      border: `1px solid ${accepted ? '#10b98130' : '#ef444430'}`,
      fontSize: 12, direction: 'ltr',
    }}>
      <span style={{ color: accepted ? C.green : C.red, fontWeight: 700 }}>
        {accepted ? '✓' : '✗'}
      </span>
      <span style={{ color: C.muted, minWidth: 55 }}>{rec.orientation}</span>
      <span style={{ color: C.text }}>
        gap {rec.gap_px?.toFixed(0)}px @ axis {rec.axis_position?.toFixed(0)}
      </span>
      <span style={{
        marginLeft: 'auto', color: accepted ? C.green : C.muted,
        fontWeight: 600,
      }}>score: {score}%</span>
      {rec.reject_reason && (
        <span style={{ color: C.muted, fontSize: 10 }}>{rec.reject_reason}</span>
      )}
    </div>
  );
};

// ── Merged cell row ────────────────────────────────────────────────────────
const MergedCellRow = ({ cell }) => (
  <div style={{
    display: 'flex', gap: 8, alignItems: 'center',
    padding: '5px 10px', borderRadius: 6, marginBottom: 3,
    background: cell.is_merged ? '#f9731610' : C.card,
    border: `1px solid ${cell.is_merged ? '#f9731630' : C.border}`,
    fontSize: 12, direction: 'ltr',
  }}>
    <span style={{ color: cell.is_merged ? C.orange : C.muted, fontWeight: 700, minWidth: 60 }}>
      {cell.rowspan}r × {cell.colspan}c
    </span>
    <span style={{ color: C.muted }}>
      row {cell.row_start}-{cell.row_end} | col {cell.col_start}-{cell.col_end}
    </span>
    <span style={{ marginLeft: 'auto', color: C.muted }}>
      conf: {(cell.confidence * 100).toFixed(0)}%
    </span>
    {cell.is_merged && (
      <span style={{ background: '#f9731620', color: C.orange, padding: '1px 7px', borderRadius: 10, fontSize: 10 }}>
        MERGED
      </span>
    )}
  </div>
);

// ── Hypothesis summary card ────────────────────────────────────────────────
const HypCard = ({ type, stats }) => {
  const typeColors = {
    checkbox: C.green, radio_group: C.orange, table_cell: C.accent,
    section_header: C.purple, signature_area: C.yellow, text_block: C.muted,
  };
  const color = typeColors[type] || C.indigo;
  return (
    <div style={{
      background: `${color}10`, border: `1px solid ${color}25`,
      borderRadius: 10, padding: '10px 14px', minWidth: 120,
    }}>
      <div style={{ fontSize: 11, color, fontWeight: 700, marginBottom: 4 }}>{type}</div>
      <div style={{ display: 'flex', gap: 6 }}>
        <span style={{ fontSize: 18, fontWeight: 800, color }}>{stats.total}</span>
        <div style={{ display: 'flex', flexDirection: 'column', justifyContent: 'center' }}>
          <span style={{ fontSize: 10, color: C.green }}>✓ {stats.accepted}</span>
          <span style={{ fontSize: 10, color: C.red }}>✗ {stats.rejected}</span>
        </div>
      </div>
    </div>
  );
};

// ── Drop zone ──────────────────────────────────────────────────────────────
const DropZone = ({ onFile, disabled }) => {
  const [drag, setDrag] = useState(false);
  const ref = useRef();
  return (
    <div
      onDragOver={e => { e.preventDefault(); if (!disabled) setDrag(true); }}
      onDragLeave={() => setDrag(false)}
      onDrop={e => {
        e.preventDefault(); setDrag(false);
        const f = e.dataTransfer.files[0];
        if (f?.type === 'application/pdf' && !disabled) onFile(f);
      }}
      onClick={() => !disabled && ref.current?.click()}
      style={{
        border: `2px dashed ${drag ? C.accent : C.border}`,
        borderRadius: 16, padding: '40px 32px', textAlign: 'center',
        cursor: disabled ? 'not-allowed' : 'pointer',
        background: drag ? `${C.accent}08` : C.card,
        transition: 'all .2s', opacity: disabled ? 0.5 : 1,
      }}
    >
      <input ref={ref} type="file" accept=".pdf" style={{ display: 'none' }}
        onChange={e => e.target.files[0] && onFile(e.target.files[0])} />
      <div style={{ fontSize: 40, marginBottom: 10 }}>{drag ? '📂' : '📐'}</div>
      <div style={{ fontSize: 18, fontWeight: 700, marginBottom: 6, fontFamily: "'Cairo', sans-serif" }}>
        ارفع PDF لتحليل الهندسة
      </div>
      <div style={{ fontSize: 12, color: C.muted }}>
        Phase 2B: Border Inference · Cell Merger · Radio Groups · Geometry Debug
      </div>
    </div>
  );
};

// ── Main Component ─────────────────────────────────────────────────────────
export default function GeometryDebugViewer() {
  const [stage, setStage] = useState('idle');   // idle | loading | done | error
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [filename, setFilename] = useState('');
  const [activeTab, setActiveTab] = useState('overlay');
  const [pageNum, setPageNum] = useState(0);
  const [showAll, setShowAll] = useState(false);

  // Layer toggles
  const ALL_LAYERS = [
    { id: 'lines',        label: '📏 خطوط',         color: C.accent  },
    { id: 'boxes',        label: '☑ صناديق',         color: C.green   },
    { id: 'anchors',      label: '⚓ مرتسى',          color: C.red     },
    { id: 'regions',      label: '🗺 مناطق',           color: C.purple  },
    { id: 'grids',        label: '🔲 شبكات',          color: C.yellow  },
    { id: 'hypotheses',   label: '🧪 فرضيات',         color: C.indigo  },
    { id: 'border_gaps',  label: '🩹 فجوات الحدود',   color: C.orange  },
    { id: 'merged_cells', label: '🔗 خلايا مدمجة',    color: C.orange  },
  ];
  const [activeLayers, setActiveLayers] = useState(
    new Set(ALL_LAYERS.map(l => l.id))
  );

  const toggleLayer = id => {
    setActiveLayers(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  // Quick layer toggle using backend cache
  useEffect(() => {
    if (!result?.session_id) return;
    const fetchOverlay = async () => {
      const layerStr = [...activeLayers].join(',');
      try {
        const res = await fetch(`${API}/${result.session_id}/overlay?layers=${encodeURIComponent(layerStr)}`);
        if (res.ok) {
          const data = await res.json();
          setResult(prev => ({ ...prev, overlay_image_b64: data.overlay_image_b64 }));
        }
      } catch (e) {
        console.error("Failed to re-render overlay", e);
      }
    };
    fetchOverlay();
  }, [activeLayers, result?.session_id]);


  const analyze = useCallback(async (file) => {
    setFilename(file.name);
    setStage('loading');
    setError('');
    setResult(null);

    const fd = new FormData();
    fd.append('file', file);

    const layerStr = [...activeLayers].join(',');
    const url = `${API}?page_number=${pageNum}&layers=${encodeURIComponent(layerStr)}&run_inference=true&run_merger=true&run_radio=true`;

    try {
      const res = await fetch(url, { method: 'POST', body: fd });
      if (!res.ok) {
        const e = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(e.detail || 'خطأ في الخادم');
      }
      const data = await res.json();
      setResult(data);
      setStage('done');
      setActiveTab('overlay');
    } catch (e) {
      setError(e.message);
      setStage('error');
    }
  }, [activeLayers, pageNum]);

  const TAB = (id, label) => (
    <button onClick={() => setActiveTab(id)} style={{
      padding: '7px 16px', borderRadius: 8, cursor: 'pointer', fontSize: 13,
      border: `1px solid ${activeTab === id ? C.accent : C.border}`,
      background: activeTab === id ? `${C.accent}15` : C.card,
      color: activeTab === id ? C.accent : C.muted,
      fontWeight: activeTab === id ? 700 : 400,
      fontFamily: "'Cairo', sans-serif",
    }}>{label}</button>
  );

  return (
    <div style={{ fontFamily: "'Cairo', 'Segoe UI', sans-serif", color: C.text }}>

      {/* ── Header ── */}
      <div style={{ marginBottom: 20, direction: 'rtl' }}>
        <div style={{ fontSize: 20, fontWeight: 800, marginBottom: 4 }}>
          🔬 محرك تحليل الهندسة — Phase 2B
        </div>
        <div style={{ fontSize: 12, color: C.muted }}>
          Border Inference · Cell Merger · Radio Group Fusion · Geometry Overlay
        </div>
      </div>

      {/* ── Layer toggles ── */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 14, direction: 'rtl' }}>
        {ALL_LAYERS.map(l => (
          <LayerBtn key={l.id} id={l.id} label={l.label}
            active={activeLayers.has(l.id)} color={l.color}
            onClick={() => toggleLayer(l.id)} />
        ))}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginLeft: 'auto' }}>
          <span style={{ fontSize: 12, color: C.muted }}>صفحة:</span>
          <input type="number" min={0} value={pageNum}
            onChange={e => setPageNum(Math.max(0, parseInt(e.target.value) || 0))}
            style={{
              width: 56, background: C.card, border: `1px solid ${C.border}`,
              borderRadius: 6, padding: '4px 8px', color: C.text, fontSize: 13, textAlign: 'center',
            }} />
        </div>
      </div>

      {/* ── Upload / Results ── */}
      {(stage === 'idle' || stage === 'error') && (
        <div style={{ maxWidth: 560, margin: '0 auto' }}>
          <DropZone onFile={analyze} disabled={stage === 'loading'} />
          {stage === 'error' && (
            <div style={{
              marginTop: 14, padding: '12px 16px',
              background: `${C.red}10`, border: `1px solid ${C.red}30`,
              borderRadius: 10, color: C.red, direction: 'rtl', fontSize: 13,
            }}>❌ {error}</div>
          )}
        </div>
      )}

      {stage === 'loading' && (
        <div style={{ textAlign: 'center', padding: 60 }}>
          <div style={{ fontSize: 40, marginBottom: 14 }}>⚙️</div>
          <div style={{ fontSize: 16, fontWeight: 700, marginBottom: 8 }}>{filename}</div>
          <div style={{ fontSize: 13, color: C.muted }}>
            تشغيل محرك Phase 2B... (Border Inference · Cell Merger · Hypotheses)
          </div>
          <div style={{
            marginTop: 20, height: 4, background: C.border, borderRadius: 10, overflow: 'hidden',
            maxWidth: 400, margin: '20px auto 0',
          }}>
            <div style={{
              height: '100%', width: '60%',
              background: `linear-gradient(90deg, ${C.accent}, ${C.purple})`,
              borderRadius: 10, animation: 'pulse 1.5s ease-in-out infinite',
            }} />
          </div>
        </div>
      )}

      {stage === 'done' && result && (
        <div>
          {/* ── Top stats ── */}
          <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 16, direction: 'rtl' }}>
            <Badge label="وقت المعالجة" value={`${result.processing_time_ms?.toFixed(0)}ms`} color={C.accent} />
            <Badge label="الصفحة" value={result.page_number} color={C.purple} />
            <Badge label="التوكينز" value={result.token_count} color={C.green} />
            <Badge label="الفجوات" value={result.layers?.border_gaps?.total} color={C.orange} />
            <Badge label="مقبولة" value={result.layers?.border_gaps?.accepted} color={C.green} />
            <Badge label="الخلايا" value={result.layers?.merged_cells?.total} color={C.yellow} />
            <Badge label="مدمجة" value={result.layers?.merged_cells?.merged} color={C.orange} />
            <Badge label="راديو" value={result.radio_groups?.length} color={C.indigo} />
          </div>

          {/* ── Tabs ── */}
          <div style={{ display: 'flex', gap: 8, marginBottom: 16, direction: 'rtl' }}>
            {TAB('overlay',  '🖼 Overlay المشروح')}
            {TAB('compare',  '⚖ مقارنة الصفحة')}
            {TAB('audit',    '🩹 سجل الفجوات')}
            {TAB('merged',   '🔗 الخلايا المدمجة')}
            {TAB('hyp',      '🧪 الفرضيات')}
            {TAB('json',     '{ } JSON')}
          </div>

          {/* ── Overlay tab ── */}
          {activeTab === 'overlay' && result.overlay_image_b64 && (
            <div>
              <div style={{ fontSize: 12, color: C.muted, marginBottom: 8, direction: 'rtl' }}>
                الصورة المشروحة بكل طبقات الهندسة المكتشفة
              </div>
              <img
                src={`data:image/png;base64,${result.overlay_image_b64}`}
                alt="geometry overlay"
                style={{ width: '100%', borderRadius: 12, border: `1px solid ${C.border}` }}
              />
              <div style={{ display: 'flex', gap: 12, marginTop: 10, flexWrap: 'wrap', direction: 'ltr', fontSize: 11 }}>
                {[
                  ['━━', '#7ec8e3', 'Horizontal lines'],
                  ['━━', '#4a7fbd', 'Vertical lines'],
                  ['□', '#10b981', 'Checkboxes / boxes'],
                  ['▣', '#00ffc8', 'Grid cells'],
                  ['●', '#ffff00', 'Grid nodes'],
                  ['✓', '#3fff60', 'Gap filled (accepted)'],
                  ['✗', '#ff2828', 'Gap rejected'],
                  ['▣', '#ff8c00', 'Merged cells'],
                ].map(([sym, clr, desc]) => (
                  <span key={desc} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                    <span style={{ color: clr, fontWeight: 700 }}>{sym}</span>
                    <span style={{ color: C.muted }}>{desc}</span>
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* ── Compare tab ── */}
          {activeTab === 'compare' && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
              <div>
                <div style={{ fontSize: 12, color: C.muted, marginBottom: 6, textAlign: 'center' }}>صفحة أصلية</div>
                {result.page_image_b64 && (
                  <img src={`data:image/png;base64,${result.page_image_b64}`}
                    alt="original" style={{ width: '100%', borderRadius: 10, border: `1px solid ${C.border}` }} />
                )}
              </div>
              <div>
                <div style={{ fontSize: 12, color: C.muted, marginBottom: 6, textAlign: 'center' }}>مع طبقات الهندسة</div>
                {result.overlay_image_b64 && (
                  <img src={`data:image/png;base64,${result.overlay_image_b64}`}
                    alt="overlay" style={{ width: '100%', borderRadius: 10, border: `1px solid ${C.border}` }} />
                )}
              </div>
            </div>
          )}

          {/* ── Audit tab ── */}
          {activeTab === 'audit' && (
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 10, direction: 'rtl' }}>
                سجل قرارات البورد إنفيرنس ({result.border_audit?.length} قرار)
              </div>
              {(result.border_audit || []).length === 0
                ? <div style={{ color: C.muted, fontSize: 13 }}>لا توجد فجوات محللة</div>
                : (showAll ? result.border_audit : result.border_audit.slice(0, 25)).map((r, i) => (
                    <AuditRow key={i} rec={r} />
                  ))
              }
              {(result.border_audit?.length || 0) > 25 && (
                <button onClick={() => setShowAll(s => !s)} style={{
                  marginTop: 8, padding: '6px 16px', borderRadius: 8, cursor: 'pointer',
                  background: C.card, border: `1px solid ${C.border}`, color: C.muted, fontSize: 12,
                }}>
                  {showAll ? 'عرض أقل' : `عرض الكل (${result.border_audit.length})`}
                </button>
              )}
            </div>
          )}

          {/* ── Merged tab ── */}
          {activeTab === 'merged' && (
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 10, direction: 'rtl' }}>
                الخلايا المدمجة ({result.merged_cells?.length} خلية)
              </div>
              {(result.merged_cells || []).length === 0
                ? <div style={{ color: C.muted, fontSize: 13 }}>لا توجد خلايا مدمجة</div>
                : result.merged_cells.map((c, i) => <MergedCellRow key={i} cell={c} />)
              }
              {result.radio_groups?.length > 0 && (
                <div style={{ marginTop: 20 }}>
                  <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8, color: C.indigo }}>
                    مجموعات الراديو المكتشفة ({result.radio_groups.length})
                  </div>
                  {result.radio_groups.map((g, i) => (
                    <div key={i} style={{
                      display: 'flex', gap: 8, alignItems: 'center',
                      padding: '6px 12px', borderRadius: 8, marginBottom: 4,
                      background: `${C.indigo}10`, border: `1px solid ${C.indigo}30`, fontSize: 12,
                    }}>
                      <span style={{ color: C.indigo, fontWeight: 700 }}>⊙</span>
                      <span style={{ color: C.text }}>{g.text_content || '(بدون تسمية)'}</span>
                      <span style={{ marginLeft: 'auto', color: C.muted }}>
                        score: {(g.fusion_score * 100).toFixed(0)}%
                      </span>
                      <span style={{
                        background: g.accepted ? `${C.green}20` : `${C.red}20`,
                        color: g.accepted ? C.green : C.red,
                        padding: '1px 8px', borderRadius: 10, fontSize: 10,
                      }}>
                        {g.accepted ? 'مقبول' : 'مرفوض'}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* ── Hypotheses tab ── */}
          {activeTab === 'hyp' && (
            <div>
              <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 12, direction: 'rtl' }}>
                ملخص الفرضيات حسب النوع
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginBottom: 20 }}>
                {Object.entries(result.hypotheses_summary || {}).map(([type, stats]) => (
                  <HypCard key={type} type={type} stats={stats} />
                ))}
              </div>
              {Object.keys(result.hypotheses_summary || {}).length === 0 && (
                <div style={{ color: C.muted, fontSize: 13 }}>لا توجد فرضيات محللة</div>
              )}
              {result.nested_grids && Object.keys(result.nested_grids).length > 0 && (
                <div style={{ marginTop: 16 }}>
                  <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 8, color: C.yellow }}>
                    جداول متداخلة
                  </div>
                  {Object.entries(result.nested_grids).map(([parentId, count]) => (
                    <div key={parentId} style={{
                      display: 'flex', gap: 8, padding: '5px 12px', borderRadius: 8, marginBottom: 4,
                      background: `${C.yellow}10`, border: `1px solid ${C.yellow}25`, fontSize: 12,
                    }}>
                      <span style={{ color: C.yellow }}>⊞</span>
                      <span style={{ color: C.muted, fontFamily: 'monospace' }}>{parentId.slice(0, 12)}…</span>
                      <span style={{ color: C.yellow, fontWeight: 700, marginLeft: 'auto' }}>
                        {count} جدول داخلي
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* ── JSON tab ── */}
          {activeTab === 'json' && (
            <div style={{ position: 'relative' }}>
              <button
                onClick={() => {
                  const { page_image_b64, overlay_image_b64, ...rest } = result;
                  const b = new Blob([JSON.stringify(rest, null, 2)], { type: 'application/json' });
                  const u = URL.createObjectURL(b);
                  const a = document.createElement('a');
                  a.href = u; a.download = `phase2b_debug_p${result.page_number}.json`; a.click();
                  URL.revokeObjectURL(u);
                }}
                style={{
                  position: 'absolute', top: 12, left: 12, zIndex: 10,
                  background: `${C.purple}cc`, color: '#fff', border: 'none',
                  borderRadius: 6, padding: '6px 14px', cursor: 'pointer', fontSize: 12,
                }}
              >⬇ تحميل JSON</button>
              <textarea
                readOnly
                value={(() => {
                  const { page_image_b64, overlay_image_b64, ...rest } = result;
                  return JSON.stringify(rest, null, 2);
                })()}
                style={{
                  width: '100%', background: '#0d1117', borderRadius: 12,
                  padding: '48px 16px 16px', fontSize: 11, color: '#e6edf3',
                  border: `1px solid ${C.border}`, height: 500,
                  direction: 'ltr', lineHeight: 1.6, fontFamily: 'monospace',
                  boxSizing: 'border-box',
                }}
              />
            </div>
          )}

          {/* ── Re-analyze ── */}
          <div style={{ marginTop: 20, display: 'flex', gap: 10, direction: 'rtl' }}>
            <button onClick={() => { setStage('idle'); setResult(null); }} style={{
              padding: '8px 18px', borderRadius: 8, cursor: 'pointer',
              background: C.card, border: `1px solid ${C.border}`, color: C.muted, fontSize: 13,
            }}>← ملف جديد</button>
            <div style={{ fontSize: 11, color: C.muted, alignSelf: 'center' }}>
              {filename} · صفحة {result.page_number} · {result.processing_time_ms?.toFixed(0)}ms
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
