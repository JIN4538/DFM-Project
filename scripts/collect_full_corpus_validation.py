"""Copy compact audits, not raw databases, and bind deployed artifacts by SHA."""
import hashlib,json,shutil,sqlite3
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
RUN=ROOT.parent/'study/ai-full-corpus-2026-09-30'
DEST=ROOT/'validation/ai-full-corpus-2026-09-30'

def main():
    DEST.mkdir(parents=True,exist_ok=True)
    names=['am-full/audit.json','am-full/evaluation.json','mfinstseg-verified-audit.json',
        'pocket-measurement-audit.json','feature-models/evaluation.json','feature-models/calibrated-evaluation.json',
        'feature-geometric/feature-models/evaluation.json','feature-geometric/feature-models/calibrated-evaluation.json',
        'feature-geometric64/feature-models/evaluation.json','feature-geometric64/feature-models/calibrated-evaluation.json',
        'plan-full/evaluation.json','plan-full/am-role-evaluation.json','base-plan/evaluation.json',
        'rl-full/manifest.json','cad-pair-benchmark.json','full-am-benchmark.json','rl-runtime-benchmark.json',
        'public-runtime-audit/public-demo-review-audit.json','public-runtime-audit-final/public-demo-review-audit.json','feature-selection.json']
    records=[]
    for name in names:
        source=RUN/name
        if not source.exists():continue
        target=DEST/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
        records.append(dict(file=name,sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
    rl=json.loads((RUN/'rl-full/test-evaluation.json').read_text())
    (DEST/'rl-full/test-summary.json').write_text(json.dumps(rl['summary'],indent=2),encoding='utf8')
    models=[]
    for name in ('neural_orientation_external_v4','external_feature_mfinstseg_v2','external_feature_localization_v1','plan_ranker_v1','plan_ranker_external_v3','rl_planner_v1'):
        source=ROOT/'data/models'/(name+'.json')
        models.append(dict(file=str(source.relative_to(ROOT)),sha256=hashlib.sha256(source.read_bytes()).hexdigest()))
    catalog=dict(schema='dfm-full-corpus-catalog-1',local_root=str(RUN.resolve()),
        raw_records=128981,accepted_external_records=120178,
        am=dict(accepted=42295,train=29943,validation=6097,test=6255),
        cnc=dict(accepted=77883,train=54570,validation=11763,test=11550),
        combined_weight_training_records=84513,construction_stock_records=dict(train=1200,validation=150,test=150),
        counts_note='External source records, not universally unique physical shapes. Candidate views and repeated RL episodes are not added to shape counts.',
        models=models,audits=records)
    (ROOT/'data/training/full-corpus-catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2),encoding='utf8')
    index=sqlite3.connect(f'file:{(RUN/"am-full/index.sqlite").as_posix()}?mode=ro',uri=True)
    source=ROOT.parent/'study/external-training-2026-09-30/thingi.sqlite'
    things=sqlite3.connect(f'file:{source.as_posix()}?mode=ro',uri=True)
    attribution=[]
    for identifier,split in index.execute('SELECT id,split FROM records WHERE dataset=? AND accepted=1',('Thingi10K',)):
        thing,license,metadata,sha=things.execute('SELECT thing_id,license,metadata,sha256 FROM parts WHERE id=?',(int(identifier),)).fetchone()
        meta=json.loads(metadata)
        attribution.append(dict(file_id=int(identifier),thing_id=thing,split=split,sha256=sha,license=license,
            author=meta.get('Author'),title=meta.get('Name'),source_url=f'https://www.thingiverse.com/thing:{thing}'))
    if len(attribution)!=1375:raise ValueError('Full Thingi attribution count mismatch')
    (ROOT/'data/training/thingi-full-attribution.json').write_text(json.dumps(dict(dataset='Thingi10K author v1.5.0',records=attribution),ensure_ascii=False,indent=2),encoding='utf8')
    index.close();things.close()
    print(json.dumps(dict(audits=len(records),models=len(models))))

if __name__=='__main__':main()
