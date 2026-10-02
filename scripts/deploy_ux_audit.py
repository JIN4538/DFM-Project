"""Deploy the audited UX delta while retaining the prior desktop files."""
from pathlib import Path
import hashlib
import json
import shutil

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    desktop = Path.home() / 'Desktop/AM-DFM_v3_0'
    if not (desktop / 'app.py').is_file():
        raise ValueError('Expected the existing desktop application')
    previous = json.loads((ROOT.parent / 'study/ai-full-corpus-2026-09-30/desktop-deployment.json').read_text(encoding='utf8'))
    changed = []
    for row in previous['files']:
        relative = Path(row['file'])
        source = (ROOT / relative).resolve()
        target = (desktop / relative).resolve()
        if ROOT not in source.parents or desktop not in target.parents:
            raise ValueError('Path outside deployment roots')
        if sha(source) != row['sha256']:
            if target.exists() and sha(target) not in (row['sha256'], sha(source)):
                raise ValueError(f'Desktop has a separate edit: {relative}')
            changed.append(relative)
    changed.extend(Path(p) for p in (
        'tests_v3/test_novice_workflow.py',
        'tests_v3/test_am_novice_detail.py',
        'tests_v3/test_cnc_beginner_workflow.py',
        'docs/project-knowledge/AI_CAPABILITY_AUDIT_2026-09-30.md',
        'docs/project-knowledge/USER_PRACTICALITY_2026-09-30.md',
    ))
    # A UX deployment must not silently install new learned weights.
    for row in json.loads((ROOT / 'data/training/full-corpus-catalog.json').read_text(encoding='utf8'))['models']:
        if sha(ROOT / row['file']) != row['sha256'] or sha(desktop / row['file']) != row['sha256']:
            raise ValueError('Model drift: abort UX deployment')
    run = ROOT.parent / 'study/ux-audit-2026-09-30'
    backup = run / 'desktop-before'
    backup.mkdir(parents=True, exist_ok=True)
    records = []
    for relative in dict.fromkeys(changed):
        source, target, saved = ROOT / relative, desktop / relative, backup / relative
        before = sha(target) if target.exists() else None
        if before is not None and before != sha(source) and not saved.exists():
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, saved)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if sha(target) != sha(source):
            raise ValueError(f'Copy verification failed: {relative}')
        records.append(dict(file=relative.as_posix(), before_sha256=before, sha256=sha(target)))
    result = dict(destination=str(desktop), backup=str(backup), verified_files=len(records), files=records)
    output = run / 'desktop-deployment.json'
    # Keep the first deployment record when documentation is finalized later.
    if output.exists():
        output = run / 'desktop-deployment-final.json'
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding='utf8')
    print(json.dumps(dict(verified_files=len(records), manifest=str(output)), ensure_ascii=False))


if __name__ == '__main__':
    main()
