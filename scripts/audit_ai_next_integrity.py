"""Preserve evidence and verify deployed identities without changing weights."""
from pathlib import Path
import hashlib
import json
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT/'validation/ai-next-2026-09-30'

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    previous=json.loads((RUN/'predeployment-integrity.json').read_text(encoding='utf8'))
    desktop=Path.home()/'Desktop/AM-DFM_v3_0'
    preservation=[]
    for key in ('old_models','old_contract_sources'):
        for row in previous.get(key,[]):
            name=row['file'];expected=row.get('expected_sha256',row['sha256'])
            actual=sha(ROOT/name);deployed=sha(desktop/name)
            preservation.append(dict(file=name,expected_sha256=expected,sha256=actual,desktop_sha256=deployed))
            if actual!=expected or deployed!=expected:raise ValueError('Preserved identity changed: '+name)
    manifests=sorted((ROOT.parent/'study/ai-next-2026-09-30').glob('desktop-deployment-*.json'))
    deployed={}
    for path in manifests:
        for row in json.loads(path.read_text(encoding='utf8'))['files']:deployed[row['file']]=row['sha256']
    for name,expected in deployed.items():
        if sha(ROOT/name)!=expected or sha(desktop/name)!=expected:
            raise ValueError('Deployment differs: '+name)
    final={};initial_failures=[];runs=[]
    for path in sorted(RUN.glob('*.xml'),key=lambda p:p.stat().st_mtime):
        cases=ET.parse(path).findall('.//testcase')
        runs.append(dict(file=path.name,tests=len(cases)))
        for case in cases:
            scope='desktop' if path.name.startswith('desktop') else 'repository'
            key=(scope,case.get('classname'),case.get('name'))
            status='failed' if case.find('failure') is not None or case.find('error') is not None else 'skipped' if case.find('skipped') is not None else 'passed'
            record=dict(scope=scope,test_class=key[1],test_name=key[2],status=status,run=path.name)
            final[key]=record
            if status=='failed':initial_failures.append(record)
    result=dict(preservation=preservation,old_model_artifacts=len(previous['old_models']),
        frozen_source_contracts=len(previous.get('old_contract_sources',[])),deployment_verified_files=len(deployed),
        runs=runs,latest_unique_results=list(final.values()),preserved_initial_failures=initial_failures,
        repository_passed=sum(r['scope']=='repository' and r['status']=='passed' for r in final.values()),
        desktop_passed=sum(r['scope']=='desktop' and r['status']=='passed' for r in final.values()),
        remaining_failed=[r for r in final.values() if r['status']=='failed'])
    number=1
    while (RUN/f'final-integrity-{number:02d}.json').exists():number+=1
    path=RUN/f'final-integrity-{number:02d}.json'
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k in ('old_model_artifacts','frozen_source_contracts','deployment_verified_files','repository_passed','desktop_passed','remaining_failed')}))
    if result['remaining_failed']:raise ValueError('Unresolved tests remain')

if __name__=='__main__':main()
