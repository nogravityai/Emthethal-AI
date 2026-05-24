/**
 * Left Panel — Stages, Engines, Artifacts, and Replay Timeline
 * 
 * Maps exactly to Phase 3/4 pipeline orchestration details.
 */
import React, { useState } from 'react';
import { motion } from 'framer-motion';
import { useWorkbenchStore, PIPELINE_STAGES, LAYER_META } from '../store/workbenchStore.js';
import { pipelineService } from '../services/pipelineService.js';

const C = {
  bg: '#05080F', panel: '#0B1120', border: '#1A2438',
  blue: '#3B82F6', green: '#10B981', red: '#EF4444',
  yellow: '#F59E0B', purple: '#A78BFA', pink: '#EC4899',
  orange: '#F97316', text: '#E2E8F0', muted: '#64748B', accent: '#0EA5E9',
};

const STAGE_COLORS = {
  'raw_ocr_input':     C.muted,
  'raw_cv2_data':      C.muted,
  'ocr_adapter':       C.green,
  'geometry':          C.blue,
  'evidence_patching': C.purple,
  'alignment':         C.pink,
  'alignment_fusion':  C.yellow,
};

// Pipeline engines metadata
const PIPELINE_ENGINES = [
  {
    name: 'OCRAdapterEngine',
    desc: 'Ingests raw OCR and outputs normalized token evidence (OCRTokenEvidence).',
    inputs: ['raw_ocr_dicts'],
    outputs: ['ocr_evidence']
  },
  {
    name: 'GeometryAdapterEngine',
    desc: 'Maps raw CV2 boxes/lines into DetectedBoxEvidence and DetectedLineEvidence.',
    inputs: ['raw_cv2_dicts'],
    outputs: ['geometry_evidence']
  },
  {
    name: 'CoordinateSpaceDetectorEngine',
    desc: 'Detects scale, page boundaries, and DPI scaling adjustments.',
    inputs: ['raw_ocr_dicts', 'raw_cv2_dicts'],
    outputs: ['coordinate_space_evidence']
  },
  {
    name: 'PrimitiveShapeEngine',
    desc: 'Extracts shape contours, centroids, and invariant Hu moments descriptor.',
    inputs: ['geometry_evidence'],
    outputs: ['shape_evidence']
  },
  {
    name: 'TopologyStage',
    desc: 'Extracts hierarchical tables, layout trees, and linked checkboxes.',
    inputs: ['geometry_evidence', 'ocr_evidence'],
    outputs: ['topology_evidence']
  },
  {
    name: 'AlignmentStage',
    desc: 'Matches text tokens to geometry regions using spatial intersection score.',
    inputs: ['ocr_evidence', 'geometry_evidence'],
    outputs: ['alignment_evidence']
  },
  {
    name: 'FusionStage',
    desc: 'Applies evidence fusion with confidence scoring and conflict resolution.',
    inputs: ['alignment_evidence', 'topology_evidence'],
    outputs: ['resolved_fields']
  }
];

