"""Arbitrate exact-checked sequential proposals without changing the old model."""
from __future__ import annotations

from copy import deepcopy
import math
from pathlib import Path

from . import plan_learning as prior
from .rl_planner import propose_rl_plan, evaluate_changes
from .compound_planning import propose_compound_plan


def same_changes(left, right):
    if len(left) != len(right):
        return False
    by_field = {x['field']: x for x in right}
    return all(x['field'] in by_field and x.get('cad_face_id') == by_field[x['field']].get('cad_face_id')
               and all(math.isclose(float(x[k]), float(by_field[x['field']][k]), rel_tol=1e-10, abs_tol=1e-9)
                       for k in ('before', 'after')) for x in left)


def restore_measured_candidates(report, result, prefs):
    """Recover pre-Pareto plans without changing a frozen model's teacher."""
    raw, _, _ = prior._cnc_candidates(report, prefs)
    output = deepcopy(result)
    ranking = output.setdefault('ranking', [])
    for candidate in raw:
        if not any(same_changes(candidate['changes'], old['changes']) for old in ranking):
            ranking.append(candidate)
    return output


def am_comparison_reference(report):
    """Use the same measured scales for selection and its optional explanation."""
    rows = (report.get('neural_search') or {}).get('selection_reference_rows')
    if not rows:
        return report
    reference = deepcopy(report)
    reference['orientations'] = deepcopy(rows)
    return reference


def recommend_plan(report, *, preferences=None, feedback_path=None, model_path=None):
    from .verified_selection import include_current_direction, arbitrate
    measured = include_current_direction(report)
    cnc = prior._process(measured) in ('CNC', 'MILLING_3AXIS')
    if cnc and any(h.get('entry_blocked') for h in measured.get('verified_hole_inventory', {}).get('holes', [])):
        # Changing diameters cannot open the blind floor. Re-review a different
        # setup before asking the frozen numeric planner to propose tool edits.
        return dict(status='unavailable', reason='먼저 구멍이 열린 쪽으로 방향을 바꾸세요.', selected=None,
                    ranking=[], selection_source='verified_hole_entry', learning={},
                    entry_direction_required=True)
    if model_path is None and cnc:
        directory = Path(__file__).resolve().parents[1] / 'data/models'
        for filename in ('plan_ranker_external_v3.json', 'plan_ranker_external_v2.json'):
            external = directory / filename
            if external.exists():
                model_path = external
                break
    result = prior.recommend_plan(measured, preferences=preferences,
                                  feedback_path=feedback_path, model_path=model_path)
    if not cnc:
        from .am_joint_planning import combine_am_plan
        reference = am_comparison_reference(report)
        return combine_am_plan(measured, arbitrate(measured, result, preferences=preferences,
                                                   feedback_path=feedback_path, normalization_report=reference), preferences)
    try:
        prefs = prior._preferences(measured, preferences)
    except (ValueError, TypeError):
        return result
    try:
        result = restore_measured_candidates(measured, result, prefs)
    except (ValueError, KeyError, TypeError, OverflowError):
        pass
    proposal = propose_rl_plan(measured, preferences=prefs)
    record = {key: value for key, value in proposal.items() if key != 'proposal'}
    record.update(adopted=False, policy='minimum exact conflicts, Pareto gate, common exact trade-off and local preference')
    candidate = proposal.get('proposal')
    proposal_id = None
    if candidate and result.get('ranking'):
        try:
            checked = evaluate_changes(measured, candidate['changes'], preferences=prefs)
            candidate = deepcopy(candidate)
            for key in ('remaining', 'remaining_finding_ids', 'covered_finding_ids', 'outcomes',
                        '_metrics', '_dominance', '_baseline', 'planning_cost', 'title', 'keep_current',
                        'verified', 'availability', 'orientation', 'family', 'verification_scope', 'conflict_details'):
                candidate[key] = checked['plan'][key]
            record.update(proposal_conflicts=checked['conflicts'], proposal_cost=checked['cost'],
                          steps=candidate.get('steps', []))
            old_checked = [evaluate_changes(measured, old['changes'], preferences=prefs)
                           for old in result['ranking']]
            best = min(old_checked, key=lambda x: (x['conflicts'], x['cost']))
            record.update(baseline_conflicts=best['conflicts'], baseline_cost=best['cost'])
            if any(same_changes(candidate['changes'], old['changes']) for old in result['ranking']):
                record['reason'] = '동일한 기존 개선안이 있어 중복을 제거했습니다'
            elif checked['conflicts'] > best['conflicts']:
                record['reason'] = '수치 충돌이 더 적은 기존 개선안을 유지했습니다'
            else:
                proposal_id = candidate['id']
                result = deepcopy(result)
                result['ranking'].append(candidate)
        except (ValueError, KeyError, TypeError, OverflowError, IndexError) as error:
            record['reason'] = '순차 개선안 재검산 제외: ' + str(error)
    compound = propose_compound_plan(measured, preferences=prefs)
    # Timing belongs in benchmarks, not the review's stable decision payload.
    # Opening/closing a location view must not alter the recorded conclusion.
    compound_record = {key: value for key, value in compound.items() if key not in ('proposal', 'seconds')}
    compound_record['adopted'] = False
    compound_id = None
    candidate = compound.get('proposal')
    if candidate and result.get('ranking'):
        try:
            checked = evaluate_changes(measured, candidate['changes'], preferences=prefs)
            if any(same_changes(candidate['changes'], old['changes']) for old in result['ranking']):
                compound_record['reason'] = '동일한 기존 개선안을 유지했습니다'
            elif checked['conflicts'] > min(evaluate_changes(measured, old['changes'], preferences=prefs)['conflicts'] for old in result['ranking']):
                compound_record['reason'] = '충돌이 더 적은 기존 개선안을 유지했습니다'
            else:
                candidate = deepcopy(candidate)
                for key in ('remaining', 'remaining_finding_ids', 'covered_finding_ids', 'outcomes',
                            '_metrics', '_dominance', '_baseline', 'planning_cost', 'keep_current',
                            'verified', 'availability', 'orientation', 'family', 'verification_scope', 'conflict_details'):
                    candidate[key] = checked['plan'][key]
                compound_id = candidate['id']
                result['ranking'].append(candidate)
        except (ValueError, KeyError, TypeError, OverflowError, IndexError) as error:
            compound_record['reason'] = '부위별 개선안 재검산 제외: ' + str(error)
    result = arbitrate(measured, result, preferences=prefs, feedback_path=feedback_path)
    if proposal_id:
        record['adopted'] = (result.get('selected') or {}).get('id') == proposal_id
        record['reason'] = ('치수 재검산과 동일 기준 비교를 통과한 순차 개선안을 선택했습니다' if record['adopted']
                            else '동일 기준으로 비교하여 기존 추천을 유지했습니다')
        if record['adopted']:
            result['selection_source'] = 'deep_rl+preference' if result.get('learning', {}).get('choices') else 'deep_rl_verified'
    result['reinforcement_planning'] = record
    if compound_id:
        compound_record['adopted'] = (result.get('selected') or {}).get('id') == compound_id
        if compound_record['adopted']:
            result['selection_source'] = ('learned_compound_verified' if compound.get('search', {}).get('used_learning') else 'exact_compound_verified')
    result['compound_planning'] = compound_record
    return result


