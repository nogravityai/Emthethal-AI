import React from 'react';
import { motion } from 'framer-motion';
import { useWorkbenchStore, LAYER_META } from '../store/workbenchStore.js';

const C = {
  bg: '#05080F', panel: '#0B1120', border: '#1A2438',
  blue: '#3B82F6', green: '#10B981', red: '#EF4444',
  yellow: '#F59E0B', purple: '#A78BFA', text: '#E2E8F0',
  muted: '#64748B', accent: '#0EA5E9',
};

function IconBtn({ icon, label, onClick, active, color, disabled, id }) {
  return (
    <button
      id={id}
      onClick={onClick}
      disabled={disabled}
      title={label}
      aria-label={label}
      style={{
        display: 'flex', alignItems: 'center', gap: 6,
        padding: '6px 12px', borderRadius: 7,
        border: `1px solid ${active ? (color ?? C.blue) + '60' : C.border}`,
        background: active ? (color ?? C.blue) + '15' : 'transparent',
        color: active ? (color ?? C.blue) : C.muted,
        fontSize: 11, fontWeight: 600, cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.4 : 1,
        transition: 'all 0.15s',
        whiteSpace: 'nowrap',
      }}
      onMouseEnter={e => { if (!disabled) e.currentTarget.style.borderColor = (color ?? C.blue) + '80'; }}
      onMouseLeave={e => { if (!disabled) e.currentTarget.style.borderColor = active ? (color ?? C.blue) + '60' : C.border; }}
    >
      <span>{icon}</span>
      <span>{label}</span>
    </button>
  );
}

function StatusPill({ label, value, color }) {
  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center',
      padding: '4px 10px', borderRadius: 6,
      border: `1px solid ${C.border}`, background: C.panel,
    }}>
      <span style={{ fontSize: 8, color: C.muted, textTransform: 'uppercase', letterSpacing: '0.08em' }}>{label}</span>
      <span style={{ fontSize: 10, fontFamily: 'monospace', color: color ?? C.text, fontWeight: 700 }}>{value}</span>
    </div>
  );
}

