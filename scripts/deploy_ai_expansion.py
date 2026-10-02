"""Back up and byte-verify the existing desktop runtime, without deleting files."""
import hashlib,json,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    dest=Path.home()/'Desktop/AM-DFM_v3_0'
    if not (dest/'app.py').is_file():raise ValueError('Expected existing desktop installation')
    run=ROOT.parent/'study/ai-expansion-2026-09-30';backup=run/'desktop-before-expansion';backup.mkdir(exist_ok=True)
    files=[ROOT/'app.py',ROOT/'requirements-training.txt']
    for folder in ('amdfm','dfm','scripts','tests_v3'):
        files.extend(p for p in (ROOT/folder).rglob('*.py') if '__pycache__' not in p.parts)
    for folder in ('data','examples/public_demo','examples/learning_validation'):
        files.extend(p for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in ('.json','.txt','.md','.step','.stp'))
    paths=[ROOT/'docs/project-knowledge/AI_EXPANSION_2026-09-30.md',ROOT/'examples/geometry_manifest.json',ROOT/'examples/README.md']
    inventory=json.loads((ROOT/'examples/geometry_manifest.json').read_text(encoding='utf8'))
    for row in inventory['files']:
        path=(ROOT/row['path']).resolve()
        if ROOT not in path.parents:raise ValueError('Inventory path outside repository')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('Inventory geometry changed')
        files.append(path)
    files=list(dict.fromkeys(files))
    files.extend(p for p in paths if p.is_file());records=[]
    for source in files:
        relative=source.relative_to(ROOT);target=dest/relative;sha=hashlib.sha256(source.read_bytes()).hexdigest()
        if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest()!=sha:
            saved=backup/relative;saved.parent.mkdir(parents=True,exist_ok=True)
            if not saved.exists():shutil.copy2(target,saved)
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        if hashlib.sha256(target.read_bytes()).hexdigest()!=sha:raise ValueError('Desktop copy mismatch')
        records.append(dict(file=str(relative),sha256=sha))
    (run/'desktop-deployment.json').write_text(json.dumps(dict(destination=str(dest),backup=str(backup),verified_files=len(records),files=records),indent=2))
    print(json.dumps(dict(verified_files=len(records),destination=str(dest))))
if __name__=='__main__':main()
