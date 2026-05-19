/**
 * Right Panel — Replay Timeline + Provenance
 * 
 * Timeline maps to GET /api/cfis/v3/pipeline/runs/{run_id}/timeline response:
 * { run_id, document_id, stages: [{stage_name, output_type, artifact_id}], human_operations: [] }
 * 
 * Stage sequence from backend orchestration.py:
 * raw_ocr_input → raw_cv2_data → ocr_adapter → geometry → evidence_patching → alignment → alignment_fusion
 */
import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { useWorkbenchStore, PIPELINE_STAGES } from '../store/workbenchStore.js';
import { pipelineService } from '../services/pipelineService.js';

const C = {
  bg: '#05080F', panel: '#0B1120', border: '#1A2438',
  blue: '#3B82F6', green: '#10B981', red: '#EF4444',
  yellow: '#F59E0B', purple: '#A78BFA', pink: '#EC4899',
  orange: '#F97316', text: '#E2E8F0', muted: '#64748B', accent: '#0EA5E9',
};

// Stage color by type
const STAGE_COLORS = {
  'raw_ocr_input':     C.muted,
  'raw_cv2_data':      C.muted,
  'ocr_adapter':       C.green,
  'geometry':          C.blue,
  'evidence_patching': C.purple,
  'alignment':         C.pink,
  'alignment_fusion':  C.yellow,
};

function ArtifactBadge({ artifactId, type }) {
  const [inspecting, setInspecting] = useState(false);
  const [meta, setMeta] = useState(null);

  const inspect = async () => {
    if (!artifactId || inspecting) return;
    setInspecting(true);
    try {
      const data = await pipelineService.inspectArtifact(artifactId);
      setMeta(data);
    } catch (_) {
      setMeta({ error: 'Artifact metadata unavailable' });
    }
    setInspecting(false);
  };

  return (
    <div>
      <div
        onClick={inspect}
        title="Click to inspect artifact metadata"
        style={{
          fontSize: 8, fontFamily: 'monospace',
          color: C.accent, wordBreak: 'break-all',
          background: C.bg, borderRadius: 4,
          padding: '4px 6px', border: `1px solid ${C.border}`,
          cursor: 'pointer', lineHeight: 1.5,
          transition: 'border-color 0.15s',
        }}
        onMouseEnter={e => e.currentTarget.style.borderColor = C.accent + '60'}
        onMouseLeave={e => e.currentTarget.style.borderColor = C.border}
      >
        {inspecting ? '…' : `${artifactId?.slice(0, 24)}…`}
      </div>
      {meta && !meta.error && (
        <div style={{ fontSize: 8, color: C.muted, marginTop: 4, lineHeight: 1.6, fontFamily: 'monospace' }}>
          v{meta.schema_version} · {meta.payload_summary?.count ?? '?'} items
        </div>
      )}
    </div>
  );
}

