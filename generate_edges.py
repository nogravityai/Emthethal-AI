import json
import ast
import os

with open('.understand-anything/knowledge-graph.json', 'r') as f:
    d = json.load(f)

# Build a mapping from file paths to node IDs
path_to_node = {}
for node in d.get('nodes', []):
    fp = node.get('filePath')
    if fp:
        path_to_node[fp] = node['id']

# Function to resolve python import to a file path
def resolve_import(module_name):
    if not module_name: return None
    # backend.app.core.geometry_engine -> backend/app/core/geometry_engine.py
    parts = module_name.split('.')
    path = os.path.join(*parts) + '.py'
    if os.path.exists(path):
        return path
    # or a package __init__.py
    pkg_path = os.path.join(*parts, '__init__.py')
    if os.path.exists(pkg_path):
        return pkg_path
    return None

new_edges = []
for fp, src_id in path_to_node.items():
    if not fp.endswith('.py'):
        continue
    if not os.path.exists(fp):
        continue
    with open(fp, 'r', encoding='utf-8') as f:
        try:
            content = f.read()
            tree = ast.parse(content, filename=fp)
        except Exception:
            continue
    
    # Extract imports
    imports = []
    for stmt in ast.walk(tree):
        if isinstance(stmt, ast.Import):
            for alias in stmt.names:
                imports.append(alias.name)
        elif isinstance(stmt, ast.ImportFrom):
            if stmt.module:
                imports.append(stmt.module)
    
    # Resolve and create edges
    for imp in imports:
        target_fp = resolve_import(imp)
        if target_fp and target_fp in path_to_node:
            target_id = path_to_node[target_fp]
            new_edges.append({
                "source": src_id,
                "target": target_id,
                "type": "imports",
                "description": f"imports {imp}",
                "direction": "forward",
                "weight": 0.5
            })

# Ensure we keep existing non-import edges if any
existing_edges = [e for e in d.get('edges', []) if e.get('type') != 'imports']
# Add missing fields to existing edges if they don't have it
for e in existing_edges:
    if 'direction' not in e: e['direction'] = 'forward'
    if 'weight' not in e: e['weight'] = 0.5

d['edges'] = existing_edges + new_edges

with open('.understand-anything/knowledge-graph.json', 'w') as f:
    json.dump(d, f, indent=2)

print(f"Generated {len(new_edges)} import edges.")
