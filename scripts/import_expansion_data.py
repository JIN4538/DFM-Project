"""Raw CC0 CAD and Apache-declared PBF datasets. Never execute CAD programs."""
import argparse, hashlib, json, sqlite3, zipfile
from collections import Counter
from pathlib import Path
import pyarrow.parquet as pq

def split(group):
    bucket=int(hashlib.sha256(group.encode()).hexdigest()[:8],16)%100
    return 'train' if bucket<70 else 'validation' if bucket<85 else 'test'

def main(root):
    target=root/'public-expansion.sqlite'
    if target.exists():raise ValueError('Preserve existing DB')
    db=sqlite3.connect(target); db.executescript('''CREATE TABLE parts
    (id TEXT PRIMARY KEY,dataset TEXT,family TEXT,group_id TEXT,split TEXT,license TEXT,
    step BLOB,stl BLOB,metadata TEXT,step_sha256 TEXT,stl_sha256 TEXT);
    CREATE INDEX data_split ON parts(dataset,split); CREATE INDEX groups ON parts(group_id);''')
    sources={};counts=Counter()
    # Read bounded parquet batches. Source strings are inert metadata only.
    for batch in pq.ParquetFile(root/'archives/1k_corpus-step.parquet').iter_batches(batch_size=32):
        for row in batch.to_pylist():
            if row['license']!='CC0-1.0':raise ValueError('Unexpected CAD license')
            step=row.pop('step_bytes');identifier=row['part_id'];group='cq:'+row['family']+':'+row['geometry_signature']
            db.execute('INSERT INTO parts VALUES (?,?,?,?,?,?,?,?,?,?,?)',(identifier,'CadQuarry',row['family'],group,split(group),row['license'],step,None,json.dumps(row),hashlib.sha256(step).hexdigest(),None))
            counts['CadQuarry']+=1
    for batch in pq.ParquetFile(root/'archives/1k_corpus-stl.parquet').iter_batches(batch_size=32):
        for row in batch.to_pylist():
            stl=row['stl_bytes'];db.execute('UPDATE parts SET stl=?,stl_sha256=? WHERE id=?',(stl,hashlib.sha256(stl).hexdigest(),row['part_id']))
    db.commit()
    for path in sorted((root/'archives').glob('*_10000.zip')):
        family=path.stem.removesuffix('_10000')
        with zipfile.ZipFile(path) as z:
            names=z.namelist(); files={Path(n).stem:n for n in names if n.endswith('.stl')}
            for name in names:
                if not name.endswith('.json'):continue
                identifier=Path(name).stem; raw=z.read(name);meta=json.loads(raw)
                # Published random-view split is recorded, not trusted to
                # separate repeated underlying dimension/shape families.
                geometry={k:v for k,v in meta.items() if not k.startswith('target_') and k not in ('phi','theta','psi','num_triangles','num_vertices')}
                group='pbf:'+family+':'+json.dumps(geometry,sort_keys=True)
                if identifier not in files:raise ValueError('Missing source mesh')
                stl=z.read(files[identifier]);meta['original_split_path']=files[identifier]
                db.execute('INSERT INTO parts VALUES (?,?,?,?,?,?,?,?,?,?,?)',(identifier,'PBF-orientation',family,group,split(group),'Apache-2.0 declared by author',None,stl,json.dumps(meta),None,hashlib.sha256(stl).hexdigest()))
                counts['PBF-orientation']+=1
                if counts['PBF-orientation']%2000==0:db.commit();print(dict(counts),flush=True)
        db.commit()
    # Identical raw source bytes spanning groups/splits are quarantined.
    duplicates=db.execute('SELECT stl_sha256 FROM parts GROUP BY stl_sha256 HAVING COUNT(DISTINCT split)>1').fetchall()
    for sha, in duplicates:db.execute("UPDATE parts SET split='quarantine' WHERE stl_sha256=?",(sha,))
    db.commit(); summary=dict(raw=dict(counts),splits=list(db.execute('SELECT dataset,split,COUNT(*),COUNT(DISTINCT group_id) FROM parts GROUP BY dataset,split')),
        cad_missing_mesh=db.execute("SELECT COUNT(*) FROM parts WHERE dataset='CadQuarry' AND stl IS NULL").fetchone()[0],
        cross_split_raw_duplicate_groups=len(duplicates),quick_check=db.execute('PRAGMA quick_check').fetchone()[0],
        group_policy='Canonical dimension parameters exclude published rotation; CadQuarry quantized geometry signature; author split retained in metadata',
        scope='Raw original data; source programs stored but never executed; derived measurements/targets require separate audit')
    (root/'intake.json').write_text(json.dumps(summary,indent=2),encoding='utf8');db.close();print(json.dumps(summary),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);main(p.parse_args().root)
