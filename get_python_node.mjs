import fs from 'fs';
const data = JSON.parse(fs.readFileSync('.understand-anything/intermediate/assembled-graph.json', 'utf8'));
const pyNode = data.nodes.find(n => n.filePath && n.filePath.endsWith('.py'));
console.log(JSON.stringify(pyNode, null, 2));
