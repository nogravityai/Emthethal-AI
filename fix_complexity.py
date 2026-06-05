import json

with open('.understand-anything/knowledge-graph.json', 'r') as f:
    d = json.load(f)

for node in d.get('nodes', []):
    if 'complexity' not in node:
        node['complexity'] = 'moderate'

with open('.understand-anything/knowledge-graph.json', 'w') as f:
    json.dump(d, f, indent=2)

print("Fixed complexity warnings.")
