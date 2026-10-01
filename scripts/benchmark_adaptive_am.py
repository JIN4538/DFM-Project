"""Paired, equal six-query AM proposal benchmark on disjoint source groups."""
import argparse
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import sys
import time

import numpy as np
import trimesh
from threadpoolctl import threadpool_limits

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from amdfm.adaptive_search import adaptive_queries
from amdfm.full_search import refined_directions,MODEL_PATH
from amdfm.neural_orientation import load_model,baseline_descriptor,proposal_pool,predict_surrogates,proposal_scores
from amdfm.ensemble_search import enrich_ensemble
from amdfm.orientation import compare_orientations,measure_orientation
from amdfm.profiles import Profile
from scripts.train_neural_orientation import objective

POLICIES={
    'rerank':dict(width_deg=40.,ridge=.05,strength=0.,facet_reserve=0),
    'residual20':dict(width_deg=20.,ridge=.03,strength=1.,facet_reserve=0),
    'residual40':dict(width_deg=40.,ridge=.05,strength=1.,facet_reserve=0),
    'residual40_facet2':dict(width_deg=40.,ridge=.05,strength=1.,facet_reserve=2),
    'facet2':dict(width_deg=40.,ridge=.05,strength=0.,facet_reserve=2),
    'retained2_residual20':dict(width_deg=20.,ridge=.03,strength=1.,retain_legacy=2),
    'retained3_residual20':dict(width_deg=20.,ridge=.03,strength=1.,retain_legacy=3),
    'retained4_residual20':dict(width_deg=20.,ridge=.03,strength=1.,retain_legacy=4),
    'retained3_half20':dict(width_deg=20.,ridge=.03,strength=.5,retain_legacy=3),
}


def groups(split,count):
    source=ROOT.parent/'study/ai-full-corpus-2026-09-30'
    index=sqlite3.connect(f'file:{(source/"am-full/index.sqlite").as_posix()}?mode=ro',uri=True)
    previous=json.loads((source/'full-am-benchmark.json').read_text())
    previous_groups={row['group'] for row in previous['cases']}
    output=[]
    for dataset in ('PBF-orientation','CadQuarry','Thingi10K'):
        rows=[json.loads(raw) for raw, in index.execute('SELECT record FROM records WHERE dataset=? AND accepted=1 AND split=?',(dataset,split))]
        seen=set()
        for row in sorted(rows,key=lambda row:hashlib.sha256(('adaptive-v1:'+row['id']).encode()).hexdigest()):
            if row['group'] in seen or row['faces']>5000 or (split=='test' and row['group'] in previous_groups):
                continue
            seen.add(row['group']);output.append(row)
            if len(seen)==count:
                break
    index.close()
    return output


def mesh_for(group,public,things):
    if group['dataset']=='Thingi10K':
        raw=things.execute('SELECT npz FROM parts WHERE id=?',(int(group['id']),)).fetchone()[0]
        with np.load(io.BytesIO(raw),allow_pickle=False) as data:
            mesh=trimesh.Trimesh(data['vertices'],data['facets'],process=False)
    else:
        raw=public.execute('SELECT stl FROM parts WHERE id=?',(group['id'],)).fetchone()[0]
        mesh=trimesh.load(io.BytesIO(raw),file_type='stl',force='mesh')
    mesh.vertices=(mesh.vertices-mesh.vertices.mean(0))/max(mesh.extents)*100
    rng=np.random.default_rng(int(hashlib.sha256(group['id'].encode()).hexdigest()[:8],16))
    mesh.vertices=mesh.vertices@trimesh.transformations.euler_matrix(*rng.uniform(-np.pi,np.pi,3))[:3,:3].T
    return mesh


def comparison(cases,method,control):
    difference=np.array([case['scores'][method]-case['scores'][control] for case in cases])
    return dict(cases=len(cases),better=int(np.sum(difference< -1e-8)),same=int(np.sum(np.abs(difference)<=1e-8)),
                worse=int(np.sum(difference>1e-8)),mean_difference=float(np.mean(difference)))


