"""Train bounded CNC combination proposals on exact feature-completion targets.

Validation selects the model. Test is a separate explicit operation, performed
after selection. All geometry/condition variants of one part share a split.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from threadpoolctl import threadpool_limits
from sklearn.ensemble import GradientBoostingRegressor, ExtraTreesRegressor
from dfm import compound_planning as cp, plan_learning as prior, rl_planner as env
from scripts.train_rl_planner import scenario
from scripts.train_plan_model import export_tree


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf8')


def cases(seed, split, per_family):
    offset = {'train': 0, 'validation': 1900000, 'test': 7300000}[split]
    for family in range(7 if split == 'test' else 5):
        for index in range(per_family):
            base = scenario(seed+offset, family, index)
            for priority in ('balanced','accuracy','tool_access'):
                report = deepcopy(base['report'])
                report['review_context']['priority'] = priority
                # Geometry and tool locks are orthogonal to priority, and every
                # preference variant stays in its original geometry group.
                prefs = dict(priority=priority, preserve_geometry=index%10 == 8,
                             allow_tool_change=index%10 != 9)
                yield dict(id=base['id']+'-'+priority, group=base['id'], split=split,
                    family=family, heldout_family=family >= 5, report=report, preferences=prefs,
                    source='Procedural exact feature dimensions, not a loaded CAD file')


def baseline_candidates(case):
    report, prefs = case['report'], case['preferences']
    plans, _, _ = prior._cnc_candidates(report, prior._preferences(report,prefs))
    candidates = []
    for plan in plans:
        try:
            assessed = env.evaluate_changes(report, plan['changes'], preferences=prefs)
            candidates.append(assessed['plan'])
        except ValueError:
            pass
    rl = env.propose_rl_plan(report, preferences=prefs)
    if rl.get('proposal'):
        candidates.append(env.evaluate_changes(report, rl['proposal']['changes'], preferences=prefs)['plan'])
    return candidates


def gated_best(plans):
    if not plans:
        return None
    minimum = min(p['outcomes']['remaining_numeric_conflicts'] for p in plans)
    plans = [p for p in plans if p['outcomes']['remaining_numeric_conflicts'] == minimum]
    # Include the edit-count term used by the disclosed cost. This audit is
    # independent of the app's current wrapper; integration is checked later.
    def dominates(a, b):
        x = a['_dominance']+[min(len(a['changes']),8)/8]
        y = b['_dominance']+[min(len(b['changes']),8)/8]
        return all(i <= j+1e-10 for i,j in zip(x,y)) and any(i < j-1e-10 for i,j in zip(x,y))
    eligible = [p for p in plans if not any(dominates(o,p) for o in plans if o is not p)]
    return min(eligible, key=lambda p: (p['outcomes']['remaining_numeric_conflicts'], p['planning_cost'], len(p['changes'])))


def measure_case(case):
    problem = env.make_problem(case['report'], case['preferences'])
    configurations = cp.tool_configurations(problem)
    features = [cp.configuration_features(problem,c) for c in configurations]
    labels, qualities = [], []
    start = time.monotonic()
    for config in configurations:
        state = cp.complete_configuration(problem,config)
        quality = env.quality(problem,state)
        labels.append(quality[0]+quality[1])
        qualities.append(list(quality))
    return dict(case=case, features=features, targets=labels, qualities=qualities,
                teacher_seconds=time.monotonic()-start, configuration_count=len(configurations))


def export(fit):
    if isinstance(fit, GradientBoostingRegressor):
        return dict(intercept=float(fit.init_.constant_.reshape(-1)[0]), learning_rate=float(fit.learning_rate),
                    trees=[export_tree(e[0]) for e in fit.estimators_])
    return dict(intercept=0., learning_rate=1/len(fit.estimators_), trees=[export_tree(t) for t in fit.estimators_])


def ranking_summary(queries, model, budget):
    rows = []
    for query in queries:
        scores = cp.predict(model, query['features'])
        selected = np.argsort(scores,kind='stable')[:budget]
        target = min(query['targets'][i] for i in selected)
        best = min(query['targets'])
        rows.append(target-best)
    return dict(queries=len(rows), best_in_budget=sum(v <= 1e-7 for v in rows),
                mean_regret=float(np.mean(rows)), maximum_regret=max(rows))


def compare(queries, model, budget):
    rows = []
    for index, query in enumerate(queries):
        case = query['case']
        problem = env.make_problem(case['report'], case['preferences'])
        baseline = baseline_candidates(case)
        base = gated_best(baseline)
        row = dict(id=case['id'], group=case['group'], family=case['family'],
                   heldout_family=case['heldout_family'], source=case['source'],
                   baseline_quality=[base['outcomes']['remaining_numeric_conflicts'],base['planning_cost']] if base else None,
                   baseline_changes=base['changes'] if base else None, comparisons={})
        for policy in ('learned','greedy','random','all'):
            start = time.monotonic()
            state, audit = cp.search(problem, model=model, policy=policy, budget=budget, seed=index+503)
            proposal = env.evaluate_changes(case['report'], env.edits(problem,state), preferences=case['preferences'])['plan']
            final = gated_best(baseline+[proposal])
            row['comparisons'][policy] = dict(raw_quality=[proposal['outcomes']['remaining_numeric_conflicts'],proposal['planning_cost']],
                final_quality=[final['outcomes']['remaining_numeric_conflicts'],final['planning_cost']],
                selected_proposal=final is proposal, changes=final['changes'],
                seconds=time.monotonic()-start, search=audit)
        rows.append(row)
    summaries = {}
    for policy in ('learned','greedy','random','all'):
        selected = [r['comparisons'][policy] for r in rows]
        pairs = [(tuple(r['comparisons'][policy]['final_quality']),tuple(r['baseline_quality'])) for r in rows if r['baseline_quality']]
        def comparable(a,b):
            return next((i-j for i,j in zip(a,b) if abs(i-j)>1e-7),0.)
        differences = [comparable(a,b) for a,b in pairs]
        summaries[policy] = dict(queries=len(rows), better=sum(d<0 for d in differences),same=sum(d==0 for d in differences),
            worse=sum(d>0 for d in differences), proposal_adopted=sum(v['selected_proposal'] for v in selected),
            mean_seconds=float(np.mean([v['seconds'] for v in selected])),
            completed_configurations=sum(v['search']['evaluated_count'] for v in selected))
    learned_vs = {}
    for policy in ('greedy','random','all'):
        differences = [comparable(r['comparisons']['learned']['final_quality'],r['comparisons'][policy]['final_quality']) for r in rows]
        learned_vs[policy] = dict(better=sum(d<0 for d in differences),same=sum(d==0 for d in differences),worse=sum(d>0 for d in differences))
    return dict(summary=summaries, learned_vs=learned_vs, rows=rows)


def train(args):
    args.output.mkdir(parents=True,exist_ok=False)
    start = time.monotonic()
    sources = cp.source_hashes()
    write(args.output/'preregistered.json',dict(seed=args.seed, budget=args.budget,
        train_groups_per_family=args.train, validation_groups_per_family=args.validation,
        test_groups_per_family=args.test, sources=sources,
        teacher='Exact discrete tool thresholds and feature-specific geometry/edit-count dynamic programming',
        model_selection='Validation mean policy regret within proposal budget; no test access before selection',
        heldout_families=[5,6], split_unit='procedural part; all priorities/permission variants stay together',
        existing_weight_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'data/models').glob('*.json')}))
    for path in list(sources)+['scripts/train_compound_planner.py']:
        target=args.output/'frozen'/path
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((ROOT/path).read_bytes())
    queries = {}
    for split,count in (('train',args.train),('validation',args.validation)):
        queries[split]=[]
        for i,case in enumerate(cases(args.seed,split,count)):
            queries[split].append(measure_case(case))
            if (i+1)%30 == 0: print(split,i+1,'queries',flush=True)
        with gzip.open(args.output/(split+'-queries.json.gz'),'wt',encoding='utf8') as stream:
            json.dump(queries[split],stream,ensure_ascii=False)
    x = np.asarray([f for q in queries['train'] for f in q['features']])
    y = np.asarray([t for q in queries['train'] for t in q['targets']])
    weights = np.asarray([1/len(q['features']) for q in queries['train'] for _ in q['features']])
    choices = {'gb80-d3': GradientBoostingRegressor(n_estimators=80,max_depth=3,min_samples_leaf=8,learning_rate=.06,random_state=args.seed),
               'gb120-d4': GradientBoostingRegressor(n_estimators=120,max_depth=4,min_samples_leaf=8,learning_rate=.06,random_state=args.seed),
               'extra96-d10': ExtraTreesRegressor(n_estimators=96,max_depth=10,min_samples_leaf=3,random_state=args.seed,n_jobs=1)}
    fitted = {}
    summaries = {}
    for name, estimator in choices.items():
        with threadpool_limits(limits=1): estimator.fit(x,y,sample_weight=weights)
        portable = export(estimator)
        parity = float(np.max(np.abs(cp.predict(portable,x[:1000])-estimator.predict(x[:1000]))))
        if parity > 1e-10: raise ValueError('Portable inference parity failed')
        summaries[name]=dict(**ranking_summary(queries['validation'],portable,args.budget),portable_max_difference=parity)
        fitted[name]=portable
        print(name,summaries[name],flush=True)
    selected = min(summaries,key=lambda key:(summaries[key]['mean_regret'],summaries[key]['maximum_regret'],key))
    model = dict(schema=cp.SCHEMA, id='local-compound-tool-proposer-v1', features=list(cp.FEATURES),sources=sources,
                 selected=selected, training=dict(groups=len({q['case']['group'] for q in queries['train']}),queries=len(queries['train']),
                    candidate_rows=len(x),target='minimum exact feature-completion conflict count plus disclosed edit cost'),**fitted[selected])
    write(args.output/'compound_planner_v1.json',model)
    write(args.output/'compound_planner_v1.manifest.json',dict(sha256=hashlib.sha256((args.output/'compound_planner_v1.json').read_bytes()).hexdigest(),sources=sources))
    comparison = compare(queries['validation'],model,args.budget)
    write(args.output/'validation-comparison.json',comparison)
    write(args.output/'selection.json',dict(selected=selected,models=summaries,validation=comparison['summary'],
        learned_vs=comparison['learned_vs'],seconds=time.monotonic()-start,source_unchanged=sources==cp.source_hashes()))
    print(json.dumps(dict(selected=selected,summary=comparison['summary'],learned_vs=comparison['learned_vs'],seconds=time.monotonic()-start)),flush=True)
    if sources != cp.source_hashes(): raise ValueError('Training source changed; retain run but do not deploy')


def test(args):
    model = cp.load_model(args.output/'compound_planner_v1.json')
    preregistered = json.loads((args.output/'preregistered.json').read_text(encoding='utf8'))
    if (args.output/'test-comparison.json').exists(): raise ValueError('Test already recorded; do not overwrite')
    queries=[]
    for i,case in enumerate(cases(preregistered['seed'],'test',preregistered['test_groups_per_family'])):
        queries.append(measure_case(case))
        if (i+1)%30==0: print('test',i+1,flush=True)
    with gzip.open(args.output/'test-queries.json.gz','wt',encoding='utf8') as stream: json.dump(queries,stream,ensure_ascii=False)
    comparison=compare(queries,model,preregistered['budget'])
    write(args.output/'test-comparison.json',comparison)
    print(json.dumps({k:v for k,v in comparison.items() if k!='rows'}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    p.add_argument('--seed',type=int,default=2026093043);p.add_argument('--train',type=int,default=24)
    p.add_argument('--validation',type=int,default=8);p.add_argument('--test',type=int,default=20)
    p.add_argument('--budget',type=int,default=8);p.add_argument('--evaluate-test',action='store_true')
    args=p.parse_args();test(args) if args.evaluate_test else train(args)
