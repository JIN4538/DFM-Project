"""Audit exact policy arbitration against frozen learned ranking on held-out queries.

This benchmark changes neither weights nor training labels. Zero policy regret
is a decision-policy upper bound on the existing candidates, not new ML accuracy.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dfm import plan_learning as prior
from scripts.train_full_plans import portable_predict
from scripts.train_plan_model import selection_objective


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fresh_stats():
    return dict(queries=0, candidate_rows=0, learned_exact_policy_best=0,
                exact_policy_best=0, selection_changed=0, better=0, same=0, worse=0,
                learned_regret_sum=0., exact_regret_sum=0., learned_max_regret=0., exact_max_regret=0.)


def update(stats, query, learned_index, exact_index):
    truth = max(query['targets'])
    old = max(0., truth-query['targets'][learned_index])
    new = max(0., truth-query['targets'][exact_index])
    stats['queries'] += 1
    stats['candidate_rows'] += len(query['features'])
    stats['learned_exact_policy_best'] += old <= 1e-7
    stats['exact_policy_best'] += new <= 1e-7
    stats['selection_changed'] += learned_index != exact_index
    stats['better'] += new < old-1e-7
    stats['same'] += abs(new-old) <= 1e-7
    stats['worse'] += new > old+1e-7
    stats['learned_regret_sum'] += old
    stats['exact_regret_sum'] += new
    stats['learned_max_regret'] = max(stats['learned_max_regret'], old)
    stats['exact_max_regret'] = max(stats['exact_max_regret'], new)
    return old, new


def custom_current_counterexample():
    """Decision fixture only; these are deliberately constructed metric rows."""
    row = lambda name, direction, overhang, height: dict(name=name, direction=direction,
        overhang_projected_area_sum_mm2=overhang, height_mm=height, build_fit=True,
        candidate_role='search')
    current = row('현재 사용자 방향', [2**-.5, 0., 2**-.5], 4., 14.)
    current['candidate_role'] = 'current_only'
    report = dict(profile=dict(process='VPP', build_volume_mm=None), process='VPP',
        summary=dict(review_status='geometry_review'), model=dict(unit_status='declared'),
        findings=[], review_context=dict(priority='balanced'), current_orientation=current,
        orientations=[row('+Z', [0, 0, 1], 0., 20.), row('+X', [1, 0, 0], 10., 10.)])
    original = deepcopy(report)
    plans, reason, _ = prior.candidate_plans(report)
    existing = [selection_objective(p['_features']) for p in plans]
    copied = deepcopy(report)
    copied['orientations'].append(dict(current, name='추가한 현재 방향', candidate_role='search'))
    expanded, _, _ = prior.candidate_plans(copied)
    all_scores = [selection_objective(p['_features']) for p in expanded]
    result = dict(scope='Constructed decision-row regression, not physical CAD measurement',
        before_candidate_ids=[p['id'] for p in plans], reason=reason,
        before_best_objective=max(existing), with_current_best_objective=max(all_scores),
        current_in_original_candidates=any(p.get('keep_current') for p in plans),
        source_report_unchanged=original==report, report=report)
    if not result['source_report_unchanged']:
        raise ValueError('Candidate generation mutated the source report')
    return result


def main(args):
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    paths = {family: ROOT/'data/models'/name for family, name in
             (('AM', 'plan_ranker_v1.json'), ('CNC', 'plan_ranker_external_v3.json'))}
    tracked = [ROOT/p for p in prior.TEACHER_SOURCES]
    tracked += [ROOT/'dfm/rl_planner.py', ROOT/'data/models/rl_planner_v1.json',
                ROOT/'data/models/rl_planner_v1.manifest.json']
    tracked += [p for source in paths.values() for p in (source, source.with_suffix('.manifest.json'))]
    before = {p.relative_to(ROOT).as_posix(): sha(p) for p in tracked}
    for p in tracked:
        target = args.output/'frozen'/p.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(p.read_bytes())
    models = {}
    for family, path in paths.items():
        data = path.read_bytes()
        manifest = json.loads(path.with_suffix('.manifest.json').read_text(encoding='utf8'))
        if hashlib.sha256(data).hexdigest() != manifest['sha256']:
            raise ValueError('Baseline model checksum mismatch')
        models[family] = json.loads(data)
        if models[family]['sources'] != prior.source_hashes():
            raise ValueError('Frozen ranking model is not bound to the current teacher sources')
    db = sqlite3.connect(args.queries.resolve().as_uri()+'?mode=ro', uri=True)
    split_inventory = [dict(split=s, external=bool(e), queries=n, candidate_rows=c, family_groups=g)
        for s, e, n, c, g in db.execute('SELECT split,external,COUNT(*),SUM(count),COUNT(DISTINCT group_id) '
                                      'FROM queries GROUP BY split,external ORDER BY split,external')]
    overlaps = {}
    for a, b in (('train','validation'),('train','test'),('validation','test')):
        count = db.execute('SELECT COUNT(*) FROM (SELECT DISTINCT group_id FROM queries WHERE split=? '
            'INTERSECT SELECT DISTINCT group_id FROM queries WHERE split=?)', (a, b)).fetchone()[0]
        overlaps[a+'/'+b] = count
    if any(overlaps.values()):
        raise ValueError('Frozen query database has cross-split group overlap')
    stats = {key: fresh_stats() for key in ('all', 'AM', 'CNC', 'external', 'procedural')}
    rows = db.execute("SELECT group_id,external,payload FROM queries WHERE split='test' ORDER BY rowid")
    learned_seconds = exact_seconds = maximum_target_difference = 0.
    examples = []
    while batch := rows.fetchmany(512):
        queries = [json.loads(r[2]) for r in batch]
        x = np.asarray([f for q in queries for f in q['features']], dtype='float32')
        predictions = np.empty(len(x), dtype=float)
        tick = time.perf_counter()
        for family, model in models.items():
            mask = x[:,0] == float(family == 'CNC')
            if mask.any():
                predictions[mask] = portable_predict(model, x[mask])
        learned_seconds += time.perf_counter()-tick
        tick = time.perf_counter()
        exact = [[selection_objective(f) for f in q['features']] for q in queries]
        exact_seconds += time.perf_counter()-tick
        offset = 0
        for raw, q, target_scores in zip(batch, queries, exact):
            differences = [abs(a-b) for a, b in zip(q['targets'], target_scores)]
            maximum_target_difference = max(maximum_target_difference, max(differences, default=0.))
            count = len(q['features'])
            scores = predictions[offset:offset+count]
            offset += count
            learned_index = prior.selection_index(scores, q['stable_keys'])
            exact_index = prior.selection_index(target_scores, q['stable_keys'])
            family = 'CNC' if q['features'][0][0] else 'AM'
            subset = 'external' if raw[1] else 'procedural'
            for key in ('all', family, subset):
                old, new = update(stats[key], q, learned_index, exact_index)
            if old > 1e-7:
                examples.append(dict(group_id=raw[0], family=family, external=bool(raw[1]),
                    learned_index=learned_index, exact_index=exact_index, learned_regret=old,
                    exact_regret=new, features=q['features'], targets=q['targets'],
                    scores=[float(v) for v in scores], stable_keys=q['stable_keys']))
                examples = sorted(examples, key=lambda r:-r['learned_regret'])[:10]
        print('Evaluated', stats['all']['queries'], 'held-out queries', flush=True)
    db.close()
    for values in stats.values():
        values['learned_mean_regret'] = values.pop('learned_regret_sum')/max(1, values['queries'])
        values['exact_mean_regret'] = values.pop('exact_regret_sum')/max(1, values['queries'])
    after = {p.relative_to(ROOT).as_posix(): sha(p) for p in tracked}
    result = dict(scope='Same frozen held-out candidate sets; disclosed policy upper bound, not ML generalization improvement',
        evaluated_split='test', fitted_or_selected_on_this_run=False, split_inventory=split_inventory,
        cross_split_family_group_overlap=overlaps, queries_sha256=sha(args.queries),
        models={family:dict(id=model['id'], sha256=before[paths[family].relative_to(ROOT).as_posix()])
                for family, model in models.items()}, stats=stats, maximum_target_recompute_difference=maximum_target_difference,
        learned_forward_seconds=learned_seconds, exact_policy_seconds=exact_seconds,
        timing_scope='Sequential CPU wall time for batch predictions or direct objective values; excludes IO, normalization, candidate generation, sorting',
        frozen_source_hashes=before, after_source_hashes=after, weights_and_teacher_sources_unchanged=before==after,
        illustrative_failures=examples, custom_current_counterexample=custom_current_counterexample(),
        script_sha256=sha(__file__), elapsed_seconds=time.monotonic()-started)
    (args.output/'evaluation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k in ('stats','learned_forward_seconds','exact_policy_seconds',
        'maximum_target_recompute_difference','weights_and_teacher_sources_unchanged','elapsed_seconds')}, ensure_ascii=False, indent=2))
    if before!=after or maximum_target_difference>1e-12 or stats['all']['worse']:
        raise ValueError('Frozen benchmark contract failed; retain this run as diagnostic evidence')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--queries', type=Path,
        default=ROOT.parent/'study/ai-full-corpus-2026-09-30/plan-full/queries.sqlite')
    parser.add_argument('--output', type=Path, required=True)
    main(parser.parse_args())