def orientation_recommendation(report,plan_result=None):
    from .am_joint_planning import direction_result
    plan_result = plan_result or recommend_plan(report)
    result = direction_result(am_comparison_reference(report),plan_result)
    if result.get('recommended'):
        result['policy']['score_meaning'] = 'exact measured trade-off score plus explicit local preference; lower is preferred'
        result['policy']['version'] = plan_result.get('verified_selection', {}).get('version', result['policy'].get('version'))
    return result


def record_plan_preference(report, chosen_id, *, preferences=None, feedback_path=None):
    """Same local pairwise learner, including a verified new sequential plan."""
    prefs = prior._preferences(report, preferences)
    result = recommend_plan(report, preferences=prefs, feedback_path=feedback_path)
    plans = result['ranking']
    chosen = next((p for p in plans if p['id'] == chosen_id), None)
    if chosen is None:
        raise ValueError('현재 검증된 후보에서 선택하세요')
    differences = [[a-b for a, b in zip(chosen['_features'], other['_features'])]
                   for other in plans if other['id'] != chosen_id]
    differences = [d for d in differences if any(abs(v) > 1e-12 for v in d)]
    if not differences:
        raise ValueError('동일한 후보끼리는 선호를 학습하지 않습니다')
    path = prior._feedback_path(feedback_path)
    data = prior._read_feedback(path)
    scope = prior._scope(report, prefs)
    old = data['scopes'].get(scope, {'choices': 0, 'pairs': [], 'weights': [0.] * len(prior.FEATURES)})
    pairs = (old['pairs'] + differences)[-300:]
    weights = [0.] * len(prior.FEATURES)
    for _ in range(100):
        for i, delta in enumerate(pairs):
            margin = sum(w*d for w, d in zip(weights, delta))
            gradient = 1 / (1 + math.exp(max(-30., min(30., margin))))
            rate = .04 * (2 if i >= len(pairs) - len(differences) else 1)
            weights = [max(-10., min(10., w + rate * (gradient*d - .01*w))) for w, d in zip(weights, delta)]
    data['scopes'][scope] = dict(choices=old['choices'] + 1, pairs=pairs, weights=weights)
    prior._write_feedback(path, data)
    return {'choices': old['choices'] + 1, 'scope': scope, 'path': str(path)}
