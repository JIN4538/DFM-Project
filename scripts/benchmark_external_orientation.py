"""Compare old/new proposed directions with exact measurements on held-out Things."""
import argparse,io,json,sqlite3,time,sys
from pathlib import Path
import numpy as np
import trimesh
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from amdfm.neural_orientation import enrich_orientations
from amdfm.orientation import compare_orientations
from amdfm.profiles import Profile

def main(root):
    out=root/'orientation-proposal-audit.json'
    if out.exists():raise FileExistsError(out)
    db=sqlite3.connect(f'file:{(root/"thingi.sqlite").resolve()}?mode=ro',uri=True)
    groups=json.loads((root/'orientation-final/groups.json').read_text())
    done=set();cases=[];started=time.monotonic()
    for g in groups:
        if g['split']!='test' or g['thing_id'] in done:continue
        done.add(g['thing_id']);raw=db.execute('SELECT npz FROM parts WHERE id=?',(g['file_id'],)).fetchone()[0]
        with np.load(io.BytesIO(raw),allow_pickle=False) as z:mesh=trimesh.Trimesh(z['vertices'],z['facets'],process=False)
        mesh.vertices=(mesh.vertices-mesh.vertices.mean(0))/max(mesh.extents)*100
        profile=Profile();rows=compare_orientations(mesh,profile,dense=True)
        def objective(rows):
            return float(min(r['height_mm']/np.linalg.norm(mesh.extents)+r['overhang_projected_area_sum_mm2']/mesh.area for r in rows))
        old=enrich_orientations(mesh,profile,rows,model_path=Path(__file__).resolve().parents[1]/'data/models/neural_orientation_v1.json',timeout_s=30)
        new=enrich_orientations(mesh,profile,rows,timeout_s=30)
        cases.append(dict(file_id=g['file_id'],thing_id=g['thing_id'],old=objective(old['rows']),new=objective(new['rows']),baseline=objective(rows),
            old_status=old['metadata']['status'],new_status=new['metadata']['status'],new_added=new['metadata']['added_count']))
    summary=dict(cases=cases,criterion='Minimum normalized height + normalized downward projected-area among exact remeasured proposals; separate from final recommendation policy',
        better=sum(c['new']<c['old']-1e-8 for c in cases),worse=sum(c['new']>c['old']+1e-8 for c in cases),same=sum(abs(c['new']-c['old'])<=1e-8 for c in cases),seconds=time.monotonic()-started)
    out.write_text(json.dumps(summary,indent=2));print({k:v for k,v in summary.items() if k!='cases'})

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);main(p.parse_args().root)
