import fs from 'fs';

// Load the original AI-generated graph
const aiGraph = JSON.parse(fs.readFileSync('.understand-anything/intermediate/assembled-graph.json', 'utf8'));

// Load the AST import map for edges
const importMapData = JSON.parse(fs.readFileSync('.understand-anything/tmp/ua-import-map-output.json', 'utf8'));
const importMap = importMapData.importMap || {};

// Build a set of valid node IDs
const validNodeIds = new Set(aiGraph.nodes.map(n => n.id));

const newEdges = [];

for (const [srcFp, targets] of Object.entries(importMap)) {
    let srcId = null;
    for (const nid of validNodeIds) {
        if (nid.endsWith(':' + srcFp)) {
            srcId = nid;
            break;
        }
    }
    
    if (!srcId) continue;
    
    for (const targetFp of targets) {
        let targetId = null;
        for (const nid of validNodeIds) {
            if (nid.endsWith(':' + targetFp)) {
                targetId = nid;
                break;
            }
        }
        
        if (targetId) {
            newEdges.push({
                source: srcId,
                target: targetId,
                type: "imports",
                description: `imports ${targetFp.split('/').pop()}`,
                direction: "forward",
                weight: 0.5
            });
        }
    }
}

aiGraph.edges = newEdges;
if (!aiGraph.tour) aiGraph.tour = [];

fs.writeFileSync('.understand-anything/knowledge-graph.json', JSON.stringify(aiGraph, null, 2));
console.log(`Merged successfully: ${aiGraph.nodes.length} nodes, ${newEdges.length} edges.`);
