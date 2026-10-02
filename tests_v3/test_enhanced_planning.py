from copy import deepcopy

from dfm import enhanced_planning as enhanced
from dfm import plan_learning as prior
from dfm.rl_planner import make_problem, plan_from_state
from dfm.verified_selection import arbitrate


def report():
    return dict(process='MILLING_3AXIS', profile=dict(machine='test', material='test',
        tool_diameter_mm=4., flute_length_mm=8., reach_mm=10., hole_depth_ratio_limit=None),
        findings=[dict(id='cnc_input', status='observed', measurements={'cad_feature_dimensions_available': True}),
          dict(id='cnc_holes', status='not_detected', measurements={'cylindrical_faces': []}),
          dict(id='cnc_curved_corners', status='not_detected', measurements={'cylindrical_faces': []}),
          dict(id='cnc_rectangular_pockets', status='attention', measurements={
              'pockets': [dict(floor_face_id=42, width_mm=3., wall_height_mm=20.)]})])


def test_duplicate_final_effects_are_independent_of_edit_order(monkeypatch, tmp_path):
    original = report()
    expected = arbitrate(original, prior.recommend_plan(original, feedback_path=tmp_path/'prefs.json'), feedback_path=tmp_path/'prefs.json')
    candidate = deepcopy(expected['selected'])
    candidate['changes'].reverse()
    monkeypatch.setattr(enhanced, 'propose_rl_plan', lambda *a, **kw: {'proposal': candidate, 'status': 'proposed'})
    got = enhanced.recommend_plan(original, feedback_path=tmp_path/'prefs.json', model_path=prior.MODEL_PATH)
    assert got['selected'] == expected['selected']
    assert len(got['ranking']) == len(expected['ranking'])
    assert '중복' in got['reinforcement_planning']['reason']


def test_network_cannot_exchange_added_conflicts_for_lower_edit_cost(monkeypatch, tmp_path):
    original = report()
    problem = make_problem(original)
    candidate = plan_from_state(problem, problem['initial'], [])
    # Fake optimistic predicted metadata must be ignored by arbitration.
    candidate['outcomes']['remaining_numeric_conflicts'] = 0
    candidate['planning_cost'] = -100.
    monkeypatch.setattr(enhanced, 'propose_rl_plan', lambda *a, **kw: {'proposal': candidate, 'status': 'proposed'})
    got = enhanced.recommend_plan(original, feedback_path=tmp_path/'prefs.json')
    audit = got['reinforcement_planning']
    assert not audit['adopted']
    assert audit['proposal_conflicts'] > audit['baseline_conflicts']
    assert got['selected']['id'] != candidate['id']
    assert original == report()


def test_changed_before_value_or_face_is_rejected(monkeypatch, tmp_path):
    original = report()
    candidate = deepcopy(prior.recommend_plan(original, feedback_path=tmp_path/'prefs.json')['selected'])
    candidate['changes'][0]['before'] += 100.
    monkeypatch.setattr(enhanced, 'propose_rl_plan', lambda *a, **kw: {'proposal': candidate, 'status': 'proposed'})
    got = enhanced.recommend_plan(original, feedback_path=tmp_path/'prefs.json')
    assert not got['reinforcement_planning']['adopted']
    assert '재검산 제외' in got['reinforcement_planning']['reason']


def test_missing_proposal_model_retains_verified_recommendation_and_preferences(monkeypatch, tmp_path):
    original = report()
    path = tmp_path/'prefs.json'
    monkeypatch.setattr(enhanced, 'propose_rl_plan', lambda *a, **kw: {'proposal': None, 'status': 'unavailable'})
    expected = arbitrate(original, prior.recommend_plan(original, feedback_path=path), feedback_path=path)
    got = enhanced.recommend_plan(original, feedback_path=path, model_path=prior.MODEL_PATH)
    assert got['selected'] == expected['selected']
    candidate = got['alternatives'][0]
    enhanced.record_plan_preference(original, candidate['id'], feedback_path=path)
    updated = enhanced.recommend_plan(original, feedback_path=path)
    assert updated['learning']['choices'] == 1
    external=enhanced.Path(__file__).resolve().parents[1]/'data/models/plan_ranker_external_v3.json'
    assert arbitrate(original, prior.recommend_plan(original, feedback_path=path,model_path=external), feedback_path=path)['selected'] == updated['selected']


