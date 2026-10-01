from copy import deepcopy
import numpy as np
import pytest
import trimesh
from amdfm import full_search as module, geometry_guided_search as guided
from amdfm.profiles import Profile
from amdfm.orientation import compare_orientations,measure_orientation


def fixture(profile=None):
    mesh=trimesh.creation.box((37.,11.,3.))
    mesh.apply_transform(trimesh.transformations.euler_matrix(.3,.58,-.24))
    profile=profile or Profile()
    return mesh,profile,compare_orientations(mesh,profile,dense=True)


def test_product_guided_queries_still_use_geometry_engine_and_retain_old_rows():
    from amdfm.ensemble_search import enrich_ensemble
    mesh,profile,baseline=fixture()
    snapshot=deepcopy(baseline)
    old=enrich_ensemble(mesh,profile,baseline,timeout_s=30)
    result=module.enrich_full(mesh,profile,baseline,timeout_s=30)
    ignore_flags=lambda rows:[{k:v for k,v in r.items() if k!='pareto'} for r in rows]
    assert ignore_flags(result['rows'][:len(old['rows'])])==ignore_flags(old['rows'])
    assert result['metadata']['geometry_guided_acquisition']['requested_full_queries']==6
    assert result['metadata']['full_added_count']==6 and result['metadata']['guided_added_count']==6
    assert result['metadata']['added_count']<=30
    assert baseline==snapshot
    for row in result['rows'][len(old['rows']):]:
        expected=measure_orientation(mesh,row['direction'],profile)
        for field in ('height_mm','overhang_projected_area_sum_mm2','contact_triangle_area_mm2','build_fit'):
            assert row[field]==expected[field]
        if row.get('acquisition_method'):
            assert row['learned_acquisition_component']=='downward projected-area acquisition only'


def test_reference_rows_preserve_old_exact_choice_and_allow_real_improvements(tmp_path):
    from dfm.enhanced_planning import recommend_plan,orientation_recommendation
    from tests_v3.test_verified_selection import row,vpp_report
    rows=[row('A',[0,0,1],0.,20.),row('B',[1,0,0],10.,10.),row('C',[0,1,0],4.,14.)]
    original=vpp_report(rows,rows[0])
    old=recommend_plan(original,feedback_path=tmp_path/'empty.json')
    extended=deepcopy(original)
    extended['neural_search']=dict(selection_reference_rows=deepcopy(rows))
    extended['orientations'].append(row('worse',[0.,.6,.8],1000.,14.))
    same=recommend_plan(extended,feedback_path=tmp_path/'empty.json')
    assert same['selected']['id']==old['selected']['id']
    assert same['selected']['exact_score']==old['selected']['exact_score']
    assert orientation_recommendation(extended,same)['criteria']==orientation_recommendation(original,old)['criteria']
    extended['orientations'].append(row('improved',[.6,0.,.8],3.,13.))
    better=recommend_plan(extended,feedback_path=tmp_path/'empty.json')
    assert better['selected']['id']=='orientation:improved'
    assert better['selected']['exact_score']>old['selected']['exact_score']


def test_pure_height_queries_are_not_counted_as_neural_proposals():
    mesh,profile,baseline=fixture(Profile(process='PBF_POLYMER'))
    result=module.enrich_full(mesh,profile,baseline,priority='height',timeout_s=30)
    record=result['metadata']
    rows=[r for r in result['rows'] if r.get('acquisition_method')]
    assert rows and len(rows)==record['geometry_query_count']==record['guided_added_count']
    assert all(r['proposal_source']=='exact_height_geometry' and r['learned_acquisition_component'] is None for r in rows)
    assert record['added_count']==record['neural_query_count']+record['facet_query_count']+record['geometry_query_count']


def test_html_direction_uses_same_final_decision_as_screen(monkeypatch,tmp_path):
    from amdfm.analysis import review
    from amdfm.io import load_model
    from amdfm.presentation import html_report
    from dfm import enhanced_planning
    from tests_v3.test_verified_selection import row
    mesh=trimesh.creation.box((37.,11.,3.))
    model=load_model(mesh.export(file_type='stl'),'test.stl',dimensions_confirmed=True)
    report=review(model,Profile(process='VPP'),dense=True)
    rows=[row('A',[0,0,1],0.,20.),row('B',[1,0,0],10.,10.),row('C',[0,1,0],4.,14.)]
    for r in rows:
        r.update(transform=report['current_orientation']['transform'],pareto=True,contact_triangle_area_mm2=0.)
    worse=deepcopy(rows[2])
    worse.update(name='worse',direction=[0,.6,.8],overhang_projected_area_sum_mm2=1000.)
    report['orientations']=deepcopy(rows)+[worse]
    report['current_orientation']=deepcopy(rows[0])
    report['neural_search']={'selection_reference_rows':deepcopy(rows)}
    final=enhanced_planning.recommend_plan(report,feedback_path=tmp_path/'empty.json')
    expected=enhanced_planning.orientation_recommendation(report,final)
    real=enhanced_planning.orientation_recommendation
    calls=[]
    def capture(*args,**kwargs):
        result=real(*args,**kwargs)
        calls.append(result)
        return result
    monkeypatch.setattr(enhanced_planning,'orientation_recommendation',capture)
    document=html_report(report).decode('utf8')
    assert expected['recommended']['name']=='C'
    assert calls and all(r['recommended']['name']=='C' for r in calls)
    assert expected['title'] in document


def test_current_only_direction_is_excluded_from_acquisition_pool(monkeypatch):
    mesh,profile,baseline=fixture()
    current=measure_orientation(mesh,np.asarray([.21,.63,.75]),profile)
    current.update(name='현재',candidate_role='current_only')
    baseline.append(current)
    original=guided.rank_geometry_guided_queries
    def audit(*args,**kwargs):
        directions=np.asarray(args[3])
        assert np.all(directions@current['direction']<1-1e-10)
        return original(*args,**kwargs)
    monkeypatch.setattr(guided,'rank_geometry_guided_queries',audit)
    result=module.enrich_full(mesh,profile,baseline,timeout_s=30)
    assert 'geometry_guided_acquisition' in result['metadata']


def test_outside_scope_and_failed_new_selector_keep_legacy_queries(monkeypatch):
    monkeypatch.setattr(module,'refined_directions',lambda *args:[])
    mesh,profile,baseline=fixture(Profile(overhang_angle_deg=60.))
    legacy=module.enrich_full(mesh,profile,baseline,timeout_s=30)
    assert 'geometry_guided_acquisition' not in legacy['metadata']
    def fail(*args,**kwargs):raise ValueError('experimental acquisition unavailable')
    monkeypatch.setattr(guided,'rank_geometry_guided_queries',fail)
    result=module.enrich_full(mesh,profile,baseline,timeout_s=30)
    assert result['rows']==legacy['rows']
    assert 'geometry_guided_unavailable_reason' in result['metadata']


def test_partial_native_query_failure_keeps_reference_for_successful_extra_query(monkeypatch):
    mesh,profile,baseline=fixture()
    measure=module.measure_orientation
    calls=[]
    def partial(*args,**kwargs):
        calls.append(args[1])
        if len(calls)==8:raise ValueError('simulated later native query failure')
        return measure(*args,**kwargs)
    monkeypatch.setattr(module,'measure_orientation',partial)
    result=module.enrich_full(mesh,profile,baseline,timeout_s=30)
    record=result['metadata']
    assert record['full_added_count']==6 and record['guided_added_count']==1
    assert len(record['selection_reference_rows'])==len(result['rows'])-1
    assert record['status']=='partial'
    assert 'geometry_guided_unavailable_reason' in record
