import json
import os
import re

with open('.understand-anything/knowledge-graph.json', 'r') as f:
    d = json.load(f)

edges = []
path_to_node = {n.get('filePath'): n['id'] for n in d.get('nodes', []) if n.get('filePath')}

for fp, src_id in path_to_node.items():
    if not fp.endswith('.py'): continue
    if not os.path.exists(fp): continue
    
    with open(fp, 'r', encoding='utf-8') as f:
        content = f.read()
    
    imports = re.findall(r'^(?:from|import)\s+([\w\.]+)', content, re.MULTILINE)
    
    for imp in imports:
        parts = imp.split('.')
        possible_paths = [
            os.path.join(*parts) + '.py',
            os.path.join(*parts, '__init__.py'),
            os.path.join('backend', *parts) + '.py',
            os.path.join('backend', *parts, '__init__.py'),
            os.path.join('backend', 'app', *parts) + '.py',
            os.path.join('backend', 'app', *parts, '__init__.py')
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

# Deduplicate
unique_edges = []
seen_edges = set()
for e in edges:
    sig = frozenset(e.items())
    if sig not in seen_edges:
        seen_edges.add(sig)
        unique_edges.append(e)

d['edges'] = unique_edges

with open('.understand-anything/knowledge-graph.json', 'w') as f:
    json.dump(d, f, indent=2)

print(f"Edges generated: {len(unique_edges)}")
