"""Copy this task's runtime/data additions; retain and hash-check replaced files."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

root = Path('C:/Users/JIN/Documents/ChatGPT/DFM/DFM-Project').resolve()
target = Path('C:/Users/JIN/Desktop/AM-DFM_v3_0').resolve()
work = Path(__file__).resolve().parent
stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
backup = work / ('desktop-backup-' + stamp)

names = ['app.py', 'amdfm/analysis.py', 'amdfm/presentation.py', 'amdfm/profiles.py',
         'dfm/machining.py', 'dfm/machining_view.py', 'dfm/conditions.py', 'dfm/conditions_view.py',
         'scripts/audit_conditions.py', 'scripts/index_condition_literature.py',
         'scripts/audit_random_models.py', 'scripts/refresh_corpus_reports.py',
         'tests_v3/test_conditions.py', 'tests_v3/test_conditions_integration.py', 'tests_v3/test_conditions_ui.py',
         'docs/CONDITION_LIBRARY.md', 'docs/project-knowledge/README.md',
         'docs/project-knowledge/CONDITION_DATABASE_2026-09-28.md']
for folder in ('data/conditions', 'docs/research/conditions-2026-09-28'):
    names.extend(p.relative_to(root).as_posix() for p in (root / folder).rglob('*') if p.is_file())
names = sorted(set(names))
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
old_manifest = json.loads((target/'release_manifest.json').read_text(encoding='utf-8'))
old_files = {f['path']: f for f in old_manifest['files']}
plan = []
for name in names:
    src, dst = (root/name).resolve(), (target/name).resolve()
    assert src.is_relative_to(root) and dst.is_relative_to(target)
    assert src.is_file()
    old_sha = sha(dst) if dst.exists() else None
    new_sha = sha(src)
    if old_sha and old_sha != new_sha and old_files.get(name, {}).get('sha256') != old_sha:
        raise RuntimeError('Unexpected local edit, inspect before replacing: ' + str(dst))
    plan.append({'path': name, 'before_sha256': old_sha, 'sha256': new_sha,
                 'bytes': src.stat().st_size,
                 'operation': 'unchanged' if old_sha == new_sha else 'replace' if old_sha else 'add'})

backup.mkdir(parents=True, exist_ok=False)
shutil.copy2(target/'release_manifest.json', backup/'release_manifest.json')
for item in plan:
    src, dst = root/item['path'], target/item['path']
    if item['operation'] == 'replace':
        saved = backup/item['path']
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(dst, saved)
        assert sha(saved) == item['before_sha256']
    if item['operation'] != 'unchanged':
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    assert sha(dst) == item['sha256']
    old_files[item['path']] = item

record = {'timestamp_utc': datetime.now(timezone.utc).isoformat(), 'source': str(root), 'destination': str(target),
          'backup': str(backup), 'scope': 'Conditions database and engine/UI integration; no deletion; existing environment, geometries and user outputs preserved',
          'files': plan, 'verified': True}
out = work/('desktop-sync-' + stamp + '.json')
out.write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
updated = {**old_manifest, 'files': [old_files[k] for k in sorted(old_files)],
           'conditions_update': {'timestamp_utc': record['timestamp_utc'], 'base_git_commit': old_manifest.get('git_commit'),
                                 'working_tree_changes': True, 'backup': str(backup), 'manifest': str(out)}}
(target/'release_manifest.json').write_text(json.dumps(updated, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print(json.dumps({'copied_files': len(plan), 'added': sum(p['operation']=='add' for p in plan),
                  'replaced': sum(p['operation']=='replace' for p in plan), 'verified': True,
                  'backup': str(backup), 'manifest': str(out)}, ensure_ascii=False, indent=2))
