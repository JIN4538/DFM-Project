"""Guarded desktop update; preserve independent edits and every learned weight."""
from pathlib import Path
import hashlib,json,shutil
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT.parent/'study/practical-holes-2026-09-30'
FILES=['app.py','amdfm/cad_worker.py','dfm/verified_holes.py','dfm/hole_view.py','dfm/tool_recommendation.py',
       'dfm/tool_recommendation_presentation.py','dfm/machining_view.py','dfm/enhanced_planning.py',
       'dfm/conclusion.py','dfm/conclusion_view.py','dfm/feature_learning_view.py',
       'tests_v3/test_verified_holes.py','scripts/benchmark_verified_holes.py','scripts/audit_practical_holes.py',
       'scripts/prepare_hole_review_demo.py','scripts/deploy_practical_holes.py',
       'scripts/audit_practical_holes_integrity.py',
       'tests_v3/test_packaged_geometry.py','examples/geometry_manifest.json','examples/README.md',
       'docs/project-knowledge/PRACTICAL_HOLES_2026-09-30.md']

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    desktop=Path.home()/'Desktop/AM-DFM_v3_0'
    baseline={}
    manifests=[ROOT.parent/'study/ai-full-corpus-2026-09-30/desktop-deployment.json',
               ROOT.parent/'study/ux-audit-2026-09-30/desktop-deployment-final.json']
    for folder in ('ai-improvement-2026-09-30','ai-next-2026-09-30','practical-holes-2026-09-30'):
        manifests+=sorted((ROOT.parent/'study'/folder).glob('desktop-deployment-*.json'))
    for path in manifests:
        for row in json.loads(path.read_text(encoding='utf8'))['files']:
            baseline[Path(row['file']).as_posix()]=row['sha256']
    names=FILES+[p.relative_to(ROOT).as_posix() for p in (ROOT/'examples/learning_validation/hole_review').iterdir() if p.is_file()]
    before_models={p.relative_to(ROOT).as_posix():sha(p) for p in (ROOT/'data/models').glob('*.json')}
    frozen=json.loads((ROOT/'validation/ai-next-2026-09-30/predeployment-integrity.json').read_text(encoding='utf8'))
    for row in frozen['old_contract_sources']+frozen['old_models']:
        expected=row.get('expected_sha256',row['sha256'])
        if sha(ROOT/row['file'])!=expected or sha(desktop/row['file'])!=expected:raise ValueError('Frozen artifact drift: '+row['file'])
    for name,expected in before_models.items():
        if sha(desktop/name)!=expected:raise ValueError('Desktop learned artifact differs: '+name)
    for name in names:
        src,dest=(ROOT/name).resolve(),(desktop/name).resolve()
        if ROOT not in src.parents or desktop not in dest.parents or not src.is_file():raise ValueError('Invalid deployment path')
        if dest.exists() and sha(dest) not in (baseline.get(name),sha(src)):
            raise ValueError('Preserve separate desktop edit: '+name)
    records=[]
    for name in names:
        src,dest=ROOT/name,desktop/name
        previous=sha(dest) if dest.exists() else None
        if previous and previous!=sha(src):
            saved=RUN/'desktop-before'/name
            if not saved.exists():saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(dest,saved)
        dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dest)
        if sha(dest)!=sha(src):raise ValueError('Copy mismatch: '+name)
        records.append(dict(file=name,before_sha256=previous,sha256=sha(dest)))
    if before_models!={p.relative_to(ROOT).as_posix():sha(p) for p in (ROOT/'data/models').glob('*.json')}:raise ValueError('Learned artifacts changed')
    # The desktop knowledge index has an independent history. Add a pointer
    # while preserving every existing byte instead of replacing it from repo.
    index=desktop/'docs/project-knowledge/README.md'
    content=index.read_text(encoding='utf8')
    pointer=(ROOT/'docs/project-knowledge/README.md').read_text(encoding='utf8').split('\n\n')[0]+'\n\n'
    index_before=sha(index)
    if 'PRACTICAL_HOLES_2026-09-30.md' not in content:
        saved=RUN/'desktop-before/docs/project-knowledge/README.md'
        if not saved.exists():saved.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(index,saved)
        index.write_text(pointer+content,encoding='utf8')
    demo=Path.home()/'Desktop/DFM_구멍검토_STEP'
    demo.mkdir(parents=True,exist_ok=True)
    for source in (ROOT/'examples/learning_validation/hole_review').iterdir():
        target=demo/source.name
        if target.exists() and sha(target)!=sha(source):raise ValueError('Preserve separate user demo')
        shutil.copy2(source,target)
    number=1
    while (RUN/f'desktop-deployment-{number:02d}.json').exists():number+=1
    output=RUN/f'desktop-deployment-{number:02d}.json'
    output.write_text(json.dumps(dict(destination=str(desktop),files=records,learned_artifacts_unchanged=before_models,
        frozen_source_contracts=len(frozen['old_contract_sources']),demo=str(demo),
        preserved_desktop_index=dict(file=str(index),before_sha256=index_before,sha256=sha(index),
                                    policy='Add latest document pointer; preserve all existing index content')),
        ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(dict(files=len(records),manifest=str(output),demo=str(demo)),ensure_ascii=False))

if __name__=='__main__':main()
