import json,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.train_full_plans import score,portable_predict

def main():
    run=ROOT.parent/'study/ai-full-corpus-2026-09-30'
    db=sqlite3.connect(':memory:')
    db.execute('ATTACH DATABASE ? AS original',(str((run/'plan-full/queries.sqlite').resolve()),))
    db.execute("CREATE TEMP VIEW queries AS SELECT * FROM original.queries WHERE json_extract(payload,'$.features[0][0]')=0")
    models={name:json.loads((ROOT/'data/models'/name).read_text()) for name in ('plan_ranker_external_v3.json','plan_ranker_v1.json')}
    validation={name:score(db,'validation',lambda x:portable_predict(m,x)) for name,m in models.items()}
    selected=min(validation,key=lambda name:validation[name]['mean_objective_regret'])
    test={name:score(db,'test',lambda x:portable_predict(m,x)) for name,m in models.items()}
    result=dict(validation=validation,test=test,selected_for_am=selected,
        scope='Generated AM geometry-family holdouts; select model by validation before testing')
    (run/'plan-full/am-role-evaluation.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
if __name__=='__main__':main()
