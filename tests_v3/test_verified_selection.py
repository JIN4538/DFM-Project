from copy import deepcopy
import math

import pytest

from dfm import enhanced_planning as enhanced, plan_learning as prior
from dfm.verified_selection import selection_score
from scripts.train_plan_model import selection_objective
from tests_v3.test_plan_learning import am_report, cnc_report


def test_policy_is_exact_frozen_training_target():
    import numpy as np
    random = np.random.default_rng(20260930)
    for _ in range(200):
        values = random.uniform(0, 1, len(prior.FEATURES)).tolist()
        values[0] = float(random.integers(2))
        assert selection_score(values) == selection_objective(values)
    with pytest.raises(ValueError):
        selection_score([math.nan]*len(prior.FEATURES))


def test_bad_ranker_cannot_override_measured_final_choice(monkeypatch, tmp_path):
    original = am_report()
    before = deepcopy(original)
    monkeypatch.setattr(prior, 'predict_score', lambda model, x: 10*x[2])
    approximate = prior.recommend_plan(original, feedback_path=tmp_path/'empty.json')
    final = enhanced.recommend_plan(original, feedback_path=tmp_path/'empty.json')
    assert approximate['selected']['id'] == 'orientation:A'
    assert final['selected']['id'] == 'orientation:B'
    assert final['verified_selection']['corrected']
    assert original == before
    direction = enhanced.orientation_recommendation(original, final)
    assert direction['recommended']['name'] == final['selected']['orientation']['name']


def vpp_report(rows, current):
    return dict(profile={'process': 'VPP', 'build_volume_mm': None},
                current_orientation=deepcopy(current), orientations=deepcopy(rows), findings=[],
                model={'unit_status': 'declared'}, summary={'review_status': 'geometry_review'})


def row(name, direction, overhang, height):
    return dict(name=name, direction=direction, overhang_projected_area_sum_mm2=overhang,
                height_mm=height, candidate_role='search', build_fit=None)


def test_custom_tradeoff_direction_can_be_best_without_dominating(tmp_path):
    a, b = row('A', [0, 0, 1], 0., 20.), row('B', [1, 0, 0], 10., 10.)
    current = row('custom', [0., .6, .8], 4., 14.)
    original = vpp_report([a, b], current)
    assert prior.recommend_plan(original, feedback_path=tmp_path/'empty.json')['status'] != 'keep'
    final = enhanced.recommend_plan(original, feedback_path=tmp_path/'empty.json')
    assert final['status'] == 'keep'
    assert final['selected']['orientation']['direction'] == current['direction']
    assert final['selected']['exact_score'] == pytest.approx(-.4)


def test_dominated_current_cannot_rescale_fixed_winner(tmp_path):
    a, b, c = row('A', [0, 0, 1], 0., 20.), row('B', [1, 0, 0], 4., 14.), row('C', [0, 1, 0], 10., 10.)
    rows = [a, b, c]
    ordinary = enhanced.recommend_plan(vpp_report(rows, a), feedback_path=tmp_path/'empty.json')
    extreme = enhanced.recommend_plan(vpp_report(rows, row('bad', [0., .6, .8], 100., 15.)),
                                     feedback_path=tmp_path/'empty.json')
    assert ordinary['selected']['id'] == extreme['selected']['id'] == 'orientation:B'
    assert {p['id']: p['exact_score'] for p in ordinary['ranking']} == {
        p['id']: p['exact_score'] for p in extreme['ranking']}


def test_policy_tie_keeps_current_tradeoff(tmp_path):
    a, b = row('A', [0, 0, 1], 0., 20.), row('B', [1, 0, 0], 10., 10.)
    result = enhanced.recommend_plan(vpp_report([a, b], b), feedback_path=tmp_path/'empty.json')
    assert result['status'] == 'keep'
    assert result['selected']['orientation']['direction'] == b['direction']


def test_model_absence_does_not_change_exact_choice(tmp_path):
    original = am_report()
    enabled = enhanced.recommend_plan(original, feedback_path=tmp_path/'empty.json')
    absent = enhanced.recommend_plan(original, feedback_path=tmp_path/'empty.json', model_path=tmp_path/'missing.json')
    assert enabled['selected']['id'] == absent['selected']['id']
    assert enabled['selected']['outcomes'] == absent['selected']['outcomes']
    assert absent['selection_source'] == 'verified_policy'


def test_actual_preference_can_change_tradeoff_but_not_conflict_gate(monkeypatch, tmp_path):
    monkeypatch.setattr(enhanced, 'propose_rl_plan', lambda *a, **k: {'proposal': None, 'status': 'unavailable'})
    path = tmp_path/'prefs.json'
    original = am_report()
    enhanced.record_plan_preference(original, 'orientation:C', feedback_path=path)
    final = enhanced.recommend_plan(original, feedback_path=path)
    assert final['selected']['id'] == 'orientation:C'
    assert final['selection_source'] == 'verified_policy+preference'
    cnc = enhanced.recommend_plan(cnc_report(), feedback_path=path)
    assert all(p['outcomes']['remaining_numeric_conflicts'] == 0 for p in cnc['ranking'])


def test_failed_build_space_current_stays_excluded(tmp_path):
    original = am_report()
    original['profile']['build_volume_mm'] = [10., 10., 10.]
    for r in original['orientations']:
        r['build_fit'] = True
    original['current_orientation'].update(direction=[0., .6, .8], build_fit=False,
                                           height_mm=.01, overhang_projected_area_sum_mm2=0.)
    final = enhanced.recommend_plan(original, feedback_path=tmp_path/'empty.json')
    assert final['selected'] and not final['selected']['keep_current']
    assert 'orientation:현재 사용자 방향' not in {p['id'] for p in final['ranking']}
