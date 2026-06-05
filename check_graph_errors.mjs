import fs from 'fs';
const data = JSON.parse(fs.readFileSync('.understand-anything/knowledge-graph.json', 'utf8'));

// Check for duplicate nodes
const nodeIds = new Set();
let duplicates = 0;
data.nodes.forEach(n => {
    if(nodeIds.has(n.id)) {
        duplicates++;
        console.log("Duplicate node:", n.id);
    }
    nodeIds.add(n.id);
});

// Check for missing targets in edges
let badEdges = 0;
data.edges.forEach(e => {
    if(!nodeIds.has(e.source) || !nodeIds.has(e.target)) {
        badEdges++;
    }
});

console.log(`Duplicates: ${duplicates}, Bad Edges: ${badEdges}, Total Nodes: ${data.nodes.length}`);
