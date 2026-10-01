"""Checked allowlist copy with backup; never copy credentials or delete files."""
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
names = [
    'app.py','dfm/advisor.py','dfm/advisor_view.py','dfm/ai_client.py','dfm/machining_view.py',
    'amdfm/recommendation.py','amdfm/action_view.py','amdfm/decision_view.py','amdfm/workflow.py','amdfm/presentation.py',
    'tests_v3/test_advisor.py','tests_v3/test_ai_client.py','tests_v3/test_advisor_ui.py',
    'tests_v3/test_app.py','tests_v3/test_navigation_ux.py','tests_v3/test_orientation_recommendation.py',
    'docs/AI_ADVISOR_GUIDE.md','docs/project-knowledge/README.md',
    'docs/project-knowledge/AI_ADVISOR_IMPLEMENTATION_2026-09-28.md',
]
optional = ['scripts/evaluate_ai_intent.py','validation/ai-advisor-2026-09-28/intent-cases.json',
            'tests_v3/test_advisor_focus.py']
names += [name for name in optional if (root/name).is_file()]
validation_names = ['README.md', 'regression.txt', 'regression.xml', 'legacy.txt', 'legacy.xml',
                    'ai-ui.txt', 'ai-ui.xml', 'final-related.txt', 'final-related.xml',
                    'focus.log', 'focus.xml', 'desktop-final.txt', 'desktop-final.xml',
                    'intent-fixtures-offline.json', 'browser-action-card.png',
                    'browser-final-action-card.png', 'browser-final-action-card-verified.png']
names += ['validation/ai-advisor-2026-09-28/' + name for name in validation_names
          if (root/'validation/ai-advisor-2026-09-28'/name).is_file()]
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
manifest = target/'release_manifest.json'
old_manifest = json.loads(manifest.read_text(encoding='utf-8'))
old_files = {f['path']: f for f in old_manifest['files']}
plan = []
for name in sorted(set(names)):
    src,dst=(root/name).resolve(),(target/name).resolve()
    assert src.is_relative_to(root) and dst.is_relative_to(target) and src.is_file()
    before=sha(dst) if dst.exists() else None
    after=sha(src)
    if before and before!=after and old_files.get(name,{}).get('sha256')!=before:
        raise RuntimeError('Unexpected user edit, inspect before replacing: '+str(dst))
    plan.append(dict(path=name,before_sha256=before,sha256=after,bytes=src.stat().st_size,
                     operation='unchanged' if before==after else 'replace' if before else 'add'))
backup.mkdir(parents=True,exist_ok=False)
shutil.copy2(manifest,backup/'release_manifest.json')
for item in plan:
    src,dst=root/item['path'],target/item['path']
    if item['operation']=='replace':
        saved=backup/item['path']; saved.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(dst,saved); assert sha(saved)==item['before_sha256']
    if item['operation']!='unchanged':
        dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
    assert sha(dst)==item['sha256']
    old_files[item['path']]=item
record=dict(timestamp_utc=datetime.now(timezone.utc).isoformat(),source=str(root),destination=str(target),
            backup=str(backup),scope='AI intent integration and novice decision UI; no credentials or deletion',files=plan,verified=True)
out=work/('desktop-sync-'+stamp+'.json')
out.write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
updated={**old_manifest,'files':[old_files[k] for k in sorted(old_files)],
         'ai_advisor_update':dict(timestamp_utc=record['timestamp_utc'],working_tree_changes=True,backup=str(backup),manifest=str(out))}
manifest.write_text(json.dumps(updated,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(dict(added=sum(p['operation']=='add' for p in plan),replaced=sum(p['operation']=='replace' for p in plan),
                     verified=True,backup=str(backup),manifest=str(out)),ensure_ascii=False,indent=2))