export default function RightPanel() {
  const { timeline, runs, runId, determinismOk, artifacts, hitlLedger } = useWorkbenchStore();
  const [tab, setTab] = useState('timeline'); // 'timeline' | 'runs' | 'artifacts'

  // Fill in any gaps — show all expected stages even if backend didn't produce them yet
  const timelineStages = timeline?.stages ?? [];
  
  // Merge backend stages with expected stage list for complete display
  const allStages = PIPELINE_STAGES.map(ps => {
    const backendStage = timelineStages.find(s => s.stage_name === ps.name || s.output_type === ps.type);
    return { ...ps, artifact_id: backendStage?.artifact_id, produced: !!backendStage };
  });

  return (
    <aside style={{
      width: 280, minWidth: 280,
      background: C.panel,
      borderLeft: `1px solid ${C.border}`,
      display: 'flex', flexDirection: 'column',
      overflow: 'hidden',
      flexShrink: 0,
    }}>
      {/* Tab bar */}
      <div style={{ display: 'flex', borderBottom: `1px solid ${C.border}`, flexShrink: 0 }}>
        {[
          { key: 'timeline',  label: '⏱ Timeline' },
          { key: 'runs',      label: `🔄 Runs (${runs.length})` },
          { key: 'artifacts', label: '📦 Artifacts' },
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

        {/* ── TIMELINE TAB ──────────────────────────────────────────── */}
        {tab === 'timeline' && (
          <div>
            {/* Run metadata */}
            {runId && (
              <div style={{ background: C.bg, borderRadius: 7, padding: 10, border: `1px solid ${C.border}`, marginBottom: 14 }}>
                <div style={{ fontSize: 9, color: C.muted, marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.08em' }}>Current Run</div>
                <div style={{ fontSize: 9, fontFamily: 'monospace', color: C.accent, wordBreak: 'break-all', marginBottom: 4 }}>
                  {runId}
                </div>
                <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                  <span style={{
                    fontSize: 8, padding: '2px 7px', borderRadius: 4, fontWeight: 700,
                    background: determinismOk ? `${C.green}15` : `${C.red}15`,
                    border: `1px solid ${determinismOk ? C.green + '40' : C.red + '40'}`,
                    color: determinismOk ? C.green : C.red,
                  }}>
                    {determinismOk ? '✓ DETERMINISTIC' : '⚠ DRIFT'}
                  </span>
                  <span style={{ fontSize: 8, padding: '2px 7px', borderRadius: 4, background: `${C.blue}15`, border: `1px solid ${C.blue}40`, color: C.blue }}>
                    v3.0.0
                  </span>
                </div>
              </div>
            )}

            {/* Stage timeline */}
            {timeline ? (
              <div style={{ position: 'relative' }}>
                {/* Vertical spine */}
                <div style={{ position: 'absolute', left: 8, top: 8, bottom: 8, width: 2, background: `${C.border}80` }} />

                {allStages.map((stage, i) => {
                  const color = STAGE_COLORS[stage.name] ?? C.muted;
                  return (
                    <motion.div
                      key={stage.name}
                      initial={{ opacity: 0, x: -10 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: i * 0.04 }}
                      style={{ display: 'flex', alignItems: 'flex-start', gap: 12, marginBottom: 18, paddingLeft: 4 }}
                    >
                      {/* Node */}
                      <div style={{
                        width: 18, height: 18, borderRadius: 9, flexShrink: 0, zIndex: 1,
                        marginTop: 2,
                        background: stage.produced ? C.bg : 'transparent',
                        border: `2px solid ${stage.produced ? color : C.border}`,
                        boxShadow: stage.produced ? `0 0 8px ${color}40` : 'none',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                      }}>
                        {stage.produced && (
                          <div style={{ width: 6, height: 6, borderRadius: '50%', background: color }} />
                        )}
                      </div>

                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{
                          fontSize: 11, fontWeight: 600, color: stage.produced ? C.text : C.muted,
                          marginBottom: 2, textTransform: 'capitalize',
                        }}>
                          {stage.label}
                        </div>
                        <div style={{ fontSize: 8, color: C.muted, fontFamily: 'monospace', marginBottom: 4 }}>
                          {stage.type}
                        </div>
                        {stage.artifact_id && (
                          <ArtifactBadge artifactId={stage.artifact_id} type={stage.type} />
                        )}
                        {/* Highlight evidence_patching if HITL ops exist */}
                        {stage.name === 'evidence_patching' && hitlLedger.length > 0 && (
                          <div style={{ fontSize: 8, color: C.purple, marginTop: 4, fontWeight: 700 }}>
                            ↳ {hitlLedger.length} HITL operations applied
                          </div>
                        )}
                      </div>
                    </motion.div>
                  );
                })}

                {/* Determinism footer */}
                <div style={{
                  display: 'flex', justifyContent: 'space-between',
                  marginTop: 4, padding: '8px 10px',
                  background: C.bg, borderRadius: 6, border: `1px solid ${C.border}`,
                }}>
                  <span style={{ fontSize: 9, color: C.muted }}>Artifact determinism</span>
                  <span style={{ fontSize: 9, fontWeight: 700, color: determinismOk ? C.green : C.red }}>
                    {determinismOk ? '✓ SHA-256 VERIFIED' : '⚠ IDs CHANGED'}
                  </span>
                </div>

                {!determinismOk && (
                  <div style={{ marginTop: 8, fontSize: 9, color: C.red, lineHeight: 1.6, background: `${C.red}10`, border: `1px solid ${C.red}30`, borderRadius: 6, padding: '8px 10px' }}>
                    ⚠ DETERMINISM BREACH: Artifact IDs changed after replay. This should not happen — investigate input changes.
                  </div>
                )}
              </div>
            ) : (
              <div style={{ fontSize: 11, color: C.muted, textAlign: 'center', padding: 28 }}>
                Run the pipeline to see the execution timeline
              </div>
            )}
          </div>
        )}

        {/* ── RUNS HISTORY TAB ──────────────────────────────────────── */}
        {tab === 'runs' && (
          <div>
            <div style={{ fontSize: 9, color: C.muted, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 12, fontWeight: 700 }}>
              Run History
            </div>
            {runs.length === 0 ? (
              <div style={{ fontSize: 11, color: C.muted, textAlign: 'center', padding: 20 }}>No runs yet</div>
            ) : (
              runs.map((run, i) => (
                <div key={run.run_id} style={{
                  background: C.bg, borderRadius: 7, padding: 10, marginBottom: 8,
                  border: `1px solid ${i === 0 ? C.blue + '40' : C.border}`,
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                    <span style={{ fontSize: 9, fontFamily: 'monospace', color: C.accent }}>
                      {run.run_id?.slice(0, 16)}…
                    </span>
                    {i === 0 && <span style={{ fontSize: 8, color: C.blue, fontWeight: 700 }}>CURRENT</span>}
                  </div>
                  <div style={{ fontSize: 8, color: C.muted, marginBottom: 4 }}>
                    {new Intl.DateTimeFormat('en-GB', { timeStyle: 'medium' }).format(new Date(run.timestamp))}
                  </div>
                  <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap' }}>
                    <span style={{ fontSize: 8, padding: '2px 6px', borderRadius: 3, background: `${run.determinism_ok ? C.green : C.red}15`, color: run.determinism_ok ? C.green : C.red, border: `1px solid ${run.determinism_ok ? C.green : C.red}30` }}>
                      {run.determinism_ok ? '✓ Det.' : '⚠ Drift'}
                    </span>
                    {run.is_hitl_rerun && (
                      <span style={{ fontSize: 8, padding: '2px 6px', borderRadius: 3, background: `${C.purple}15`, color: C.purple, border: `1px solid ${C.purple}30` }}>
                        HITL Rerun
                      </span>
                    )}
                    <span style={{ fontSize: 8, padding: '2px 6px', borderRadius: 3, background: `${C.muted}15`, color: C.muted, border: `1px solid ${C.muted}30` }}>
                      {run.stages?.length ?? 0} stages
                    </span>
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {/* ── ARTIFACTS TAB ─────────────────────────────────────────── */}
        {tab === 'artifacts' && (
          <div>
            <div style={{ fontSize: 9, color: C.muted, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 12, fontWeight: 700 }}>
              Artifact References
            </div>
            <div style={{ fontSize: 9, color: C.muted, marginBottom: 12, lineHeight: 1.6 }}>
              These are the <span style={{ color: C.accent }}>stable SHA-256 artifact_ids</span> from the current run. IDs are deterministic — same inputs always produce the same IDs.
            </div>
            {Object.keys(artifacts).length === 0 ? (
              <div style={{ fontSize: 11, color: C.muted, textAlign: 'center', padding: 20 }}>
                Run the pipeline first
              </div>
            ) : (
              Object.entries(artifacts).map(([type, id]) => (
                <div key={type} style={{ marginBottom: 10 }}>
                  <div style={{ fontSize: 9, color: C.purple, fontWeight: 700, marginBottom: 3, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                    {type}
                  </div>
                  <ArtifactBadge artifactId={id} type={type} />
                </div>
              ))
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
