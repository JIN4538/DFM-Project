"""Compare frozen learned selection and verified selection on public STEP files.

CAD is loaded and measured here; all recommendations share those measurements.
This audits final decision quality under the project's disclosed objective. It
does not estimate external expert agreement or retrain a model.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from amdfm.analysis import review
from amdfm.io import load_model
from amdfm.profiles import Profile
from amdfm.recommendation import recommend_orientation
from dfm import enhanced_planning, plan_learning
from dfm.conclusion import summarize_conclusion
from dfm.machining import MachiningProfile
from dfm.rl_planner import evaluate_changes
from dfm.tool_recommendation import review_with_tool_recommendation


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def am_cost(report, plan, priority):
    """Independent arithmetic on the original fixed measured comparison range."""
    weighted = []
    weights = []
    names = {'height_mm': 'height', 'overhang_projected_area_sum_mm2': 'support',
             'contact_triangle_area_mm2': 'contact'}
    for criterion in recommend_orientation(report)['criteria']:
        value = plan['outcomes'][criterion['field']]
        low, high = criterion['minimum'], criterion['maximum']
        if criterion['constant']:
            regret = (value-low)/max(1., abs(low), abs(value))
        else:
            regret = (value-low)/(high-low)
        if criterion['direction'] == 'max':
            regret = -regret if criterion['constant'] else 1-regret
        weight = 3. if names[criterion['field']] == priority else 1.
        weighted.append(weight*regret)
        weights.append(weight)
    return [.7*max(weighted)/max(weights) + .3*sum(weighted)/sum(weights)] if weights else [0.]


def comparison(report, *, family, priority, preserve_geometry, feedback):
    prefs = dict(priority=priority, preserve_geometry=preserve_geometry, allow_tool_change=True)
    report = deepcopy(report)
    report['review_context'] = dict(report.get('review_context', {}), priority=priority,
                                    plan_preferences=prefs)
    before = json.dumps(report, sort_keys=True, ensure_ascii=False)
    model = ROOT/'data/models'/('plan_ranker_external_v3.json' if family == 'CNC' else 'plan_ranker_v1.json')
    start = time.monotonic()
    old = plan_learning.recommend_plan(report, preferences=prefs, feedback_path=feedback, model_path=model)
    old_seconds = time.monotonic()-start
    start = time.monotonic()
    new = enhanced_planning.recommend_plan(report, preferences=prefs, feedback_path=feedback)
    new_seconds = time.monotonic()-start
    a, b = old.get('selected'), new.get('selected')
    row = dict(priority=priority, preserve_geometry=preserve_geometry,
        old_status=old['status'], new_status=new['status'], old_reason=old.get('reason'), new_reason=new.get('reason'),
        old_id=(a or {}).get('id'), new_id=(b or {}).get('id'),
        old_title=(a or {}).get('title'), new_title=(b or {}).get('title'),
        old_seconds=old_seconds, new_seconds=new_seconds,
        old_ranking_count=len(old.get('ranking', [])), new_ranking_count=len(new.get('ranking', [])),
        verification=new.get('verified_selection'), rl=new.get('reinforcement_planning'),
        source_report_unchanged=before == json.dumps(report, sort_keys=True, ensure_ascii=False))
    conclusion = summarize_conclusion(report, plan_result=new)
    row['conclusion_same_plan'] = (conclusion.get('plan', {}).get('selected') or {}).get('id') == row['new_id']
    if family == 'AM' and b:
        direction = enhanced_planning.orientation_recommendation(report, new)
        row['direction_same_plan'] = direction.get('recommended', {}).get('direction') == b['orientation']['direction']
    if a and b:
        if family == 'AM':
            q_a, q_b = am_cost(report, a, priority), am_cost(report, b, priority)
        else:
            ac = evaluate_changes(report, a['changes'], preferences=prefs)
            bc = evaluate_changes(report, b['changes'], preferences=prefs)
            q_a, q_b = [ac['conflicts'], ac['cost']], [bc['conflicts'], bc['cost']]
        differences = [x-y for x, y in zip(q_b, q_a)]
        nonzero = next((d for d in differences if abs(d) > 1e-7), 0.)
        row.update(old_quality=q_a, new_quality=q_b, better=nonzero < 0, worse=nonzero > 0,
                   same=nonzero == 0, changed=row['old_id'] != row['new_id'])
    return row


def main(args):
    args.output.mkdir(parents=True, exist_ok=False)
    feedback = args.output/'absent-local-preferences.json'
    tracked = list(plan_learning.TEACHER_SOURCES) + ['dfm/rl_planner.py']
    tracked += [p.relative_to(ROOT).as_posix() for p in sorted((ROOT/'data/models').glob('*.json'))]
    before_sha = {p: sha(ROOT/p) for p in tracked}
    implementation = ('scripts/benchmark_verified_public_cad.py', 'dfm/verified_selection.py', 'dfm/enhanced_planning.py')
    implementation_before = {p: sha(ROOT/p) for p in implementation}
    manifest = json.loads((ROOT/'examples/public_demo/manifest.json').read_text(encoding='utf8'))
    results = []
    started = time.monotonic()
    for item in manifest:
        path = ROOT/'examples/public_demo'/item['file']
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != item['sha256']:
            raise ValueError('Demo SHA mismatch')
        entry = dict(file=item['file'], sha256=item['sha256'], queries=[])
        try:
            model = load_model(raw, item['file'], deflection_mm=.1, timeout_s=100)
            entry['cad'] = {key: model.metadata.get(key) for key in
                            ('cad_valid', 'solid_count', 'exact_volume_mm3', 'cad_face_count')}
            reports = {}
            for process in ('MEX', 'VPP', 'PBF_POLYMER', 'PBF_METAL'):
                report = review(model, Profile(process=process, minimum_wall_mm=1.2, minimum_hole_mm=2.), dense=True)
                reports[process] = report
                for priority in ('balanced', 'height', 'support', 'contact'):
                    entry['queries'].append(dict(process=process, **comparison(report, family='AM', priority=priority,
                        preserve_geometry=False, feedback=feedback)))
            cnc = review_with_tool_recommendation(model, MachiningProfile(), visibility=False)
            reports['CNC'] = cnc
            for priority in ('balanced', 'accuracy', 'tool_access'):
                for lock in (False, True):
                    entry['queries'].append(dict(process='CNC', **comparison(cnc, family='CNC', priority=priority,
                        preserve_geometry=lock, feedback=feedback)))
            stem = path.stem
            (args.output/(stem+'-measured-reports.json')).write_text(
                json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf8')
        except Exception as error:
            entry['error'] = repr(error)
        results.append(entry)
        print(json.dumps(dict(file=item['file'], queries=len(entry['queries']), error=entry.get('error')), ensure_ascii=False), flush=True)
        (args.output/'progress.json').write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf8')
    all_rows = [r for e in results for r in e['queries']]
    stats = {}
    for family in ('AM', 'CNC'):
        rows = [r for r in all_rows if (r['process'] == 'CNC') == (family == 'CNC')]
        stats[family] = dict(queries=len(rows), compared=sum('old_quality' in r for r in rows),
            better=sum(r.get('better', False) for r in rows), same=sum(r.get('same', False) for r in rows),
            worse=sum(r.get('worse', False) for r in rows), changed=sum(r.get('changed', False) for r in rows),
            old_unavailable=sum(r['old_status']=='unavailable' for r in rows),
            new_unavailable=sum(r['new_status']=='unavailable' for r in rows),
            conclusion_disagreement=sum(not r['conclusion_same_plan'] for r in rows),
            direction_disagreement=sum(not r.get('direction_same_plan', True) for r in rows),
            old_seconds=sum(r['old_seconds'] for r in rows), new_seconds=sum(r['new_seconds'] for r in rows))
    after_sha = {p: sha(ROOT/p) for p in tracked}
    implementation_after = {p: sha(ROOT/p) for p in implementation}
    result = dict(scope='Actual public STEP measurements; frozen learned ranking versus exact policy selection on measured candidates. '
        'AM fixed 26-direction search; no extra neural direction search or wall run; CNC automated missing tool dimensions; '
        'empty local feedback; no new fitting. Quality is project policy cost, not independent expert accuracy.',
        files=len(results), completed_files=sum('error' not in e for e in results), stats=stats,
        seconds=time.monotonic()-started, model_and_teacher_sha256_before=before_sha,
        model_and_teacher_sha256_after=after_sha, model_and_teacher_unchanged=before_sha==after_sha,
        implementation_sha256_before=implementation_before, implementation_sha256_after=implementation_after,
        implementation_unchanged=implementation_before==implementation_after,
        source_reports_unchanged=all(r['source_report_unchanged'] for r in all_rows), results=results)
    (args.output/'evaluation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({k: v for k, v in result.items() if k not in
        ('results', 'model_and_teacher_sha256_before', 'model_and_teacher_sha256_after')}, ensure_ascii=False), flush=True)
    if not result['model_and_teacher_unchanged'] or not result['implementation_unchanged']:
        raise ValueError('Benchmark sources changed during execution; preserve this run and repeat against final sources')
    if any(s['worse'] or s['conclusion_disagreement'] or s['direction_disagreement'] for s in stats.values()):
        raise ValueError('Decision comparison found a regression or disagreement')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    main(parser.parse_args())