def main(args):
    if args.output.exists() and any(args.output.iterdir()):
        raise FileExistsError('Benchmark output must be a new directory; previous records are preserved')
    args.output.mkdir(parents=True,exist_ok=True)
    selected_groups=groups(args.split,args.groups_per_source)
    public=sqlite3.connect(f'file:{(ROOT.parent/"study/ai-expansion-2026-09-30/public-expansion.sqlite").as_posix()}?mode=ro',uri=True)
    things=sqlite3.connect(f'file:{(ROOT.parent/"study/external-training-2026-09-30/thingi.sqlite").as_posix()}?mode=ro',uri=True)
    model=load_model(MODEL_PATH)
    selected_policies={key:value for key,value in POLICIES.items() if not args.policy or key in args.policy}
    cases=[];started=time.monotonic()
    for group in selected_groups:
        mesh=mesh_for(group,public,things)
        for process,priority in [('MEX','balanced'),('MEX','support'),('VPP','balanced'),('PBF_POLYMER','height'),('PBF_METAL','balanced')]:
            profile=Profile(process=process)
            height_only=process=='PBF_POLYMER'
            base=compare_orientations(mesh,profile,dense=True)
            before=enrich_ensemble(mesh,profile,base,priority=priority,timeout_s=8.)
            rows=before['rows'];descriptor=baseline_descriptor(mesh,base,require_overhang=not height_only)
            pool,sources=proposal_pool(mesh,base)
            old=np.array([row['direction'] for row in rows])
            available=[i for i,direction in enumerate(pool) if np.max(old@direction)<1-1e-10]
            pool=pool[available];sources=[sources[i] for i in available]
            infer_start=time.monotonic()
            refined=refined_directions(model,descriptor,pool,profile.overhang_angle_deg,priority,height_only,time.monotonic()+.7)
            inference_seconds=time.monotonic()-infer_start
            prediction=predict_surrogates(model,descriptor,pool,profile.overhang_angle_deg,height_only=height_only)
            scores=proposal_scores(prediction,descriptor,priority=priority,height_only=height_only)
            legacy=[]
            for direction in refined+[pool[i] for i in np.argsort(scores,kind='stable')[:40]]:
                if any(direction@d>1-1e-8 for d in list(old)+legacy):continue
                if legacy and max(direction@d for d in legacy)>np.cos(np.deg2rad(8.)):continue
                legacy.append(direction)
                if len(legacy)==6:break
            common=list(pool);common_sources=list(sources)
            for direction in refined:
                if not any(direction@d>1-1e-8 for d in list(old)+common):
                    common.append(direction);common_sources.append('continuous_refinement')
            common=np.asarray(common)
            extras={};timings={};query_log={}
            for name,directions in [('legacy',legacy),('blind',[common[i] for i in np.linspace(0,len(common)-1,6,dtype=int)])]:
                begin=time.monotonic()
                extras[name]=[measure_orientation(mesh,direction,profile) for direction in directions]
                timings[name]=time.monotonic()-begin+(inference_seconds if name=='legacy' else 0.)
            for name,policy in selected_policies.items():
                begin=time.monotonic()
                options=dict(policy)
                retained=options.pop('retain_legacy',0)
                extras[name],query_log[name]=adaptive_queries(model,descriptor,common,common_sources,rows,
                    profile.overhang_angle_deg,lambda direction:measure_orientation(mesh,direction,profile),
                    priority=priority,height_only=height_only,deadline=begin+8.-before['metadata']['elapsed_s']-inference_seconds,
                    warm_start=legacy[:retained],**options)
                timings[name]=time.monotonic()-begin+inference_seconds
            union=rows+[row for extra in extras.values() for row in extra]
            best={name:float(objective(rows+extra,union,process=process,priority=priority).min()) for name,extra in extras.items()}
            case=dict(id=group['id'],dataset=group['dataset'],group=group['group'],split=args.split,process=process,priority=priority,
                source_sha256=group['sha256'],scores=best,counts={name:len(value) for name,value in extras.items()},seconds=timings,
                common_pool_size=len(common),base_added_count=before['metadata']['added_count'])
            cases.append(case)
            key=hashlib.sha256((group['dataset']+group['id']+process+priority).encode()).hexdigest()
            (args.output/(key+'.json')).write_text(json.dumps(dict(**case,base=rows,extras=extras,queries=query_log),ensure_ascii=False))
        print(json.dumps(dict(groups=len(cases)//5,seconds=time.monotonic()-started)),flush=True)
    summary={name:{control:comparison(cases,name,control) for control in ('legacy','blind')} for name in selected_policies}
    result=dict(split=args.split,groups=len(selected_groups),cases=cases,summary=summary,policies=selected_policies,
        neural_model_sha256=model['sha256'],algorithm_sha256=hashlib.sha256((ROOT/'amdfm/adaptive_search.py').read_bytes()).hexdigest(),
        previous_test_groups_excluded=args.split=='test',seconds=time.monotonic()-started,
        criterion='Exact common-union .7 max weighted regret + .3 weighted mean; six added geometry queries and same candidate pool for each policy; candidate utility, not generic accuracy')
    (args.output/'summary.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({key:value for key,value in result.items() if key not in ('cases',)}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--split',choices=('validation','test'),required=True)
    parser.add_argument('--groups-per-source',type=int,default=8);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--policy',choices=list(POLICIES),action='append');args=parser.parse_args()
    with threadpool_limits(limits=1):main(args)
