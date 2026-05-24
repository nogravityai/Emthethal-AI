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

    const renderTopology = () => {
        if (!visibleLayers.topology || !snapshots.topology || !snapshots.topology.tables) return null;
        return snapshots.topology.tables.map(table => {
            const [tx1, ty1, tx2, ty2] = table.bbox;
            return (
                <React.Fragment key={table.table_id}>
                    {/* Table Border */}
                    <div 
                        onClick={() => onEvidenceClick('table', table)}
                        className="absolute border-2 border-dashed border-yellow-500 bg-yellow-500 bg-opacity-5 pointer-events-auto cursor-pointer hover:bg-opacity-10 transition-colors"
                        style={{
                            left: tx1,
                            top: ty1,
                            width: tx2 - tx1,
                            height: ty2 - ty1,
                            zIndex: 10
                        }}
                        title={`Table: ${table.table_id}\nRows: ${table.rows_count}, Cols: ${table.cols_count}`}
                    >
                        {/* Table Badge */}
                        <div className="absolute -top-6 left-0 bg-yellow-500 text-black text-xs font-bold px-1.5 py-0.5 rounded shadow flex items-center gap-1 z-20">
                            <span>📊</span>
                            <span>{table.table_id} ({table.rows_count}x{table.cols_count})</span>
                        </div>
                    </div>
                    {/* Render Cells */}
                    {table.cells.map(cell => {
                        const [cx1, cy1, cx2, cy2] = cell.bbox;
                        return (
                            <div 
                                key={cell.cell_id}
                                onClick={() => onEvidenceClick('cell', cell)}
                                className="absolute border border-yellow-400 bg-yellow-400 bg-opacity-10 hover:bg-opacity-20 cursor-pointer pointer-events-auto transition-colors z-11 flex items-center justify-center"
                                style={{
                                    left: cx1,
                                    top: cy1,
                                    width: cx2 - cx1,
                                    height: cy2 - cy1
                                }}
                                title={`Cell ID: ${cell.cell_id}\nRow: ${cell.row_index}, Col: ${cell.column_index}`}
                            >
                                <span className="text-yellow-600 font-semibold text-[8px] opacity-75">
                                    R{cell.row_index} C{cell.column_index}
                                </span>
                            </div>
                        );
                    })}
                </React.Fragment>
            );
        });
    };

    return (
        <>
            {renderRegions()}
            {renderTokens()}
            {renderAlignments()}
            {renderTopology()}
        </>
    );
}
