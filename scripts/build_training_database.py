"""Immutable raw CAD/labels plus verified label-free B-rep graphs in SQLite."""
from __future__ import annotations
import argparse, concurrent.futures, hashlib, io, json, pickle, sqlite3, sys, tempfile, time, zipfile
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dfm.cad_graph import read_step_graph, SCHEMA, FEATURES
from scripts.audit_public_cad_data import PrimitiveUnpickler

def extract(job):
    identifier,raw,truth=job
    try:
        labels=PrimitiveUnpickler(io.BytesIO(truth)).load()
        if not isinstance(labels,list) or not all(type(v)==int and 0<=v<16 for v in labels): raise ValueError('Invalid label range')
        with tempfile.TemporaryDirectory(prefix='dfm-graph-') as temp:
            path=Path(temp)/'part.step'; path.write_bytes(raw); g=read_step_graph(path,labels)
        b=io.BytesIO(); np.savez_compressed(b,x=g['x'],edges=g['edges'],y=g['y'])
        return identifier,b.getvalue(),json.dumps({k:v for k,v in g.items() if k not in ('x','edges','y')}),None
    except Exception as exc: return identifier,None,None,f'{type(exc).__name__}: {exc}'

def build(archive,destination,workers):
    if destination.exists(): raise FileExistsError(destination)
    destination.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(destination); db.executescript('''
    CREATE TABLE sources(id TEXT PRIMARY KEY,metadata TEXT NOT NULL);
    CREATE TABLE parts(id TEXT PRIMARY KEY,source TEXT NOT NULL,sha256 TEXT NOT NULL,split TEXT NOT NULL,
    step BLOB NOT NULL,labels BLOB NOT NULL,graph BLOB,measurement TEXT,error TEXT);
    CREATE INDEX part_split ON parts(split);
    ''')
    digest=hashlib.sha256()
    with archive.open('rb') as f:
        for block in iter(lambda:f.read(2**20),b''): digest.update(block)
    db.execute('INSERT INTO sources VALUES (?,?)',('mfcad',json.dumps(dict(url='https://github.com/hducg/MFCAD',
        commit='ef6d58a40164d5192666821ce98d0cc90e379fac',license='MIT',archive_sha256=digest.hexdigest(),
        graph_schema=SCHEMA,features=FEATURES,label_mapping='label[STEP face Name()]',
        split='SHA256 of sorted feature multiset; all combinations in same partition; 70/15/15',
        semantic_mapping='numeric IDs retained; names audited separately'))))
    started=time.monotonic()
    with zipfile.ZipFile(archive) as z:
        members=sorted(n for n in z.namelist() if n.endswith('.step'))
        jobs=[]
        for n in members:
            identifier=Path(n).stem; raw=z.read(n); truth=z.read(n[:-5]+'.face_truth')
            family='-'.join(sorted(identifier.split('-')[:-1],key=int))
            bucket=int(hashlib.sha256(family.encode()).hexdigest()[:8],16)%100
            split='train' if bucket<70 else 'val' if bucket<85 else 'test'
            db.execute('INSERT INTO parts(id,source,sha256,split,step,labels) VALUES (?,?,?,?,?,?)',
                       (identifier,'mfcad',hashlib.sha256(raw).hexdigest(),split,raw,truth))
        db.commit(); print(f'Raw intake {len(members)} parts',flush=True)
        # Bounded batches prevent keeping all raw CADs/futures in RAM.
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
            for start in range(0,len(members),128):
                batch=[(Path(n).stem,z.read(n),z.read(n[:-5]+'.face_truth')) for n in members[start:start+128]]
                for identifier,graph,measurement,error in pool.map(extract,batch):
                    db.execute('UPDATE parts SET graph=?,measurement=?,error=? WHERE id=?',(graph,measurement,error,identifier))
                db.commit()
                print(f'Graphs {min(start+128,len(members))}/{len(members)} elapsed {time.monotonic()-started:.0f}s',flush=True)
    counts={s:db.execute('SELECT count(*) FROM parts WHERE split=? AND graph IS NOT NULL',(s,)).fetchone()[0] for s in ('train','val','test')}
    failures=db.execute('SELECT id,error FROM parts WHERE error IS NOT NULL').fetchall()
    duplicates=db.execute('SELECT sha256,count(*) FROM parts GROUP BY sha256 HAVING count(*)>1').fetchall()
    summary=dict(raw_parts=len(members),graph_parts=sum(counts.values()),splits=counts,failures=failures,
                 byte_duplicates=duplicates,seconds=time.monotonic()-started,database=str(destination))
    destination.with_suffix('.json').write_text(json.dumps(summary,indent=2),encoding='utf8'); print(json.dumps(summary),flush=True); db.close()

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--archive',type=Path,required=True); p.add_argument('--database',type=Path,required=True);p.add_argument('--workers',type=int,default=4)
    a=p.parse_args(); build(a.archive,a.database,a.workers)
