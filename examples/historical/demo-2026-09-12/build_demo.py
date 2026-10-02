from pathlib import Path
import sys, math
import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'study/versions/AM-DFM_v2_6/dfm2'))
from src.core.model_loader import load_model
from src.core.mesh_diagnostics import inspect_mesh
from src.core.reproducibility import runtime_record, file_sha256, save_new_json
from src.processes.additive import AMRuleEngine

OUT = Path(__file__).parent
def box(lo, hi):
    lo, hi = np.array(lo), np.array(hi)
    return trimesh.creation.box(extents=hi-lo, transform=trimesh.transformations.translation_matrix((lo+hi)/2))

def build(thin):
    parts = [box([0,0,0],[86,64,3])]
    # Front: walls, all connected through the base.
    for x,t in zip([7,17,27], [thin,1.2,2.0]):
        parts.append(box([x,5,2],[x+t,20,19]))
    # Bridges with clear spans 6, 12 and 20 mm.
    for x,span in [(4,6),(23,12),(49,20)]:
        parts += [box([x,27,2],[x+3,33,21]),
                  box([x+3+span,27,2],[x+6+span,33,21]),
                  box([x,27,21],[x+6+span,33,24])]
    # Three inclined solid beams; lower faces at 30/45/60 degrees to XY.
    for x,angle in [(7,30),(30,45),(53,60)]:
        rise=14.0; run=rise/math.tan(math.radians(angle))
        points=[[x+dx, y+shift, z] for z,shift in [(2,0),(2+rise,run)]
                for dx in [0,5] for y in [40,43]]
        parts.append(trimesh.convex.convex_hull(np.array(points)))
    # Rear-right arch: rectangular body minus a cylindrical through-hole along Y.
    body=box([65,43,2],[83,51,31])
    hole=trimesh.creation.cylinder(radius=6,height=12,sections=96)
    hole.apply_transform(trimesh.transformations.rotation_matrix(math.pi/2,[1,0,0]))
    hole.apply_translation([74,47,19])
    parts.append(trimesh.boolean.difference([body,hole],engine='manifold'))
    return trimesh.boolean.union(parts,engine='manifold')

records=[]
for name,thin in [('AM_DFM_demo',0.8),('AM_DFM_demo_thin_0p3',0.3)]:
    path=OUT/(name+'.stl')
    mesh=build(thin)
    mesh.export(path)
    raw=trimesh.load_mesh(path,process=True)
    diag=inspect_mesh(raw)
    assert diag['topology_ready'],diag
    assert len(raw.split())==1
    print(name, 'mesh PASS',len(raw.faces),flush=True)
    loaded=load_model(str(path),unit='mm')['mesh']
    result=AMRuleEngine().evaluate(loaded,printer_dims=(250,250,250))
    print(name,result.evaluation_status,result.total_score,'layers',result.layer_review.get('status'),flush=True)
    records.append(dict(file=path.name,sha256=file_sha256(path),diagnostics=diag,evaluation=result))
save_new_json(OUT/'validation.json',dict(runtime=runtime_record(),unit='mm',build_direction=[0,0,1],printer=[250,250,250],models=records))

# Local interactive preview, embedded JS, no server or CDN required.
import plotly.graph_objects as go
m=trimesh.load_mesh(OUT/'AM_DFM_demo.stl')
fig=go.Figure(go.Mesh3d(x=m.vertices[:,0],y=m.vertices[:,1],z=m.vertices[:,2],
    i=m.faces[:,0],j=m.faces[:,1],k=m.faces[:,2],color='#4c9ead',flatshading=True))
fig.update_layout(title='AM-DFM demonstration geometry (mm)',scene=dict(aspectmode='data',
    xaxis_title='X (mm)',yaxis_title='Y (mm)',zaxis_title='Z (mm)'),margin=dict(l=0,r=0,b=0,t=45))
fig.write_html(OUT/'preview.html',include_plotlyjs=True)
