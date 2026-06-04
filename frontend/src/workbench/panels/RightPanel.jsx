/**
 * Right Panel — Evidence Inspector + HITL Operations
 * 
 * Maps exactly to selected evidence details and human feedback triggers.
 */
import React, { useState, useEffect, useMemo } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useWorkbenchStore } from '../store/workbenchStore.js';
import { HITL_OP_TYPES } from '../services/pipelineService.js';
import {
  detectFieldsInZone, detectFieldType,
  FIELD_TYPE_ICONS, FIELD_TYPE_LABELS, FIELD_TYPE_COLORS, ALL_FIELD_TYPES,
} from '../services/fieldTypeDetector.js';

const ZONE_TYPES = [
  { value: 'patient_info', label: 'Patient Info / معلومات المريض' },
  { value: 'section_header', label: 'Section Header / عنوان القسم' },
  { value: 'table', label: 'Table / جدول' },
  { value: 'checkbox_group', label: 'Checkbox Group / مجموعة مربعات اختيار' },
  { value: 'free_text', label: 'Free Text / نص حر' },
  { value: 'signature_block', label: 'Signature Block / مربع توقيع' },
  { value: 'footer', label: 'Footer / تذييل الصفحة' },
  { value: 'unknown', label: 'Unknown / غير معروف' },
];

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
  const {
    selected, runId, loading, snapshots, hitlLedger, setSelected, runs, determinismOk,
    drawingMode, setDrawingMode, zoneFieldCorrections, setZoneFieldCorrection,
  } = useWorkbenchStore();
  const [tab, setTab] = useState('inspector'); // 'inspector' | 'hitl' | 'ledger'
  const [localLabel, setLocalLabel] = useState('');

  const sel = selected;
  const isRegion = sel?.type === 'region';
  const isToken  = sel?.type === 'token';
  const isField  = sel?.type === 'field';
  const isTable  = sel?.type === 'table';
  const isCell   = sel?.type === 'cell';
  const isShape  = sel?.type === 'shape';
  const isZone   = sel?.type === 'zone';
  const isFormElement = sel?.type === 'form_element';

  // Compute child fields for the selected zone
  const zoneFields = useMemo(() => {
    if (!isZone || !sel?.data?.bbox) return [];
    const fusionFields = snapshots?.fusion?.fields || [];
    const ocrTokens   = snapshots?.ocr?.tokens   || [];
    return detectFieldsInZone(sel.data, ocrTokens, fusionFields);
  }, [isZone, sel, snapshots]);

  const elementEdges = useMemo(() => {
    if (!isFormElement || !snapshots?.topology?.form_graph?.edges) return [];
    return snapshots.topology.form_graph.edges.filter(
      edge => edge.source_id === sel.data.element_id || edge.target_id === sel.data.element_id
    );
  }, [isFormElement, sel, snapshots]);

  const elementConstraints = useMemo(() => {
    if (!isFormElement || !snapshots?.topology?.form_graph?.constraints) return [];
    return snapshots.topology.form_graph.constraints.filter(
      c => c.target_element_ids.includes(sel.data.element_id)
    );
  }, [isFormElement, sel, snapshots]);

  // Zone's include_in_form state (from zone data, default true)
  const zoneIncluded = isZone ? (sel.data.include_in_form ?? true) : true;

  useEffect(() => {
    if (sel?.type === 'zone') {
      setLocalLabel(sel.data.zone_label ?? '');
    } else {
      setLocalLabel('');
    }
  }, [sel]);

  const handleRenameSubmit = () => {
    if (!localLabel.trim() || loading) return;
    dispatch('zone_operation', {
      zone_op_type: 'RENAME_ZONE',
      parameters: { zone_label: localLabel.trim() }
    });
  };

  const dispatch = (operation_type, extra = {}) => {
    if (!sel || !runId) return;
    
    // Resolve target IDs depending on element type
    let targetIds = [];
    if (isRegion) targetIds = [sel.data.id];
    else if (isToken) targetIds = [sel.data.id];
    else if (isField) targetIds = [sel.data.field_id];
    else if (isTable) targetIds = [sel.data.table_id];
    else if (isCell) targetIds = [sel.data.cell_id];
    else if (isZone) targetIds = [sel.data.zone_id];

    // Fallback trigger if onHitlOp is passed or global window hook is available
    const trigger = onHitlOp || window.__cfisHitl;
    if (trigger) {
      if (operation_type === 'zone_operation') {
        trigger({
          operation_type: 'zone_operation',
          target_evidence_ids: targetIds,
          payload: {
            zone_op_type: extra.zone_op_type,
            target_zone_id: sel.data.zone_id,
            parameters: extra.parameters ?? {},
          }
        });
      } else {
        trigger({
          operation_type,
          target_evidence_ids: targetIds,
          payload: extra,
        });
      }
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
                key={sel.data.element_id ?? sel.data.id ?? sel.data.centroid?.join(',')}
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
                        sel.type === 'table' || sel.type === 'cell' ? C.yellow :
                        sel.type === 'form_element' ? C.purple : C.pink
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

                  {isZone && (
                    <div style={{ fontSize: 13, color: C.text, fontWeight: 600, marginBottom: 8 }}>
                      🧬 Semantic Zone / منطقة دلالية
                      <div style={{ fontSize: 11, color: C.muted, marginTop: 6 }}>
                        Label: <span style={{ color: C.pink }}>{sel.data.zone_label}</span><br />
                        Type: <span style={{ color: C.accent }}>{sel.data.zone_type}</span><br />
                        Fields: <span style={{ color: C.green }}>{zoneFields.length} حقل مكتشف</span>
                      </div>
                    </div>
                  )}

                  {isFormElement && (
                    <div style={{ fontSize: 13, color: C.text, fontWeight: 600, marginBottom: 8 }}>
                      🕸 Form Element / عنصر النموذج
                      <div style={{ fontSize: 11, color: C.muted, marginTop: 6, lineHeight: 1.6 }}>
                        Label: <span style={{ color: C.purple }}>{sel.data.label}</span><br />
                        Type: <span style={{ color: C.accent }}>{sel.data.element_type.replace('_', ' ').toUpperCase()}</span>
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
                      <span style={{ color: C.accent }}>stable_id: </span>{sel.data.element_id ?? sel.data.id ?? sel.data.zone_id ?? sel.data.field_id ?? sel.data.table_id ?? sel.data.cell_id ?? '—'}
                    </div>
                  )}

                  {sel.data.bbox && (
                    <div style={{ fontSize: 9, fontFamily: 'monospace', color: C.muted, marginTop: 4 }}>
                      <span style={{ color: C.accent }}>bbox: </span>
                      {Array.isArray(sel.data.bbox) 
                        ? `[${sel.data.bbox.map(v => Math.round(v)).join(', ')}]`
                        : `[${Math.round(sel.data.bbox.x_min)}, ${Math.round(sel.data.bbox.y_min)}, ${Math.round(sel.data.bbox.x_max)}, ${Math.round(sel.data.bbox.y_max)}]`
                      }
                    </div>
                  )}

                  {isFormElement && sel.data.topology_signature && (
                    <div style={{ borderTop: `1px solid ${C.border}`, marginTop: 8, paddingTop: 8 }}>
                      <div style={{ fontSize: 9, color: C.yellow, marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Topology Signature</div>
                      <div style={{ fontSize: 10, color: C.muted, lineHeight: 1.5 }}>
                        Alignment Group: <span style={{ color: C.text }}>{sel.data.topology_signature.alignment_group}</span><br />
                        Indentation Level: <span style={{ color: C.text }}>{sel.data.topology_signature.indentation_level}</span><br />
                        {sel.data.topology_signature.row_index !== null && sel.data.topology_signature.row_index !== undefined && <>Row Index: <span style={{ color: C.text }}>{sel.data.topology_signature.row_index}</span><br /></>}
                        {sel.data.topology_signature.column_index !== null && sel.data.topology_signature.column_index !== undefined && <>Col Index: <span style={{ color: C.text }}>{sel.data.topology_signature.column_index}</span><br /></>}
                        {sel.data.topology_signature.lane_id && <>Lane ID: <span style={{ color: C.text }}>{sel.data.topology_signature.lane_id}</span><br /></>}
                      </div>
                    </div>
                  )}
                </div>

                {/* Zone child fields inspector */}
                {isZone && zoneFields.length > 0 && (
                  <div style={{ background: C.bg, borderRadius: 8, border: `1px solid ${C.border}`, marginBottom: 10, overflow: 'hidden' }}>
                    <div style={{
                      padding: '8px 12px', borderBottom: `1px solid ${C.border}`,
                      fontSize: 9, color: C.pink, textTransform: 'uppercase', letterSpacing: '0.1em', fontWeight: 700,
                    }}>
                      🧩 الحقول المكتشفة ({zoneFields.length})
                    </div>
                    {zoneFields.map((field, idx) => {
                      const correction = zoneFieldCorrections[sel.data.zone_id]?.[field.field_id];
                      const ftype = correction?.type || field.detected_type;
                      const icon  = FIELD_TYPE_ICONS[ftype] || '❓';
                      const color = FIELD_TYPE_COLORS[ftype] || C.muted;
                      return (
                        <div key={field.field_id || idx} style={{
                          padding: '8px 12px',
                          borderBottom: idx < zoneFields.length - 1 ? `1px solid ${C.border}` : 'none',
                        }}>
                          {/* Field header */}
                          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                            <span style={{ fontSize: 13 }}>{icon}</span>
                            <span style={{ fontSize: 10, color: C.text, fontWeight: 600, flex: 1, direction: 'rtl' }}>
                              {correction?.label || field.label}
                            </span>
                            {/* Type dropdown */}
                            <select
                              value={ftype}
                              onChange={e => {
                                const newType = e.target.value;
                                const newLabel = correction?.label || field.label;
                                setZoneFieldCorrection(sel.data.zone_id, field.field_id, { type: newType, label: newLabel });
                                const trigger = onHitlOp || window.__cfisHitl;
                                if (trigger) {
                                  trigger({
                                    operation_type: 'field_type_correction',
                                    target_evidence_ids: [field.field_id],
                                    payload: {
                                      zone_id: sel.data.zone_id,
                                      field_id: field.field_id,
                                      corrected_type: newType,
                                      corrected_label: newLabel,
                                    }
                                  });
                                }
                              }}
                              style={{
                                background: `${color}20`,
                                border: `1px solid ${color}60`,
                                borderRadius: 4, color, fontSize: 9,
                                padding: '2px 4px', cursor: 'pointer', fontWeight: 700,
                              }}
                            >
                              {ALL_FIELD_TYPES.map(t => (
                                <option key={t} value={t}>{FIELD_TYPE_LABELS[t]}</option>
                              ))}
                            </select>
                          </div>
                          {/* Value preview */}
                          {field.value && (
                            <div style={{ fontSize: 10, color: C.muted, direction: 'rtl', paddingRight: 20, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                              {String(field.value)}
                            </div>
                          )}
                          {/* Confidence bar */}
                          <div style={{ marginTop: 4, display: 'flex', alignItems: 'center', gap: 6 }}>
                            <div style={{ flex: 1, height: 2, background: C.border, borderRadius: 2 }}>
                              <div style={{ height: '100%', width: `${(field.confidence || 0) * 100}%`, background: field.confidence > 0.8 ? C.green : field.confidence > 0.5 ? C.yellow : C.red, borderRadius: 2, transition: 'width 0.4s' }} />
                            </div>
                            <span style={{ fontSize: 8, fontFamily: 'monospace', color: C.muted }}>
                              {((field.confidence || 0) * 100).toFixed(0)}%
                            </span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                )}

                {isZone && zoneFields.length === 0 && (
                  <div style={{ background: C.bg, borderRadius: 8, border: `1px dashed ${C.border}`, padding: 12, marginBottom: 10, textAlign: 'center' }}>
                    <div style={{ fontSize: 18, opacity: 0.2, marginBottom: 4 }}>🧩</div>
                    <div style={{ fontSize: 9, color: C.muted }}>لا توجد حقول fusion داخل هذا الزون</div>
                    <div style={{ fontSize: 8, color: C.muted, marginTop: 4, opacity: 0.6 }}>شغّل الـ pipeline أولاً أو تحقق من إعدادات الـ Fusion layer</div>
                  </div>
                )}

                {/* Form Element Relationships & Constraints */}
                {isFormElement && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 10 }}>
                    {/* Edges list */}
                    <div style={{ background: C.bg, borderRadius: 8, border: `1px solid ${C.border}`, overflow: 'hidden' }}>
                      <div style={{
                        padding: '8px 12px', borderBottom: `1px solid ${C.border}`,
                        fontSize: 9, color: C.purple, textTransform: 'uppercase', letterSpacing: '0.1em', fontWeight: 700,
                      }}>
                        🔗 Relationships / العلاقات ({elementEdges.length})
                      </div>
                      <div style={{ maxHeight: 150, overflowY: 'auto' }}>
                        {elementEdges.length === 0 ? (
                          <div style={{ padding: '8px 12px', fontSize: 10, color: C.muted, fontStyle: 'italic' }}>No relations found</div>
                        ) : (
                          elementEdges.map((edge, idx) => {
                            const isSource = edge.source_id === sel.data.element_id;
                            const remoteId = isSource ? edge.target_id : edge.source_id;
                            const remoteEl = snapshots?.topology?.form_graph?.elements?.[remoteId];
                            const remoteLabel = remoteEl ? remoteEl.label : remoteId.slice(0, 12) + '...';
                            const direction = isSource ? 'Out' : 'In';
                            
                            return (
                              <div
                                key={idx}
                                onClick={() => {
                                  if (remoteEl) setSelected({ type: 'form_element', data: remoteEl });
                                }}
                                style={{
                                  padding: '6px 12px', borderBottom: idx < elementEdges.length - 1 ? `1px solid ${C.border}` : 'none',
                                  fontSize: 10, cursor: remoteEl ? 'pointer' : 'default',
                                  display: 'flex', justifyContent: 'space-between', alignItems: 'center'
                                }}
                                onMouseEnter={e => { if (remoteEl) e.currentTarget.style.background = `${C.border}50`; }}
                                onMouseLeave={e => { if (remoteEl) e.currentTarget.style.background = 'transparent'; }}
                              >
                                <div>
                                  <span style={{ color: edge.relation_type === 'option_of' ? C.green : edge.relation_type === 'activates' ? C.red : C.accent, fontWeight: 600 }}>
                                    {edge.relation_type.replace('_', ' ')}
                                  </span>
                                  <div style={{ fontSize: 9, color: C.muted }}>
                                    {direction}: {remoteLabel}
                                  </div>
                                </div>
                                <span style={{ fontSize: 8, background: C.border, padding: '1px 4px', borderRadius: 3, color: C.muted }}>
                                  {(edge.confidence * 100).toFixed(0)}%
                                </span>
                              </div>
                            );
                          })
                        )}
                      </div>
                    </div>

                    {/* Constraints list */}
                    <div style={{ background: C.bg, borderRadius: 8, border: `1px solid ${C.border}`, overflow: 'hidden' }}>
                      <div style={{
                        padding: '8px 12px', borderBottom: `1px solid ${C.border}`,
                        fontSize: 9, color: C.yellow, textTransform: 'uppercase', letterSpacing: '0.1em', fontWeight: 700,
                      }}>
                        ⚡ Constraints / القيود ({elementConstraints.length})
                      </div>
                      <div style={{ maxHeight: 150, overflowY: 'auto' }}>
                        {elementConstraints.length === 0 ? (
                          <div style={{ padding: '8px 12px', fontSize: 10, color: C.muted, fontStyle: 'italic' }}>No constraints found</div>
                        ) : (
                          elementConstraints.map((c, idx) => (
                            <div
                              key={idx}
                              style={{
                                padding: '8px 12px', borderBottom: idx < elementConstraints.length - 1 ? `1px solid ${C.border}` : 'none',
                                fontSize: 10, lineHeight: 1.4
                              }}
                            >
                              <div style={{ color: C.orange, fontWeight: 600, textTransform: 'capitalize' }}>
                                {c.constraint_type.replace('_', ' ')}
                              </div>
                              <div style={{ fontSize: 9, color: C.muted, marginTop: 2 }}>
                                Scope: {c.target_element_ids.map(id => {
                                  const name = snapshots?.topology?.form_graph?.elements?.[id]?.label || id.slice(0, 8);
                                  return name;
                                }).join(', ')}
                              </div>
                            </div>
                          ))
                        )}
                      </div>
                    </div>
                  </div>
                )}

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

            {/* Global Zone Drawing Toggle */}
            <div style={{ marginBottom: 14 }}>
              <div style={{ fontSize: 9, color: C.pink, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8 }}>Semantic Zones / المناطق الدلالية</div>
              <button
                onClick={() => setDrawingMode(!drawingMode)}
                style={{
                  width: '100%', padding: '7px 10px', borderRadius: 7,
                  border: `1px solid ${drawingMode ? '#F43F5E' : C.border}`,
                  background: drawingMode ? 'rgba(244, 63, 94, 0.25)' : 'transparent',
                  color: drawingMode ? '#F43F5E' : C.text,
                  fontSize: 11, cursor: 'pointer',
                  fontWeight: 600, display: 'flex', alignItems: 'center', gap: 6,
                  transition: 'all 0.15s',
                  boxShadow: drawingMode ? '0 0 8px rgba(244, 63, 94, 0.4)' : 'none',
                }}
              >
                <span style={{ fontSize: 12 }}>➕</span>
                <span>{drawingMode ? 'Drawing Mode Active / وضع الرسم نشط' : 'Draw New Zone / رسم منطقة جديدة'}</span>
              </button>
            </div>

            {!sel ? (
              <div style={{ fontSize: 10, color: C.yellow, background: `${C.yellow}10`, border: `1px solid ${C.yellow}30`, borderRadius: 6, padding: '8px 10px', marginBottom: 12 }}>
                ⚠ Select an element on the document canvas first / الرجاء تحديد عنصر أولاً
              </div>
            ) : (
              <>
                {/* Render zone specific controls here if zone selected */}
                {isZone && (
                  <div style={{ background: C.bg, borderRadius: 8, padding: 10, border: `1px dashed ${C.border}`, marginBottom: 14 }}>
                    <div style={{ fontSize: 10, color: C.text, fontWeight: 600, marginBottom: 8 }}>
                      Edit Selected Zone / تعديل المنطقة المحددة
                    </div>
                    
                    {/* Rename field */}
                    <div style={{ marginBottom: 8 }}>
                      <label style={{ fontSize: 8, color: C.muted, textTransform: 'uppercase', display: 'block', marginBottom: 4 }}>
                        Zone Label / تسمية المنطقة
                      </label>
                      <div style={{ display: 'flex', gap: 4 }}>
                        <input
                          type="text"
                          value={localLabel}
                          onChange={(e) => setLocalLabel(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' && localLabel.trim() && !loading) {
                              handleRenameSubmit();
                            }
                          }}
                          style={{
                            flex: 1,
                            background: C.panel,
                            border: `1px solid ${C.border}`,
                            borderRadius: 4,
                            color: C.text,
                            fontSize: 10,
                            padding: '4px 6px',
                          }}
                          placeholder="e.g. Patient Header"
                        />
                        <button
                          onClick={handleRenameSubmit}
                          disabled={loading || !localLabel.trim()}
                          style={{
                            padding: '4px 8px',
                            background: C.blue,
                            color: '#FFF',
                            border: 'none',
                            borderRadius: 4,
                            fontSize: 10,
                            fontWeight: 600,
                            cursor: 'pointer',
                            opacity: (loading || !localLabel.trim()) ? 0.5 : 1,
                          }}
                        >
                          OK
                        </button>
                      </div>
                    </div>

                    {/* Zone Type dropdown */}
                    <div style={{ marginBottom: 12 }}>
                      <label style={{ fontSize: 8, color: C.muted, textTransform: 'uppercase', display: 'block', marginBottom: 4 }}>
                        Zone Type / نوع المنطقة
                      </label>
                      <select
                        value={sel.data.zone_type ?? 'unknown'}
                        onChange={(e) => dispatch('zone_operation', { zone_op_type: 'RENAME_ZONE', parameters: { zone_type: e.target.value } })}
                        disabled={loading}
                        style={{
                          width: '100%',
                          background: C.panel,
                          border: `1px solid ${C.border}`,
                          borderRadius: 4,
                          color: C.text,
                          fontSize: 10,
                          padding: '4px 6px',
                          cursor: 'pointer',
                        }}
                      >
                        {ZONE_TYPES.map(t => (
                          <option key={t.value} value={t.value}>{t.label}</option>
                        ))}
                      </select>
                    </div>

                    {/* Delete button */}
                    <HitlButton
                      icon="🗑"
                      label="Delete Zone / حذف المنطقة"
                      color={C.red}
                      onClick={() => dispatch('zone_operation', { zone_op_type: 'DELETE_ZONE' })}
                      disabled={loading}
                    />
                  </div>
                )}

                {/* Zone semantic actions */}
                {isZone && (
                  <div style={{ background: C.bg, borderRadius: 8, padding: 10, border: `1px solid ${C.border}`, marginBottom: 14 }}>
                    <div style={{ fontSize: 9, color: C.pink, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8 }}>
                      Zone Semantics / إجراءات دلالية
                    </div>

                    {/* SET_FORM_TITLE */}
                    <HitlButton
                      icon="📋"
                      label="تعيين كاسم الاستمارة (form_title)"
                      color={C.accent}
                      onClick={() => dispatch('zone_operation', { zone_op_type: 'SET_FORM_TITLE' })}
                      disabled={loading}
                    />

                    {/* TOGGLE_INCLUDE */}
                    <HitlButton
                      icon={zoneIncluded ? '🚫' : '✅'}
                      label={zoneIncluded
                        ? 'استثناء من التصدير (TOGGLE_INCLUDE)'
                        : 'إدراج في التصدير (TOGGLE_INCLUDE)'}
                      color={zoneIncluded ? C.red : C.green}
                      onClick={() => dispatch('zone_operation', { zone_op_type: 'TOGGLE_INCLUDE' })}
                      disabled={loading}
                    />
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
              </>
            )}
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
