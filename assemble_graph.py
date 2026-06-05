import json

with open('.understand-anything/tmp/ua-scan-files.json') as f:
    scan = json.load(f)

with open('.understand-anything/tmp/ua-import-map-output.json') as f:
    import_map = json.load(f).get('importMap', {})

nodes = []
edges = []

for file_info in scan.get('files', []):
    fp = file_info['path']
    cat = file_info.get('fileCategory', 'code')
    # Use categories to determine node types
    node_type = "file"
    if cat == "config": node_type = "config"
    elif cat == "docs": node_type = "document"
    elif cat == "script": node_type = "pipeline"
    elif cat == "infra": node_type = "resource"
    elif cat == "code": node_type = "service"
    
    node_id = f"{node_type}:emthethal-ai:{fp}"
    nodes.append({
        "id": node_id,
        "name": fp.split('/')[-1],
        "type": node_type,
        "filePath": fp,
        "summary": f"{cat.capitalize()} file: {fp}",
        "tags": [cat, file_info.get('language', 'unknown')]
    })

# Map file paths to node IDs for quick lookup
fp_to_id = {n['filePath']: n['id'] for n in nodes}

for src_fp, targets in import_map.items():
    if src_fp not in fp_to_id: continue
    src_id = fp_to_id[src_fp]
    for target_fp in targets:
        if target_fp in fp_to_id:
            target_id = fp_to_id[target_fp]
            edges.append({
                "source": src_id,
                "target": target_id,
                "type": "imports",
                "description": f"imports {target_fp.split('/')[-1]}",
                "direction": "forward",
                "weight": 0.5
            })

knowledge_graph = {
    "version": "1.0.0",
    "project": {
        "name": "emthethal-ai",
        "description": "Project analyzed via automated AST extraction",
        "languages": ["python", "shell", "json", "markdown", "yaml"],
        "frameworks": ["FastAPI", "Docker"],
        "analyzedAt": "2026-06-05T00:00:00Z",
        "gitCommitHash": "latest"
    },
    "nodes": nodes,
    "edges": edges,
    "layers": [],
    "tour": []
}

with open('.understand-anything/knowledge-graph.json', 'w') as f:
    json.dump(knowledge_graph, f, indent=2)

print(f"Assembled {len(nodes)} nodes and {len(edges)} edges.")
