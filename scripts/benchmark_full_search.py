"""Frozen holdout query/final-choice benchmark, including equal-budget control."""
import hashlib,io,json,sqlite3,sys,time
from pathlib import Path
import numpy as np
import trimesh
from threadpoolctl import threadpool_limits
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from amdfm.orientation import compare_orientations,measure_orientation
from amdfm.neural_orientation import proposal_pool
from amdfm.ensemble_search import enrich_ensemble
from amdfm.full_search import enrich_full
from amdfm.profiles import Profile
from scripts.train_neural_orientation import objective
from dfm.enhanced_planning import recommend_plan


def main():
    root=ROOT.parent/'study/ai-full-corpus-2026-09-30'
    start=time.monotonic();cases=[];groups=[]
    index=sqlite3.connect(root/'am-full/index.sqlite')
    for dataset in ('PBF-orientation','CadQuarry','Thingi10K'):
        rows=[json.loads(raw) for raw, in index.execute("SELECT record FROM records WHERE dataset=? AND accepted=1 AND split='test'",(dataset,))]
        seen=set()
        for r in sorted(rows,key=lambda r:hashlib.sha256(r['id'].encode()).hexdigest()):
            if r['group'] in seen or r['faces']>5000:continue
            seen.add(r['group']);groups.append(r)
            if len(seen)==35:break
    public=sqlite3.connect(ROOT.parent/'study/ai-expansion-2026-09-30/public-expansion.sqlite')
    things=sqlite3.connect(ROOT.parent/'study/external-training-2026-09-30/thingi.sqlite')
    for g in groups:
        if g['dataset']=='Thingi10K':
            raw=things.execute('SELECT npz FROM parts WHERE id=?',(int(g['id']),)).fetchone()[0]
            with np.load(io.BytesIO(raw),allow_pickle=False) as z:mesh=trimesh.Trimesh(z['vertices'],z['facets'],process=False)
        else:
            raw=public.execute('SELECT stl FROM parts WHERE id=?',(g['id'],)).fetchone()[0]
            mesh=trimesh.load(io.BytesIO(raw),file_type='stl',force='mesh')
        mesh.vertices=(mesh.vertices-mesh.vertices.mean(0))/max(mesh.extents)*100
        rng=np.random.default_rng(int(hashlib.sha256(g['id'].encode()).hexdigest()[:8],16))
        mesh.vertices=mesh.vertices@trimesh.transformations.euler_matrix(*rng.uniform(-np.pi,np.pi,3))[:3,:3].T
        for process,priority in [('MEX','balanced'),('MEX','support'),('VPP','balanced'),('PBF_POLYMER','height'),('PBF_METAL','balanced')]:
            p=Profile(process=process);base=compare_orientations(mesh,p,dense=True)
            old=enrich_ensemble(mesh,p,base,priority=priority,timeout_s=30)
            new=enrich_full(mesh,p,base,priority=priority,timeout_s=30)
            pool,_=proposal_pool(mesh,base)
            remain=[d for d in pool if all(d@np.array(r['direction'])<1-1e-10 for r in old['rows'])]
            blind=[measure_orientation(mesh,remain[i],p) for i in np.linspace(0,len(remain)-1,6,dtype=int)]
            control=old['rows']+blind
            union=new['rows']+blind
            scores={name:float(objective(rows,union,process=process,priority=priority).min()) for name,rows in [('previous',old['rows']),('expanded',new['rows']),('equal_budget_control',control)]}
            final={}
            for name,rows in [('previous',old['rows']),('expanded',new['rows'])]:
                r=dict(process=process,profile=p.to_dict(),summary={'review_status':'geometry_review'},model={'unit_status':'declared'},findings=[],
                    orientations=rows,current_orientation=measure_orientation(mesh,[0,0,1],p),review_context={'priority':priority})
                plan=recommend_plan(r,feedback_path=root/'benchmark-no-user-feedback.json').get('selected')
                if plan:
                    selected=measure_orientation(mesh,plan['orientation']['direction'],p)
                    final[name]=float(objective([selected],union,process=process,priority=priority)[0])
            cases.append(dict(id=g['id'],dataset=g['dataset'],group=g['group'],process=process,priority=priority,**scores,
                final=final,old_queries=old['metadata']['added_count'],new_queries=new['metadata']['added_count']))
        print(json.dumps(dict(groups=len(cases)//5,seconds=time.monotonic()-start)),flush=True)
    def compare(key,final=False):
        eligible=[r for r in cases if not final or set(r['final'])=={'previous','expanded'}]
        diffs=[(r['final']['expanded']-r['final']['previous']) if final else r['expanded']-r[key] for r in eligible]
        return dict(cases=len(diffs),better=sum(d< -1e-8 for d in diffs),same=sum(abs(d)<=1e-8 for d in diffs),worse=sum(d>1e-8 for d in diffs),mean_difference=float(np.mean(diffs)))
    result=dict(previous_comparison=compare('previous'),equal_query_budget_comparison=compare('equal_budget_control'),final_choice_comparison=compare('previous',True),
        distinct_holdout_groups=len(groups),cases=cases,seconds=time.monotonic()-start,
        criterion='Exact geometry common-union weighted regret; candidate search and final chosen plan separately. Expanded retains old 18 and adds 6; control adds 6 deterministic blind queries.')
    (root/'full-am-benchmark.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='cases'}),flush=True)
if __name__=='__main__':
    with threadpool_limits(limits=1):main()