function ArtifactBadge({ artifactId }) {
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

export default function LeftPanel() {
  const {
    timeline, runs, runId, determinismOk, artifacts, hitlLedger, snapshots,
    layers, toggleLayer, setLayerVisible,
    layerOpacities, setLayerOpacity,
    layerRenderModes, setLayerRenderMode,
    irLevel, setIrLevel,
    compareRunId, setCompareMode, setCompareSnapshots, setLoading,
  } = useWorkbenchStore();
  const [tab, setTab] = useState('stages'); // 'stages' | 'layers' | 'timeline' | 'artifacts'

  const timelineStages = timeline?.stages ?? [];
  const allStages = PIPELINE_STAGES.map(ps => {
    const backendStage = timelineStages.find(s => s.stage_name === ps.name || s.output_type === ps.type);
    return { ...ps, artifact_id: backendStage?.artifact_id, produced: !!backendStage };
  });

  const handleIsolateLayer = (targetKey) => {
    Object.keys(layers).forEach(k => {
      setLayerVisible(k, k === targetKey);
    });
  };

  const LAYER_GROUPS = [
    {
      name: '🧱 Structural Layers',
      desc: 'Lattices, grids, and boundaries',
      items: [
        { key: 'geometry', label: 'Geometry Regions', color: '#3B82F6' },
        { key: 'topology', label: 'Table Topology', color: '#FBBF24' },
        { key: 'coordinate_space', label: 'Coordinate Spaces', color: '#06B6D4' },
      ]
    },
    {
      name: '🧠 Semantic Layers',
      desc: 'Text tokens and resolved values',
      items: [
        { key: 'ocr', label: 'OCR Tokens', color: '#10B981' },
        { key: 'alignment', label: 'Alignment Edges', color: '#EC4899' },
        { key: 'fusion', label: 'Resolved Fields', color: '#8B5CF6' },
      ]
    },
    {
      name: '⚠️ Attention Layers',
      desc: 'Mathematical contours and conflicts',
      items: [
        { key: 'shapes', label: 'Primitive Contours', color: '#F59E0B' },
        { key: 'conflict', label: 'Conflict Edges', color: '#EF4444' },
        { key: 'orphan', label: 'Orphan Tokens', color: '#F97316' },
        { key: 'hitl', label: 'HITL Operations', color: '#A78BFA' },
      ]
    },
    {
      name: '⚙️ Workspace Controls',
      desc: 'Minimap & cursor metrics options',
      items: [
        { key: 'minimap', label: 'Viewport Minimap', color: '#10B981' },
        { key: 'coord_tooltip', label: 'Cursor Coordinates', color: '#0EA5E9' },
      ]
    }
  ];

  return (
    <aside style={{
      width: 280, minWidth: 280,
      background: C.panel,
      borderRight: `1px solid ${C.border}`,
      display: 'flex', flexDirection: 'column',
      overflow: 'hidden',
      flexShrink: 0,
    }}>
      {/* Tab bar */}
      <div style={{ display: 'flex', borderBottom: `1px solid ${C.border}`, flexShrink: 0, flexWrap: 'wrap' }}>
        {[
          { key: 'stages',    label: '📋 Stages' },
          { key: 'layers',    label: '🌳 Layers' },
          { key: 'timeline',  label: '⏱ Replays' },
          { key: 'artifacts', label: '📦 Artifacts' },
        ].map(t => (
          <button
            key={t.key}
            id={`left-tab-${t.key}`}
            onClick={() => setTab(t.key)}
            style={{
              flex: 1, padding: '10px 2px', fontSize: 9, fontWeight: 600,
              background: 'transparent', border: 'none',
              borderBottom: `2px solid ${tab === t.key ? C.blue : 'transparent'}`,
              color: tab === t.key ? C.text : C.muted,
              cursor: 'pointer', transition: 'all 0.15s',
              minWidth: '60px',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div style={{ flex: 1, overflowY: 'auto', padding: '14px 14px' }}>
        {/* ── STAGES TAB ────────────────────────────────────────────── */}
        {tab === 'stages' && (
          <div>
            <div style={{ fontSize: 9, color: C.muted, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 12, fontWeight: 700 }}>
              Pipeline Stages
            </div>
            {allStages.map((stage, i) => {
              const color = STAGE_COLORS[stage.name] ?? C.muted;
              return (
                <div
                  key={stage.name}
                  style={{
                    background: C.bg, borderRadius: 6, padding: '8px 10px',
                    border: `1px solid ${stage.produced ? C.border : 'rgba(26,36,56,0.4)'}`,
                    marginBottom: 10, opacity: stage.produced ? 1 : 0.5,
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                    <span style={{ fontSize: 11, fontWeight: 600, color: C.text }}>
                      {stage.label}
                    </span>
                    <span style={{
                      fontSize: 8, padding: '1px 5px', borderRadius: 3,
                      background: stage.produced ? `${color}20` : 'transparent',
                      border: `1px solid ${stage.produced ? color + '40' : C.border}`,
                      color: stage.produced ? color : C.muted
                    }}>
                      {stage.produced ? 'Active' : 'Pending'}
                    </span>
                  </div>
                  <div style={{ fontSize: 8, color: C.muted, fontFamily: 'monospace' }}>
                    Output: {stage.type}
                  </div>
                  {stage.artifact_id && (
                    <div style={{ marginTop: 6 }}>
                      <ArtifactBadge artifactId={stage.artifact_id} />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {/* ── LAYERS TAB ────────────────────────────────────────────── */}
        {tab === 'layers' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            {/* 1. IR Compiler Level Stepper */}
            <div>
              <div style={{ fontSize: 9, color: C.muted, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8, fontWeight: 700 }}>
                Visual Compiler IR Levels
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, background: C.bg, padding: 8, borderRadius: 8, border: `1px solid ${C.border}` }}>
                {[
                  { key: 'raw_geometry', label: '1. Raw Geometry IR', desc: 'Contours & lines (no context)' },
                  { key: 'structural', label: '2. Structural IR', desc: 'Grid lattice & suppression context' },
                  { key: 'coordinate', label: '3. Coordinate IR', desc: 'DPI normalized & calibrated scales' },
                  { key: 'cognitive', label: '4. Cognitive IR', desc: 'Salient evidence filters (no noise)' },
                  { key: 'reasoning', label: '5. Semantic IR', desc: 'Unified resolved medical entities' },
                ].map(lvl => {
                  const isActive = irLevel === lvl.key;
                  return (
                    <button
                      key={lvl.key}
                      onClick={() => setIrLevel(lvl.key)}
                      style={{
                        textAlign: 'left',
                        padding: '6px 10px',
                        borderRadius: 6,
                        border: `1px solid ${isActive ? C.accent : 'transparent'}`,
                        background: isActive ? `${C.accent}15` : 'transparent',
                        cursor: 'pointer',
                        transition: 'all 0.15s',
                        width: '100%',
                      }}
                    >
                      <div style={{ fontSize: 10, fontWeight: 700, color: isActive ? C.accent : C.text }}>
                        {lvl.label}
                      </div>
                      <div style={{ fontSize: 8, color: C.muted, marginTop: 2 }}>
                        {lvl.desc}
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>

            {/* 2. Hierarchical Layer Tree */}
            <div>
              <div style={{ fontSize: 9, color: C.muted, textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 8, fontWeight: 700 }}>
                Spatial Representation Layers
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {LAYER_GROUPS.map((group) => (
                  <div key={group.name} style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '2px 4px' }}>
                      <span style={{ fontSize: 9, fontWeight: 700, color: C.text }}>{group.name}</span>
                      <span style={{ fontSize: 8, color: C.muted }}>{group.desc}</span>
                    </div>

                    <div style={{ display: 'flex', flexDirection: 'column', gap: 3, borderLeft: `1px solid ${C.border}`, marginLeft: 4, paddingLeft: 4 }}>
                      {group.items.map((item) => {
                        const visible = !!layers[item.key];
                        const opacity = layerOpacities[item.key] ?? 1.0;
                        return (
                          <div key={item.key} style={{
                            display: 'flex', flexDirection: 'column', gap: 4,
                            padding: '6px 8px', borderRadius: 6, background: C.bg,
                            border: `1px solid ${visible ? C.border : 'rgba(26,36,56,0.3)'}`,
                          }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                              <div style={{ width: 6, height: 6, borderRadius: '50%', background: item.color }} />
                              <span style={{ fontSize: 9, fontWeight: 500, color: visible ? C.text : C.muted, flex: 1, textOverflow: 'ellipsis', overflow: 'hidden', whiteSpace: 'nowrap' }}>
                                {item.label}
                              </span>

                              {/* Visibility */}
                              <button
                                onClick={() => toggleLayer(item.key)}
                                style={{
                                  background: 'transparent', border: 'none', color: visible ? item.color : C.muted,
                                  cursor: 'pointer', fontSize: 10, padding: '2px 4px',
                                }}
                                title={visible ? "Hide Layer" : "Show Layer"}
                              >
                                {visible ? '👁️' : '🙈'}
                              </button>

                              {/* Isolate */}
                              <button
                                onClick={() => handleIsolateLayer(item.key)}
                                style={{
                                  background: 'transparent', border: `1px solid ${C.border}`, borderRadius: 3,
                                  color: C.muted, cursor: 'pointer', fontSize: 7, padding: '1px 3px',
                                  fontWeight: 700,
                                }}
                                title="Isolate Layer"
                              >
                                ISO
                              </button>
                            </div>

                            {visible && (
                              <div style={{ display: 'flex', alignItems: 'center', gap: 6, paddingLeft: 12 }}>
                                <span style={{ fontSize: 7, color: C.muted }}>Opacity</span>
                                <input
                                  type="range"
                                  min="0.1"
                                  max="1"
                                  step="0.05"
                                  value={opacity}
                                  onChange={(e) => setLayerOpacity(item.key, parseFloat(e.target.value))}
                                  style={{ flex: 1, accentColor: item.color, height: 2, cursor: 'pointer' }}
                                />
                                <span style={{ fontSize: 7, color: C.text, fontFamily: 'monospace' }}>
                                  {Math.round(opacity * 100)}%
                                </span>
                              </div>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* 3. Adaptive Suppression Visualizer Info */}
            <div style={{ background: 'rgba(245, 158, 11, 0.05)', border: '1px dashed rgba(245, 158, 11, 0.25)', borderRadius: 8, padding: 10 }}>
              <div style={{ fontSize: 9, fontWeight: 700, color: '#FBBF24', marginBottom: 4 }}>
                🛡 Perceptual Suppression Visualizer
              </div>
              <div style={{ fontSize: 8, color: C.muted, lineHeight: 1.4 }}>
                Periodic structural filters running at <strong>98% lattice confidence</strong>. Noise objects matching pre-printed templates are auto-suppressed.
              </div>
            </div>
          </div>
        )}

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
                </div>
              </div>
            )}

            {/* Run history list */}
            <div>
              <div style={{ fontSize: 9, color: C.muted, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 10, fontWeight: 700 }}>
                Run Execution History
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
                    <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', alignItems: 'center' }}>
                      <span style={{ fontSize: 8, padding: '2px 6px', borderRadius: 3, background: `${run.determinism_ok ? C.green : C.red}15`, color: run.determinism_ok ? C.green : C.red, border: `1px solid ${run.determinism_ok ? C.green : C.red}30` }}>
                        {run.determinism_ok ? '✓ Det.' : '⚠ Drift'}
                      </span>
                      {run.is_hitl_rerun && (
                        <span style={{ fontSize: 8, padding: '2px 6px', borderRadius: 3, background: `${C.purple}15`, color: C.purple, border: `1px solid ${C.purple}30` }}>
                          HITL Rerun
                        </span>
                      )}
                      {run.run_id !== runId && (
                        <button
                          onClick={async () => {
                            if (compareRunId === run.run_id) {
                              setCompareMode(false);
                            } else {
                              setLoading(true, 'Fetching comparison run...');
                              try {
                                const snaps = await pipelineService.getAllSnapshots(run.run_id);
                                setCompareSnapshots({ run_id: run.run_id, snapshots: snaps });
                                setCompareMode(true);
                              } catch (e) {
                                console.error('Failed to load comparison snapshots', e);
                              } finally {
                                setLoading(false);
                              }
                            }
                          }}
                          style={{
                            fontSize: 8, padding: '2px 6px', borderRadius: 3,
                            background: compareRunId === run.run_id ? C.accent : 'transparent',
                            border: `1px solid ${C.accent}`,
                            color: compareRunId === run.run_id ? '#000000' : C.accent,
                            cursor: 'pointer',
                            fontWeight: 700,
                            marginLeft: 'auto',
                          }}
                        >
                          {compareRunId === run.run_id ? 'Comparing ✓' : 'Compare'}
                        </button>
                      )}
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        )}

        {/* ── ARTIFACTS TAB ─────────────────────────────────────────── */}
        {tab === 'artifacts' && (
          <div>
            <div style={{ fontSize: 9, color: C.muted, textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 12, fontWeight: 700 }}>
              Artifact References
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
                  <ArtifactBadge artifactId={id} />
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
