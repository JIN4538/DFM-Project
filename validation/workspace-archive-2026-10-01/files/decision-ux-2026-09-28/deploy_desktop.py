"""Back up and deploy the verified decision workflow without deleting user files."""
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
names = ['app.py', 'amdfm/analysis.py', 'amdfm/orientation.py', 'amdfm/recommendation.py',
         'amdfm/assessment.py', 'amdfm/action_view.py', 'amdfm/decision_view.py',
         'amdfm/detail_summary.py', 'amdfm/workflow.py', 'amdfm/presentation.py',
         'dfm/machining_view.py', 'tests_v3/test_app.py', 'tests_v3/test_navigation_ux.py',
         'tests_v3/test_visual_accessibility.py', 'tests_v3/test_workflow_ux.py',
         'tests_v3/test_assessment.py', 'tests_v3/test_orientation_recommendation.py',
         'tests_v3/test_decision_workflow.py', 'tests_v3/test_machining_decisions_ui.py',
         'docs/USER_DECISION_WORKFLOW.md', 'docs/project-knowledge/README.md',
         'docs/project-knowledge/USER_DECISION_RESEARCH_2026-09-28.md',
         'docs/project-knowledge/USER_DECISION_IMPLEMENTATION_2026-09-28.md']
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
manifest = target/'release_manifest.json'
old_manifest = json.loads(manifest.read_text(encoding='utf-8'))
old_files = {f['path']: f for f in old_manifest['files']}
plan = []
for name in sorted(set(names)):
    src, dst = (root/name).resolve(), (target/name).resolve()
    assert src.is_relative_to(root) and dst.is_relative_to(target) and src.is_file()
    old_sha = sha(dst) if dst.exists() else None
    new_sha = sha(src)
    if old_sha and old_sha != new_sha and old_files.get(name, {}).get('sha256') != old_sha:
        raise RuntimeError('Unexpected local edit, inspect before replacing: ' + str(dst))
    plan.append(dict(path=name,before_sha256=old_sha,sha256=new_sha,bytes=src.stat().st_size,
                     operation='unchanged' if old_sha==new_sha else 'replace' if old_sha else 'add'))
backup.mkdir(parents=True,exist_ok=False)
shutil.copy2(manifest,backup/'release_manifest.json')
for item in plan:
    src,dst=root/item['path'],target/item['path']
    if item['operation']=='replace':
        saved=backup/item['path']
        saved.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(dst,saved)
        assert sha(saved)==item['before_sha256']
    if item['operation']!='unchanged':
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(src,dst)
    assert sha(dst)==item['sha256']
    old_files[item['path']]=item
record=dict(timestamp_utc=datetime.now(timezone.utc).isoformat(),source=str(root),destination=str(target),
            backup=str(backup),scope='Decision workflow UI, stable orientation recommendation, bounded automatic checks; no deletion',
            files=plan,verified=True)
out=work/('desktop-sync-'+stamp+'.json')
out.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
updated={**old_manifest,'files':[old_files[k] for k in sorted(old_files)],
         'decision_workflow_update':dict(timestamp_utc=record['timestamp_utc'],working_tree_changes=True,
                                         backup=str(backup),manifest=str(out))}
manifest.write_text(json.dumps(updated,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(dict(copied_files=len(plan),added=sum(p['operation']=='add' for p in plan),
                     replaced=sum(p['operation']=='replace' for p in plan),verified=True,
                     backup=str(backup),manifest=str(out)),ensure_ascii=False,indent=2))
