"""Latest unique test results, deployment SHA and untouched model contracts."""
from pathlib import Path
import hashlib,json,xml.etree.ElementTree as ET
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'validation/practical-holes-2026-09-30'
STUDY=ROOT.parent/'study/practical-holes-2026-09-30'

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    desktop=Path.home()/'Desktop/AM-DFM_v3_0'
    manifests=sorted(STUDY.glob('desktop-deployment-*.json'))
    latest={}
    for path in manifests:
        record=json.loads(path.read_text(encoding='utf8'))
        for r in record['files']:latest[r['file']]=r['sha256']
    for name,expected in latest.items():
        if sha(ROOT/name)!=expected or sha(desktop/name)!=expected:raise ValueError('Deployment differs: '+name)
    frozen=json.loads((ROOT/'validation/ai-next-2026-09-30/predeployment-integrity.json').read_text(encoding='utf8'))
    preservation=[]
    for r in frozen['old_contract_sources']+frozen['old_models']:
        expected=r.get('expected_sha256',r['sha256'])
        preservation.append(dict(file=r['file'],sha256=sha(ROOT/r['file']),desktop_sha256=sha(desktop/r['file']),expected_sha256=expected))
        if preservation[-1]['sha256']!=expected or preservation[-1]['desktop_sha256']!=expected:raise ValueError('Frozen identity drift')
    learned=json.loads(manifests[-1].read_text(encoding='utf8'))['learned_artifacts_unchanged']
    for name,expected in learned.items():
        if sha(ROOT/name)!=expected or sha(desktop/name)!=expected:raise ValueError('Learned artifact drift')
    final={};failures=[];runs=[]
    for path in sorted(RUN.glob('*.xml'),key=lambda p:p.stat().st_mtime):
        cases=ET.parse(path).findall('.//testcase')
        runs.append(dict(file=path.name,cases=len(cases)))
        for c in cases:
            scope='desktop' if path.name.startswith('desktop') else 'repository'
            key=(scope,c.get('classname'),c.get('name'))
            state='failed' if c.find('failure') is not None or c.find('error') is not None else 'skipped' if c.find('skipped') is not None else 'passed'
            row=dict(scope=scope,test_class=key[1],test_name=key[2],status=state,run=path.name)
            final[key]=row
            if state=='failed':failures.append(row)
    geometry=json.loads((RUN/'independent-02/result.json').read_text(encoding='utf8'))
    runtime=json.loads((RUN/'runtime-02/result.json').read_text(encoding='utf8'))
    result=dict(files_verified=len(latest),learned_artifacts_unchanged=len(learned),frozen_source_contracts=len(frozen['old_contract_sources']),
                preservation=preservation,learned_artifact_sha256=learned,
                repository_passed=sum(r['scope']=='repository' and r['status']=='passed' for r in final.values()),
                desktop_passed=sum(r['scope']=='desktop' and r['status']=='passed' for r in final.values()),
                remaining_failed=[r for r in final.values() if r['status']=='failed'],preserved_initial_failures=failures,
                runs=runs,latest_unique_results=list(final.values()),
                independent_cad=dict(cases=geometry['cases'],passed=geometry['passed'],holes=sum(len(r['expected']) for r in geometry['results'])),
                actual_input=dict(files=runtime['files'],passed=runtime['passed'],conditions=runtime['direction_conditions']),
                training_changed=False)
    number=1
    while (RUN/f'final-integrity-{number:02d}.json').exists():number+=1
    dest=RUN/f'final-integrity-{number:02d}.json'
    dest.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('preservation','learned_artifact_sha256','runs','latest_unique_results','preserved_initial_failures')},ensure_ascii=False))
    if result['remaining_failed'] or geometry['cases']!=geometry['passed'] or runtime['files']!=runtime['passed']:raise ValueError('Outstanding verification failure')

if __name__=='__main__':main()
