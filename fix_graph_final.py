import json

# Load the original AI-generated graph (which has good nodes and layers)
with open('.understand-anything/intermediate/assembled-graph.json', 'r') as f:
    ai_graph = json.load(f)

# Load the AST import map for edges
with open('.understand-anything/tmp/ua-import-map-output.json', 'r') as f:
    import_map = json.load(f).get('importMap', {})

# Build a set of valid node IDs from the AI graph
valid_node_ids = {n['id'] for n in ai_graph.get('nodes', [])}

# Generate edges only between nodes that actually exist in the AI graph
new_edges = []
for src_fp, targets in import_map.items():
    # Guess the node type based on extension (most code is service)
    # The AI might have used different types, so we search the valid_node_ids by suffix
    src_id = None
    for nid in valid_node_ids:
        if nid.endswith(f":{src_fp}"):
            src_id = nid
            break
            
    if not src_id: continue
    
    for target_fp in targets:
        target_id = None
        for nid in valid_node_ids:
            if nid.endswith(f":{target_fp}"):
                target_id = nid
                break
                
        if target_id:
            new_edges.append({
                "source": src_id,
                "target": target_id,
                "type": "imports",
                "description": f"imports {target_fp.split('/')[-1]}",
                "direction": "forward",
                "weight": 0.5
            })

# Ensure the graph structure is complete
ai_graph['edges'] = new_edges

if 'tour' not in ai_graph or not ai_graph['tour']:
    ai_graph['tour'] = []

with open('.understand-anything/knowledge-graph.json', 'w') as f:
    json.dump(ai_graph, f, indent=2)

print(f"Merged successfully: {len(ai_graph['nodes'])} nodes, {len(new_edges)} edges.")
