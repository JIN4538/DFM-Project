"""Use the existing verified deployment with a separate full-corpus backup."""
import json,hashlib,shutil
from pathlib import Path
from deploy_ai_expansion import ROOT

def main():
    dest=Path.home()/'Desktop/AM-DFM_v3_0'
    if not (dest/'app.py').is_file():raise ValueError('Expected existing desktop runtime')
    run=ROOT.parent/'study/ai-full-corpus-2026-09-30';backup=run/'desktop-before-full';backup.mkdir(exist_ok=True)
    files=[ROOT/'app.py',ROOT/'requirements-training.txt',ROOT/'examples/README.md',ROOT/'examples/geometry_manifest.json']
    for folder in ('amdfm','dfm','scripts','tests_v3'):
        files.extend(p for p in (ROOT/folder).rglob('*.py') if '__pycache__' not in p.parts)
    for folder in ('data','examples/public_demo','examples/learning_validation'):
        files.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in ('.json','.txt','.md','.step','.stp'))
    for row in json.loads((ROOT/'examples/geometry_manifest.json').read_text(encoding='utf8'))['files']:
        path=(ROOT/row['path']).resolve()
        if ROOT not in path.parents or hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:
            raise ValueError('Geometry inventory mismatch')
        files.append(path)
    files.append(ROOT/'docs/project-knowledge/AI_FULL_CORPUS_2026-09-30.md')
    records=[]
    for source in dict.fromkeys(files):
        relative=source.relative_to(ROOT);target=dest/relative;sha=hashlib.sha256(source.read_bytes()).hexdigest()
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()!=sha:
            saved=backup/relative;saved.parent.mkdir(parents=True,exist_ok=True)
            if not saved.exists():shutil.copy2(target,saved)
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        if hashlib.sha256(target.read_bytes()).hexdigest()!=sha:raise ValueError('Desktop copy mismatch')
        records.append(dict(file=str(relative),sha256=sha))
    result=dict(destination=str(dest),backup=str(backup),verified_files=len(records),files=records)
    (run/'desktop-deployment.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps(dict(verified_files=len(records),destination=str(dest))))

if __name__=='__main__':main()
