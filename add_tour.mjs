import fs from 'fs';

const graphPath = '.understand-anything/knowledge-graph.json';
const graph = JSON.parse(fs.readFileSync(graphPath, 'utf8'));

// Find some key nodes to highlight
const backendMain = graph.nodes.find(n => n.name === 'main.py' || n.name === 'app.py');
const frontendMain = graph.nodes.find(n => n.name === 'App.tsx' || n.name === 'index.tsx' || n.name === 'main.tsx');
const configNodes = graph.nodes.filter(n => n.type === 'config').slice(0, 3);

graph.tour = [
  {
    order: 1,
    title: "Project Configuration",
    description: "These are the core configuration files that define the project setup, dependencies, and environment.",
    nodeIds: configNodes.map(n => n.id)
  }
];

if (backendMain) {
  graph.tour.push({
    order: 2,
    title: "Backend Entry Point",
    description: "This is the main entry point for the backend API. It handles incoming requests and routes them to appropriate services.",
    nodeIds: [backendMain.id]
  });
}

if (frontendMain) {
  graph.tour.push({
    order: 3,
    title: "Frontend Application",
    description: "This is the root of the React frontend application, responsible for rendering the UI.",
    nodeIds: [frontendMain.id]
  });
}

// Ensure at least one step exists if previous searches failed
if (graph.tour.length === 0 && graph.nodes.length > 0) {
    graph.tour.push({
        order: 1,
        title: "Overview",
        description: "An overview of some key files in the project.",
        nodeIds: graph.nodes.slice(0, 5).map(n => n.id)
    });
}

fs.writeFileSync(graphPath, JSON.stringify(graph, null, 2));
console.log("Tour generated successfully!");
