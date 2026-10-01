"""Publish actual intake/learning counts and model hashes, excluding raw archives."""
import hashlib,json,sqlite3
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def main():
    run=ROOT.parent/'study/ai-expansion-2026-09-30';target=ROOT/'validation/ai-expansion-2026-09-30';target.mkdir(parents=True,exist_ok=True)
    intake=json.loads((run/'intake.json').read_text());am=json.loads((run/'am-training/audit.json').read_text());mf=json.loads((run/'mfinstseg-verified-audit.json').read_text())
    result=dict(schema='dfm-public-expansion-1',date='2026-09-30',db_root=str(run),new_raw_objects=41000,
       datasets=[dict(id='PBF-orientation',raw=40000,selected_for_quality_check=2000,eligible=1906,
            license='Apache-2.0 declared by author',revision='24d4f3f5f05cad5488fcf9a4cbc95e28ff528a8a',source='https://huggingface.co/datasets/sebius/pbflbm-part-orientation'),
         dict(id='CadQuarry',raw=1000,eligible_meshes=801,license='CC0-1.0',revision='be52b95de212431d995c3ebd25bdd9d56a5c96bf',source='https://huggingface.co/datasets/jacobjennings/cadquarry'),
         dict(id='MFInstSeg',raw_previous=62495,certification_attempts=5000,certified_graphs=4996,rejected=4,
            train=3540,validation=728,test=728,source='https://github.com/whjdark/AAGNet',license='Author CC0 declaration')],
       am_geometry_count=am['accepted'],am_geometry_by_dataset=am['by_dataset'],
       am_splits={s:dict(meshes=sum(g['split']==s for g in am['groups']),groups=len({g['group'] for g in am['groups'] if g['split']==s})) for s in ('train','validation','test')},
       machine_additions=20,public_step_files=14,models=[])
    for filename in ('external_feature_mfinstseg_v1.json','neural_orientation_external_v3.json'):
        path=ROOT/'data/models'/filename;result['models'].append(dict(file='data/models/'+filename,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),bytes=path.stat().st_size))
    (ROOT/'data/training/expansion-catalog.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    # Preserve the incorrect elapsed timer as a failed diagnostic, not as a
    # valid negative execution time. Model error metrics were unaffected.
    ameval=json.loads((run/'am-training/evaluation.json').read_text())
    if ameval['seconds']<0:
        saved=run/'am-training/evaluation-invalid-timing.json'
        if not saved.exists():saved.write_bytes((run/'am-training/evaluation.json').read_bytes())
        ameval['seconds']=None;ameval['timing_issue']='Original evaluation loop shadowed timer variable; fixed in trainer; duration unavailable for this run'
    (target/'am-evaluation.json').write_text(json.dumps(ameval,indent=2))
    for name,source in [('intake.json',run/'intake.json'),('mf-certification.json',run/'mfinstseg-verified-audit.json'),
          ('mf-evaluation.json',run/'models/mfinstseg-evaluation.json'),('am-proposal-benchmark.json',run/'am-proposal-benchmark.json'),
          ('am-ensemble-benchmark.json',run/'am-ensemble-benchmark.json'),('machine-audit.json',run/'machine-audit.json'),
          ('public-demo-review-audit.json',run/'public-demo-review-audit.json'),('condition-audit.json',run/'condition-audit.json')]:
        (target/name).write_bytes(source.read_bytes())
    # Attach actual CAD volume to the demos after the independent review;
    # geometry signature is rounded source metadata, not an exact reference.
    demo=json.loads((run/'public-demo-review-audit.json').read_text(encoding='utf8'));byfile={x['file']:x for x in demo['results']}
    path=ROOT/'examples/public_demo/manifest.json';manifest=json.loads(path.read_text(encoding='utf8'))
    for item in manifest:
        row=byfile[item['file']]
        item['cad_volume_mm3']=row['exact_volume_mm3']
        item['solid_count']=row['solid_count']
        item['cad_geometry_kind']='solid' if row['solid_count'] else 'surface'
        if not row['solid_count']:
            item['title']='케이스 · 표면 모델 · CadQuarry'
            item['purpose']='공개 표면 STEP; 솔리드 부피·벽 미확정 처리 시연'
    raw=json.dumps(manifest,ensure_ascii=False,indent=2);path.write_text(raw,encoding='utf8');(Path.home()/'Desktop/DFM_공개_STEP_시연/manifest.json').write_text(raw,encoding='utf8')
    guide='공개 STEP 시연 파일\n\n앱 왼쪽 입력에서 「공개 STEP 시연」을 선택하세요. 같은 파일은 이 폴더에서 직접 업로드할 수 있습니다.\n\n'
    guide+='\n'.join(f"{x['file']} : {x['title']}\n출처: {x['source_url']}\n이용조건: {x['license']}\n" for x in manifest)
    (path.parent/'README.md').write_text(guide,encoding='utf8')
    (Path.home()/'Desktop/DFM_공개_STEP_시연/사용법.txt').write_text(guide,encoding='utf8')
    print(json.dumps(result['am_splits']))
if __name__=='__main__':main()
