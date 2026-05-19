/**
 * Left Panel — Evidence Inspector + HITL Operations
 * 
 * Maps exactly to Phase 3 backend models:
 * - OcrToken:      { id (stable_id), text, confidence, bbox }
 * - GeometryRegion: { id (stable_id), bbox, confidence }
 * - AlignmentEdge: { id, type (AlignmentType enum), score, token, region }
 * - FusionField:   { id (field_id), field_type, confidence, ocr_tokens[], alignment_edges[] }
 *                    + confidence_breakdown: { geometry_score, assignment_score, text_score,
 *                                             anchor_penalty, conflict_penalty, human_override_score }
 * 
 * HITL operations map to backend hitl/models.py:
 * - line_rejection, line_approval
 * - region_merge, region_split  
 * - token_reassignment
 * - checkbox_correction
 */
import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useWorkbenchStore, LAYER_META } from '../store/workbenchStore.js';
import { HITL_OP_TYPES } from '../services/pipelineService.js';

const C = {
  bg: '#05080F', panel: '#0B1120', border: '#1A2438',
  blue: '#3B82F6', green: '#10B981', red: '#EF4444',
  yellow: '#F59E0B', purple: '#A78BFA', pink: '#EC4899',
  orange: '#F97316', text: '#E2E8F0', muted: '#64748B', accent: '#0EA5E9',
};

// Confidence formula from backend: fusion/models.py ConfidenceBreakdown.final_score
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

