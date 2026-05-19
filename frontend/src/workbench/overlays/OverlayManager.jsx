import React from 'react';

/**
 * Responsible for rendering stateless evidence layers (Tokens, Regions, Edges).
 * It receives Snapshots from the backend and renders them deterministically.
 */
export default function OverlayManager({ snapshots, visibleLayers, onEvidenceClick }) {
    
    // Scale factors: For now we assume 1:1 if the viewer is 1000x1000.
    // In production, this maps the canonical coordinates to the current display scale.
    
    const renderRegions = () => {
        if (!visibleLayers.geometry || !snapshots.geometry) return null;
        return snapshots.geometry.regions.map(r => {
            const [x1, y1, x2, y2] = r.bbox;
            return (
                <div 
                    key={r.id}
                    onClick={() => onEvidenceClick('region', r)}
                    className="absolute border-2 border-blue-500 bg-blue-500 bg-opacity-10 cursor-pointer hover:bg-opacity-30 pointer-events-auto transition-colors"
                    style={{
                        left: x1,
                        top: y1,
                        width: x2 - x1,
                        height: y2 - y1
                    }}
                    title={`Region: ${r.id}\nConf: ${r.confidence}`}
                />
            );
        });
    };

    const renderTokens = () => {
        if (!visibleLayers.ocr || !snapshots.ocr) return null;
        return snapshots.ocr.tokens.map(t => {
            const [x1, y1, x2, y2] = t.bbox;
            return (
                <div 
                    key={t.id}
                    onClick={() => onEvidenceClick('token', t)}
                    className="absolute border border-green-400 bg-green-400 bg-opacity-20 cursor-pointer hover:bg-opacity-40 pointer-events-auto flex items-center justify-center overflow-hidden transition-colors"
                    style={{
                        left: x1,
                        top: y1,
                        width: x2 - x1,
                        height: y2 - y1,
                        fontSize: '10px'
                    }}
                    title={`Token: ${t.id}\nConf: ${t.confidence}`}
                >
                    <span className="text-green-900 font-bold truncate px-1">{t.text}</span>
                </div>
            );
        });
    };

    const renderAlignments = () => {
        // Drawing arrows between tokens and regions is complex in raw DOM, 
        // usually we'd use an SVG overlay here.
        if (!visibleLayers.alignment || !snapshots.alignment || !snapshots.ocr || !snapshots.geometry) return null;
        
        return (
            <svg className="absolute inset-0 w-full h-full pointer-events-none">
                {snapshots.alignment.alignments.map(a => {
                    const token = snapshots.ocr.tokens.find(t => t.id === a.token);
                    const region = snapshots.geometry.regions.find(r => r.id === a.region);
                    if (!token || !region) return null;
                    
                    const tx = (token.bbox[0] + token.bbox[2]) / 2;
                    const ty = (token.bbox[1] + token.bbox[3]) / 2;
                    const rx = (region.bbox[0] + region.bbox[2]) / 2;
                    const ry = (region.bbox[1] + region.bbox[3]) / 2;
                    
                    return (
                        <line 
                            key={a.id}
                            x1={tx} y1={ty} x2={rx} y2={ry}
                            stroke="rgba(236, 72, 153, 0.6)" // Pink
                            strokeWidth="2"
                            strokeDasharray="4 2"
                        />
                    );
                })}
            </svg>
        );
    };

    return (
        <>
            {renderRegions()}
            {renderTokens()}
            {renderAlignments()}
        </>
    );
}
