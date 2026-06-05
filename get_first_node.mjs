import fs from 'fs';
const data = JSON.parse(fs.readFileSync('.understand-anything/intermediate/assembled-graph.json', 'utf8'));
console.log(JSON.stringify(data.nodes[0], null, 2));
