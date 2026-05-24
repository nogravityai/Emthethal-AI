/**
 * Right Panel — Evidence Inspector + HITL Operations
 * 
 * Maps exactly to selected evidence details and human feedback triggers.
 */
import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useWorkbenchStore } from '../store/workbenchStore.js';
import { HITL_OP_TYPES } from '../services/pipelineService.js';

const C = {
  bg: '#05080F', panel: '#0B1120', border: '#1A2438',
  blue: '#3B82F6', green: '#10B981', red: '#EF4444',
  yellow: '#F59E0B', purple: '#A78BFA', pink: '#EC4899',
  orange: '#F97316', text: '#E2E8F0', muted: '#64748B', accent: '#0EA5E9',
};

function computeFinalScore(cb) {
  if (!cb) return 0;
  const base = (cb.geometry_score ?? 0) * 0.4 + (cb.assignment_score ?? 0) * 0.4 + (cb.text_score ?? 0) * 0.2;
  const penalty = (cb.anchor_penalty ?? 0) + (cb.conflict_penalty ?? 0);
  return Math.max(0, Math.min(1, base - penalty + (cb.human_override_score ?? 0)));
}

function ConfBar({ label, value, color, tooltip }) {
  return (
    <div style={{ marginBottom: 6 }} title={tooltip}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
        <span style={{ fontSize: 9, color: C.muted, textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</span>
        <span style={{ fontSize: 10, fontFamily: 'monospace', color }}>{(value * 100).toFixed(0)}%</span>
      </div>
      <div style={{ height: 3, background: C.border, borderRadius: 9 }}>
        <div style={{ height: '100%', width: `${value * 100}%`, background: color, borderRadius: 9, transition: 'width 0.5s ease' }} />
      </div>
    </div>
  );
}

function Badge({ text, color }) {
  return (
    <span style={{
      fontSize: 9, fontFamily: 'monospace', padding: '2px 7px', borderRadius: 4,
      background: `${color}20`, border: `1px solid ${color}50`, color,
      letterSpacing: '0.06em', whiteSpace: 'nowrap',
    }}>{text}</span>
  );
}

function SectionTitle({ children }) {
  return (
    <div style={{ fontSize: 9, color: C.muted, textTransform: 'uppercase', letterSpacing: '0.12em', marginBottom: 10, fontWeight: 700 }}>
      {children}
    </div>
  );
}

function HitlButton({ label, icon, color, onClick, disabled, title }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      style={{
        width: '100%', padding: '7px 10px', borderRadius: 7,
        border: `1px solid ${color}40`,
        background: `${color}10`,
        color, fontSize: 11, cursor: disabled ? 'not-allowed' : 'pointer',
        fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6,
        opacity: disabled ? 0.45 : 1,
        transition: 'all 0.15s', marginBottom: 5,
        textAlign: 'left',
      }}
      onMouseEnter={e => { if (!disabled) e.currentTarget.style.background = `${color}20`; }}
      onMouseLeave={e => { if (!disabled) e.currentTarget.style.background = `${color}10`; }}
    >
      <span style={{ fontSize: 12 }}>{icon}</span>
      <span>{label}</span>
    </button>
  );
}

export default function RightPanel({ onHitlOp }) {
  const { selected, runId, loading, snapshots, hitlLedger, setSelected, runs, determinismOk } = useWorkbenchStore();
  const [tab, setTab] = useState('inspector'); // 'inspector' | 'hitl' | 'ledger'

  const sel = selected;
  const isRegion = sel?.type === 'region';
  const isToken  = sel?.type === 'token';
  const isField  = sel?.type === 'field';
  const isTable  = sel?.type === 'table';
  const isCell   = sel?.type === 'cell';
  const isShape  = sel?.type === 'shape';

  const dispatch = (operation_type, extra = {}) => {
    if (!sel || !runId) return;
    
    // Resolve target IDs depending on element type
    let targetIds = [];
    if (isRegion) targetIds = [sel.data.id];
    else if (isToken) targetIds = [sel.data.id];
    else if (isField) targetIds = [sel.data.field_id];
    else if (isTable) targetIds = [sel.data.table_id];
    else if (isCell) targetIds = [sel.data.cell_id];

    // Fallback trigger if onHitlOp is passed or global window hook is available
    const trigger = onHitlOp || window.__cfisHitl;
    if (trigger) {
      trigger({
        operation_type,
        target_evidence_ids: targetIds,
        payload: extra,
      });
    }
  };

  return (
    <aside style={{
      width: 280, minWidth: 280,
      background: C.panel,
      borderLeft: `1px solid ${C.border}`,
      display: 'flex', flexDirection: 'column',
      overflowY: 'auto',
      flexShrink: 0,
    }}>
      {/* Tab bar */}
      <div style={{ display: 'flex', borderBottom: `1px solid ${C.border}`, flexShrink: 0 }}>
        {[
          { key: 'inspector', label: '🔍 Inspector' },
          { key: 'hitl',      label: '✏ HITL Ops' },
          { key: 'ledger',    label: `📋 Ledger${hitlLedger.length > 0 ? ` (${hitlLedger.length})` : ''}` },
        ].map(t => (
          <button
            key={t.key}
            id={`right-tab-${t.key}`}
            onClick={() => setTab(t.key)}
            style={{
              flex: 1, padding: '10px 4px', fontSize: 10, fontWeight: 600,
              background: 'transparent', border: 'none',
              borderBottom: `2px solid ${tab === t.key ? C.blue : 'transparent'}`,
              color: tab === t.key ? C.text : C.muted,
              cursor: 'pointer', transition: 'all 0.15s',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '14px 14px' }}>
        {/* ── INSPECTOR TAB ─────────────────────────────────────────── */}
        {tab === 'inspector' && (
          <AnimatePresence mode="wait">
            {sel ? (
              <motion.div
                key={sel.data.id ?? sel.data.centroid?.join(',')}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
              >
                {/* Element card */}
                <div style={{ background: C.bg, borderRadius: 8, padding: 12, border: `1px solid ${C.border}`, marginBottom: 10 }}>
                  <div style={{ display: 'flex', gap: 6, marginBottom: 8, flexWrap: 'wrap' }}>
                    <Badge
                      text={sel.type.toUpperCase()}
                      color={
                        sel.type === 'token' ? C.green :
                        sel.type === 'region' ? C.blue :
                        sel.type === 'field' ? C.purple :
                        sel.type === 'shape' ? C.orange :
                        sel.type === 'table' || sel.type === 'cell' ? C.yellow : C.pink
                      }
                    />
                    {sel.data.confidence != null && (
                      <Badge
                        text={`${(sel.data.confidence * 100).toFixed(0)}% conf`}
                        color={sel.data.confidence > 0.85 ? C.green : sel.data.confidence > 0.6 ? C.yellow : C.red}
                      />
                    )}
                  </div>

                  {/* Details by type */}
                  {isTable && (
                    <div style={{ fontSize: 13, color: C.text, fontWeight: 600, marginBottom: 8 }}>
                      📊 Table ID: <span style={{ fontFamily: 'monospace', color: C.yellow }}>{sel.data.table_id}</span>
                      <div style={{ fontSize: 11, color: C.muted, marginTop: 4 }}>
                        Dimensions: {sel.data.rows_count} Rows × {sel.data.cols_count} Columns
                      </div>
                    </div>
                  )}

                  {isCell && (
                    <div style={{ fontSize: 13, color: C.text, fontWeight: 600, marginBottom: 8 }}>
                      🧱 Cell ID: <span style={{ fontFamily: 'monospace', color: C.yellow }}>{sel.data.cell_id}</span>
                      <div style={{ fontSize: 11, color: C.muted, marginTop: 4 }}>
                        Position: Row {sel.data.row_index}, Column {sel.data.column_index}
                      </div>
                    </div>
                  )}

                  {isShape && (
                    <div style={{ fontSize: 13, color: C.text, fontWeight: 600, marginBottom: 8 }}>
                      📐 Shape Contour
                      <div style={{ fontSize: 11, color: C.muted, marginTop: 4, fontFamily: 'monospace' }}>
                        Area: {sel.data.area.toFixed(1)}px²<br />
                        Perimeter: {sel.data.perimeter.toFixed(1)}px<br />
                        Aspect Ratio: {sel.data.aspect_ratio.toFixed(3)}<br />
                        Centroid: ({Math.round(sel.data.centroid[0])}, {Math.round(sel.data.centroid[1])})
                      </div>
                      <div style={{ borderTop: `1px solid ${C.border}`, marginTop: 8, paddingTop: 8 }}>
                        <div style={{ fontSize: 9, color: C.yellow, marginBottom: 4, textTransform: 'uppercase' }}>Hu Moments (7 descriptor logs)</div>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: 2, maxHeight: 110, overflowY: 'auto' }}>
                          {sel.data.hu_moments.map((val, idx) => (
                            <div key={idx} style={{ fontSize: 8, fontFamily: 'monospace', color: C.muted }}>
                              h{idx}: <span style={{ color: C.text }}>{val.toExponential(4)}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  )}

                  {sel.data.text && (
                    <div style={{ fontSize: 14, color: C.text, fontWeight: 600, marginBottom: 6, direction: 'rtl' }}>
                      "{sel.data.text}"
                    </div>
                  )}

                  {!isShape && (
                    <div style={{ fontSize: 9, fontFamily: 'monospace', color: C.muted, wordBreak: 'break-all', lineHeight: 1.6 }}>
                      <span style={{ color: C.accent }}>stable_id: </span>{sel.data.id ?? sel.data.field_id ?? sel.data.table_id ?? sel.data.cell_id ?? '—'}
                    </div>
                  )}

                  {sel.data.bbox && (
                    <div style={{ fontSize: 9, fontFamily: 'monospace', color: C.muted, marginTop: 4 }}>
                      <span style={{ color: C.accent }}>bbox: </span>
                      [{sel.data.bbox.map(v => Math.round(v)).join(', ')}]
                    </div>
                  )}
                </div>

                {/* Confidence breakdown for fused fields */}
                {isField && sel.data.confidence_breakdown && (() => {
                  const cb = sel.data.confidence_breakdown;
                  const final = computeFinalScore(cb);
                  return (
                    <div style={{ background: C.bg, borderRadius: 8, padding: 12, border: `1px solid ${C.border}`, marginBottom: 10 }}>
                      <SectionTitle>Confidence Breakdown</SectionTitle>
                      <ConfBar label="Geometry Score"    value={cb.geometry_score    ?? 0} color={C.blue}   tooltip="Spatial overlap quality (×0.4)" />
                      <ConfBar label="Assignment Score"  value={cb.assignment_score  ?? 0} color={C.green}  tooltip="Alignment edge strength (×0.4)" />
                      <ConfBar label="Text Score"        value={cb.text_score        ?? 0} color={C.yellow} tooltip="OCR confidence (×0.2)" />
                      {(cb.anchor_penalty ?? 0) > 0 && (
                        <ConfBar label="Anchor Penalty" value={cb.anchor_penalty} color={C.orange} tooltip="Anchor region penalty" />
                      )}
                      {(cb.conflict_penalty ?? 0) > 0 && (
                        <ConfBar label="Conflict Penalty" value={cb.conflict_penalty} color={C.red} tooltip="Conflict edges penalty" />
                      )}
                      {(cb.human_override_score ?? 0) > 0 && (
                        <ConfBar label="HITL Boost" value={cb.human_override_score} color={C.purple} tooltip="Human override adjustment" />
                      )}
                      <div style={{ borderTop: `1px solid ${C.border}`, marginTop: 8, paddingTop: 8 }}>
                        <ConfBar label="Final Score" value={final} color={C.accent} />
                      </div>
                    </div>
                  );
                })()}

                {/* Provenance graph */}
                {isField && (sel.data.ocr_tokens?.length > 0 || sel.data.alignment_edges?.length > 0) && (
                  <div style={{ background: C.bg, borderRadius: 8, padding: 12, border: `1px solid ${C.border}`, marginBottom: 10 }}>
                    <SectionTitle>Provenance Graph</SectionTitle>
                    <div style={{ fontSize: 10, color: C.muted, lineHeight: 1.8 }}>
                      <div>
                        <span style={{ color: C.green }}>OCR Tokens: </span>
                        <span style={{ fontFamily: 'monospace', color: C.text }}>{sel.data.ocr_tokens?.length ?? 0}</span>
                      </div>
                      <div>
                        <span style={{ color: C.pink }}>Alignment Edges: </span>
                        <span style={{ fontFamily: 'monospace', color: C.text }}>{sel.data.alignment_edges?.length ?? 0}</span>
                      </div>
                    </div>
                  </div>
                )}
              </motion.div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                {/* System Overview */}
                <div style={{ background: C.bg, borderRadius: 8, padding: 12, border: `1px solid ${C.border}` }}>
                  <SectionTitle>System Overview</SectionTitle>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 8, fontSize: 10 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: C.muted }}>Status:</span>
                      <span style={{ fontWeight: 700, color: loading ? C.yellow : C.green }}>
                        {loading ? 'RUNNING…' : 'IDLE'}
                      </span>
                    </div>
                    {runId && (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                        <span style={{ color: C.muted }}>Active Run ID:</span>
                        <span style={{ fontFamily: 'monospace', fontSize: 8, color: C.accent, wordBreak: 'break-all' }}>{runId}</span>
                      </div>
                    )}
                    <div style={{ display: 'flex', justifyContent: 'space-between', borderTop: `1px solid ${C.border}`, paddingTop: 6 }}>
                      <span style={{ color: C.muted }}>Determinism:</span>
                      {determinismOk ? (
                        <span style={{ color: C.green, fontWeight: 700 }}>✓ VERIFIED</span>
                      ) : (
                        <span style={{ color: C.red, fontWeight: 700 }}>⚠️ DRIFT DETECTED</span>
                      )}
                    </div>
                  </div>
                </div>

                {/* Metrics */}
                <div style={{ background: C.bg, borderRadius: 8, padding: 12, border: `1px solid ${C.border}` }}>
                  <SectionTitle>Pipeline Metrics</SectionTitle>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <span style={{ fontSize: 10, color: C.text }}>OCR Tokens</span>
                      <Badge text={snapshots.ocr?.tokens?.length ?? 0} color={C.green} />
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <span style={{ fontSize: 10, color: C.text }}>Geometry Regions</span>
                      <Badge text={snapshots.geometry?.regions?.length ?? 0} color={C.blue} />
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                      <span style={{ fontSize: 10, color: C.text }}>Resolved Fields</span>
                      <Badge text={snapshots.fusion?.fields?.length ?? 0} color={C.purple} />
                    </div>
                  </div>
                </div>

                {/* Help tip */}
                <div style={{ border: `1px dashed ${C.border}`, borderRadius: 8, padding: 14, textAlign: 'center' }}>
                  <div style={{ fontSize: 20, marginBottom: 6, opacity: 0.35 }}>🔍</div>
                  <div style={{ fontSize: 9, color: C.muted, lineHeight: 1.5 }}>
                    Click any element on the canvas to inspect text, bounding boxes, parent nodes, confidence scores, and more.
                  </div>
                </div>
              </div>
            )}
          </AnimatePresence>
        )}

        {/* ── HITL OPS TAB ──────────────────────────────────────────── */}
        {tab === 'hitl' && (
          <div>
            <SectionTitle>HITL Editor</SectionTitle>
            <div style={{ fontSize: 10, color: C.muted, marginBottom: 14, lineHeight: 1.7 }}>
              Trigger intent-based operations that update downstream elements on rerun.
            </div>

            {!sel && (
              <div style={{ fontSize: 10, color: C.yellow, background: `${C.yellow}10`, border: `1px solid ${C.yellow}30`, borderRadius: 6, padding: '8px 10px', marginBottom: 12 }}>
                ⚠ Select an element on the document canvas first
              </div>
            )}

            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 9, color: C.blue, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8 }}>Region Operations</div>
              <HitlButton icon="⛔" label="Reject Region (line_rejection)"    color={C.red}    onClick={() => dispatch(HITL_OP_TYPES.LINE_REJECTION)} disabled={!isRegion || loading} />
              <HitlButton icon="✅" label="Approve Region (line_approval)"    color={C.green}  onClick={() => dispatch(HITL_OP_TYPES.LINE_APPROVAL)}  disabled={!isRegion || loading} />
              <HitlButton icon="🔀" label="Merge Regions (region_merge)"      color={C.yellow} onClick={() => dispatch(HITL_OP_TYPES.REGION_MERGE, { source_regions: [sel?.data?.id] })} disabled={!isRegion || loading} />
              <HitlButton icon="✂" label="Split Region (region_split)"       color={C.orange} onClick={() => dispatch(HITL_OP_TYPES.REGION_SPLIT, { source_region: sel?.data?.id, split_coordinates: { x: 0.5 } })} disabled={!isRegion || loading} />
            </div>

            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 9, color: C.green, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8 }}>Token Operations</div>
              <HitlButton icon="🔗" label="Reassign Token" color={C.green} onClick={() => dispatch(HITL_OP_TYPES.TOKEN_REASSIGNMENT, { token_id: sel?.data?.id, new_region_id: '' })} disabled={!isToken || loading} />
            </div>

            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 9, color: C.purple, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8 }}>Checkbox Operations</div>
              <HitlButton icon="☑" label="Set Checkbox True"  color={C.purple} onClick={() => dispatch(HITL_OP_TYPES.CHECKBOX_CORRECTION, { region_id: sel?.data?.id, new_state: true })} disabled={!isRegion || loading} />
              <HitlButton icon="☐" label="Set Checkbox False" color={C.pink}   onClick={() => dispatch(HITL_OP_TYPES.CHECKBOX_CORRECTION, { region_id: sel?.data?.id, new_state: false })} disabled={!isRegion || loading} />
            </div>
          </div>
        )}

        {/* ── LEDGER TAB ────────────────────────────────────────────── */}
        {tab === 'ledger' && (
          <div>
            <SectionTitle>Operations Ledger</SectionTitle>
            {hitlLedger.length === 0 ? (
              <div style={{ fontSize: 11, color: C.muted, textAlign: 'center', padding: 20 }}>
                No operations recorded yet
              </div>
            ) : (
              hitlLedger.map((op, idx) => (
                <div key={op.operation_id ?? idx} style={{
                  background: C.bg, borderRadius: 7, padding: 10, marginBottom: 8,
                  border: `1px solid ${C.border}`,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                    <Badge text={op.operation_type} color={C.purple} />
                    <span style={{ fontSize: 8, color: C.muted, fontFamily: 'monospace' }}>
                      {op.timestamp ? new Date(op.timestamp).toLocaleTimeString() : '—'}
                    </span>
                  </div>
                  <div style={{ fontSize: 8, color: C.muted, fontFamily: 'monospace' }}>
                    op_id: {op.operation_id?.slice(0, 16)}…
                  </div>
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
