"""Paired actual product paths on all shipped public STEP files, no fitting."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from threadpoolctl import threadpool_limits
from amdfm.analysis import review
from amdfm.io import load_model
from amdfm.profiles import Profile
from amdfm.ai_search import extend_review_orientations
from amdfm import geometry_guided_search as guide
from dfm.enhanced_planning import recommend_plan,orientation_recommendation
from dfm.conclusion import summarize_conclusion
from benchmark_verified_public_cad import am_cost


def main(output):
    output.mkdir(parents=True,exist_ok=False)
    names=[p.relative_to(ROOT).as_posix() for folder in ('amdfm','dfm','data/models') for p in (ROOT/folder).glob('*')
        if p.is_file() and p.suffix in ('.py','.json')]
    names.append('scripts/benchmark_guided_product.py')
    sources={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in names}
    (output/'source-start.json').write_text(json.dumps(sources,indent=2))
    (output/'benchmark-source.py').write_bytes(Path(__file__).read_bytes())
    records=json.loads((ROOT/'examples/public_demo/manifest.json').read_text(encoding='utf8'))
    conditions=(('MEX','balanced'),('MEX','support'),('VPP','balanced'),('PBF_METAL','balanced'),('PBF_POLYMER','height'))
    cases=[];started=time.perf_counter()
    for item in records:
        path=ROOT/'examples/public_demo'/item['file']
        model=load_model(path.read_bytes(),path.name)
        for process,priority in conditions:
            profile=Profile(process=process)
            base=review(model,profile,dense=True)
            base['review_context']=dict(priority=priority)
            original=json.dumps(base,sort_keys=True)
            t=time.perf_counter()
            with patch.object(guide,'rank_geometry_guided_queries',lambda *a,**k:None):
                old=extend_review_orientations(model,profile,base,priority=priority)
            old_s=time.perf_counter()-t;t=time.perf_counter()
            new=extend_review_orientations(model,profile,base,priority=priority)
            new_s=time.perf_counter()-t
            assert json.dumps(base,sort_keys=True)==original
            a=recommend_plan(old,feedback_path=output/'unused-feedback.json')
            b=recommend_plan(new,feedback_path=output/'unused-feedback.json')
            reference=deepcopy(base);reference['orientations']=old['orientations']+new['orientations']
            selected=[p.get('selected') for p in (a,b)]
            costs=[am_cost(reference,p,priority)[0] if p else None for p in selected]
            conclusions=[summarize_conclusion(r,plan_result=p) for r,p in ((old,a),(new,b))]
            directions=[orientation_recommendation(r,p) for r,p in ((old,a),(new,b))]
            consistent=all((c['plan'].get('selected') or {}).get('id')==(p.get('selected') or {}).get('id') and
                ((d.get('recommended') or {}).get('direction')==(p.get('selected') or {}).get('orientation',{}).get('direction'))
                for c,d,p in zip(conclusions,directions,(a,b)))
            cases.append(dict(file=item['file'],source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),process=process,priority=priority,
                old_status=a['status'],new_status=b['status'],old_id=(selected[0] or {}).get('id'),new_id=(selected[1] or {}).get('id'),
                old_cost=costs[0],new_cost=costs[1],old_seconds=old_s,new_seconds=new_s,
                old_added=old['neural_search']['added_count'],new_added=new['neural_search']['added_count'],
                guided_used='geometry_guided_acquisition' in new['neural_search'],conclusion_direction_consistent=consistent,
                before=a.get('selected'),after=b.get('selected')))
        (output/'cases.json').write_text(json.dumps(cases,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps(dict(files=len(cases)//5,cases=len(cases))),flush=True)
    comparable=[r for r in cases if r['old_cost'] is not None and r['new_cost'] is not None]
    delta=[r['new_cost']-r['old_cost'] for r in comparable]
    end={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in sources}
    (output/'source-end.json').write_text(json.dumps(end,indent=2))
    if end!=sources:
        (output/'failure.json').write_text(json.dumps(dict(reason='Product source changed during benchmark',
            changed=[name for name in sources if sources[name]!=end[name]],conditions=len(cases)),indent=2))
        raise ValueError('Product source changed during benchmark')
    result=dict(files=len(records),conditions=len(cases),comparable=len(comparable),better=sum(d<-1e-8 for d in delta),
        same=sum(abs(d)<=1e-8 for d in delta),worse=sum(d>1e-8 for d in delta),
        unavailable_preserved=sum(r['old_cost'] is None and r['new_cost'] is None for r in cases),
        guided_conditions=sum(r['guided_used'] for r in cases),consistency_failures=sum(not r['conclusion_direction_consistent'] for r in cases),
        mean_common_cost_difference=sum(delta)/max(1,len(delta)),seconds=time.perf_counter()-started,source_unchanged=end==sources,
        note='Actual 8-second product paths; same maximum six final queries and retained earlier candidates; per-method candidate-set normalization, evaluated on a common measured union. Previously seen public demos are integration regressions, not a new independent holdout.')
    (output/'summary.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps(result))


if __name__=='__main__':
    with threadpool_limits(limits=1):main(Path(sys.argv[1]))
