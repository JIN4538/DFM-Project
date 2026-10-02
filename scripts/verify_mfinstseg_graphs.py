"""Certify every admitted face ordinal using author geometry + adjacency."""
import argparse, concurrent.futures, hashlib, io, json, sqlite3, sys, tempfile, time, zipfile
from pathlib import Path
import numpy as np
import ijson
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dfm.cad_graph import read_step_graph

def certify(graph, original):
    attrs=np.asarray(original['graph_face_attr'],float);n=len(graph['x'])
    if attrs.shape!=(n,10):raise ValueError('Face count/schema differs')
    kinds=np.asarray([m['surface_kind'] for m in graph['measurements']]);expected=np.eye(6)[kinds][:,:5]
    if not np.array_equal(attrs[:,:5],expected):raise ValueError('Surface type order differs')
    actual=np.asarray([m['centroid_mm'] for m in graph['measurements']]); published=attrs[:,7:10]
    a=actual-actual.mean(0); b=published-published.mean(0)
    scale=float(np.sum(a*b)/np.sum(a*a));offset=published.mean(0)-scale*actual.mean(0)
    if not scale>0:raise ValueError('Invalid scale correspondence')
    centroid_error=float(np.max(np.abs(actual*scale+offset-published)))
    area=np.asarray([m['area_mm2'] for m in graph['measurements']])*scale**2
    area_error=float(np.max(np.abs(area-attrs[:,5])/np.maximum(attrs[:,5],1e-6)))
    ours={tuple(map(int,e)) for e in graph['edges']}; theirs=set(zip(*original['graph']['edges']))
    if centroid_error>1e-5 or area_error>1e-4 or ours!=theirs:
        raise ValueError(f'Geometry correspondence rejected: centroid={centroid_error:g}, area={area_error:g}, adjacency={ours==theirs}')
    return dict(centroid_max_abs_error=centroid_error,area_max_relative_error=area_error,adjacency_equal=True,scale=scale)

def worker(job):
    identifier,raw,label,original=job
    try:
        rows=json.loads(label);matching=[r[1] for r in rows if r[0]==identifier]
        if len(matching)!=1:raise ValueError('Original identifier mismatch')
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'source.step';path.write_bytes(raw);g=read_step_graph(path)
        audit=certify(g,original)
        labels=matching[0]['seg'];g['y']=np.array([labels[str(i)] for i in range(len(g['x']))],dtype=np.int64)
        # A feature-multiset family stays together, rather than repeated
        # randomly positioned features contaminating the holdout split.
        group=','.join(map(str,sorted(v for v in g['y'].tolist() if v!=24)))
        bucket=int(hashlib.sha256(group.encode()).hexdigest()[:8],16)%100
        split='train' if bucket<70 else 'val' if bucket<85 else 'test'
        buffer=io.BytesIO();np.savez_compressed(buffer,x=g['x'],edges=g['edges'],y=g['y'])
        return identifier,split,group,buffer.getvalue(),json.dumps(audit),None
    except Exception as error:return identifier,None,None,None,None,str(error)

def main(root,limit,workers):
    target=root/'mfinstseg-verified.sqlite'
    if target.exists():raise ValueError('Preserve previous audit DB')
    db=sqlite3.connect(target);db.execute('CREATE TABLE parts(id TEXT PRIMARY KEY,split TEXT,group_id TEXT,graph BLOB,audit TEXT,error TEXT)')
    source=sqlite3.connect('file:../study/external-training-2026-09-30/mfinstseg-complete.sqlite?mode=ro',uri=True)
    started=time.monotonic();seen=0;accepted=0
    with zipfile.ZipFile('../study/external-training-2026-09-30/archives/MFInstSeg-data2.zip') as z, concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
        jobs=[]
        for identifier,original in ijson.items(z.open('aag/graphs.json'),'item',use_float=True):
            row=source.execute('SELECT step,labels,split FROM parts WHERE id=?',(identifier,)).fetchone()
            if row is None or row[2] in ('quarantine','unassigned'):continue
            # Published UV grids are ignored; only ordered area/centroid/type
            # and adjacency are evidence for ordinal certification.
            compact={k:original[k] for k in ('graph','graph_face_attr')}
            jobs.append((identifier,row[0],row[1],compact));seen+=1
            if len(jobs)>=64 or seen>=limit:
                for result in pool.map(worker,jobs):
                    db.execute('INSERT INTO parts VALUES (?,?,?,?,?,?)',result);accepted+=result[3] is not None
                db.commit();jobs=[];print(json.dumps(dict(audited=seen,accepted=accepted,seconds=time.monotonic()-started)),flush=True)
            if seen>=limit:break
    if jobs:
        for result in map(worker,jobs):db.execute('INSERT INTO parts VALUES (?,?,?,?,?,?)',result);accepted+=result[3] is not None
    db.commit();summary=dict(audited=seen,accepted=accepted,counts=list(db.execute('SELECT split,COUNT(*) FROM parts GROUP BY split')),
        failures=list(db.execute('SELECT error,COUNT(*) FROM parts WHERE error IS NOT NULL GROUP BY error LIMIT 25')),
        ordinal_policy='Every admitted graph independently matches ordered surface type, area, centroid after isotropic transform and all directed adjacency edges',
        sampling='First author graph records; generated CAD corpus, feature-multiset family holdout; not an industrial external benchmark',seconds=time.monotonic()-started)
    (root/'mfinstseg-verified-audit.json').write_text(json.dumps(summary,indent=2));db.close();source.close();print(json.dumps(summary),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--limit',type=int,default=5000);p.add_argument('--workers',type=int,default=3);a=p.parse_args();main(a.root,a.limit,a.workers)
