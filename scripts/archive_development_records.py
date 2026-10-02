"""Publish development receipts without copying environments or external databases.

Original study files stay untouched. Duplicate bytes point to their repository
copy; excluded working data retain an explicit reason in the archive manifest.
"""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT.parent / 'study'
DEST = ROOT / 'validation/workspace-archive-2026-10-01'
DATES = ('2026-09-26', '2026-09-28', '2026-09-29', '2026-09-30')
SECRET = re.compile(rb'(?:sk-(?:proj-)?[A-Za-z0-9_-]{32,}|gh[pousr]_[A-Za-z0-9]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----)')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    DEST.mkdir(parents=True, exist_ok=True)
    known = {}
    pending = subprocess.check_output(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'], cwd=ROOT).decode('utf8')
    for name in sorted(set(pending.split('\0')) - {''}):
        path = ROOT / name
        if path.is_file() and DEST not in path.parents:
            known.setdefault(digest(path.read_bytes()), name)
    rows = []
    pruned = []
    for stage in sorted(p for p in STUDY.iterdir() if p.is_dir() and p.name.endswith(DATES)):
        for base, dirs, files in os.walk(stage):
            for folder in list(dirs):
                if any(x in folder.lower() for x in ('backup', 'desktop-before', 'repo-models-before', '__pycache__')) or folder in ('archives', 'mfcad'):
                    pruned.append({'path': (Path(base) / folder).relative_to(STUDY).as_posix(), 'reason': 'Local backup, source archive or duplicate external input; original retained'})
                    dirs.remove(folder)
            for name in sorted(files):
                source = Path(base) / name
                rel = source.relative_to(STUDY)
                within = source.relative_to(stage)
                row = {'study_file': rel.as_posix(), 'bytes': source.stat().st_size}
                suffix = source.suffix.lower()
                if suffix in ('.sqlite', '.db', '.zip', '.rar', '.npy', '.npz'):
                    reason = 'External database, source package or rebuildable training array; use catalog and acquisition/training scripts'
                elif 'server' in name.lower() or 'pid' in name.lower():
                    reason = 'Live process state; not a portable development artifact'
                elif any(p in ('train', 'test', 'validation', 'arrays') for p in within.parts[:-1]):
                    reason = 'Rebuildable per-record training/query cache; evaluation summaries retained'
                elif suffix in ('.py', '.ps1', '.bat', '.cmd', '.step', '.stp', '.brep', '.png', '.jpg', '.jpeg', '.svg', '.xml', '.log', '.md', '.docx'):
                    reason = None
                elif suffix in ('.json', '.txt', '.csv', '.html') and len(within.parts) <= 2:
                    reason = None
                elif suffix == '.pdf' and 'manual' in within.parts:
                    reason = None
                else:
                    reason = 'Intermediate source capture or detailed cache; catalog/provenance and selected summaries retained'
                if reason:
                    row.update(status='local_only', reason=reason)
                    rows.append(row)
                    continue
                data = source.read_bytes()
                if SECRET.search(data):
                    raise ValueError('Credential-like content requires inspection: ' + rel.as_posix())
                sha = digest(data)
                row['sha256'] = sha
                if sha in known:
                    row.update(status='existing_repository_copy', repository_file=known[sha])
                else:
                    target = DEST / 'files' / rel
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists() and target.read_bytes() != data:
                        raise ValueError('Preserve previous archive bytes: ' + str(target))
                    target.write_bytes(data)
                    repo_name = target.relative_to(ROOT).as_posix()
                    known[sha] = repo_name
                    row.update(status='archived', repository_file=repo_name)
                rows.append(row)
    result = {'schema': 'dfm-development-publication-1', 'study_root': str(STUDY),
              'policy': 'Originals untouched; exact-byte copies or SHA references; external DB/environment/cache kept local',
              'pruned_directories': pruned, 'files': rows}
    (DEST / 'manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    update_geometry_inventory(rows)
    summary = {s: sum(r['status'] == s for r in rows) for s in ('archived', 'existing_repository_copy', 'local_only')}
    summary['archived_bytes'] = sum(r['bytes'] for r in rows if r['status'] == 'archived')
    print(json.dumps(summary, ensure_ascii=False))


def update_geometry_inventory(rows):
    """Register archived STEP bytes in the same all-repository geometry audit."""
    inventory_path = ROOT / 'examples/geometry_manifest.json'
    inventory = json.loads(inventory_path.read_text(encoding='utf8'))
    existing = {r['path']: r for r in inventory['files']}
    formats = {'.step', '.stp', '.stl', '.3mf', '.brep', '.iges', '.igs', '.obj', '.ply'}
    for row in rows:
        if row['status'] != 'archived' or Path(row['repository_file']).suffix.lower() not in formats:
            continue
        name = row['repository_file']
        record = {'path': name, 'group': 'existing/workspace-research-archive',
                  'format': Path(name).suffix.lower().lstrip('.'), 'bytes': row['bytes'],
                  'sha256': row['sha256'], 'study_source': row['study_file']}
        if name in existing and existing[name] != record:
            raise ValueError('Preserve existing geometry inventory: ' + name)
        existing[name] = record
    records = sorted(existing.values(), key=lambda r: r['path'])
    groups = {}
    for record in records:
        groups[record['group']] = groups.get(record['group'], 0) + 1
    inventory.update(files=records, geometry_file_count=len(records),
                     unique_sha256_count=len({r['sha256'] for r in records}),
                     total_bytes=sum(r['bytes'] for r in records), groups=groups)
    inventory['workspace_archive_note'] = '2026-10-01: independently archived research STEP and edited CAD pairs are indexed too; they are not additional app picker demos or universally unique physical designs.'
    inventory_path.write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding='utf8')


if __name__ == '__main__':
    main()
