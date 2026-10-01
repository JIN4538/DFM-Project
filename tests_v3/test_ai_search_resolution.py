from copy import deepcopy
from pathlib import Path

from amdfm.ai_search import _filter_subresolution_height_proposals, extend_review_orientations
from amdfm.profiles import Profile


def inputs(base_height=20., candidate_height=19.999):
    baseline = [dict(name='+Z', height_mm=base_height, build_fit=True)]
    row = dict(name='AI 1', height_mm=candidate_height, build_fit=True,
               proposal_source='deep_neural_surrogate')
    extra = dict(rows=deepcopy(baseline)+[row], metadata=dict(added_count=1, proposals=[deepcopy(row)]))
    metadata = dict(source_format='step', tessellation=dict(requested_linear_deflection_mm=.05))
    return baseline, extra, metadata


def test_small_height_change_is_not_promoted_but_raw_values_remain():
    baseline, extra, metadata = inputs()
    recorded = deepcopy(extra['metadata']['proposals'])
    _filter_subresolution_height_proposals(extra, baseline, Profile(process='PBF_POLYMER'), metadata)
    assert extra['metadata']['added_count'] == 0
    assert extra['metadata']['measured_count'] == 1
    assert extra['metadata']['proposals'] == recorded
    assert [r['name'] for r in extra['rows']] == ['+Z']
    assert extra['metadata']['height_resolution_filter']['threshold_mm'] == .02
    assert extra['rows'][0]['pareto']


def test_geometry_height_queries_use_same_precision_gate_and_filter_reference():
    baseline, extra, metadata = inputs()
    extra['rows'][-1]['proposal_source']='exact_height_geometry'
    extra['metadata']['selection_reference_rows']=deepcopy(extra['rows'])
    _filter_subresolution_height_proposals(extra,baseline,Profile(process='PBF_POLYMER'),metadata)
    assert [r['name'] for r in extra['rows']]==['+Z']
    assert [r['name'] for r in extra['metadata']['selection_reference_rows']]==['+Z']
    assert extra['metadata']['proposals'][0]['height_mm']==19.999


def test_use_effective_deflection_and_preserve_substantial_gain():
    baseline, extra, metadata = inputs(base_height=1000., candidate_height=999.8)
    _filter_subresolution_height_proposals(extra, baseline, Profile(process='PBF_POLYMER'), metadata)
    assert extra['metadata']['added_count'] == 1
    metadata['tessellation']['body_attempts'] = [dict(effective_deflection_mm=.2)]
    _filter_subresolution_height_proposals(extra, baseline, Profile(process='PBF_POLYMER'), metadata)
    assert extra['metadata']['added_count'] == 0
    assert extra['metadata']['height_resolution_filter']['threshold_mm'] == .4


def test_build_space_rescue_is_kept_even_if_height_gain_is_tiny():
    baseline, extra, metadata = inputs()
    baseline[0]['build_fit'] = False
    extra['rows'][0]['build_fit'] = False
    _filter_subresolution_height_proposals(extra, baseline, Profile(process='PBF_POLYMER'), metadata)
    assert extra['metadata']['added_count'] == 1


def test_current_only_direction_does_not_change_proposal_screening():
    baseline, extra, metadata = inputs(candidate_height=19.)
    baseline.append(dict(name='current', height_mm=18.99, build_fit=True, candidate_role='current_only'))
    _filter_subresolution_height_proposals(extra, baseline, Profile(process='PBF_POLYMER'), metadata)
    assert extra['metadata']['added_count'] == 1


def test_small_planar_part_retains_large_relative_improvement():
    baseline, extra, metadata = inputs(base_height=.08, candidate_height=.02)
    _filter_subresolution_height_proposals(extra, baseline, Profile(process='PBF_POLYMER'), metadata)
    assert extra['metadata']['added_count'] == 1


def test_unknown_fit_does_not_suppress_confirmed_fit_with_space_constraint():
    baseline, extra, metadata = inputs()
    baseline[0]['build_fit'] = None
    profile = Profile(process='PBF_POLYMER', build_volume_mm=(30., 30., 30.))
    _filter_subresolution_height_proposals(extra, baseline, profile, metadata)
    assert extra['metadata']['added_count'] == 1


def test_other_body_precision_does_not_suppress_selected_body_improvement():
    baseline, extra, metadata = inputs(base_height=1000., candidate_height=999.8)
    metadata['selected_body'] = 1
    metadata['tessellation']['body_attempts'] = [dict(body_id=1, effective_deflection_mm=.05),
                                                dict(body_id=2, effective_deflection_mm=.5)]
    _filter_subresolution_height_proposals(extra, baseline, Profile(process='PBF_POLYMER'), metadata)
    assert extra['metadata']['added_count'] == 1


def test_without_cad_precision_or_with_other_objectives_no_height_only_filter():
    for process, source in [('MEX', 'step'), ('PBF_METAL', 'step'), ('VPP', 'step'), ('PBF_POLYMER', 'stl')]:
        baseline, extra, metadata = inputs()
        metadata['source_format'] = source
        _filter_subresolution_height_proposals(extra, baseline, Profile(process=process), metadata)
        assert extra['metadata']['added_count'] == 1
    baseline, extra, metadata = inputs()
    metadata['tessellation'] = {}
    _filter_subresolution_height_proposals(extra, baseline, Profile(process='PBF_POLYMER'), metadata)
    assert extra['metadata']['added_count'] == 1


def test_real_sphere_does_not_gain_height_from_new_mesh_orientations():
    from amdfm.io import load_model
    from amdfm.analysis import review
    path = Path(__file__).parents[1] / 'examples/cad/12_sphere.step'
    model = load_model(path.read_bytes(), path.name)
    profile = Profile(process='PBF_POLYMER')
    report = review(model, profile, dense=True)
    original = deepcopy(report)
    result = extend_review_orientations(model, profile, report, timeout_s=30.)
    assert result['neural_search']['status'] == 'complete'
    assert result['neural_search']['measured_count'] > 0
    assert len(result['orientations']) == len(report['orientations']) + result['neural_search']['added_count']
    before_minimum = min(r['height_mm'] for r in report['orientations'])
    assert min(r['height_mm'] for r in result['orientations']) == before_minimum
    assert report == original
    assert max(r['height_mm'] for r in result['orientations']) < 20.001
