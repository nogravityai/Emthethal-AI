import fs from 'fs';

const graphPath = '.understand-anything/knowledge-graph.json';
const graph = JSON.parse(fs.readFileSync(graphPath, 'utf8'));

graph.version = "1.0.0";
graph.project = {
  name: "emthethal-ai",
  description: "Project analyzed via automated AST extraction",
  languages: ["python", "shell", "json", "markdown", "yaml", "javascript", "typescript"],
  frameworks: ["FastAPI", "React", "Docker"],
  analyzedAt: new Date().toISOString(),
  gitCommitHash: "latest"
};

fs.writeFileSync(graphPath, JSON.stringify(graph, null, 2));
console.log("Project metadata injected successfully.");
