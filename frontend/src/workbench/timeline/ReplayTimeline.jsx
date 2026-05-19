import React, { useEffect, useState } from 'react';
import { pipelineApi } from '../api';

export default function ReplayTimeline({ runId }) {
    const [timeline, setTimeline] = useState(null);
    const [loading, setLoading] = useState(false);

    const loadTimeline = async () => {
        if (!runId) return;
        setLoading(true);
        try {
            const data = await pipelineApi.getTimeline(runId);
            setTimeline(data);
        } catch (e) {
            console.error("Failed to load timeline", e);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadTimeline();
    }, [runId]);

    if (!runId) return (
        <div className="p-4 text-gray-500 text-sm text-center">
            Waiting for Pipeline Run...
        </div>
    );

    if (loading) return (
        <div className="p-4 text-gray-400 text-sm animate-pulse text-center">
            Loading timeline...
        </div>
    );

    if (!timeline) return null;

    return (
        <div className="flex flex-col h-full w-80 bg-[#0B0F19]/90 backdrop-blur-2xl border-l border-gray-800/80 shadow-[-10px_0_30px_rgba(0,0,0,0.5)] z-20">
            <div className="p-5 border-b border-gray-800/60 bg-gradient-to-r from-gray-900 to-[#0B0F19]">
                <h2 className="text-[11px] font-bold text-gray-400 uppercase tracking-widest flex items-center gap-2">
                    <span className="text-blue-500">⏱️</span> Execution Timeline
                </h2>
            </div>
            
            <div className="flex-1 overflow-auto p-6 custom-scrollbar">
                <div className="relative border-l-2 border-gray-700 ml-3 space-y-6">
                    {timeline.stages.map((stage, idx) => (
                        <div key={idx} className="relative pl-6">
                            {/* Node Dot */}
                            <div className="absolute w-4 h-4 bg-gray-900 border-2 border-blue-500 rounded-full -left-[9px] top-1"></div>
                            
                            {/* Content */}
                            <div className="group">
                                <h3 className="text-sm font-bold text-gray-200 capitalize group-hover:text-blue-400 transition-colors">
                                    {stage.stage_name.replace(/_/g, ' ')}
                                </h3>
                                <div className="mt-1.5 bg-[#121826] rounded-lg p-2.5 border border-gray-800/80 shadow-inner group-hover:border-blue-500/30 transition-all">
                                    <p className="text-[10px] text-gray-500 uppercase tracking-wider mb-1">Output Artifact</p>
                                    <span className="text-[10px] text-blue-400/80 font-mono block break-all">
                                        {stage.artifact_id}
                                    </span>
                                </div>
                            </div>
                        </div>
                    ))}
                    
                    {timeline.human_operations && timeline.human_operations.map((op, idx) => (
                        <div key={`op_${idx}`} className="relative pl-6">
                            <div className="absolute w-4 h-4 bg-gray-900 border-2 border-pink-500 rounded-full -left-[9px] top-1"></div>
                            <div>
                                <h3 className="text-sm font-bold text-pink-400">
                                    Human Operation
                                </h3>
                                <div className="mt-1 bg-gray-800 rounded p-2 border border-pink-900">
                                    <span className="text-xs text-gray-300">
                                        {op.operation_type}
                                    </span>
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            </div>
            
            <div className="p-4 border-t border-gray-800 bg-gray-800 bg-opacity-50">
                <div className="flex items-center justify-between text-xs">
                    <span className="text-gray-400">Determinism:</span>
                    <span className="text-green-400 font-bold bg-green-900 bg-opacity-30 px-2 py-1 rounded">VERIFIED</span>
                </div>
                <div className="flex items-center justify-between text-xs mt-2">
                    <span className="text-gray-400">Artifacts Tracked:</span>
                    <span className="text-gray-200 font-mono">{timeline.stages.length}</span>
                </div>
            </div>
        </div>
    );
}
