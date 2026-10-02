"""Same-budget neural proposals on disjoint public geometry groups."""
import argparse,hashlib,io,json,sqlite3,sys,time
from pathlib import Path
import numpy as np
import trimesh
from threadpoolctl import threadpool_limits
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from amdfm.neural_orientation import enrich_orientations
from amdfm.ensemble_search import enrich_ensemble
from amdfm.orientation import compare_orientations
from amdfm.profiles import Profile
from scripts.train_neural_orientation import objective
from dfm.enhanced_planning import recommend_plan

def main(root,ensemble=False,offset=0):
    start=time.monotonic();audit=json.loads((root/'am-training/audit.json').read_text());groups=[];seen=set()
    for ds in ('PBF-orientation','CadQuarry','Thingi10K'):
        rows=[g for g in audit['groups'] if g['split']=='test' and g['dataset']==ds and g['faces']<=5000]
        count=0;unique=0
        for g in sorted(rows,key=lambda g:hashlib.sha256(g['id'].encode()).hexdigest()):
            if g['group'] in seen:continue
            seen.add(g['group']);unique+=1
            if unique<=offset:continue
            groups.append(g);count+=1
            if count>=25:break
    db=sqlite3.connect(f'file:{(root/"public-expansion.sqlite").resolve()}?mode=ro',uri=True)
    olddb=sqlite3.connect(f'file:{(root.parent/"external-training-2026-09-30/thingi.sqlite").resolve()}?mode=ro',uri=True)
    cases=[]
    for g in groups:
        if g['dataset']=='Thingi10K':
            raw=olddb.execute('SELECT npz FROM parts WHERE id=?',(int(g['id']),)).fetchone()[0]
            with np.load(io.BytesIO(raw),allow_pickle=False) as z:mesh=trimesh.Trimesh(z['vertices'],z['facets'],process=False)
        else:mesh=trimesh.load(io.BytesIO(db.execute('SELECT stl FROM parts WHERE id=?',(g['id'],)).fetchone()[0]),file_type='stl',force='mesh')
        mesh.vertices=(mesh.vertices-mesh.vertices.mean(0))/max(mesh.extents)*100
        rng=np.random.default_rng(int(hashlib.sha256(g['id'].encode()).hexdigest()[:8],16));rotation=trimesh.transformations.euler_matrix(*rng.uniform(-np.pi,np.pi,3))[:3,:3];mesh.vertices=mesh.vertices@rotation.T
        for process,priority in [('MEX','balanced'),('MEX','support'),('PBF_POLYMER','height'),('PBF_METAL','balanced')]:
            profile=Profile(process=process);rows=compare_orientations(mesh,profile,dense=True)
            old=enrich_orientations(mesh,profile,rows,priority=priority,timeout_s=30,model_path=ROOT/'data/models/neural_orientation_external_v2.json')
            new=(enrich_ensemble(mesh,profile,rows,priority=priority,timeout_s=30) if ensemble else
                 enrich_orientations(mesh,profile,rows,priority=priority,timeout_s=30,model_path=root/'am-training/neural_orientation_external_v3.json'))
            union=old['rows']+new['rows'];scores={}
            for name,r in [('previous',old),('expanded',new)]:
                scores[name]=float(objective(r['rows'],union,process=process,priority=priority).min())
            cases.append(dict(id=g['id'],group=g['group'],dataset=g['dataset'],process=process,priority=priority,**scores,
                old_status=old['metadata']['status'],new_status=new['metadata']['status']))
        print(json.dumps(dict(groups=len(cases)//4,seconds=time.monotonic()-start)),flush=True)
    def summary(rows):return dict(better=sum(r['expanded']<r['previous']-1e-8 for r in rows),worse=sum(r['expanded']>r['previous']+1e-8 for r in rows),same=sum(abs(r['expanded']-r['previous'])<=1e-8 for r in rows),case_count=len(rows))
    result=dict(**summary(cases),by_dataset={d:summary([r for r in cases if r['dataset']==d]) for d in set(r['dataset'] for r in cases)},cases=cases,
       criterion='Best exact-measured .7 max weighted regret + .3 weighted mean regret; union normalization; candidate search benchmark, not final plan preference accuracy',
       previous_budget=12,expanded_budget=18 if ensemble else 12,ensemble=ensemble,disjoint_from_diagnostic=offset>0,
       distinct_geometry_groups=len(groups),seconds=time.monotonic()-start)
    (root/('am-ensemble-benchmark.json' if ensemble else 'am-proposal-benchmark.json')).write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='cases'}),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--ensemble',action='store_true');p.add_argument('--offset',type=int,default=0);a=p.parse_args()
    with threadpool_limits(limits=2):main(a.root,a.ensemble,a.offset)
