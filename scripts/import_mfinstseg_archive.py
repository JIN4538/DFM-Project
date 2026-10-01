"""Preserve the full author-linked MFInstSeg archive in a local staging DB.

Face ordinal correspondence across OCCT versions has NOT been certified.
No rows are training-ready; do not use this database as verified labels.
"""
import argparse, hashlib, json, sqlite3, time, zipfile
from pathlib import Path

def main(root, partitions):
    started=time.monotonic(); archive=root/'archives/MFInstSeg-data2.zip'
    path=root/'mfinstseg-complete.sqlite'
    if path.exists():raise ValueError('Preserve existing DB; choose a new run directory')
    digest=hashlib.sha256()
    with archive.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):digest.update(chunk)
    if digest.hexdigest()!='5b3bbb5c9242eb6199a5dafe1d758aa12eef9d08ef51a3f80b378b912f10c735':
        raise ValueError('Author archive checksum mismatch')
    assignments={}; overlaps=set(); duplicate_rows=0
    for split,filename in [('train','mfinstseg_train.txt'),('val','mfinstseg_val.txt'),('test','mfinstseg_test.txt')]:
        seen=set()
        for identifier in (partitions/filename).read_text().splitlines():
            identifier=identifier.strip()
            if not identifier:continue
            if identifier in seen:duplicate_rows+=1
            seen.add(identifier)
            if identifier in assignments and assignments[identifier]!=split:overlaps.add(identifier)
            assignments[identifier]=split
    db=sqlite3.connect(path)
    db.executescript('''CREATE TABLE sources(id TEXT PRIMARY KEY,metadata TEXT);
    CREATE TABLE parts(id TEXT PRIMARY KEY,split TEXT,step BLOB,step_sha256 TEXT,
    labels BLOB,label_sha256 TEXT,face_labels INTEGER,training_ready INTEGER,reason TEXT);
    CREATE TABLE files(path TEXT PRIMARY KEY,bytes INTEGER,crc INTEGER);''')
    metadata=dict(dataset='MFInstSeg',author_record='https://aistudio.baidu.com/datasetdetail/211864?lang=en',
      author_mirror='https://github.com/whjdark/AAGNet',declared_license='CC0 in author dataset page metadata',
      license_scope='archive contains no license text; record declaration preserved, redistribution not enabled',
      archive_sha256='5b3bbb5c9242eb6199a5dafe1d758aa12eef9d08ef51a3f80b378b912f10c735',
      label_mapping='pythonocc/occwl TopologyExplorer ordinal; correspondence to OCP 7.9 unverified',training_ready=False)
    db.execute('INSERT INTO sources VALUES (?,?)',('mfinstseg',json.dumps(metadata)))
    counts={}; labels_count=0; mismatches=[]
    with zipfile.ZipFile(archive) as z:
        for f in z.infolist():
            db.execute('INSERT INTO files VALUES (?,?,?)',(f.filename,f.file_size,f.CRC))
        steps=sorted(n for n in z.namelist() if n.startswith('steps/') and n.endswith('.step'))
        for i,name in enumerate(steps):
            identifier=Path(name).stem; raw=z.read(name); label=z.read(f'labels/{identifier}.json')
            rows=json.loads(label); matching=[r[1] for r in rows if r[0]==identifier]
            mismatched=len(matching)!=1
            if mismatched:
                mismatches.append(dict(id=identifier,label_ids=[r[0] for r in rows]))
                matching=[rows[0][1]]
            seg=matching[0]['seg']; n=len(seg)
            if set(seg)!=set(map(str,range(n))) or any(type(v)!=int or not 0<=v<=24 for v in seg.values()):raise ValueError('Invalid semantic labels')
            inst=matching[0]['inst']; bottom=matching[0]['bottom']
            if len(inst)!=n or any(len(r)!=n for r in inst) or len(bottom)!=n:raise ValueError('Invalid instance/bottom dimensions')
            split='quarantine' if identifier in overlaps or mismatched else assignments.get(identifier,'unassigned')
            reason='Unverified OCCT face ordinal correspondence; full semantic vocabulary audit pending'
            if identifier in overlaps:reason+='; published cross-split duplicate'
            if mismatched:reason+='; original label identifier mismatch'
            db.execute('INSERT INTO parts VALUES (?,?,?,?,?,?,?,?,?)',(identifier,split,raw,hashlib.sha256(raw).hexdigest(),
                label,hashlib.sha256(label).hexdigest(),n,0,reason))
            counts[split]=counts.get(split,0)+1; labels_count+=n
            if (i+1)%1000==0:db.commit();print(json.dumps(dict(imported=i+1,seconds=time.monotonic()-started)),flush=True)
    db.execute('CREATE INDEX step_hash ON parts(step_sha256)');db.commit()
    duplicates=list(db.execute('SELECT step_sha256,COUNT(*) FROM parts GROUP BY step_sha256 HAVING COUNT(*)>1'))
    cross=db.execute('SELECT step_sha256 FROM parts GROUP BY step_sha256 HAVING COUNT(DISTINCT split)>1').fetchall()
    for (sha,) in cross:
        db.execute("UPDATE parts SET split='quarantine',reason=reason||'; duplicate STEP bytes across split' WHERE step_sha256=?",(sha,))
    db.commit();counts=dict(db.execute('SELECT split,COUNT(*) FROM parts GROUP BY split').fetchall())
    summary=dict(imported=len(steps),face_labels=labels_count,splits=counts,training_ready=0,
      published_overlap_ids=sorted(overlaps),duplicate_partition_rows=duplicate_rows,duplicate_step_groups=len(duplicates),
      label_identifier_mismatches=mismatches,
      raw_duplicate_cross_split_groups=len(cross),
      seconds=time.monotonic()-started,source=metadata,db=str(path.resolve()))
    (root/'mfinstseg-intake.json').write_text(json.dumps(summary,indent=2),encoding='utf8');db.close();print(json.dumps(summary),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--partitions',type=Path,required=True)
    args=p.parse_args();main(args.root,args.partitions)
