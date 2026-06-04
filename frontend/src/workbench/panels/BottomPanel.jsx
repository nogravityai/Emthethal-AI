/**
 * Bottom Panel — Canonical Schema Preview
 * 
 * Displays the export from GET /api/cfis/v3/pipeline/export/{run_id}:
 * {
 *   canonical_document: { document_id, schema_version, sections: [...] },
 *   formio_schema: { components: [{ title, components: [{ type, label, key, defaultValue }] }] }
 * }
 * 
 * Also shows raw evidence snapshots and diff (before/after HITL).
 */
import React, { useState } from 'react';
import { useWorkbenchStore } from '../store/workbenchStore.js';

const C = {
  bg: '#05080F', panel: '#0B1120', border: '#1A2438',
  blue: '#3B82F6', green: '#10B981', red: '#EF4444',
  yellow: '#F59E0B', purple: '#A78BFA', pink: '#EC4899',
  text: '#E2E8F0', muted: '#64748B', accent: '#0EA5E9',
};

function JsonTree({ data, depth = 0 }) {
  if (data === null || data === undefined) return <span style={{ color: C.muted }}>null</span>;
  if (typeof data === 'boolean') return <span style={{ color: C.purple }}>{String(data)}</span>;
  if (typeof data === 'number') return <span style={{ color: C.yellow, fontVariantNumeric: 'tabular-nums' }}>{data}</span>;
  if (typeof data === 'string') return <span style={{ color: C.green }}>"{data}"</span>;
  if (Array.isArray(data)) {
    if (data.length === 0) return <span style={{ color: C.muted }}>[]</span>;
    return (
      <span>
        [<br />
        {data.slice(0, 5).map((item, i) => (
          <span key={i}>
            <span style={{ paddingLeft: (depth + 1) * 14 }} />
            <JsonTree data={item} depth={depth + 1} />
            {i < data.length - 1 ? ',' : ''}<br />
          </span>
        ))}
        {data.length > 5 && <span style={{ paddingLeft: (depth + 1) * 14, color: C.muted }}>…+{data.length - 5} more<br /></span>}
        <span style={{ paddingLeft: depth * 14 }}>]</span>
      </span>
    );
  }
  // Object
  const keys = Object.keys(data);
  return (
    <span>
      {'{'}<br />
      {keys.slice(0, 20).map((k, i) => (
        <span key={k}>
          <span style={{ paddingLeft: (depth + 1) * 14 }}>
            <span style={{ color: C.accent }}>"{k}"</span>
            <span style={{ color: C.muted }}>: </span>
            <JsonTree data={data[k]} depth={depth + 1} />
            {i < keys.length - 1 ? ',' : ''}
          </span><br />
        </span>
      ))}
      {keys.length > 20 && <span style={{ paddingLeft: (depth + 1) * 14, color: C.muted }}>…+{keys.length - 20} more keys<br /></span>}
      <span style={{ paddingLeft: depth * 14 }}>{'}'}</span>
    </span>
  );
}