def test_fewer_conflicts_rebuilds_semantics_and_removes_inadmissible_preferences(monkeypatch, tmp_path):
    original = report()
    path = tmp_path/'prefs.json'
    genuine = prior.recommend_plan(original, feedback_path=path)
    candidate = deepcopy(genuine['selected'])
    problem = make_problem(original)
    unchanged = plan_from_state(problem, problem['initial'], [])
    candidate.update(title='wrong title', keep_current=True, conflict_details=['wrong'])
    baseline = {**genuine, 'selected': unchanged, 'ranking': [unchanged], 'alternatives': []}
    # Deliberately omit the recovered candidates to isolate the independent
    # sequential-proposal verification contract in this adversarial test.
    monkeypatch.setattr(enhanced, 'restore_measured_candidates', lambda report, result, prefs: result)
    monkeypatch.setattr(enhanced, 'propose_compound_plan', lambda *args, **kwargs: {'status':'unavailable','proposal':None})
    monkeypatch.setattr(prior, 'recommend_plan', lambda *a, **kw: deepcopy(baseline))
    monkeypatch.setattr(enhanced, 'propose_rl_plan', lambda *a, **kw: {'proposal': candidate, 'status': 'proposed'})
    got = enhanced.recommend_plan(original, feedback_path=path)
    assert got['reinforcement_planning']['adopted']
    assert got['selected']['title'] != 'wrong title'
    assert got['selected']['keep_current'] is False
    assert got['selected']['conflict_details'] != ['wrong']
    assert got['alternatives'] == []
    assert [row['id'] for row in got['ranking']] == [candidate['id']]


def test_disabled_and_repeat_search_strip_both_proposal_sources(monkeypatch):
    from amdfm import ai_search
    from amdfm.profiles import Profile
    from types import SimpleNamespace
    base = {'name': '+Z', 'height_mm': 3.}
    original = dict(orientations=[base, {'name': '面', 'proposal_source': 'geometric_facet_seed'},
                                 {'name': 'AI', 'proposal_source': 'deep_neural_surrogate'}],
                    neural_search={'proposals': [{'name': '面'}, {'name': 'AI'}]},
                    summary={'review_status': 'geometry_review'})
    def enrich(mesh, profile, rows, **kwargs):
        assert [row['name'] for row in rows] == ['+Z']
        return {'rows': rows + [{'name': 'new'}], 'metadata': {'added_count': 1}}
    monkeypatch.setattr(ai_search, 'enrich_ensemble', enrich)
    model = SimpleNamespace(mesh=None)
    disabled = ai_search.extend_review_orientations(model, Profile(), original, enabled=False)
    assert [row['name'] for row in disabled['orientations']] == ['+Z']
    assert disabled['orientation_search']['neural_added_count'] == 0
    repeated = ai_search.extend_review_orientations(model, Profile(), original)
    assert [row['name'] for row in repeated['orientations']] == ['+Z', 'new']
    assert len(original['orientations']) == 3


def test_disabling_search_restores_baseline_pareto_flags():
    import trimesh
    from types import SimpleNamespace
    from amdfm.ai_search import extend_review_orientations
    from amdfm.orientation import compare_orientations
    from amdfm.profiles import Profile
    mesh = trimesh.creation.box(extents=[40.,30.,.3])
    mesh.apply_transform(trimesh.transformations.euler_matrix(.42,.17,.83))
    profile = Profile()
    base = compare_orientations(mesh, profile, dense=True)
    report = dict(orientations=base, summary={'review_status':'geometry_review'})
    model = SimpleNamespace(mesh=mesh)
    extended = extend_review_orientations(model, profile, report)
    assert extended['neural_search']['added_count'] > 0
    restored = extend_review_orientations(model, profile, extended, enabled=False)
    assert {r['name']:r['pareto'] for r in restored['orientations']} == {r['name']:r['pareto'] for r in base}
