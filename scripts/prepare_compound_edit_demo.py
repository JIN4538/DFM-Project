"""Independent, dimensioned three-pocket STEP reference; never training data."""
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SPECS = ((3,18.,5.,1.), (4,45.,7.,.8), (6,73.,4.,1.5))


def mixed_cavity(rotated=False):
    import numpy as np
    from OCP.gp import gp_Pnt, gp_Vec, gp_Trsf, gp_Ax1, gp_Dir
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace, BRepBuilderAPI_Transform
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakePrism
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    shape = BRepPrimAPI_MakeBox(90.,60.,20.).Shape()
    for sides, x, depth, _ in SPECS:
        polygon = BRepBuilderAPI_MakePolygon()
        for i in range(sides):
            angle = 2*math.pi*i/sides
            polygon.Add(gp_Pnt(x+9*math.cos(angle),30+9*math.sin(angle),20-depth))
        polygon.Close()
        cutter = BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(polygon.Wire()).Face(), gp_Vec(0,0,depth+2)).Shape()
        shape = BRepAlgoAPI_Cut(shape,cutter).Shape()
    if rotated:
        transform = gp_Trsf()
        transform.SetRotation(gp_Ax1(gp_Pnt(0,0,0),gp_Dir(0,1,0)),math.pi/2)
        shape = BRepBuilderAPI_Transform(shape,transform,True).Shape()
    return shape


def measured_requests(shape, rotated=False):
    import numpy as np
    from dfm.cad_graph import extract_graph
    from dfm.external_features_review import pocket_dimensions
    rows = extract_graph(shape)['measurements']
    result = []
    for sides,x,depth,radius in SPECS:
        chosen = []
        for row in rows:
            p = np.asarray(row['centroid_mm'])
            if rotated:
                p = np.asarray([-p[2],p[1],p[0]])
            if abs(p[0]-x)<9.1 and abs(p[1]-30)<9.1 and (abs(p[2]-(20-depth))<1e-7 or abs(p[2]-(20-depth/2))<1e-7):
                chosen.append(row)
        direction = [1,0,0] if rotated else [0,0,1]
        candidate = dict(feature={3:'triangular_pocket',4:'rectangular_pocket',6:'6sides_pocket'}[sides],
            face_ids=[row['face_id'] for row in chosen],measured_faces=chosen)
        pocket = pocket_dimensions(candidate,direction)
        if pocket is None:
            raise ValueError('Independent reference pocket could not be remeasured')
        result.append(dict(pocket=dict(pocket,direction=direction),radius=radius))
    return result


def main():
    from dfm.cad_edit_pairs import write_step, read_shape
    from dfm.multi_cad_edit import round_multiple_corners
    folder = ROOT/'examples/learning_validation/compound_edits'
    folder.mkdir(parents=True,exist_ok=True)
    before = folder/'three_pockets_before.step'
    if before.exists():
        raise ValueError('Reference already exists; preserve its original bytes')
    write_step(mixed_cavity(),before)
    shape = read_shape(before)
    request = dict(pockets=measured_requests(shape))
    after,audit = round_multiple_corners(shape,request['pockets'])
    path = folder/'three_pockets_after.step'
    write_step(after,path)
    (folder/'audit.json').write_text(json.dumps(dict(request=request,audit=audit),indent=2),encoding='utf8')
    inventory_path=ROOT/'examples/geometry_manifest.json'
    inventory=json.loads(inventory_path.read_text(encoding='utf8'))
    import hashlib
    for p in (before,path):
        inventory['files'].append(dict(path=p.relative_to(ROOT).as_posix(),group='examples/learning_validation',format='step',
            bytes=p.stat().st_size,sha256=hashlib.sha256(p.read_bytes()).hexdigest(),purpose='Independent three-pocket CAD edit reference'))
    inventory.update(geometry_file_count=len(inventory['files']),unique_sha256_count=len({r['sha256'] for r in inventory['files']}),
        total_bytes=sum(r['bytes'] for r in inventory['files']))
    inventory['groups']={g:sum(r['group']==g for r in inventory['files']) for g in sorted({r['group'] for r in inventory['files']})}
    inventory_path.write_text(json.dumps(inventory,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps(dict(before=str(before),after=str(path),modified_edges=audit['modified_corner_edges'])))


if __name__=='__main__':main()
