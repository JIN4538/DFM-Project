"""Imported-CAD audit of learned proposals and the actual final plan selection.

Never overwrites a run. Uses no user preference file and never trains a model.
Geometric remeasurement checks integration, not independent manufacturing truth.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import sys
import time
import traceback

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
PROCESSES = ('MEX', 'VPP', 'PBF_POLYMER', 'PBF_METAL')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    from amdfm.models import json_bytes
    with Path(path).open('xb') as stream:
        stream.write(json_bytes(value))


def source_snapshot(mode):
    # The other training agent may change unrelated RL files during the AM run.
    # Freeze the actual audited dependency chain, not unrelated app screens.
    files = ['scripts/audit_neural_cad.py', 'amdfm/analysis.py', 'amdfm/orientation.py', 'amdfm/recommendation.py',
             'amdfm/profiles.py', 'amdfm/models.py', 'amdfm/io.py', 'dfm/plan_learning.py',
             'dfm/machining.py', 'data/models/plan_ranker_v1.json',
             'data/models/plan_ranker_v1.manifest.json']
    files += (['amdfm/neural_orientation.py', 'amdfm/ai_search.py',
               'data/models/neural_orientation_v1.json', 'data/models/neural_orientation_v1.manifest.json']
              if mode == 'am' else ['dfm/rl_planner.py', 'dfm/enhanced_planning.py',
               'data/models/rl_planner_v1.json', 'data/models/rl_planner_v1.manifest.json'])
    return {name: sha(ROOT/name) for name in files}


def cases(mode, corpus=True):
    rows = []
    for folder in (('cad', 'machining') if mode == 'am' else ('machining',)):
        path = ROOT/'examples'/folder/'manifest.json'
        for item in json.loads(path.read_text(encoding='utf-8')):
            rows.append(dict(id=folder+'_'+item['id'], path=path.parent/item['file'],
                             sha256=item['sha256'], expected=item.get('expected', {})))
    if corpus:
        manifest = ROOT/'examples/corpus/manifest.json'
        for index, item in enumerate(json.loads(manifest.read_text(encoding='utf-8'))['files']):
            if item.get('kind') == 'geometry' and Path(item['path']).suffix.lower() in ('.step', '.stp'):
                rows.append(dict(id=f'corpus_{index:02d}', path=manifest.parent/item['path'], sha256=item['sha256'], expected={}))
    return rows


def selected_summary(plan):
    selected = plan.get('selected')
    return dict(status=plan.get('status'), source=plan.get('selection_source'),
                selected=None if selected is None else {key: selected.get(key) for key in
                    ('id', 'title', 'changes', 'outcomes', 'orientation', 'remaining', 'remaining_finding_ids')},
                model=plan.get('model'))


def common_objective(row, rows, process):
    fields = ['height_mm']
    if process != 'PBF_POLYMER': fields.insert(0, 'overhang_projected_area_sum_mm2')
    if process == 'MEX': fields.append('contact_triangle_area_mm2')
    regrets = []
    for field in fields:
        values = [r[field] for r in rows if r.get('build_fit') is not False]
        if row.get(field) is None or not values or any(v is None for v in values):
            return None
        lo, hi = min(values), max(values)
        term = 0. if hi-lo <= max(1e-12, abs(hi)*1e-12) else (row[field]-lo)/(hi-lo)
        if field == 'contact_triangle_area_mm2' and hi > lo: term = 1-term
        regrets.append(term)
    return .7*max(regrets)+.3*sum(regrets)/len(regrets)


def check_proposals(model, profile, report, reliable):
    from amdfm.orientation import measure_orientation
    checks = []
    for proposed in report.get('neural_search', {}).get('proposals', []):
        row = next(r for r in report['orientations'] if r['name'] == proposed['name'])
        truth = measure_orientation(model.mesh, row['direction'], profile, reliable_normals=reliable)
        failures, errors = [], {}
        for field in ('height_mm', 'overhang_projected_area_sum_mm2', 'contact_triangle_area_mm2',
                      'build_fit', 'transform', 'placed_extents_mm'):
            actual, expected = row[field], truth[field]
            if expected is None or isinstance(expected, bool):
                if actual is not expected: failures.append(field)
            else:
                aa, bb = np.asarray(actual, dtype=float), np.asarray(expected, dtype=float)
                if not np.allclose(aa, bb, atol=1e-8, rtol=1e-10): failures.append(field)
                errors[field] = float(np.max(np.abs(aa-bb)))
        checks.append(dict(name=row['name'], source=row['proposal_source'], failures=failures,
                           absolute_errors=errors, build_fit=row['build_fit']))
    return checks


def am_case(model, process, feedback):
    from amdfm.analysis import review
    from amdfm.ai_search import extend_review_orientations
    from amdfm.neural_orientation import MAX_FACES
    from amdfm.profiles import Profile
    from dfm.plan_learning import recommend_plan
    profile = Profile(process=process, minimum_wall_mm=1.2, build_volume_mm=None,
                      threshold_basis='Imported-CAD integration audit; explicit comparison setting')
    sweep = len(model.mesh.faces) <= MAX_FACES
    begin = time.perf_counter()
    report = review(model, profile, dense=True, compare=sweep)
    baseline_seconds = time.perf_counter()-begin
    before = deepcopy(report)
    first = recommend_plan(report, feedback_path=feedback)
    begin = time.perf_counter()
    enriched = extend_review_orientations(model, profile, report, timeout_s=8.)
    extension_seconds = time.perf_counter()-begin
    last = recommend_plan(enriched, feedback_path=feedback)
    errors = []
    if report != before: errors.append('Input report mutated')
    for field in ('findings', 'summary', 'geometry', 'profile', 'model_fingerprint', 'current_orientation'):
        if enriched[field] != report[field]: errors.append('Changed original '+field)
    reliable = report['summary']['review_status'] == 'geometry_review'
    checks = check_proposals(model, profile, enriched, reliable)
    if any(row['failures'] for row in checks): errors.append('Exact remeasurement mismatch')
    if enriched['neural_search'].get('predicted_values_used_as_measurements'): errors.append('Predictions used as measurements')
    for selected in (first.get('selected'), last.get('selected')):
        if selected and selected.get('orientation', {}).get('build_fit') is False:
            errors.append('Selected out-of-build candidate')
    comparison = dict(state='unavailable')
    if first.get('selected') and last.get('selected'):
        old, new = first['selected']['orientation'], last['selected']['orientation']
        common = enriched['orientations']+[old, new]
        old_cost, new_cost = [common_objective(row, common, process) for row in (old, new)]
        if old_cost is not None and new_cost is not None:
            delta = new_cost-old_cost
            comparison = dict(state='better' if delta < -1e-9 else 'worse' if delta > 1e-9 else 'equal',
                              base_cost=old_cost, enhanced_cost=new_cost, delta=delta,
                              basis='Actual selected plans; balanced .7 worst + .3 mean normalized geometric regret on shared measured union',
                              metric_deltas={field: new[field]-old[field] for field in
                                  ('height_mm', 'overhang_projected_area_sum_mm2', 'contact_triangle_area_mm2')
                                  if old.get(field) is not None and new.get(field) is not None})
    return dict(status='failed' if errors else 'passed', errors=errors, process=process,
                original_findings={row['id']: row['status'] for row in report['findings']},
                input_summary=report['summary'], geometry=report['geometry'],
                baseline=selected_summary(first), enhanced=selected_summary(last),
                neural_search=enriched['neural_search'], exact_checks=checks, comparison=comparison,
                baseline_sweep=sweep, baseline_seconds=baseline_seconds, extension_seconds=extension_seconds)


def cnc_case(model, tool_case, preferences, direction, feedback):
    from dfm.machining import MachiningProfile, review_machining
    from dfm.plan_learning import recommend_plan as prior
    from dfm.enhanced_planning import recommend_plan
    from dfm.rl_planner import evaluate_changes
    profile = MachiningProfile(**tool_case, hole_depth_ratio_limit=4., basis='Imported-CAD integration audit')
    report = review_machining(model, profile, direction=direction, visibility=False)
    report['review_context'] = {'priority': 'balanced'}
    before = deepcopy(report)
    first = prior(report, preferences=preferences, feedback_path=feedback)
    last = recommend_plan(report, preferences=preferences, feedback_path=feedback)
    errors, comparison = [], dict(state='unavailable')
    if report != before: errors.append('Input report mutated')
    checks = []
    for name, result in (('baseline', first), ('enhanced', last)):
        selected = result.get('selected')
        if selected:
            checked = evaluate_changes(report, selected['changes'], preferences=preferences)
            if not math.isfinite(checked['cost']): errors.append('Nonfinite plan cost')
            missing = set(checked['plan']['remaining_finding_ids'])-set(selected.get('remaining_finding_ids', []))
            if missing: errors.append('Missing remaining findings: '+str(missing))
            checks.append(dict(plan=name, conflicts=checked['conflicts'], cost=checked['cost']))
    if len(checks) == 2:
        a, b = [(row['conflicts'], round(row['cost'], 12)) for row in checks]
        comparison = dict(state='better' if b<a else 'worse' if b>a else 'equal', baseline=list(a), enhanced=list(b))
    return dict(status='failed' if errors else 'passed', errors=errors, tool=tool_case, preferences=preferences, direction=direction,
                original_findings={row['id']: row['status'] for row in report['findings']},
                baseline=selected_summary(first), enhanced=selected_summary(last),
                reinforcement_planning=last.get('reinforcement_planning'), exact_checks=checks, comparison=comparison)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--mode', choices=('am', 'cnc'), default='am')
    parser.add_argument('--no-corpus', action='store_true')
    parser.add_argument('--limit', type=int, default=0)
    parser.add_argument('--ids', nargs='+', help='Optional exact case IDs; retained in the run header')
    parser.add_argument('--cnc-axes', action='store_true', help='Inspect +Z, +X and +Y tool approaches')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    from amdfm.io import load_model
    from threadpoolctl import threadpool_limits
    frozen = source_snapshot(args.mode)
    plan = cases(args.mode, not args.no_corpus)
    if args.ids:
        missing = set(args.ids)-{row['id'] for row in plan}
        if missing: raise ValueError('Unknown case IDs: '+str(sorted(missing)))
        plan = [row for row in plan if row['id'] in args.ids]
    if args.limit: plan = plan[:args.limit]
    started = time.perf_counter()
    header = dict(schema='neural-cad-integration/1', mode=args.mode, started_utc=datetime.now(timezone.utc).isoformat(),
                  python=platform.python_version(), source_hashes=frozen, script_sha256=sha(__file__),
                  model_count=len(plan), personal_preferences='disabled; isolated nonexistent audit path',
                  requested_ids=args.ids, cnc_approaches='positive XYZ' if args.cnc_axes else 'positive Z',
                  geometry_scope='STEP files imported through production loader; no training or modification',
                  exact_scope='Separate geometry recomputation; not independent validation of all geometry formulas',
                  build_volume='unlimited', cnc_visibility='not run; unknown coverage must remain unresolved')
    write(args.out/'run.json', header)
    with (args.out/'audit_script.py').open('xb') as stream:
        stream.write(Path(__file__).read_bytes())
    records = []
    feedback = args.out/'no-user-preferences.json'
    with threadpool_limits(limits=1), (args.out/'records.jsonl').open('x', encoding='utf-8') as journal:
        for i, case in enumerate(plan, 1):
            begin = time.perf_counter()
            base = dict(id=case['id'], path=str(case['path'].relative_to(ROOT)), source_sha256=case['sha256'])
            try:
                if source_snapshot(args.mode) != frozen: raise RuntimeError('Audited source/model changed')
                if sha(case['path']) != case['sha256']: raise ValueError('Fixture manifest SHA mismatch')
                model = load_model(case['path'].read_bytes(), case['path'].name)
                base.update(model_fingerprint=model.fingerprint, import_seconds=time.perf_counter()-begin,
                            metadata={k: model.metadata.get(k) for k in
                                ('solid_count', 'cad_geometry_kind', 'unit_status', 'exact_volume_mm3', 'exact_area_mm2')})
                specs = PROCESSES if args.mode == 'am' else [
                    (tool, pref, direction) for tool in (dict(tool_diameter_mm=4., flute_length_mm=8., reach_mm=10.),
                                             dict(tool_diameter_mm=12., flute_length_mm=15., reach_mm=25.))
                    for pref in ({}, {'preserve_geometry': True}, {'allow_tool_change': False})
                    for direction in ([(0,0,1), (1,0,0), (0,1,0)] if args.cnc_axes else [(0,0,1)])]
                for spec in specs:
                    tick = time.perf_counter()
                    result = (am_case(model, spec, feedback) if args.mode == 'am' else cnc_case(model, *spec, feedback))
                    record = dict(base, **result, elapsed_seconds=time.perf_counter()-tick)
                    journal.write(json.dumps(record, ensure_ascii=False, allow_nan=False)+'\n')
                    journal.flush()
                    records.append(record)
                print(json.dumps(dict(index=i, total=len(plan), id=case['id'], elapsed_seconds=time.perf_counter()-begin,
                                      latest_status=records[-1]['status']), ensure_ascii=False), flush=True)
            except Exception as error:
                record = dict(base, status='error', error=str(error), traceback=traceback.format_exc(),
                              elapsed_seconds=time.perf_counter()-begin)
                journal.write(json.dumps(record, ensure_ascii=False, allow_nan=False)+'\n')
                journal.flush()
                records.append(record)
                print(json.dumps(dict(id=case['id'], error=str(error))), flush=True)
                if source_snapshot(args.mode) != frozen: break
    states = Counter(row['status'] for row in records)
    end_sources = source_snapshot(args.mode)
    summary = dict(**header, elapsed_seconds=time.perf_counter()-started, cases=len(records),
                   states=dict(states), source_unchanged=end_sources == frozen,
                   final_selection_comparison=dict(Counter(row.get('comparison', {}).get('state', 'not_run') for row in records)),
                   search_status=dict(Counter(row.get('neural_search', {}).get('status', 'not_applicable') for row in records)),
                   proposal_checks=sum(len(row.get('exact_checks', [])) for row in records),
                   failures=[dict(id=row['id'], process=row.get('process'), errors=row.get('errors', row.get('error')))
                             for row in records if row['status'] != 'passed'])
    summary['status'] = 'passed' if not states['error'] and not states['failed'] and end_sources == frozen else 'failed'
    write(args.out/'summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False, allow_nan=False), flush=True)
    return 0 if summary['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
