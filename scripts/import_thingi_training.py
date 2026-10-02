"""Import author-published Thingi10K geometry, per-item rights and quality."""
import argparse,hashlib,io,json,sqlite3,tarfile,time
from pathlib import Path
import numpy as np
import pandas as pd

ALLOWED={'Creative Commons - Attribution','Creative Commons - Public Domain Dedication','Public Domain','BSD License'}
def build(root):
    destination=root/'thingi.sqlite'
    if destination.exists():raise FileExistsError(destination)
    db=sqlite3.connect(destination);db.executescript('CREATE TABLE parts(id INTEGER PRIMARY KEY,thing_id INTEGER,split TEXT,license TEXT,metadata TEXT,quality TEXT,npz BLOB,sha256 TEXT,training_ready INTEGER,reason TEXT);CREATE INDEX part_split ON parts(split);')
    input_rows=pd.read_csv(root/'input_summary.csv').set_index('ID').to_dict('index')
    contextual=pd.read_csv(root/'contextual_data.csv').set_index('Thing ID').to_dict('index')
    geometry=pd.read_csv(root/'geometry_data.csv').set_index('file_id').to_dict('index')
    started=time.monotonic();counts={};count=0
    with tarfile.open(root/'archives/Thingi10K_npz-v1.5.0.tar.gz','r|gz') as tar:
        for member in tar:
            if not member.isfile() or not member.name.endswith('.npz'):continue
            identifier=int(Path(member.name).stem);raw=tar.extractfile(member).read();info=input_rows.get(identifier,{})
            thing=int(info.get('Thing ID',-1));license=info.get('License','unknown_license');quality=geometry.get(identifier,{})
            ready=False;reason='rights or metadata not eligible'
            meta=dict(info,**{k:v for k,v in contextual.get(thing,{}).items() if k not in info})
            if license in ALLOWED and quality:
                good=(quality['solid']==1 and quality['num_self_intersections']==0 and quality['num_connected_components']==1
                      and quality['oriented']==1 and quality['num_geometrical_degenerated_faces']==0
                      and quality['num_boundary_edges']==0 and 4<=quality['num_faces']<=10000)
                if good:
                    try:
                        with np.load(io.BytesIO(raw),allow_pickle=False) as z:
                            v=z['vertices'];f=z['facets']
                            ready=bool(v.ndim==2 and v.shape[1]==3 and f.ndim==2 and f.shape[1]==3 and np.isfinite(v).all()
                                       and np.issubdtype(f.dtype,np.integer) and f.min()>=0 and f.max()<len(v) and np.max(np.ptp(v,axis=0))>0)
                        reason='eligible' if ready else 'invalid finite/index geometry'
                    except Exception as e:reason=type(e).__name__
                else:reason='quality or 10000-face CPU training budget'
            bucket=int(hashlib.sha256(str(thing).encode()).hexdigest()[:8],16)%100
            split='train' if bucket<70 else 'validation' if bucket<85 else 'test'
            db.execute('INSERT INTO parts VALUES (?,?,?,?,?,?,?,?,?,?)',(identifier,thing,split,license,json.dumps(meta),json.dumps(quality),raw,hashlib.sha256(raw).hexdigest(),int(ready),reason))
            count+=1;counts[reason]=counts.get(reason,0)+1
            if count%128==0:db.commit();print(f'Imported {count} meshes; {time.monotonic()-started:.0f}s',flush=True)
    db.commit(); summary=dict(imported=count,expected=10000,criteria=counts,
        eligible_splits=dict(db.execute('SELECT split,count(*) FROM parts WHERE training_ready=1 GROUP BY split')),
        raw_duplicate_groups=db.execute('SELECT count(*) FROM (SELECT sha256 FROM parts GROUP BY sha256 HAVING count(*)>1)').fetchone()[0],
        seconds=time.monotonic()-started,license_policy=sorted(ALLOWED),geometry_units='raw unspecified; normalized only for dimensionless orientation learning')
    # Exact duplicate meshes cannot occur in different training partitions.
    duplicate_cross=db.execute('SELECT sha256 FROM parts GROUP BY sha256 HAVING count(DISTINCT split)>1 AND count(*)>1').fetchall()
    for (sha,) in duplicate_cross:db.execute('UPDATE parts SET training_ready=0,reason="cross-split exact duplicate" WHERE sha256=?',(sha,))
    db.commit();summary['cross_split_duplicate_groups_quarantined']=len(duplicate_cross)
    summary['eligible_splits']=dict(db.execute('SELECT split,count(*) FROM parts WHERE training_ready=1 GROUP BY split'));db.close()
    (root/'thingi-intake.json').write_text(json.dumps(summary,indent=2),encoding='utf8');print(json.dumps(summary),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);a=p.parse_args();build(a.root)
