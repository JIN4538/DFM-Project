"""Exercise the deployed arbiter on held-out exact external pocket dimensions."""
import argparse, json, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.train_external_plans import external_reports
from dfm import enhanced_planning, plan_learning
from dfm.rl_planner import evaluate_changes

def main(cases_path, output):
    cases=json.loads(cases_path.read_text(encoding='utf8'))
    families=set(); selected=[]
    for case in cases:
        group=case.get('group_id',case['id'])
        if case['split']=='test' and group not in families:
            families.add(group);selected.append(case)
        if len(selected)>=120:break
    rows=[];started=time.monotonic()
    frozen=ROOT/'data/models/plan_ranker_external_v3.json'
    feedback=output.parent/'unused-benchmark-preferences.json'
    if feedback.exists():raise ValueError('Benchmark requires empty preference history')
    for group,split,report in external_reports(selected):
        for lock in (False,True):
            prefs=plan_learning._preferences(report,None)
            if lock:prefs['preserve_geometry']=True
            old=plan_learning.recommend_plan(report,preferences=prefs,feedback_path=feedback,model_path=frozen)
            new=enhanced_planning.recommend_plan(report,preferences=prefs,feedback_path=feedback)
            if not old.get('selected') or not new.get('selected'):continue
            a=evaluate_changes(report,old['selected']['changes'],preferences=prefs)
            b=evaluate_changes(report,new['selected']['changes'],preferences=prefs)
            # Adoption must improve the exact conflict/cost ordering. Retention
            # is judged against the actually selected old plan, not an oracle.
            quality_a=(a['conflicts'],a['cost']);quality_b=(b['conflicts'],b['cost'])
            rows.append(dict(group=group,locked=lock,priority=report['review_context']['priority'],
                old_quality=quality_a,new_quality=quality_b,adopted=new.get('reinforcement_planning',{}).get('adopted',False),
                worse=quality_b>quality_a,better=quality_b<quality_a))
    result=dict(families=len(selected),queries=len(rows),adopted=sum(r['adopted'] for r in rows),
        better=sum(r['better'] for r in rows),worse=sum(r['worse'] for r in rows),seconds=time.monotonic()-started,
        scope='Held-out CAD dimension scenarios and project conflict/edit cost; actual deployed arbitration',rows=rows)
    output.write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'}))
    if result['worse']:raise ValueError('Runtime arbitration regressed')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--cases',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();main(a.cases,a.output)
