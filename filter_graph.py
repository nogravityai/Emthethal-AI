import json
import os
import re

with open('.understand-anything/knowledge-graph.json', 'r') as f:
    d = json.load(f)

# 1. Filter out non-code nodes
valid_extensions = {'.py', '.ts', '.js', '.jsx', '.tsx'}
filtered_nodes = []
allowed_node_ids = set()

for node in d.get('nodes', []):
    fp = node.get('filePath', '')
    if fp:
        ext = os.path.splitext(fp)[1].lower()
        if ext in valid_extensions or os.path.isdir(fp):
            filtered_nodes.append(node)
            allowed_node_ids.add(node['id'])
    else:
        # keep nodes that don't represent a file path directly (like layers or logical groups if any)
        # actually, the dashboard nodes usually have a filePath if they are file nodes
        filtered_nodes.append(node)
        allowed_node_ids.add(node['id'])

d['nodes'] = filtered_nodes

# 2. Re-extract simple edges
edges = []
path_to_node = {n.get('filePath'): n['id'] for n in filtered_nodes if n.get('filePath')}
# simple python import matcher
for fp, src_id in path_to_node.items():
    if not fp.endswith('.py'): continue
    if not os.path.exists(fp): continue
    
    with open(fp, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # from backend.app.services.x import y -> backend/app/services/x.py
    # import backend.app.services.x -> backend/app/services/x.py
    imports = re.findall(r'^(?:from|import)\s+([\w\.]+)', content, re.MULTILINE)
    
    for imp in imports:
        # Convert module to path
        parts = imp.split('.')
        possible_paths = [
            os.path.join(*parts) + '.py',
            os.path.join(*parts, '__init__.py')
        ]
        for p in possible_paths:
            if p in path_to_node:
                edges.append({
                    "source": src_id,
                    "target": path_to_node[p],
                    "type": "imports",
                    "description": f"imports {imp}",
                    "direction": "forward",
                    "weight": 0.5
                })
                break

d['edges'] = edges

with open('.understand-anything/knowledge-graph.json', 'w') as f:
    json.dump(d, f, indent=2)

print(f"Nodes remaining: {len(filtered_nodes)}")
print(f"Edges generated: {len(edges)}")