function FormioPreview({ formioSchema }) {
  if (!formioSchema?.components?.length) {
    return <div style={{ color: C.muted, fontSize: 11, padding: 20, textAlign: 'center' }}>No Form.io schema available</div>;
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {formioSchema.components.map((panel, pi) => (
        <div key={pi} style={{ background: C.bg, borderRadius: 8, border: `1px solid ${C.border}`, overflow: 'hidden' }}>
          <div style={{ padding: '10px 14px', borderBottom: `1px solid ${C.border}`, background: `${C.blue}08` }}>
            <span style={{ fontSize: 12, fontWeight: 700, color: C.text }}>{panel.title ?? `Panel ${pi + 1}`}</span>
          </div>
          <div style={{ padding: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
            {panel.components?.map((comp, ci) => (
              <div key={ci}>
                <label style={{ fontSize: 9, color: C.muted, textTransform: 'uppercase', letterSpacing: '0.06em', display: 'block', marginBottom: 4 }}>
                  {comp.label}
                </label>
                {comp.type === 'checkbox' ? (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <div style={{
                      width: 16, height: 16, borderRadius: 4,
                      border: `2px solid ${comp.defaultValue ? C.blue : C.border}`,
                      background: comp.defaultValue ? C.blue : 'transparent',
                      display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
                    }}>
                      {comp.defaultValue && <span style={{ color: 'white', fontSize: 10, fontWeight: 800 }}>✓</span>}
                    </div>
                    <span style={{ fontSize: 11, color: comp.defaultValue ? C.text : C.muted }}>
                      {comp.defaultValue ? 'Checked' : 'Unchecked'}
                    </span>
                    {comp.defaultValue !== undefined && (
                      <span style={{ fontSize: 8, marginLeft: 'auto', fontFamily: 'monospace', color: C.purple }}>
                        provenance_ref: {comp.key}
                      </span>
                    )}
                  </div>
                ) : (
                  <div style={{
                    border: `1px solid ${comp.defaultValue ? C.border : C.border + '60'}`,
                    borderRadius: 6, padding: '7px 12px',
                    background: C.panel, fontSize: 13, minHeight: 36,
                    color: comp.defaultValue ? C.text : C.muted,
                    direction: 'rtl', display: 'flex', alignItems: 'center', gap: 8,
                  }}>
                    <span style={{ flex: 1 }}>{comp.defaultValue || <span style={{ opacity: 0.3 }}>—</span>}</span>
                    {comp.defaultValue && (
                      <span style={{ fontSize: 8, color: C.accent, fontFamily: 'monospace', direction: 'ltr' }}>
                        {comp.key}
                      </span>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function RawSnapshotView({ snapshots }) {
  const [activeStage, setActiveStage] = useState('ocr');
  const stageData = {
    ocr:       snapshots.ocr,
    geometry:  snapshots.geometry,
    alignment: snapshots.alignment,
    fusion:    snapshots.fusion,
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      <div style={{ display: 'flex', gap: 6 }}>
        {Object.entries({ ocr: C.green, geometry: C.blue, alignment: C.pink, fusion: C.purple }).map(([k, color]) => (
          <button
            key={k}
            id={`raw-stage-${k}`}
            onClick={() => setActiveStage(k)}
            style={{
              padding: '4px 12px', borderRadius: 5, border: `1px solid ${activeStage === k ? color + '60' : C.border}`,
              background: activeStage === k ? `${color}15` : 'transparent',
              color: activeStage === k ? color : C.muted,
              fontSize: 10, fontWeight: 600, cursor: 'pointer',
            }}
          >
            {k}
          </button>
        ))}
      </div>
      <pre style={{
        background: C.bg, borderRadius: 8, padding: 14,
        border: `1px solid ${C.border}`, fontSize: 9,
        fontFamily: 'monospace', color: C.text,
        overflow: 'auto', maxHeight: 260, lineHeight: 1.6,
      }}>
        <JsonTree data={stageData[activeStage]} />
      </pre>
    </div>
  );
}

function SystemLogsView({ snapshots, runs, determinismOk }) {
  const logs = [];

  // 1. Check determinism status
  if (!determinismOk) {
    logs.push({
      type: 'error',
      tag: 'DETERMINISM',
      msg: 'Drift detected. Output artifact stable IDs have changed post-replay.'
    });
  } else if (runs.length > 0) {
    logs.push({
      type: 'info',
      tag: 'REPLAY',
      msg: `Replay successful. Pipeline states verified deterministic across ${runs.length} iterations.`
    });
  }

  // 2. Check OCR token confidence
  const lowConfTokens = snapshots.ocr?.tokens?.filter(t => t.confidence < 0.85) || [];
  lowConfTokens.forEach(t => {
    logs.push({
      type: 'warning',
      tag: 'OCR',
      msg: `Low confidence OCR token "${t.text}" (${Math.round(t.confidence * 100)}%) at ID ${t.id.slice(0, 8)}.`
    });
  });

  // 3. Check Geometry confidence
  const lowConfRegions = snapshots.geometry?.regions?.filter(r => r.confidence < 0.80) || [];
  lowConfRegions.forEach(r => {
    logs.push({
      type: 'warning',
      tag: 'GEOMETRY',
      msg: `Low confidence geometry bounding box region (${Math.round(r.confidence * 100)}%) at ID ${r.id.slice(0, 8)}.`
    });
  });

  // 4. Check Coordinate space
  if (snapshots.coordinate_space?.coordinate_space) {
    logs.push({
      type: 'info',
      tag: 'COORD_SPACE',
      msg: `Coordinate space detected: "${snapshots.coordinate_space.coordinate_space}" @ ${snapshots.coordinate_space.detected_dpi} DPI. Dimensions: ${snapshots.coordinate_space.page_width}x${snapshots.coordinate_space.page_height}.`
    });
  }

  // 5. Shapes info
  if (snapshots.shapes?.shapes?.length > 0) {
    logs.push({
      type: 'info',
      tag: 'SHAPES',
      msg: `PrimitiveShapeEngine successfully registered ${snapshots.shapes.shapes.length} geometric contour invariants.`
    });
  }

  // 6. Conflicting alignment warnings
  const overlaps = snapshots.alignment?.alignments?.filter(a => a.type === 'token_crosses_boundary') || [];
  overlaps.forEach(a => {
    logs.push({
      type: 'warning',
      tag: 'CONFLICT',
      msg: `Boundary conflict: Token ${a.token.slice(0, 8)} crosses region boundary ${a.region.slice(0, 8)} (Score: ${Math.round(a.score * 100)}%).`
    });
  });

  if (logs.length === 0) {
    return (
      <div style={{ color: C.muted, fontSize: 11, textAlign: 'center', padding: 20 }}>
        No pipeline log events or warnings for this run.
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {logs.map((log, i) => {
        const color = log.type === 'error' ? C.red : log.type === 'warning' ? C.yellow : C.blue;
        return (
          <div key={i} style={{
            background: C.bg, borderLeft: `3px solid ${color}`,
            padding: '6px 12px', borderRadius: 4,
            fontSize: 9, fontFamily: 'monospace', color: C.text,
            display: 'flex', gap: 10, alignItems: 'center'
          }}>
            <span style={{ color, fontWeight: 700 }}>[{log.tag}]</span>
            <span style={{ flex: 1 }}>{log.msg}</span>
          </div>
        );
      })}
    </div>
  );
}

const TABS = [
  { key: 'zones',  label: '🏗 Zone Schema' },
  { key: 'json',   label: '📄 Canonical JSON' },
  { key: 'formio', label: '📝 Form.io Preview' },
  { key: 'erpnext', label: '⚙ ERPNext' },
  { key: 'raw',    label: '🔬 Raw Evidence' },
  { key: 'diff',   label: '⚖ Before/After Diff' },
  { key: 'logs',   label: '📋 Logs & Warnings' },
];

const PANEL_H = 300;

const FT_ICONS = {
  date: '📅', checkbox: '☑', radio: '🔘', dropdown: '⬇', text: '📝',
  name: '👤', number: '#', phone: '📞', email: '✉', signature: '✍',
  header: '🏷', form_title: '📋', table: '📊', unknown: '❓',
};

const FT_COLORS = {
  date: '#0EA5E9', checkbox: '#10B981', radio: '#A78BFA', dropdown: '#F59E0B',
  text: '#64748B', name: '#3B82F6', number: '#EC4899', phone: '#06B6D4',
  email: '#8B5CF6', signature: '#F97316', header: '#EF4444',
  form_title: '#F43F5E', table: '#FBBF24', unknown: '#374151',
};

function ZoneSchemaView({ schema }) {
  const doc = schema?.canonical_document;
  if (!doc) {
    return (
      <div style={{ color: C.muted, fontSize: 11, textAlign: 'center', padding: 28 }}>
        شغّل الـ pipeline أولاً لعرض Zone Schema
      </div>
    );
  }

  const allSections = doc.pages?.flatMap(p => p.sections) ?? [];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      {/* Form title */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 0', borderBottom: `1px solid ${C.border}`, marginBottom: 8 }}>
        <span style={{ fontSize: 14 }}>📋</span>
        <span style={{ fontSize: 12, fontWeight: 700, color: C.text }}>{doc.title || 'Untitled Form'}</span>
        <span style={{ fontSize: 9, color: C.muted, fontFamily: 'monospace', marginLeft: 'auto' }}>
          v{doc.schema_version} · {allSections.length} zones
        </span>
      </div>

      {/* Sections (zones) */}
      {allSections.map((sec, si) => {
        const included = sec.include_in_form !== false;
        const secColor = included ? C.green : C.red;
        const fieldCount = sec.fields?.length ?? 0;

        return (
          <div key={sec.section_id || si} style={{
            background: C.bg, borderRadius: 8,
            border: `1px solid ${included ? C.border : C.red + '40'}`,
            overflow: 'hidden', marginBottom: 6,
          }}>
            {/* Zone header */}
            <div style={{
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '7px 12px', borderBottom: fieldCount > 0 ? `1px solid ${C.border}` : 'none',
              background: included ? `${C.green}08` : `${C.red}08`,
            }}>
              <span style={{ fontSize: 10, color: secColor, fontWeight: 800 }}>{included ? '🟢' : '🔴'}</span>
              <span style={{ fontSize: 11, fontWeight: 700, color: C.text }}>{sec.title}</span>
              <span style={{ fontSize: 9, color: C.muted, fontFamily: 'monospace' }}>{sec.zone_type}</span>
              <span style={{ fontSize: 9, color: C.muted, marginLeft: 'auto' }}>{fieldCount} حقل</span>
              {!included && (
                <span style={{ fontSize: 8, color: C.red, background: `${C.red}20`, borderRadius: 3, padding: '1px 5px', fontWeight: 700 }}>EXCLUDED</span>
              )}
            </div>

            {/* Child fields */}
            {sec.fields?.map((field, fi) => {
              const ft = field.field_type || 'text';
              const icon = FT_ICONS[ft] || '❓';
              const color = FT_COLORS[ft] || C.muted;
              const isLast = fi === sec.fields.length - 1;
              return (
                <div key={field.field_id || fi} style={{
                  display: 'flex', alignItems: 'center', gap: 8,
                  padding: '5px 16px',
                  borderBottom: !isLast ? `1px solid ${C.border}40` : 'none',
                }}>
                  <span style={{ color: C.muted, fontSize: 9, width: 12 }}>{'└─'}</span>
                  <span style={{ fontSize: 11 }}>{icon}</span>
                  <span style={{
                    fontSize: 9, fontWeight: 600,
                    background: `${color}18`, color, borderRadius: 3,
                    padding: '1px 5px', fontFamily: 'monospace', minWidth: 60, textAlign: 'center',
                  }}>{ft}</span>
                  <span style={{ fontSize: 10, color: C.text, direction: 'rtl', flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {field.field_name}
                  </span>
                  {field.value !== null && field.value !== undefined && (
                    <span style={{ fontSize: 9, color: C.muted, maxWidth: 120, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', direction: 'rtl' }}>
                      {String(field.value)}
                    </span>
                  )}
                  <span style={{ fontSize: 8, fontFamily: 'monospace', color: C.muted, minWidth: 30, textAlign: 'right' }}>
                    {((field.confidence_score || 0) * 100).toFixed(0)}%
                  </span>
                </div>
              );
            })}
          </div>
        );
      })}
    </div>
  );
}

export default function BottomPanel() {
  const { activeTab, setActiveTab, schema, snapshots, runs, determinismOk, isBottomCollapsed, setBottomCollapsed } = useWorkbenchStore();

  const hasPrev = runs.length > 1;

  return (
    <div style={{
      height: isBottomCollapsed ? 32 : PANEL_H, flexShrink: 0,
      background: C.panel,
      borderTop: `1px solid ${C.border}`,
      display: 'flex', flexDirection: 'column',
      overflow: 'hidden',
      transition: 'height 0.2s ease',
    }}>
      {/* Tab bar */}
      <div style={{ display: 'flex', borderBottom: isBottomCollapsed ? 'none' : `1px solid ${C.border}`, flexShrink: 0, alignItems: 'center', height: 32 }}>
        {/* Collapse toggle */}
        <button
          id="toggle-bottom-panel"
          onClick={() => setBottomCollapsed(!isBottomCollapsed)}
          title={isBottomCollapsed ? "Expand Bottom Panel" : "Collapse Bottom Panel"}
          aria-label={isBottomCollapsed ? "Expand Bottom Panel" : "Collapse Bottom Panel"}
          style={{
            background: 'transparent', border: 'none', color: C.muted,
            cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
            width: 32, height: 32, fontSize: 10,
          }}
        >
          {isBottomCollapsed ? '▲' : '▼'}
        </button>

        {TABS.map(t => (
          <button
            key={t.key}
            id={`bottom-tab-${t.key}`}
            onClick={() => {
              setActiveTab(t.key);
              if (isBottomCollapsed) setBottomCollapsed(false);
            }}
            style={{
              padding: '0 12px', fontSize: 10, fontWeight: 600, whiteSpace: 'nowrap',
              background: 'transparent', border: 'none',
              borderBottom: !isBottomCollapsed && activeTab === t.key ? `2px solid ${C.blue}` : 'none',
              color: activeTab === t.key ? C.text : C.muted,
              cursor: 'pointer', transition: 'all 0.15s',
              height: 32,
            }}
          >
            {t.label}
          </button>
        ))}
        {schema && !isBottomCollapsed && (
          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', paddingRight: 12, gap: 8 }}>
            <span style={{ fontSize: 8, color: C.purple, fontFamily: 'monospace' }}>
              v{schema.canonical_document?.schema_version}
            </span>
            <button
              id="export-json-btn"
              aria-label="Export Canonical JSON"
              onClick={() => {
                const blob = new Blob([JSON.stringify(schema.canonical_document, null, 2)], { type: 'application/json' });
                const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
                a.download = `cfis_canonical_${Date.now()}.json`; a.click();
              }}
              style={{ fontSize: 10, padding: '3px 8px', borderRadius: 5, border: `1px solid ${C.border}`, background: C.bg, color: C.muted, cursor: 'pointer' }}
            >
              ↓ JSON
            </button>
            {schema.erpnext_schema && (
              <button
                id="export-erpnext-btn"
                aria-label="Export ERPNext DocType"
                onClick={() => {
                  const blob = new Blob([JSON.stringify(schema.erpnext_schema, null, 2)], { type: 'application/json' });
                  const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
                  a.download = `erpnext_doctype_${Date.now()}.json`; a.click();
                }}
                style={{ fontSize: 10, padding: '3px 8px', borderRadius: 5, border: `1px solid #10B98140`, background: '#10B98112', color: '#10B981', cursor: 'pointer', fontWeight: 600 }}
              >
                ↓ ERPNext
              </button>
            )}
            {schema.formio_schema && (
              <button
                id="export-formio-btn"
                aria-label="Export Form.io Schema"
                onClick={() => {
                  const blob = new Blob([JSON.stringify(schema.formio_schema, null, 2)], { type: 'application/json' });
                  const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
                  a.download = `formio_schema_${Date.now()}.json`; a.click();
                }}
                style={{ fontSize: 10, padding: '3px 8px', borderRadius: 5, border: `1px solid #3B82F640`, background: '#3B82F612', color: '#3B82F6', cursor: 'pointer', fontWeight: 600 }}
              >
                ↓ Form.io
              </button>
            )}
          </div>
        )}
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '12px 16px' }}>

        {/* ── ZONE SCHEMA ─────────────────────────────────────── */}
        {activeTab === 'zones' && (
          <ZoneSchemaView schema={schema} />
        )}

        {/* ── CANONICAL JSON ─────────────────────────────────────────── */}
        {activeTab === 'json' && (
          schema ? (
            <pre style={{ background: C.bg, borderRadius: 8, padding: 14, border: `1px solid ${C.border}`, fontSize: 9, fontFamily: 'monospace', color: C.text, overflow: 'auto', maxHeight: 200, lineHeight: 1.6 }}>
              <JsonTree data={schema.canonical_document} />
            </pre>
          ) : (
            <div style={{ color: C.muted, fontSize: 11, textAlign: 'center', padding: 28 }}>
              Run the pipeline to see the Canonical Document schema
            </div>
          )
        )}

        {/* ── ERPNEXT ────────────────────────────────────────────── */}
        {activeTab === 'erpnext' && (
          schema?.erpnext_schema ? (
            <pre style={{ background: C.bg, borderRadius: 8, padding: 14, border: `1px solid ${C.border}`, fontSize: 9, fontFamily: 'monospace', color: C.text, overflow: 'auto', maxHeight: 220, lineHeight: 1.6 }}>
              <JsonTree data={schema.erpnext_schema} />
            </pre>
          ) : (
            <div style={{ color: C.muted, fontSize: 11, textAlign: 'center', padding: 28 }}>
              شغّل الـ pipeline لعرض ERPNext DocType schema
            </div>
          )
        )}

        {/* ── FORM.IO PREVIEW ────────────────────────────────────────── */}
        {activeTab === 'formio' && (
          schema ? (
            <FormioPreview formioSchema={schema.formio_schema} />
          ) : (
            <div style={{ color: C.muted, fontSize: 11, textAlign: 'center', padding: 28 }}>
              Run the pipeline to preview the Form.io output
            </div>
          )
        )}

        {/* ── RAW EVIDENCE ───────────────────────────────────────────── */}
        {activeTab === 'raw' && (
          snapshots.ocr ? (
            <RawSnapshotView snapshots={snapshots} />
          ) : (
            <div style={{ color: C.muted, fontSize: 11, textAlign: 'center', padding: 28 }}>
              Run the pipeline to inspect raw evidence snapshots
            </div>
          )
        )}

        {/* ── DIFF VIEW ──────────────────────────────────────────────── */}
        {activeTab === 'diff' && (
          <div>
            {hasPrev ? (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                <div>
                  <div style={{ fontSize: 9, color: C.muted, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 8 }}>
                    Previous Run · {runs[1]?.run_id?.slice(0, 12)}…
                  </div>
                  <pre style={{ background: C.bg, borderRadius: 7, padding: 10, border: `1px solid ${C.border}`, fontSize: 8, fontFamily: 'monospace', color: C.text, overflow: 'auto', maxHeight: 180, lineHeight: 1.5 }}>
                    {`Fields: ${runs[1]?.stages?.length ?? '?'} stages\nDeterministic: ${runs[1]?.determinism_ok}`}
                  </pre>
                </div>
                <div>
                  <div style={{ fontSize: 9, color: C.blue, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 8 }}>
                    Current Run · {runs[0]?.run_id?.slice(0, 12)}…{runs[0]?.is_hitl_rerun ? ' (HITL)' : ''}
                  </div>
                  <pre style={{ background: C.bg, borderRadius: 7, padding: 10, border: `1px solid ${C.blue}30`, fontSize: 8, fontFamily: 'monospace', color: C.text, overflow: 'auto', maxHeight: 180, lineHeight: 1.5 }}>
                    {`Fields: ${runs[0]?.stages?.length ?? '?'} stages\nDeterministic: ${runs[0]?.determinism_ok}`}
                  </pre>
                </div>
              </div>
            ) : (
              <div style={{ color: C.muted, fontSize: 11, textAlign: 'center', padding: 28 }}>
                Run the pipeline at least twice (or perform a HITL operation) to see the diff
              </div>
            )}
          </div>
        )}
        {/* ── LOGS & WARNINGS ─────────────────────────────────────────── */}
        {activeTab === 'logs' && (
          snapshots.ocr ? (
            <SystemLogsView snapshots={snapshots} runs={runs} determinismOk={determinismOk} />
          ) : (
            <div style={{ color: C.muted, fontSize: 11, textAlign: 'center', padding: 28 }}>
              Run the pipeline to inspect system logs and warnings
            </div>
          )
        )}
      </div>
    </div>
  );
}
