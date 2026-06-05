import json

with open('.understand-anything/knowledge-graph.json', 'r') as f:
    d = json.load(f)

node_ids = [n['id'] for n in d.get('nodes', [])]

d['layers'] = [{
    "id": "layer_overview",
    "name": "Project Overview",
    "description": "Automatically generated overview containing all nodes.",
    "nodeIds": node_ids
}]

with open('.understand-anything/knowledge-graph.json', 'w') as f:
    json.dump(d, f, indent=2)

print("Added Project Overview layer with all nodes.")
