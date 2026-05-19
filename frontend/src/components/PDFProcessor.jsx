import React, { useState, useRef, useCallback, lazy } from 'react';
import QAViewer from './QAViewer';

// Lazy load Form.io builder so it doesn't inflate the main bundle
const FormBuilderComponent = lazy(() => import('./FormBuilderWrapper'));

const API = '/api/cfis/v1';

const WIDGET_LABELS = {
  text:'نص', number:'رقم', date:'تاريخ', datetime:'تاريخ/وقت',
  textarea:'نص طويل', checkbox:'خانة اختيار', radio:'اختيار',
  select:'قائمة', signature:'توقيع', file:'ملف', unknown:'نص',
};

// Build Form.io JSON client-side from doc.fields
function buildFormioSchema(doc) {
  if (!doc?.fields?.length) return null;
  const isRTL = ['ar','ar_en'].includes(doc.primary_language);

  const makeComp = f => {
    const base = {
      type: f.runtime_widget === 'number' ? 'number'
          : f.runtime_widget === 'date' ? 'datetime'
          : f.runtime_widget === 'checkbox' ? 'checkbox'
          : f.runtime_widget === 'textarea' ? 'textarea'
          : f.runtime_widget === 'select' ? 'select'
          : 'textfield',
      key: `f_${f.field_id.replace(/-/g,'').slice(0,16)}`,
      label: f.semantic_label || '',
      rtl: isRTL,
      validate: { required: false },
      properties: {
        confidence: f.confidence,
        source: f.source,
        widget: f.runtime_widget,
        page: f.page_number,
      },
    };
    if (f.runtime_widget === 'select' && (f.options_ar || f.options || []).length) {
      base.values = (f.options_ar || f.options).map((o,i) => ({ label:o, value:`opt_${i}` }));
    }
    return base;
  };

  const buildComponentsForFields = (fields) => {
    const byRow = {};
    fields.forEach(f => {
      if (!byRow[f.row_index]) byRow[f.row_index] = [];
      byRow[f.row_index].push(f);
    });

    const comps = [];
    Object.entries(byRow)
      .sort(([a],[b]) => Number(a) - Number(b))
      .forEach(([, rowFields]) => {
        // Since backend already maps logical order to column_index (0 is rightmost in RTL),
        // we ALWAYS sort ascending to match browser's native DOM rendering flow.
        const sorted = [...rowFields].sort((a,b) => a.column_index - b.column_index);

        const makeComp = f => {
          const text = f.semantic_label || '';
          
          // Heuristic: If it's the only item in a row, has no colon, and isn't a special widget,
          // it's highly likely a Section Header or Title, not an input field!
          const isStaticText = rowFields.length === 1 && !text.includes(':') && f.runtime_widget === 'text';

          if (isStaticText) {
            return {
              type: 'htmlelement',
              tag: 'h4',
              key: `f_${f.field_id.replace(/-/g,'').slice(0,16)}`,
              content: text,
              className: 'text-center my-3 font-bold',
              properties: { widget: 'title', source: f.source }
            };
          }

          const base = {
            type: f.runtime_widget === 'number' ? 'number'
                : f.runtime_widget === 'date' ? 'datetime'
                : f.runtime_widget === 'checkbox' ? 'checkbox'
                : f.runtime_widget === 'textarea' ? 'textarea'
                : f.runtime_widget === 'select' ? 'select'
                : 'textfield',
            key: `f_${f.field_id.replace(/-/g,'').slice(0,16)}`,
            label: text,
            rtl: isRTL,
            validate: { required: false },
            properties: {
              confidence: f.confidence,
              source: f.source,
              widget: f.runtime_widget,
              page: f.page_number,
            },
          };
          if (f.runtime_widget === 'select' && (f.options_ar || f.options || []).length) {
            base.values = (f.options_ar || f.options).map((o,i) => ({ label:o, value:`opt_${i}` }));
          }
          return base;
        };

        if (sorted.length === 1) {
          comps.push(makeComp(sorted[0]));
        } else {
          comps.push({
            type: 'columns',
            key: `row_${rowFields[0].page_number}_${rowFields[0].row_index}`,
            label: '',
            columns: sorted.map((f,i) => ({
              components: [makeComp(f)],
              width: Math.floor(12 / sorted.length) + (i===0 ? 12 % sorted.length : 0),
              offset:0, push:0, pull:0, size:'md',
            })),
          });
        }
      });
    return comps;
  };

  const isWizard = doc.total_pages > 1;
  const components = [];

  if (isWizard) {
    for (let p = 0; p < doc.total_pages; p++) {
      const pageFields = doc.fields.filter(f => f.page_number === p);
      if (pageFields.length > 0) {
        components.push({
          title: `صفحة ${p + 1}`,
          type: 'panel',
          key: `page${p + 1}`,
          components: buildComponentsForFields(pageFields),
        });
      }
    }
  } else {
    components.push(...buildComponentsForFields(doc.fields));
  }

  return {
    type: 'form',
    display: isWizard ? 'wizard' : 'form',
    settings: { rtl: isRTL },
    components,
    metadata: {
      document_id: doc.document_id,
      source_file: doc.source_file,
      primary_language: doc.primary_language,
      extraction_mode: doc.fingerprint?.extraction_mode,
      total_fields: doc.fields.length,
      generated_client_side: true,
    },
  };
}

