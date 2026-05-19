import React, { useState, useEffect } from 'react';
import { pipelineApi } from '../api';

export default function SchemaPreview({ runId }) {
    const [exportData, setExportData] = useState(null);
    const [loading, setLoading] = useState(false);

    const loadExport = async () => {
        if (!runId) return;
        setLoading(true);
        try {
            const data = await pipelineApi.getExport(runId);
            setExportData(data);
        } catch (e) {
            console.error("Failed to load export", e);
            setExportData(null);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadExport();
    }, [runId]);

    if (!runId) return null;

    if (loading) return (
        <div className="absolute right-0 bottom-0 w-80 h-96 bg-gray-900 border-t border-l border-gray-800 p-4 shadow-xl text-gray-400 flex justify-center items-center">
            Building Canonical Schema...
        </div>
    );

    if (!exportData) return null;

    return (
        <div className="absolute right-80 bottom-0 w-[400px] h-[500px] bg-[#0B0F19]/95 backdrop-blur-3xl border-t border-l border-r border-gray-800/80 shadow-[0_-10px_40px_rgba(0,0,0,0.5)] flex flex-col z-20 rounded-tl-2xl rounded-tr-2xl overflow-hidden">
            <div className="p-4 bg-gradient-to-r from-gray-900 to-[#121826] border-b border-gray-800 flex justify-between items-center">
                <div className="flex items-center gap-2">
                    <span className="text-purple-500">📄</span>
                    <h2 className="text-[11px] font-bold text-gray-300 uppercase tracking-widest">Canonical Schema</h2>
                </div>
                <span className="text-[10px] font-mono bg-purple-500/10 border border-purple-500/20 text-purple-400 px-2.5 py-1 rounded-md shadow-inner">
                    v{exportData.canonical_document.schema_version}
                </span>
            </div>
            
            <div className="flex-1 overflow-auto p-5 custom-scrollbar bg-[#0B0F19]">
                <h3 className="text-[10px] text-gray-500 uppercase tracking-widest mb-4">Export Interpretation</h3>
                
                {/* Form.io Native Rendering Stub */}
                <div className="bg-[#121826] rounded-xl p-5 text-gray-200 border border-gray-800/80 shadow-inner">
                    {exportData.formio_schema.components.map((panel, idx) => (
                        <div key={idx} className="mb-6 last:mb-0">
                            <h4 className="font-bold text-sm mb-4 text-gray-300 border-b border-gray-800 pb-2">{panel.title}</h4>
                            <div className="space-y-4">
                                {panel.components.map((comp, cIdx) => (
                                    <div key={cIdx} className="flex flex-col">
                                        <label className="text-[11px] font-medium text-gray-500 mb-1 uppercase tracking-wide">
                                            {comp.label}
                                        </label>
                                        {comp.type === 'textfield' && (
                                            <input 
                                                type="text" 
                                                readOnly 
                                                value={comp.defaultValue || ""}
                                                className="border border-gray-700/50 rounded-lg px-3 py-2.5 bg-[#0B0F19] text-gray-300 shadow-inner focus:outline-none focus:border-purple-500/50 transition-colors text-sm"
                                            />
                                        )}
                                        {comp.type === 'checkbox' && (
                                            <div className="flex items-center mt-1">
                                                <input 
                                                    type="checkbox" 
                                                    readOnly 
                                                    checked={comp.defaultValue === true}
                                                    className="w-4 h-4 text-purple-600 bg-[#0B0F19] border-gray-700 rounded focus:ring-purple-500"
                                                />
                                            </div>
                                        )}
                                    </div>
                                ))}
                            </div>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
}
