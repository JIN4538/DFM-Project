"""Deploy the next verified AI stage; preserve desktop edits and old weights."""
from pathlib import Path
import hashlib
import json
import shutil

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT.parent/'study/ai-next-2026-09-30'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    desktop=Path.home()/'Desktop/AM-DFM_v3_0'
    baseline={}
    manifests=[ROOT.parent/'study/ai-full-corpus-2026-09-30/desktop-deployment.json',
               ROOT.parent/'study/ux-audit-2026-09-30/desktop-deployment-final.json']
    manifests+=sorted((ROOT.parent/'study/ai-improvement-2026-09-30').glob('desktop-deployment-*.json'))
    manifests+=sorted(RUN.glob('desktop-deployment-*.json'))
    for path in manifests:
        for row in json.loads(path.read_text(encoding='utf8'))['files']:
            baseline[Path(row['file']).as_posix()]=row['sha256']
    changed=[name for name,expected in baseline.items() if (ROOT/name).is_file() and sha(ROOT/name)!=expected]
    for folder in ('dfm','amdfm','scripts','tests_v3'):
        changed += [p.relative_to(ROOT).as_posix() for p in (ROOT/folder).rglob('*.py')
                    if '__pycache__' not in p.parts and p.relative_to(ROOT).as_posix() not in baseline]
    changed += ['docs/project-knowledge/AI_NEXT_2026-09-30.md',
                'docs/project-knowledge/COMPOUND_PLANNING_2026-09-30.md',
                'docs/research/AM_QUERY_SELECTOR_2026-09-30.md',
                'data/training/ai-next-catalog.json',
                'validation/ai-next-2026-09-30/FEATURE_AFFINITY.md']
    for name in ('compound_planner_v1','external_feature_affinity_v1'):
        model=ROOT/'data/models'/f'{name}.json'
        manifest=model.with_suffix('.manifest.json')
        if json.loads(manifest.read_text(encoding='utf8'))['sha256']!=sha(model):
            raise ValueError('New model manifest mismatch')
        changed += [p.relative_to(ROOT).as_posix() for p in (model,manifest)]
    changed += [p.relative_to(ROOT).as_posix() for p in (ROOT/'examples/learning_validation/compound_edits').iterdir() if p.is_file()]
    # Old identities must retain the old learned weights.
    for row in json.loads((ROOT/'data/training/full-corpus-catalog.json').read_text(encoding='utf8'))['models']:
        if sha(ROOT/row['file'])!=row['sha256'] or sha(desktop/row['file'])!=row['sha256']:
            raise ValueError('Existing model drift')
    changed=list(dict.fromkeys(changed))
    for name in changed:
        source,target=(ROOT/name).resolve(),(desktop/name).resolve()
        if ROOT not in source.parents or desktop not in target.parents or not source.is_file():
            raise ValueError(f'Invalid deployment source: {name}')
        if target.exists() and sha(target) not in (baseline.get(name),sha(source)):
            raise ValueError(f'Separate desktop edit: {name}')
    records=[]
    for name in changed:
        source,target,saved=ROOT/name,desktop/name,RUN/'desktop-before'/name
        before=sha(target) if target.exists() else None
        if before is not None and before!=sha(source) and not saved.exists():
            saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,saved)
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        if sha(target)!=sha(source):raise ValueError(f'Copy differs: {name}')
        records.append(dict(file=name,before_sha256=before,sha256=sha(target)))
    number=1
    while (RUN/f'desktop-deployment-{number:02d}.json').exists():number+=1
    RUN.mkdir(parents=True,exist_ok=True)
    output=RUN/f'desktop-deployment-{number:02d}.json'
    output.write_text(json.dumps(dict(destination=str(desktop),files=records,verified_files=len(records),
        new_models=['compound_planner_v1','external_feature_affinity_v1'],old_global_weights_unchanged=True),indent=2),encoding='utf8')
    # Give the user both original and independently constructed reference edits.
    demo=Path.home()/'Desktop/DFM_개선전후_STEP/3개_포켓'
    demo.mkdir(parents=True,exist_ok=True)
    for source in (ROOT/'examples/learning_validation/compound_edits').iterdir():
        target=demo/source.name
        if target.exists() and sha(target)!=sha(source):
            raise ValueError('Separate user demo file must be preserved')
        shutil.copy2(source,target)
    print(json.dumps(dict(verified_files=len(records),manifest=str(output),demo=str(demo))))


if __name__=='__main__':main()