// ── Inline Form renderer (no @formio/react dependency) ────────────────────────
const InlineField = ({ comp }) => {
  const [val, setVal] = useState('');
  const dir = comp.rtl ? 'rtl' : 'ltr';
  const src = comp.properties?.source === 'native' ? '📄' : '🔍';
  const pct = Math.round((comp.properties?.confidence||0)*100);
  const confColor = pct>=85 ? '#10b981' : pct>=65 ? '#f59e0b' : '#ef4444';
  const widget = comp.properties?.widget || 'text';

  const inp = (
    comp.type === 'checkbox'
      ? <label style={{display:'flex',alignItems:'center',gap:8,cursor:'pointer'}}>
          <input type="checkbox" checked={!!val} onChange={e=>setVal(e.target.checked)}
            style={{width:18,height:18,accentColor:'#6366f1'}}/>
          <span style={{fontSize:14,color:'#cbd5e1',direction:dir}}>{comp.label}</span>
        </label>
      : comp.type === 'textarea'
      ? <textarea value={val} onChange={e=>setVal(e.target.value)} dir={dir} rows={2}
          placeholder={comp.label} style={inp_s}/>
      : comp.type === 'select' && comp.values?.length
      ? <select value={val} onChange={e=>setVal(e.target.value)} dir={dir} style={inp_s}>
          <option value="">— اختر —</option>
          {comp.values.map(o=><option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      : <input type={comp.type==='number'?'number':comp.type==='datetime'?'datetime-local':'text'}
          value={val} onChange={e=>setVal(e.target.value)} dir={dir}
          placeholder={comp.label} style={inp_s}/>
  );

  if (comp.type === 'htmlelement') {
    return (
      <div style={{...card_s, background: 'transparent', border: 'none', textAlign: 'center', margin: '16px 0'}}>
        <span style={{fontSize: 16, fontWeight: 800, color: '#e2e8f0', fontFamily: "'Cairo',sans-serif"}}>{comp.content}</span>
      </div>
    );
  }

  if (comp.type === 'checkbox') return <div style={card_s}>{inp}</div>;

  return (
    <div style={card_s}>
      <div style={{display:'flex',alignItems:'center',gap:6,marginBottom:6,direction:'rtl'}}>
        <span style={{flex:1,fontSize:13,fontWeight:600,color:'#94a3b8',textAlign:'right',fontFamily:"'Cairo',sans-serif"}}>
          {comp.label}
        </span>
        <span style={{fontSize:10,color:confColor,fontWeight:700}}>{src} {pct}%</span>
        <span style={{fontSize:10,background:'rgba(99,102,241,0.15)',color:'#a5b4fc',padding:'2px 7px',borderRadius:12,border:'1px solid rgba(99,102,241,0.3)'}}>
          {WIDGET_LABELS[widget]||widget}
        </span>
      </div>
      {inp}
    </div>
  );
};

const inp_s = {
  width:'100%', background:'#0f172a', border:'1px solid #334155',
  borderRadius:6, padding:'7px 10px', color:'#e2e8f0',
  fontSize:13, outline:'none', boxSizing:'border-box',
  fontFamily:"'Cairo','Arial',sans-serif",
};
const card_s = {
  background:'#1e293b', border:'1px solid #334155',
  borderRadius:10, padding:'10px 12px', marginBottom:6,
};

const InlineFormRenderer = ({ schema }) => {
  if (!schema) return (
    <div style={{textAlign:'center',padding:48,color:'#64748b'}}>⏳ جاري بناء الاستمارة...</div>
  );
  const [submitted, setSubmitted] = useState(false);
  const comps = schema.components || [];

  if (submitted) return (
    <div style={{textAlign:'center',padding:60}}>
      <div style={{fontSize:48,marginBottom:12}}>✅</div>
      <div style={{fontSize:18,fontWeight:700,color:'#10b981',marginBottom:8}}>تم الإرسال</div>
      <button onClick={()=>setSubmitted(false)}
        style={{marginTop:16,padding:'10px 24px',borderRadius:8,background:'#6366f1',color:'#fff',border:'none',cursor:'pointer',fontSize:14}}>
        تعبئة مجدداً
      </button>
    </div>
  );

  return (
    <div dir={schema.settings?.rtl ? 'rtl' : 'ltr'}
      style={{background:'#0f172a',borderRadius:12,padding:24,border:'1px solid #334155'}}>
      {comps.map((c,i) =>
        c.type === 'columns'
          ? <div key={c.key||i} style={{display:'grid',gridTemplateColumns:`repeat(${c.columns.length},1fr)`,gap:8,marginBottom:4}}>
              {c.columns.map((col,j) => col.components.map(cc=>
                <InlineField key={cc.key||j} comp={cc}/>
              ))}
            </div>
          : <InlineField key={c.key||i} comp={c}/>
      )}
      <button onClick={()=>setSubmitted(true)}
        style={{marginTop:16,width:'100%',padding:'12px',borderRadius:8,
          background:'linear-gradient(135deg,#0ea5e9,#6366f1)',
          color:'#fff',border:'none',cursor:'pointer',fontSize:15,fontWeight:700,
          fontFamily:"'Cairo',sans-serif"}}>
        إرسال الاستمارة
      </button>
    </div>
  );
};

// ── Raw fields view ───────────────────────────────────────────────────────────
const RawFieldsView = ({ doc, activePage, setActivePage, pageImages, formValues, onChange }) => {
  const totalPages = doc?.total_pages || 0;
  const pageFields = (doc?.fields||[]).filter(f => f.page_number === activePage);
  const rows = {};
  pageFields.forEach(f => { rows[f.row_index] = rows[f.row_index]||[]; rows[f.row_index].push(f); });
  Object.values(rows).forEach(r => r.sort((a,b)=>a.column_index-b.column_index));
  const rowList = Object.entries(rows).sort(([a],[b])=>Number(a)-Number(b));

  return (
    <div>
      {totalPages > 1 && (
        <div style={{display:'flex',gap:6,marginBottom:16,overflowX:'auto',direction:'rtl'}}>
          {Array.from({length:totalPages},(_,i)=>{
            const cnt = doc.fields.filter(f=>f.page_number===i).length;
            const qa = doc.fields.filter(f=>f.page_number===i&&f.needs_qa).length;
            return (
              <button key={i} onClick={()=>setActivePage(i)} style={{
                padding:'7px 14px',borderRadius:8,cursor:'pointer',whiteSpace:'nowrap',fontSize:13,
                border:`1px solid ${activePage===i?'#0ea5e9':'#334155'}`,
                background:activePage===i?'rgba(14,165,233,0.1)':'#1e293b',
                color:activePage===i?'#38bdf8':'#64748b',fontWeight:activePage===i?700:400,
              }}>صفحة {i+1} <span style={{opacity:.6,fontSize:10}}>{cnt}</span>
                {qa>0&&<span style={{color:'#ef4444',fontSize:10}}> ⚠{qa}</span>}
              </button>
            );
          })}
        </div>
      )}
      <div style={{display:'flex',gap:20,alignItems:'flex-start'}}>
        {pageImages[activePage] && (
          <div style={{width:240,flexShrink:0,position:'sticky',top:80}}>
            <div style={{fontSize:11,color:'#64748b',marginBottom:6,textAlign:'center'}}>معاينة الصفحة {activePage+1}</div>
            <img src={pageImages[activePage]} alt="" style={{width:'100%',borderRadius:8,border:'1px solid #334155',boxShadow:'0 4px 20px rgba(0,0,0,.5)'}}/>
          </div>
        )}
        <div style={{flex:1}} dir="rtl">
          {rowList.map(([rowIdx,rowFields])=>(
            <div key={rowIdx} style={{display:'grid',gridTemplateColumns:`repeat(${Math.min(rowFields.length,3)},1fr)`,gap:8,marginBottom:4}}>
              {rowFields.map(f=>{
                const pct=Math.round(f.confidence*100);
                const cc=pct>=85?'#10b981':pct>=65?'#f59e0b':'#ef4444';
                const src=f.source==='native'?'📄':'🔍';
                const dir=['ar','ar_en'].includes(f.language)?'rtl':'ltr';
                return (
                  <div key={f.field_id} style={{...card_s,border:`1px solid ${f.needs_qa?'rgba(239,68,68,.4)':'#334155'}`}}>
                    <div style={{display:'flex',alignItems:'center',gap:6,marginBottom:6}}>
                      <span style={{flex:1,fontSize:12,fontWeight:600,color:'#94a3b8',textAlign:'right',fontFamily:"'Cairo',sans-serif",direction:'rtl'}}>
                        {f.semantic_label}
                      </span>
                      <span style={{fontSize:10,color:cc,fontWeight:700}}>{src}{pct}%</span>
                      <span style={{fontSize:10,background:'rgba(99,102,241,.12)',color:'#a5b4fc',padding:'1px 6px',borderRadius:10,border:'1px solid rgba(99,102,241,.25)'}}>
                        {WIDGET_LABELS[f.runtime_widget]||f.runtime_widget}
                      </span>
                      {f.needs_qa&&<span style={{fontSize:10,color:'#ef4444'}}>⚠</span>}
                    </div>
                    <input dir={dir} defaultValue={f.semantic_label} onChange={e=>onChange(f.field_id,e.target.value)}
                      style={{...inp_s,borderColor:f.needs_qa?'rgba(239,68,68,.4)':'#334155'}}/>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

// ── Drop zone ─────────────────────────────────────────────────────────────────
const DropZone = ({ onFile }) => {
  const [drag, setDrag] = useState(false);
  const ref = useRef();
  return (
    <div onDragOver={e=>{e.preventDefault();setDrag(true);}} onDragLeave={()=>setDrag(false)}
      onDrop={e=>{e.preventDefault();setDrag(false);const f=e.dataTransfer.files[0];if(f?.type==='application/pdf')onFile(f);}}
      onClick={()=>ref.current?.click()}
      style={{border:`2px dashed ${drag?'#0ea5e9':'#334155'}`,borderRadius:20,padding:'64px 40px',
        textAlign:'center',cursor:'pointer',background:drag?'rgba(14,165,233,.07)':'#1e293b',transition:'all .2s'}}>
      <input ref={ref} type="file" accept=".pdf" style={{display:'none'}}
        onChange={e=>e.target.files[0]&&onFile(e.target.files[0])}/>
      <div style={{fontSize:48,marginBottom:12}}>{drag?'📂':'📄'}</div>
      <div style={{fontSize:20,fontWeight:700,marginBottom:8,fontFamily:"'Cairo',sans-serif"}}>ارفع ملف PDF</div>
      <div style={{fontSize:13,color:'#64748b',marginBottom:24}}>عربي، إنجليزي، أو مختلط — استخراج هجين تلقائي</div>
      <div style={{display:'inline-block',background:'linear-gradient(135deg,#0ea5e9,#6366f1)',color:'#fff',fontWeight:700,borderRadius:10,padding:'10px 28px',fontSize:14}}>
        اختر ملف PDF
      </div>
    </div>
  );
};

// ── Processing skeleton ───────────────────────────────────────────────────────
const Processing = ({ name, progress }) => (
  <div style={{maxWidth:520,margin:'60px auto',textAlign:'center',fontFamily:"'Cairo',sans-serif"}}>
    <div style={{fontSize:44,marginBottom:16}}>🔄</div>
    <div style={{fontSize:17,fontWeight:700,marginBottom:6}}>{name}</div>
    <div style={{fontSize:13,color:'#64748b',marginBottom:24}}>استخراج هجين: نص أصلي ← OCR عربي</div>
    {['فتح PDF','استخراج النص الأصلي','OCR للصفحات الممسوحة','تحليل الهندسة','بناء الحقول'].map((s,i)=>(
      <div key={i} style={{display:'flex',alignItems:'center',gap:10,padding:'9px 0',borderBottom:'1px solid #1e293b',direction:'rtl'}}>
        <span>{progress>i*20?'✅':progress===i*20?'⏳':'○'}</span>
        <span style={{fontSize:13,color:progress>=i*20?'#e2e8f0':'#475569'}}>{s}</span>
      </div>
    ))}
    <div style={{marginTop:20,height:6,background:'#1e293b',borderRadius:10,overflow:'hidden'}}>
      <div style={{height:'100%',width:`${progress}%`,background:'linear-gradient(90deg,#0ea5e9,#6366f1)',borderRadius:10,transition:'width .5s ease'}}/>
    </div>
  </div>
);

// ── Main ──────────────────────────────────────────────────────────────────────
export default function PDFProcessor() {
  const [stage, setStage] = useState('idle');
  const [doc, setDoc] = useState(null);
  const [schema, setSchema] = useState(null);
  const [pageImages, setPageImages] = useState({});
  const [activePage, setActivePage] = useState(0);
  const [formValues, setFormValues] = useState({});
  const [error, setError] = useState('');
  const [progress, setProgress] = useState(0);
  const [filename, setFilename] = useState('');
  const [tab, setTab] = useState('formio');

  const processFile = useCallback(async file => {
    setFilename(file.name); setStage('processing');
    setProgress(10); setError(''); setDoc(null); setSchema(null);
    setPageImages({}); setFormValues({}); setActivePage(0); setTab('formio');

    const timer = setInterval(()=>setProgress(p=>Math.min(p+7,85)),1200);
    try {
      const fd = new FormData(); fd.append('file', file);
      const res = await fetch(`${API}/process`,{method:'POST',body:fd});
      clearInterval(timer);
      if (!res.ok) { const e=await res.json().catch(()=>({detail:res.statusText})); throw new Error(e.detail); }
      setProgress(92);
      const data = await res.json();
      setDoc(data);
      setFormValues(Object.fromEntries((data.fields||[]).map(f=>[f.field_id,''])));
      // Build schema client-side immediately — no backend roundtrip needed
      setSchema(buildFormioSchema(data));
      setProgress(100); setStage('done');
      // Fetch page images (background)
      fetchPageImages(data.document_id, data.total_pages);
    } catch(e) { clearInterval(timer); setError(e.message); setStage('error'); }
  }, []);

  const fetchPageImages = async (docId, total) => {
    for (let p=0; p<total; p++) {
      try {
        const r = await fetch(`${API}/documents/${docId}/page/${p}/image`);
        if (r.ok) { const b=await r.blob(); setPageImages(prev=>({...prev,[p]:URL.createObjectURL(b)})); }
      } catch(_){}
    }
  };

  const exportJSON = () => {
    if (!schema) return;
    const b=new Blob([JSON.stringify(schema,null,2)],{type:'application/json'});
    const u=URL.createObjectURL(b); const a=document.createElement('a');
    a.href=u; a.download=`${filename.replace('.pdf','')}_formio.json`; a.click(); URL.revokeObjectURL(u);
  };

  const TAB = (id,label,emoji) => (
    <button id={`cfis-tab-${id}`} onClick={()=>setTab(id)} style={{
      padding:'8px 18px',borderRadius:8,cursor:'pointer',fontSize:13,fontWeight:600,
      border:`1px solid ${tab===id?'#0ea5e9':'#334155'}`,
      background:tab===id?'rgba(14,165,233,.12)':'#1e293b',
      color:tab===id?'#38bdf8':'#64748b',transition:'all .15s',
      fontFamily:"'Cairo',sans-serif",
    }}>{emoji} {label}</button>
  );

  const s = doc?.extraction_stats||{};

  return (
    <div style={{maxWidth:1200,margin:'0 auto',fontFamily:"'Cairo','Segoe UI',sans-serif"}}>

      {(stage==='idle'||stage==='error') && (
        <div style={{maxWidth:560,margin:'40px auto'}}>
          <div style={{textAlign:'center',marginBottom:28,direction:'rtl'}}>
            <div style={{fontSize:36,marginBottom:10}}>📑</div>
            <h2 style={{fontSize:22,fontWeight:800,marginBottom:6}}>معالج المستندات الذكي</h2>
            <p style={{color:'#64748b',fontSize:13}}>PDF → استخراج هجين (عربي/إنجليزي/مختلط) → استمارة تفاعلية</p>
          </div>
          <DropZone onFile={processFile}/>
          {stage==='error'&&<div style={{marginTop:16,padding:'12px 16px',background:'rgba(239,68,68,.08)',border:'1px solid rgba(239,68,68,.3)',borderRadius:10,color:'#f87171',direction:'rtl'}}>❌ {error}</div>}
        </div>
      )}

      {stage==='processing' && <Processing name={filename} progress={progress}/>}

      {stage==='done' && doc && (
        <div>
          {/* Header */}
          <div style={{display:'flex',justifyContent:'space-between',alignItems:'center',marginBottom:14,direction:'rtl'}}>
            <div>
              <div style={{fontWeight:700,fontSize:17}}>{doc.source_file}</div>
              <div style={{fontSize:11,color:'#475569',fontFamily:'monospace'}}>{doc.document_id?.slice(0,16)}… | {doc.fields?.length} حقل | {doc.primary_language} | {doc.fingerprint?.extraction_mode}</div>
            </div>
            <div style={{display:'flex',gap:8}}>
              <button onClick={()=>setStage('idle')} style={{background:'#1e293b',border:'1px solid #334155',color:'#64748b',borderRadius:8,padding:'7px 14px',cursor:'pointer',fontSize:13}}>← ملف جديد</button>
              <button id="cfis-export-json" onClick={exportJSON} style={{background:'linear-gradient(135deg,#0ea5e9,#6366f1)',color:'#fff',border:'none',borderRadius:8,padding:'7px 16px',cursor:'pointer',fontSize:13,fontWeight:700}}>⬇ Form.io JSON</button>
            </div>
          </div>

          {/* Stats */}
          <div style={{display:'flex',gap:8,flexWrap:'wrap',marginBottom:18,direction:'rtl'}}>
            {[['الصفحات',doc.total_pages],['الحقول',doc.fields?.length],['أصلي',s.native_pages??'—'],['OCR',s.ocr_pages??'—'],['تحتاج QA',doc.qa_issues_count||0],['ثقة',`${Math.round((doc.fingerprint?.avg_confidence||0)*100)}%`]].map(([l,v])=>(
              <div key={l} style={{background:'#1e293b',border:'1px solid #334155',borderRadius:8,padding:'5px 12px'}}>
                <div style={{fontSize:10,color:'#475569'}}>{l}</div>
                <div style={{fontSize:13,fontWeight:700}}>{v}</div>
              </div>
            ))}
          </div>

          {/* Tabs */}
          <div style={{display:'flex',gap:8,marginBottom:20,direction:'rtl'}}>
            {TAB('formio','استمارة Form.io','🖊')}
            {TAB('builder','تعديل الاستمارة (Builder)','🛠')}
            {TAB('fields','الحقول المستخرجة','📋')}
            {TAB('json','JSON الخام','{ }')}
            {TAB('qa','مراجعة QA','🎯')}
          </div>

          {tab==='formio' && <InlineFormRenderer schema={schema}/>}

          {tab==='builder' && (
            <div dir="ltr" style={{background:'#fff',padding:20,borderRadius:12}}>
              <p style={{color:'#ef4444',marginBottom:16,direction:'rtl',fontFamily:"'Cairo',sans-serif",fontWeight:600}}>
                ملاحظة: يمكنك هنا تعديل الاستمارة، حذف الحقول الزائدة، وتغيير ترتيبها. (يتطلب Form.io Builder)
              </p>
              {/* Lazy load the FormBuilder to avoid heavy imports if not used */}
              <React.Suspense fallback={<div>Loading Builder...</div>}>
                <FormBuilderComponent schema={schema} onChange={(newSchema) => setSchema(newSchema)} />
              </React.Suspense>
            </div>
          )}

          {tab==='fields' && (
            <RawFieldsView doc={doc} activePage={activePage} setActivePage={setActivePage}
              pageImages={pageImages} formValues={formValues}
              onChange={(id,v)=>setFormValues(p=>({...p,[id]:v}))}/>
          )}

          {tab==='json' && (
            <div style={{position:'relative'}}>
              <button onClick={exportJSON} style={{position:'absolute',top:12,left:12,background:'rgba(99,102,241,.9)',color:'#fff',border:'none',borderRadius:6,padding:'6px 14px',cursor:'pointer',fontSize:12,zIndex:10}}>⬇ تحميل</button>
              <textarea 
                value={schema ? JSON.stringify(schema, null, 2) : ''}
                onChange={(e) => {
                  try {
                    setSchema(JSON.parse(e.target.value));
                  } catch(err) { /* ignore parse errors while typing */ }
                }}
                style={{width:'100%',background:'#0d1117',borderRadius:12,padding:'20px 16px',fontSize:12,color:'#e6edf3',border:'1px solid #334155',height:600,direction:'ltr',lineHeight:1.6,fontFamily:'monospace'}}
              />
            </div>
          )}

          {tab==='qa' && (
            <div style={{margin:'0 -32px'}}>
              <QAViewer documentId={doc.document_id}/>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
