"""Read held-out source STEP files through the real isolated CAD worker."""
from pathlib import Path
import argparse,gzip,hashlib,io,json,sqlite3,sys,time,zipfile
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from amdfm.io import load_model
from dfm.feature_routing import recognize_cad_features


def main(output):
    started=time.monotonic();base=ROOT/'validation/ai-improvement-2026-09-30'
    root=ROOT.parent/'study/ai-full-corpus-2026-09-30'
    source=ROOT.parent/'study/external-training-2026-09-30'
    dbs={name:sqlite3.connect(f'file:{path.as_posix()}?mode=ro',uri=True) for name,path in
        [('mfinstseg',root/'mfinstseg-verified.sqlite'),('mfcad',source/'training.sqlite')]}
    archive=zipfile.ZipFile(source/'archives/MFInstSeg-data2.zip')
    chosen=[]
    for dataset,folder in [('mfinstseg','feature-routing-test-001'),('mfcad','feature-routing-mfcad-test-001')]:
        with gzip.open(base/folder/'test-events.json.gz','rt',encoding='utf8') as f:records=json.load(f)['records']
        for scope in (('planar','curved') if dataset=='mfinstseg' else ('planar',)):
            pool=sorted((r for r in records if r['scope']==scope),key=lambda r:hashlib.sha256(r['id'].encode()).hexdigest())
            chosen.extend((dataset,r) for r in pool[:6])
    results=[]
    for dataset,record in chosen:
        identifier=record['id']; db=dbs[dataset]
        if dataset=='mfinstseg':
            raw=archive.read('steps/'+identifier+'.step')
            blob=db.execute('SELECT graph FROM parts WHERE id=?',(identifier,)).fetchone()[0]
            with np.load(io.BytesIO(blob),allow_pickle=False) as z:g={k:z[k].copy() for k in z.files}
            g['measurements']=[dict(face_id=i+1,centroid_mm=g['centroids'][i].tolist(),normal=g['normals'][i].tolist(),area_mm2=float(g['areas'][i])) for i in range(len(g['x']))]
            g['scale_mm']=float(g['scale'])
        else:
            raw,blob,measurements=db.execute('SELECT step,graph,measurement FROM parts WHERE id=?',(identifier,)).fetchone()
            with np.load(io.BytesIO(blob),allow_pickle=False) as z:g={k:z[k].copy() for k in z.files}
            g.update(json.loads(measurements))
        actual_sha=hashlib.sha256(raw).hexdigest()
        if actual_sha!=record['step_sha256']:raise ValueError('Source STEP SHA mismatch')
        expected=recognize_cad_features(g)
        model=load_model(raw,identifier+'.step')
        actual=model.metadata.get('external_feature_recognition',[])
        want=sorted((c['feature'],tuple(c['face_ids'])) for c in expected['candidates'])
        got=sorted((c['feature'],tuple(c['face_ids'])) for part in actual for c in part['candidates'])
        matched=want==got and all(p.get('routing_policy')=='cad-feature-agreement-v1' for p in actual)
        row=dict(dataset=dataset,id=identifier,scope=record['scope'],step_sha256=actual_sha,
            expected_candidates=len(want),actual_candidates=len(got),cad_face_identity_matches=matched,
            input_solid_count=model.metadata.get('solid_count'),expected_status=expected['status'],actual_status=[p['status'] for p in actual])
        results.append(row);print(json.dumps(row),flush=True)
    artifact=dict(schema='feature-routing-raw-cad-audit-1',selection='Six SHA256-sorted held-out IDs per source/surface stratum; no selection by prediction outcome',
        cases=len(results),passed=all(r['cad_face_identity_matches'] for r in results),results=results,seconds=time.monotonic()-started,
        adapter_sha256=hashlib.sha256((ROOT/'dfm/feature_routing.py').read_bytes()).hexdigest(),
        cad_worker_sha256=hashlib.sha256((ROOT/'amdfm/cad_worker.py').read_bytes()).hexdigest())
    output.write_text(json.dumps(artifact,indent=2)+'\n',encoding='utf8')
    if not artifact['passed']:raise AssertionError('Raw STEP and certified graph routing differ')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);main(p.parse_args().output)
