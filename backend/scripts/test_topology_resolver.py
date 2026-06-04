#!/usr/bin/env python3
"""
Unit tests for TableTopologyResolver inside the Docker container.
Uses real project BoundingBox schema.
Run: docker exec -e PYTHONPATH=/app emthethal_backend python3 /app/scripts/test_topology_resolver.py
"""
import sys
from app.models.schemas import BoundingBox, CoordinateSpace
from app.core.topology.table_topology_resolver import TableTopologyResolver

PW, PH = 1000, 1000  # default page dims

def bbox(x1, y1, x2, y2):
    return BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2, page_width=PW, page_height=PH)

class FakeBox:
    def __init__(self, x1, y1, x2, y2, rtype='table_cell'):
        self.bbox = bbox(x1, y1, x2, y2)
        self.region_type = rtype
        self.stable_id = f'box_{x1}_{y1}'
        self.cell_id = self.stable_id

class FakeLine:
    def __init__(self, x1, y1, x2, y2, orient='horizontal'):
        self.bbox = bbox(x1, y1, x2, y2)
        self.orientation = orient
        self.stable_id = f'line_{x1}_{y1}'

r = TableTopologyResolver()
passed = 0
failed = 0

def check(name, cond, detail=''):
    global passed, failed
    if cond:
        print(f'  PASS  {name}')
        passed += 1
    else:
        print(f'  FAIL  {name}  {detail}')
        failed += 1

print('\n=== TableTopologyResolver Tests ===\n')

# T1: empty input
result = r.resolve_page_topology(1, [], [], PW, PH)
check('T1 empty input returns []', result == [])

# T2: non-table region_type filtered
result = r.resolve_page_topology(1, [FakeBox(10,10,100,50,'footer')], [], PW, PH)
check('T2 footer region filtered', result == [])

# T3: single cell
result = r.resolve_page_topology(1, [FakeBox(10,10,100,50)], [], PW, PH)
check('T3 single cell: 1 result',   len(result) == 1)
check('T3 single cell: row=0 col=0', len(result)==1 and result[0].row_index==0 and result[0].column_index==0)

# T4: 2 side-by-side → same row, 2 cols
result = r.resolve_page_topology(1, [FakeBox(10,10,90,50), FakeBox(110,10,190,50)], [], PW, PH)
rows = {x.row_index for x in result}
cols = {x.column_index for x in result}
check('T4 2 side-by-side: 1 row',  len(rows)==1, f'rows={rows}')
check('T4 2 side-by-side: 2 cols', len(cols)==2, f'cols={cols}')

# T5: 2 stacked → 2 rows
result = r.resolve_page_topology(1, [FakeBox(10,10,100,50), FakeBox(10,60,100,100)], [], PW, PH)
rows = {x.row_index for x in result}
check('T5 2 stacked: 2 rows', len(rows)==2, f'rows={rows}')

# T6: 2x2 grid → 4 cells, all span=1
boxes = [FakeBox(0,0,100,50), FakeBox(110,0,200,50),
         FakeBox(0,60,100,110), FakeBox(110,60,200,110)]
result = r.resolve_page_topology(1, boxes, [], PW, PH)
check('T6 2x2: 4 cells', len(result)==4, f'got {len(result)}')
if len(result)==4:
    ok = all(x.rowspan==1 and x.colspan==1 for x in result)
    check('T6 2x2: all spans=1', ok, str([(x.row_index,x.column_index,x.rowspan,x.colspan) for x in result]))

# T7: _merge_coordinates
merged = r._merge_coordinates([10.0, 10.5, 11.0, 50.0, 50.3, 100.0])
check('T7 merge: 3 groups',     len(merged)==3, f'got {merged}')
check('T7 merge: empty input',  r._merge_coordinates([])==[])

# T8: 2 separate tables on page → 2 distinct table_ids
boxes = [FakeBox(0,0,100,50), FakeBox(110,0,200,50),
         FakeBox(500,400,600,450), FakeBox(610,400,700,450)]
result = r.resolve_page_topology(1, boxes, [], PW, PH)
table_ids = {x.table_id for x in result}
check('T8 2 separate tables', len(table_ids)==2, f'table_ids={table_ids}')

# T9: unknown region_type is NOT filtered (included per resolver logic)
result = r.resolve_page_topology(1, [FakeBox(10,10,100,50,'unknown')], [], PW, PH)
check('T9 unknown region included', len(result)==1)

print(f'\n{"="*38}')
print(f'  Results: {passed} passed, {failed} failed')
print(f'{"="*38}\n')
sys.exit(0 if failed==0 else 1)