export default function LeftPanel({ onHitlOp }) {
  const { selected, runId, loading, snapshots, layers, toggleLayer, hitlLedger } = useWorkbenchStore();
  const [hitlView, setHitlView] = useState('inspector'); // 'inspector' | 'hitl' | 'ledger'

  const sel = selected;
  const isRegion = sel?.type === 'region';
  const isToken  = sel?.type === 'token';
  const isField  = sel?.type === 'field';

  // Dispatch HITL — uses backend operation types from hitl/models.py
  const dispatch = (operation_type, extra = {}) => {
    if (!sel || !runId) return;
    onHitlOp({
      operation_type,
      target_evidence_ids: [sel.data.id],
      payload: extra,
    });
  };

  return (
    <aside style={{
      width: 280, minWidth: 280,
      background: C.panel,
      borderRight: `1px solid ${C.border}`,
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
        ].map(tab => (
          <button
            key={tab.key}
            id={`left-tab-${tab.key}`}
            onClick={() => setHitlView(tab.key)}
            style={{
              flex: 1, padding: '10px 4px', fontSize: 10, fontWeight: 600,
              background: 'transparent', border: 'none',
              borderBottom: `2px solid ${hitlView === tab.key ? C.blue : 'transparent'}`,
              color: hitlView === tab.key ? C.text : C.muted,
              cursor: 'pointer', transition: 'all 0.15s',
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '14px 14px' }}>
        {/* ── INSPECTOR TAB ─────────────────────────────────────────── */}
        {hitlView === 'inspector' && (
          <AnimatePresence mode="wait">
            {sel ? (
              <motion.div
                key={sel.data.id}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
              >
                {/* Element type + basic info */}
                <div style={{ background: C.bg, borderRadius: 8, padding: 12, border: `1px solid ${C.border}`, marginBottom: 10 }}>
                  <div style={{ display: 'flex', gap: 6, marginBottom: 8, flexWrap: 'wrap' }}>
                    <Badge
                      text={sel.type.toUpperCase()}
                      color={sel.type === 'token' ? C.green : sel.type === 'region' ? C.blue : sel.type === 'field' ? C.purple : C.pink}
                    />
                    {sel.data.confidence != null && (
                      <Badge
                        text={`${(sel.data.confidence * 100).toFixed(0)}% conf`}
                        color={sel.data.confidence > 0.85 ? C.green : sel.data.confidence > 0.6 ? C.yellow : C.red}
                      />
                    )}
                  </div>

                  {/* Text value (OCR token) */}
                  {sel.data.text && (
                    <div style={{ fontSize: 14, color: C.text, fontWeight: 600, marginBottom: 6, direction: 'rtl' }}>
                      "{sel.data.text}"
                    </div>
                  )}

                  {/* stable_id (immutable SHA-256 hash from backend) */}
                  <div style={{ fontSize: 9, fontFamily: 'monospace', color: C.muted, wordBreak: 'break-all', lineHeight: 1.6 }}>
                    <span style={{ color: C.accent }}>stable_id: </span>{sel.data.id ?? sel.data.field_id ?? '—'}
                  </div>

                  {/* BBox */}
                  {sel.data.bbox && (
                    <div style={{ fontSize: 9, fontFamily: 'monospace', color: C.muted, marginTop: 4 }}>
                      <span style={{ color: C.accent }}>bbox: </span>
                      [{sel.data.bbox.map(v => Math.round(v)).join(', ')}]
                    </div>
                  )}

                  {/* Alignment type (for alignment edges) */}
                  {sel.data.type && sel.type === 'alignment' && (
                    <div style={{ fontSize: 9, fontFamily: 'monospace', color: C.pink, marginTop: 4 }}>
                      type: {sel.data.type} · score: {(sel.data.score * 100).toFixed(0)}%
                    </div>
                  )}
                </div>

                {/* ConfidenceBreakdown — from fusion/models.py ConfidenceBreakdown */}
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
                        <ConfBar label="Conflict Penalty" value={cb.conflict_penalty} color={C.red} tooltip={`${(cb.conflict_penalty / 0.1).toFixed(0)} conflict edges × 0.1`} />
                      )}
                      {(cb.human_override_score ?? 0) > 0 && (
                        <ConfBar label="HITL Boost" value={cb.human_override_score} color={C.purple} tooltip="Human correction boost" />
                      )}
                      <div style={{ borderTop: `1px solid ${C.border}`, marginTop: 8, paddingTop: 8 }}>
                        <ConfBar label="Final Score" value={final} color={C.accent} tooltip="(geo×0.4)+(assign×0.4)+(text×0.2) - penalties + hitl" />
                      </div>
                      <div style={{ fontSize: 8, color: C.muted, marginTop: 6, fontFamily: 'monospace', lineHeight: 1.5 }}>
                        = (geo×0.4) + (assign×0.4) + (text×0.2) − penalties + hitl_boost
                      </div>
                    </div>
                  );
                })()}

                {/* Provenance — ResolvedFieldProvenance from fusion/models.py */}
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
                      {sel.data.field_type && (
                        <div>
                          <span style={{ color: C.purple }}>Field Type: </span>
                          <span style={{ fontFamily: 'monospace', color: C.text }}>{sel.data.field_type}</span>
                        </div>
                      )}
                    </div>
                    {sel.data.ocr_tokens?.slice(0, 3).map((tid, i) => (
                      <div key={i} style={{ fontSize: 8, fontFamily: 'monospace', color: C.muted, marginTop: 3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        → {tid}
                      </div>
                    ))}
                  </div>
                )}

                {/* HITL Quick Actions — based on element type */}
                {(isRegion || isToken) && runId && (
                  <div style={{ background: C.bg, borderRadius: 8, padding: 12, border: `1px solid ${C.border}20`, marginBottom: 10 }}>
                    <SectionTitle>Quick HITL Actions</SectionTitle>
                    <div style={{ fontSize: 9, color: C.muted, marginBottom: 8, lineHeight: 1.6 }}>
                      Operations are logged in the immutable ledger then trigger /hitl/rerun from evidence_patching stage.
                    </div>
                    {isRegion && (
                      <>
                        <HitlButton
                          icon="⛔" label="Reject Region"
                          color={C.red}
                          onClick={() => dispatch(HITL_OP_TYPES.LINE_REJECTION)}
                          disabled={loading}
                          title="POST /hitl/operations: line_rejection"
                        />
                        <HitlButton
                          icon="✅" label="Approve Region"
                          color={C.green}
                          onClick={() => dispatch(HITL_OP_TYPES.LINE_APPROVAL)}
                          disabled={loading}
                          title="POST /hitl/operations: line_approval"
                        />
                      </>
                    )}
                    {isToken && (
                      <HitlButton
                        icon="🔗" label="Reassign Token"
                        color={C.yellow}
                        onClick={() => dispatch(HITL_OP_TYPES.TOKEN_REASSIGNMENT, { token_id: sel.data.id, new_region_id: '' })}
                        disabled={loading}
                        title="POST /hitl/operations: token_reassignment"
                      />
                    )}
                  </div>
                )}
              </motion.div>
            ) : (
              <motion.div
                key="empty"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                style={{ border: `1px dashed ${C.border}`, borderRadius: 8, padding: 28, textAlign: 'center', marginTop: 10 }}
              >
                <div style={{ fontSize: 28, marginBottom: 10, opacity: 0.25 }}>🔍</div>
                <div style={{ fontSize: 11, color: C.muted, lineHeight: 1.6 }}>
                  Click any token, region, or field on the canvas to inspect its provenance and evidence graph
                </div>
              </motion.div>
            )}
          </AnimatePresence>
        )}

        {/* ── HITL OPS TAB ──────────────────────────────────────────── */}
        {hitlView === 'hitl' && (
          <div>
            <SectionTitle>HITL Editor — Intent-Based Operations</SectionTitle>
            <div style={{ fontSize: 10, color: C.muted, marginBottom: 14, lineHeight: 1.7 }}>
              Select an element on the canvas, then choose an operation. Operations are logged in the immutable ledger and trigger a deterministic replay from <span style={{ color: C.accent, fontFamily: 'monospace' }}>evidence_patching</span> stage.
            </div>

            {!sel && (
              <div style={{ fontSize: 10, color: C.yellow, background: `${C.yellow}10`, border: `1px solid ${C.yellow}30`, borderRadius: 6, padding: '8px 10px', marginBottom: 12 }}>
                ⚠ Select an element on the document canvas first
              </div>
            )}

            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 9, color: C.blue, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8 }}>Region Operations</div>
              <HitlButton icon="⛔" label="Reject Region (line_rejection)"    color={C.red}    onClick={() => dispatch(HITL_OP_TYPES.LINE_REJECTION)} disabled={!isRegion || loading} title="HumanLineRejection → removes region from evidence" />
              <HitlButton icon="✅" label="Approve Region (line_approval)"    color={C.green}  onClick={() => dispatch(HITL_OP_TYPES.LINE_APPROVAL)}  disabled={!isRegion || loading} title="HumanLineApproval → boosts confidence" />
              <HitlButton icon="🔀" label="Merge Regions (region_merge)"      color={C.yellow} onClick={() => dispatch(HITL_OP_TYPES.REGION_MERGE, { source_regions: [sel?.data?.id] })} disabled={!isRegion || loading} title="HumanRegionMerge → merges selected + target" />
              <HitlButton icon="✂" label="Split Region (region_split)"       color={C.orange} onClick={() => dispatch(HITL_OP_TYPES.REGION_SPLIT, { source_region: sel?.data?.id, split_coordinates: { x: 0.5 } })} disabled={!isRegion || loading} title="HumanRegionSplit → splits at midpoint" />
            </div>

            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 9, color: C.green, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8 }}>Token Operations</div>
              <HitlButton icon="🔗" label="Reassign Token (token_reassignment)" color={C.green} onClick={() => dispatch(HITL_OP_TYPES.TOKEN_REASSIGNMENT, { token_id: sel?.data?.id, new_region_id: '' })} disabled={!isToken || loading} title="HumanTokenReassignment" />
            </div>

            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 9, color: C.purple, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8 }}>Checkbox Operations</div>
              <HitlButton icon="☑" label="Set Checkbox True (checkbox_correction)"  color={C.purple} onClick={() => dispatch(HITL_OP_TYPES.CHECKBOX_CORRECTION, { region_id: sel?.data?.id, new_state: true })} disabled={!isRegion || loading} title="HumanCheckboxCorrection: new_state=true" />
              <HitlButton icon="☐" label="Set Checkbox False (checkbox_correction)" color={C.pink}   onClick={() => dispatch(HITL_OP_TYPES.CHECKBOX_CORRECTION, { region_id: sel?.data?.id, new_state: false })} disabled={!isRegion || loading} title="HumanCheckboxCorrection: new_state=false" />
            </div>

            <div style={{ fontSize: 9, color: C.muted, background: `${C.blue}08`, border: `1px solid ${C.blue}20`, borderRadius: 6, padding: '8px 10px', lineHeight: 1.6 }}>
              🔒 The UI never directly modifies evidence. All operations are sent as <span style={{ color: C.blue }}>HumanOperation</span> intents to the backend ledger, then a replay regenerates all downstream artifacts.
            </div>
          </div>
        )}

        {/* ── LEDGER TAB ────────────────────────────────────────────── */}
        {hitlView === 'ledger' && (
          <div>
            <SectionTitle>Operations Ledger</SectionTitle>
            {hitlLedger.length === 0 ? (
              <div style={{ fontSize: 11, color: C.muted, textAlign: 'center', padding: 20 }}>
                No HITL operations recorded for this run
              </div>
            ) : (
              hitlLedger.map((op, i) => (
                <div key={op.operation_id ?? i} style={{
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
                  <div style={{ fontSize: 8, color: C.muted, fontFamily: 'monospace' }}>
                    targets: {op.target_evidence_ids?.length ?? 0} evidence items
                  </div>
                </div>
              ))
            )}
          </div>
        )}
      </div>

      {/* Stats footer */}
      {snapshots.ocr && (
        <div style={{
          padding: '10px 14px', borderTop: `1px solid ${C.border}`,
          display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6, flexShrink: 0,
        }}>
          {[
            { label: 'Tokens',    val: snapshots.ocr?.tokens?.length ?? 0,        color: C.green },
            { label: 'Regions',   val: snapshots.geometry?.regions?.length ?? 0,   color: C.blue },
            { label: 'Alignments',val: snapshots.alignment?.alignments?.length ?? 0, color: C.pink },
            { label: 'Fields',    val: snapshots.fusion?.fields?.length ?? 0,      color: C.purple },
          ].map(({ label, val, color }) => (
            <div key={label} style={{ background: C.bg, borderRadius: 5, padding: '6px 8px', textAlign: 'center', border: `1px solid ${C.border}` }}>
              <div style={{ fontSize: 16, fontWeight: 800, color, fontVariantNumeric: 'tabular-nums' }}>{val}</div>
              <div style={{ fontSize: 8, color: C.muted, textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</div>
            </div>
          ))}
        </div>
      )}
    </aside>
  );
}
