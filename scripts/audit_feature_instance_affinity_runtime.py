"""Opt-in model parity, original CAD identities and inference cost audit."""
from pathlib import Path
import argparse,gzip,hashlib,io,json,sqlite3,sys,time,zipfile
import numpy as np
from threadpoolctl import threadpool_limits
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dfm.feature_routing import recognize_cad_features
from dfm.feature_instance_refinement import recognize_refined_features,load_model,predict_affinity,refine_groups
from dfm.feature_learning import CURVED_CLASS_NAMES
from dfm.cad_graph import read_step_graph


def main(args):
    base=ROOT.parent/'study/ai-next-2026-09-30/feature-affinity-v1'
    with gzip.open(base/'test-records.json.gz','rt',encoding='utf8') as f:records=json.load(f)
    model=load_model(args.model)
    with np.load(base/'test-pairs.npz') as z:
        with threadpool_limits(limits=1):affinity=predict_affinity(z['x'],model)
    selected=[]
    for scope in ('planar','curved'):
        pool=sorted([r for r in records if r['scope']==scope],key=lambda r:hashlib.sha256(r['id'].encode()).hexdigest());selected+=pool[:20]
    selected+=sorted(records,key=lambda r:-sum(len(g['faces']) for g in r['groups']))[:5]
    selected=list({r['id']:r for r in selected}.values())
    db=sqlite3.connect(f'file:{(ROOT.parent/"study/ai-full-corpus-2026-09-30/mfinstseg-verified.sqlite").as_posix()}?mode=ro',uri=True)
    times=[];parity=[];graphs={}
    with threadpool_limits(limits=1):
        for record in selected:
            raw=db.execute('SELECT graph FROM parts WHERE id=?',(record['id'],)).fetchone()[0]
            with np.load(io.BytesIO(raw),allow_pickle=False) as z:g={k:z[k].copy() for k in z.files}
            g['measurements']=[dict(face_id=i+1,area_mm2=float(g['areas'][i]),centroid_mm=g['centroids'][i].tolist(),normal=g['normals'][i].tolist()) for i in range(len(g['x']))];g['scale_mm']=float(g['scale'])
            t=time.perf_counter();old=recognize_cad_features(g);old_ms=(time.perf_counter()-t)*1000
            t=time.perf_counter();new=recognize_refined_features(g,args.model);new_ms=(time.perf_counter()-t)*1000
            n=len(old['candidates']);same=old['candidates']==new['candidates'][:n]
            refined=refine_groups(record['groups'],record['pairs'],affinity[record['start']:record['start']+record['count']],model['merge_threshold'])
            expected=sorted((CURVED_CLASS_NAMES[r['label']],tuple(i+1 for i in r['faces'])) for r in refined if model['class_thresholds'].get(str(r['label'])) is not None and r['confidence']>=model['class_thresholds'][str(r['label'])])
            actual=sorted((r['feature'],tuple(r['face_ids'])) for r in new['candidates'][n:])
            passed=same and expected==actual
            parity.append(dict(id=record['id'],scope=record['scope'],faces=len(g['x']),old_candidates=n,added_candidates=len(actual),old_unchanged=same,parity=passed))
            times.append(dict(id=record['id'],faces=len(g['x']),pairs=record['count'],v1_ms=old_ms,refined_ms=new_ms));graphs[record['id']]=(g,new)
    raw_dir=ROOT.parent/'study/ai-next-2026-09-30/raw-cad-affinity-audit';raw_dir.mkdir(parents=True,exist_ok=True)
    archive=zipfile.ZipFile(ROOT.parent/'study/external-training-2026-09-30/archives/MFInstSeg-data2.zip');cad=[]
    with threadpool_limits(limits=1):
        for record in selected[:6]+selected[20:26]:
            raw=archive.read('steps/'+record['id']+'.step');path=raw_dir/(record['id']+'.step')
            if hashlib.sha256(raw).hexdigest()!=record['sha256']:raise ValueError('Original STEP checksum mismatch')
            path.write_bytes(raw);g=read_step_graph(path);actual=recognize_refined_features(g,args.model);cached=graphs[record['id']][1]
            want=sorted((r['feature'],tuple(r['face_ids'])) for r in cached['candidates']);got=sorted((r['feature'],tuple(r['face_ids'])) for r in actual['candidates'])
            cad.append(dict(id=record['id'],scope=record['scope'],faces=len(g['x']),passed=want==got))
    result=dict(model_sha256=hashlib.sha256(args.model.read_bytes()).hexdigest(),selection='20 SHA256-sorted IDs per surface stratum plus five largest actual CAD graphs; no selection by prediction outcome',
        parity=parity,raw_step=cad,timing=times,timing_summary={key:dict(median=float(np.median([r[key] for r in times])),p95=float(np.quantile([r[key] for r in times],.95)),maximum=max(r[key] for r in times)) for key in ('v1_ms','refined_ms')},
        budget=dict(max_faces=200,max_possible_component_pairs=19900,freeform_supported=False,largest_observed_faces=max(r['faces'] for r in times)),
        timing_scope='Portable inference including artifact/dependency checks; excludes CAD import and graph extraction. Single CPU BLAS thread.',
        passed=all(r['parity'] for r in parity) and all(r['passed'] for r in cad))
    args.output.write_text(json.dumps(result,indent=2),encoding='utf8');print(json.dumps({k:v for k,v in result.items() if k not in ('parity','raw_step','timing')}),flush=True)
    if not result['passed']:raise AssertionError('Runtime audit failed')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--model',type=Path,required=True);p.add_argument('--output',type=Path,required=True);main(p.parse_args())
