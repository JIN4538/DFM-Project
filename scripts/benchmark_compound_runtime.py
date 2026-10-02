"""Replay the frozen held-out part groups through the final application API."""
import argparse
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dfm import compound_planning as cp, enhanced_planning as enhanced, rl_planner as env


def main(args):
    args.output.mkdir(parents=True,exist_ok=False)
    with gzip.open(args.queries,'rt',encoding='utf8') as stream:queries=json.load(stream)
    source_names=[*cp.source_hashes(),'dfm/enhanced_planning.py','dfm/verified_selection.py']
    sources={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in source_names}
    results=[];started=time.monotonic()
    for index,query in enumerate(queries):
        case=query['case'];report=case['report'];prefs=case['preferences'];original=deepcopy(report)
        feedback=args.output/'absent-preferences.json'
        with patch.object(cp,'MODEL_PATH',args.output/'absent-model.json'):
            before=enhanced.recommend_plan(report,preferences=prefs,feedback_path=feedback)
        with patch.object(cp,'MODEL_PATH',args.model.resolve()):
            after=enhanced.recommend_plan(report,preferences=prefs,feedback_path=feedback)
        a,b=before.get('selected'),after.get('selected')
        row=dict(id=case['id'],group=case['group'],family=case['family'],heldout_family=case['heldout_family'],
            before_status=before['status'],after_status=after['status'],before_id=(a or {}).get('id'),after_id=(b or {}).get('id'),
            source=after.get('selection_source'),compound=after.get('compound_planning'),
            before_changes=(a or {}).get('changes'),after_changes=(b or {}).get('changes'))
        if a and b:
            first=env.evaluate_changes(report,a['changes'],preferences=prefs)
            last=env.evaluate_changes(report,b['changes'],preferences=prefs)
            qa,qb=[first['conflicts'],first['cost']],[last['conflicts'],last['cost']]
            delta=next((x-y for x,y in zip(qb,qa) if abs(x-y)>1e-7),0.)
            row.update(before_quality=qa,after_quality=qb,better=delta<0,same=delta==0,worse=delta>0)
        if report!=original:raise ValueError('Source report changed')
        results.append(row)
        if (index+1)%100==0:print(index+1,'runtime queries',flush=True)
    summary=dict(queries=len(results),groups=len({r['group'] for r in results}),
        compared=sum('before_quality' in r for r in results),better=sum(r.get('better',False) for r in results),
        same=sum(r.get('same',False) for r in results),worse=sum(r.get('worse',False) for r in results),
        before_unavailable=sum(r['before_status']=='unavailable' for r in results),
        after_unavailable=sum(r['after_status']=='unavailable' for r in results),
        old_available_lost=sum(r['before_status']!='unavailable' and r['after_status']=='unavailable' for r in results),
        adopted=sum((r['compound'] or {}).get('adopted',False) for r in results),seconds=time.monotonic()-started)
    after_sources={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in sources}
    result=dict(scope='Final enhanced_planning API; same frozen test groups; compound disabled versus enabled; existing raw candidates and RL held identical',
        query_sha256=hashlib.sha256(args.queries.read_bytes()).hexdigest(),model_sha256=hashlib.sha256(args.model.read_bytes()).hexdigest(),
        source_before=sources,source_after=after_sources,sources_unchanged=sources==after_sources,summary=summary,rows=results)
    (args.output/'evaluation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(summary),flush=True)
    if sources!=after_sources or summary['worse'] or summary['old_available_lost']:
        raise ValueError('Runtime regression or source change detected')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--queries',type=Path,required=True)
    p.add_argument('--model',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    main(p.parse_args())