export default function TopBar({ onRunDemo, onUploadClick }) {
  const {
    runId, loading, pipelineVersion, determinismOk,
    layers, toggleLayer,
    compareMode, setCompareMode,
    zoom, adjustZoom, resetView,
    status, snapshots,
  } = useWorkbenchStore();

  const tokenCount  = snapshots.ocr?.tokens?.length ?? 0;
  const regionCount = snapshots.geometry?.regions?.length ?? 0;
  const fieldCount  = snapshots.fusion?.fields?.length ?? 0;

  return (
    <header
      style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '0 16px',
        height: 52,
        background: C.panel,
        borderBottom: `1px solid ${C.border}`,
        flexShrink: 0,
        overflowX: 'auto',
      }}
    >
      {/* Logo */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginRight: 8, flexShrink: 0 }}>
        <div style={{
          width: 28, height: 28, borderRadius: 7,
          background: 'linear-gradient(135deg, #0EA5E9, #6366F1)',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          fontSize: 14, flexShrink: 0,
          boxShadow: '0 0 12px rgba(14,165,233,0.3)',
        }}>🧬</div>
        <div>
          <div style={{ fontSize: 11, fontWeight: 800, color: C.text, whiteSpace: 'nowrap' }}>
            Evidence Workbench
          </div>
          <div style={{ fontSize: 8, color: C.accent, letterSpacing: '0.1em', textTransform: 'uppercase' }}>
            CFIS · Phase 3 · v{pipelineVersion}
          </div>
        </div>
      </div>

      <div style={{ width: 1, height: 28, background: C.border, flexShrink: 0 }} />

      {/* Document actions */}
      <IconBtn id="wb-upload" icon="📄" label="Upload PDF" onClick={onUploadClick} disabled={loading} />
      <IconBtn id="wb-demo"   icon="▶" label="Demo Fixture" onClick={onRunDemo} disabled={loading} color={C.green} />

      <div style={{ width: 1, height: 28, background: C.border, flexShrink: 0 }} />

      {/* Layer toggles */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0 }}>
        <span style={{ fontSize: 9, color: C.muted, textTransform: 'uppercase', letterSpacing: '0.08em', marginRight: 4 }}>Layers</span>
        {Object.entries(LAYER_META).map(([key, meta]) => (
          <button
            key={key}
            id={`layer-toggle-${key}`}
            onClick={() => toggleLayer(key)}
            title={`${meta.label} (${meta.shortcut})`}
            aria-label={`Toggle ${meta.label} layer`}
            aria-pressed={layers[key]}
            style={{
              padding: '3px 8px', borderRadius: 5,
              border: `1px solid ${layers[key] ? meta.color + '60' : C.border}`,
              background: layers[key] ? meta.color + '18' : 'transparent',
              color: layers[key] ? meta.color : C.muted,
              fontSize: 9, fontWeight: 700, cursor: 'pointer',
              letterSpacing: '0.04em', whiteSpace: 'nowrap',
              transition: 'all 0.15s',
            }}
          >
            {meta.label.split(' ')[0]}
          </button>
        ))}
      </div>

      <div style={{ width: 1, height: 28, background: C.border, flexShrink: 0 }} />

      {/* Zoom */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 4, flexShrink: 0 }}>
        <button
          onClick={() => adjustZoom(-0.15)}
          aria-label="Zoom out"
          style={{ padding: '4px 8px', borderRadius: 5, border: `1px solid ${C.border}`, background: 'transparent', color: C.muted, cursor: 'pointer', fontSize: 13, lineHeight: 1 }}
        >−</button>
        <button
          onClick={resetView}
          aria-label="Reset zoom"
          style={{ padding: '4px 8px', borderRadius: 5, border: `1px solid ${C.border}`, background: 'transparent', color: C.text, cursor: 'pointer', fontSize: 9, fontFamily: 'monospace', minWidth: 44, textAlign: 'center' }}
        >
          {Math.round(useWorkbenchStore.getState().zoom * 100)}%
        </button>
        <button
          onClick={() => adjustZoom(0.15)}
          aria-label="Zoom in"
          style={{ padding: '4px 8px', borderRadius: 5, border: `1px solid ${C.border}`, background: 'transparent', color: C.muted, cursor: 'pointer', fontSize: 13, lineHeight: 1 }}
        >+</button>
      </div>

      <div style={{ width: 1, height: 28, background: C.border, flexShrink: 0 }} />

      {/* Compare Mode */}
      <IconBtn
        id="wb-compare"
        icon="⚖"
        label="Compare"
        onClick={() => setCompareMode(!compareMode)}
        active={compareMode}
        color={C.purple}
      />

      <div style={{ flex: 1 }} />

      {/* Status pills */}
      {runId && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
          <StatusPill label="Run ID" value={runId.slice(0, 12) + '…'} color={C.accent} />
          <StatusPill label="Tokens" value={tokenCount} color={C.green} />
          <StatusPill label="Regions" value={regionCount} color={C.blue} />
          <StatusPill label="Fields" value={fieldCount} color={C.purple} />
          <div style={{
            display: 'flex', alignItems: 'center', gap: 5,
            padding: '4px 10px', borderRadius: 6,
            border: `1px solid ${determinismOk ? C.green + '40' : C.red + '40'}`,
            background: determinismOk ? C.green + '10' : C.red + '10',
          }}>
            <div style={{
              width: 6, height: 6, borderRadius: '50%',
              background: determinismOk ? C.green : C.red,
              boxShadow: `0 0 6px ${determinismOk ? C.green : C.red}`,
            }} />
            <span style={{ fontSize: 9, fontWeight: 800, color: determinismOk ? C.green : C.red, letterSpacing: '0.1em' }}>
              {determinismOk ? 'DETERMINISTIC' : 'DRIFT DETECTED'}
            </span>
          </div>
        </div>
      )}

      {/* Loading status inline */}
      {loading && status && (
        <div style={{ fontSize: 10, color: C.accent, fontFamily: 'monospace', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {status}
        </div>
      )}
    </header>
  );
}
