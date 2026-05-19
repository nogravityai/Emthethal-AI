import React, { useState, useEffect } from 'react';

import PDFProcessor       from './components/PDFProcessor';
import GeometryDebugViewer from './components/GeometryDebugViewer';
import EvidenceWorkbench from './workbench/EvidenceWorkbench';
import './i18n';

const NAV = [
  {
    group: 'CFIS',
    items: [
      { id: 'pdf',      icon: '📑', label: 'معالج PDF',        desc: 'PDF → استخراج هجين → استمارة' },
      { id: 'geodebug', icon: '🔬', label: 'Geometry Debug',   desc: 'Phase 2B · Border · Cells · Overlay' },
      { id: 'workbench',icon: '🧬', label: 'Evidence Workbench',desc: 'Phase 3 · Inspect · Correct · Replay' },
    ],
  },
];

const ALL_VIEWS = NAV.flatMap(g => g.items);

const StatusDot = ({ online }) => (
  <span className={`inline-flex items-center gap-1.5 text-xs font-bold px-2.5 py-1 rounded-full ${
    online ? 'text-emerald-400 bg-emerald-400/10' : 'text-red-400 bg-red-400/10'
  }`}>
    <span className={`w-1.5 h-1.5 rounded-full ${online ? 'bg-emerald-400 pulse-dot' : 'bg-red-400'}`} />
    {online ? 'LIVE' : 'OFFLINE'}
  </span>
);

const App = () => {
  const [view, setView] = useState('pdf');
  const [online, setOnline] = useState(navigator.onLine);

  useEffect(() => {
    const on  = () => setOnline(true);
    const off = () => setOnline(false);
    window.addEventListener('online',  on);
    window.addEventListener('offline', off);
    return () => { window.removeEventListener('online', on); window.removeEventListener('offline', off); };
  }, []);

  const current = ALL_VIEWS.find(v => v.id === view) || ALL_VIEWS[0];

  return (
    <div className="flex" style={{ minHeight: '100vh', background: 'var(--bg-primary)' }}>

      {/* ── Sidebar ─────────────────────────────────────────────────── */}
      <aside className="w-60 shrink-0 flex flex-col" style={{
        background: 'var(--bg-secondary)',
        borderRight: '1px solid var(--border)',
        position: 'sticky', top: 0, height: '100vh', overflowY: 'auto'
      }}>
        {/* Logo */}
        <div className="p-5" style={{ borderBottom: '1px solid var(--border)' }}>
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl flex items-center justify-center text-lg"
              style={{ background: 'linear-gradient(135deg, #0ea5e9, #6366f1)', boxShadow: '0 0 20px rgba(14,165,233,0.3)' }}>
              🛡️
            </div>
            <div>
              <div className="font-black text-base leading-tight gradient-text">Emthethal</div>
              <div className="text-[10px] font-bold uppercase tracking-widest" style={{ color: 'var(--text-muted)' }}>
                AI Compliance OS
              </div>
            </div>
          </div>
        </div>

        {/* Nav groups */}
        <nav className="p-3 flex-1 space-y-4">
          {NAV.map(group => (
            <div key={group.group}>
              <p className="text-[10px] font-bold uppercase tracking-widest px-2 mb-1"
                style={{ color: 'var(--text-muted)' }}>
                {group.group}
              </p>
              {group.items.map(v => (
                <button
                  key={v.id}
                  id={`nav-${v.id}`}
                  onClick={() => setView(v.id)}
                  className={`nav-item w-full mb-0.5 ${view === v.id ? 'active' : ''}`}
                >
                  <span className="text-base">{v.icon}</span>
                  <div className="text-left">
                    <div className="text-sm font-semibold leading-tight">{v.label}</div>
                    <div className="text-[10px] leading-tight" style={{ color: 'var(--text-muted)' }}>{v.desc}</div>
                  </div>
                </button>
              ))}
            </div>
          ))}
        </nav>

        {/* Footer */}
        <div className="p-4" style={{ borderTop: '1px solid var(--border)' }}>
          <StatusDot online={online} />
          <div className="mt-2 space-y-0.5">
            <p className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
              Backend · <span style={{ color: 'var(--success)' }}>Operational</span>
            </p>
            <p className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
              RAG · <span style={{ color: 'var(--accent)' }}>Llama-3 8B</span>
            </p>
            <p className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
              Queue · <span style={{ color: 'var(--accent-2)' }}>Redis+RQ</span>
            </p>
          </div>
          <p className="text-[10px] mt-2" style={{ color: 'var(--text-muted)' }}>© 2026 امتثال AI</p>
        </div>
      </aside>

      {/* ── Main content ─────────────────────────────────────────────── */}
      <main className="flex-1 overflow-auto">
        {/* Top bar */}
        <header className="sticky top-0 z-10 px-8 py-4 flex items-center justify-between"
          style={{ background: 'var(--bg-primary)', borderBottom: '1px solid var(--border)' }}>
          <div>
            <h1 className="font-bold text-lg">{current.label}</h1>
            <p className="text-xs" style={{ color: 'var(--text-muted)' }}>{current.desc}</p>
          </div>
          <div className="flex items-center gap-3">
            <div className="text-xs px-3 py-1.5 rounded-lg font-mono"
              style={{ background: 'var(--bg-secondary)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>
              pgvector · nomic-embed-text · rq
            </div>
            <StatusDot online={online} />
          </div>
        </header>

        {/* View router */}
        <div className={view === 'workbench' ? '' : 'p-8'} style={view === 'workbench' ? {height: 'calc(100vh - 73px)'} : {}}>
          {view === 'pdf'        && <PDFProcessor />}
          {view === 'geodebug'   && <GeometryDebugViewer />}
          {view === 'workbench'  && <EvidenceWorkbench />}
        </div>
      </main>
    </div>
  );
};

export default App;
