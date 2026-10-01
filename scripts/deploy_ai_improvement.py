"""Deploy only the AI improvement delta against verified desktop baselines."""
from pathlib import Path
import hashlib
import json
import shutil

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT.parent / 'study/ai-improvement-2026-09-30'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    desktop = Path.home() / 'Desktop/AM-DFM_v3_0'
    if not (desktop/'app.py').is_file():
        raise ValueError('Expected existing desktop runtime')
    baseline = {}
    for relative in ('study/ai-full-corpus-2026-09-30/desktop-deployment.json',
                     'study/ux-audit-2026-09-30/desktop-deployment-final.json'):
        for row in json.loads((ROOT.parent/relative).read_text(encoding='utf8'))['files']:
            baseline[Path(row['file']).as_posix()] = row['sha256']
    for manifest in sorted(RUN.glob('desktop-deployment-*.json')):
        for row in json.loads(manifest.read_text(encoding='utf8'))['files']:
            baseline[Path(row['file']).as_posix()] = row['sha256']
    changed = []
    for name, expected in baseline.items():
        source = ROOT/name
        if source.is_file() and sha(source) != expected:
            changed.append(name)
    for folder in ('dfm', 'amdfm', 'scripts', 'tests_v3'):
        changed.extend(p.relative_to(ROOT).as_posix() for p in (ROOT/folder).rglob('*.py')
                       if '__pycache__' not in p.parts and p.relative_to(ROOT).as_posix() not in baseline)
    changed.append('docs/project-knowledge/AI_IMPROVEMENT_2026-09-30.md')
    # These trials did not fit new global weights. Installing a changed weight
    # under an old identity is prohibited, rather than rewriting its manifest.
    for row in json.loads((ROOT/'data/training/full-corpus-catalog.json').read_text(encoding='utf8'))['models']:
        if sha(ROOT/row['file']) != row['sha256'] or sha(desktop/row['file']) != row['sha256']:
            raise ValueError('Unexpected learned-weight drift')
    backup = RUN/'desktop-before'
    backup.mkdir(parents=True, exist_ok=True)
    # Validate every existing destination before the first file is copied.
    for name in dict.fromkeys(changed):
        source, target = (ROOT/name).resolve(), (desktop/name).resolve()
        if ROOT not in source.parents or desktop not in target.parents or not source.is_file():
            raise ValueError(f'Invalid deployment source: {name}')
        if target.exists() and sha(target) not in (baseline.get(name), sha(source)):
            raise ValueError(f'Desktop has a separate edit: {name}')
    records = []
    for name in dict.fromkeys(changed):
        source, target, saved = ROOT/name, desktop/name, backup/name
        before = sha(target) if target.exists() else None
        if before is not None and before != sha(source) and not saved.exists():
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, saved)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        if sha(target) != sha(source):
            raise ValueError(f'Copied file checksum mismatch: {name}')
        records.append(dict(file=name, before_sha256=before, sha256=sha(target)))
    number = 1
    while (RUN/f'desktop-deployment-{number:02d}.json').exists():
        number += 1
    output = RUN/f'desktop-deployment-{number:02d}.json'
    output.write_text(json.dumps(dict(destination=str(desktop), backup=str(backup), files=records,
                                      verified_files=len(records), global_weight_changes=0), indent=2), encoding='utf8')
    print(json.dumps(dict(verified_files=len(records), manifest=str(output))))


if __name__ == '__main__':
    main()
