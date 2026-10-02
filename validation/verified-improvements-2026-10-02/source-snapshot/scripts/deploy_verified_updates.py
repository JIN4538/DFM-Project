"""Hash-verified desktop update with recoverable backups, no environment replacement."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
from datetime import datetime

ROOT=Path(__file__).resolve().parents[1]


def deploy(target, output):
    target=target.resolve(); output=output.resolve()
    if target==ROOT or not (target/'app.py').is_file() or not (target/'.venv/Scripts/python.exe').is_file():
        raise ValueError('Existing separate app installation required')
    if ROOT not in output.parents or output.exists():
        raise ValueError('New repository output required')
    output.parent.mkdir(parents=True,exist_ok=True)
    backup=target/'backups'/('verified-improvements-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    files=[ROOT/'app.py',ROOT/'AGENTS.md',ROOT/'README.md']
    for folder in ('amdfm','dfm','src','data/models','data/conditions'):
        files.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in ('.py','.json'))
    files.extend((ROOT/'docs').rglob('*.md'))
    # Deployment has 155 demo fixtures; the repository's research archive is
    # deliberately separate. Do not transplant its larger inventory test.
    files.extend(p for p in (ROOT/'tests_v3').glob('*.py') if p.name not in ('test_packaged_geometry.py','test_verified_edit_study.py'))
    before_models={p.relative_to(target).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (target/'data/models').rglob('*.json')}
    rows=[]
    for source in sorted(set(files)):
        name=source.relative_to(ROOT); destination=target/name; data=source.read_bytes()
        previous=destination.read_bytes() if destination.is_file() else None
        changed=previous!=data
        if changed:
            if previous is not None:
                old=backup/name;old.parent.mkdir(parents=True,exist_ok=True);old.write_bytes(previous)
            destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(data)
        sha=hashlib.sha256(data).hexdigest()
        if hashlib.sha256(destination.read_bytes()).hexdigest()!=sha:raise ValueError('Deployment byte mismatch: '+str(name))
        rows.append(dict(path=name.as_posix(),sha256=sha,changed=changed,
            prior_sha256=hashlib.sha256(previous).hexdigest() if previous is not None else None))
    result=dict(target=str(target),backup=str(backup),files=rows,verified=True,
        changed_files=sum(r['changed'] for r in rows),existing_models_sha256=before_models,
        previous_models_unchanged=all((target/name).is_file() and hashlib.sha256((target/name).read_bytes()).hexdigest()==sha for name,sha in before_models.items()),
        research_geometry_deployed=False)
    output.write_bytes((json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode('utf8'))
    print(json.dumps({k:v for k,v in result.items() if k not in ('files','existing_models_sha256')},ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('target',type=Path);p.add_argument('output',type=Path);a=p.parse_args();deploy(a.target,a.output)
