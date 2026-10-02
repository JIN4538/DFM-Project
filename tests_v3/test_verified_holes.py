"""Independent native CAD dimensions, adverse topology and complete UI flow."""
from copy import deepcopy
import json
from pathlib import Path
import numpy as np
import pytest
from streamlit.testing.v1 import AppTest

from dfm.verified_holes import measure_holes, attach_verified_holes, MAX_CYLINDERS
from dfm.machining import MachiningProfile, review_machining
from dfm.tool_recommendation import review_with_tool_recommendation
from dfm.hole_view import entry_choice, hole_summary_html
from dfm.enhanced_planning import recommend_plan


@pytest.fixture(scope='module')
def native(tmp_path_factory):
    from scripts.benchmark_verified_holes import build, model_from_native
    from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
    folder=tmp_path_factory.mktemp('hole-cad')
    result={}
    for kind,rotated,count in [('through',False,3),('through',True,3),('blind',False,3),
                               ('split',True,3),('stepped',False,1),('cross',False,1),
                               ('sealed',False,1),('boss',False,1),('remote_boss',False,1)]:
        key=kind+('-rotated' if rotated else '')
        shape,_=build(kind,rotated=rotated,count=count)
        path=folder/(key+'.step')
        writer=STEPControl_Writer();writer.Transfer(shape,STEPControl_AsIs);writer.Write(str(path))
        model=model_from_native(path,folder/'native')
        result[key]=(model,path,folder/'native'/path.stem)
    return result


@pytest.mark.parametrize('name',['through','through-rotated','split-rotated','blind'])
def test_repeated_holes_have_independent_count_diameter_depth_and_orientation(native,name):
    model,_,_=native[name]
    original=deepcopy(model.cad_features)
    holes=measure_holes(model)['holes']
    assert len(holes)==3
    assert len({i for h in holes for i in h['face_ids']})==3*(2 if name.startswith('split') else 1)
    assert all(h['diameter_mm']==pytest.approx(6) for h in holes)
    assert all(h['depth_mm']==pytest.approx(7.2 if name=='blind' else 12) for h in holes)
    assert all(h['hole_kind']==('blind' if name=='blind' else 'through') for h in holes)
    assert model.cad_features==original


@pytest.mark.parametrize('name',['stepped','cross','sealed','boss'])
def test_counterexamples_are_not_named_as_simple_complete_holes(native,name):
    inventory=measure_holes(native[name][0])
    assert inventory['status']=='complete'
    assert inventory['holes']==[]


def test_incomplete_boundary_unknown_material_and_bad_inputs_are_not_promoted(native):
    source=native['through'][0]
    partial=deepcopy(source)
    for f in partial.cad_features:
        if f['kind']=='plane':f['boundary_status']='partial'
    assert not measure_holes(partial)['holes']
    unknown=deepcopy(source)
    for f in unknown.cad_features:
        if f['kind']=='cylinder':f['role']='unknown'
    assert not measure_holes(unknown)['holes']
    for key,value in [('cad_valid',False),('solid_count',2),('source_format','stl'),('cad_geometry_kind','surface')]:
        bad=deepcopy(source);bad.metadata[key]=value
        inventory=measure_holes(bad)
        assert inventory['status']=='unavailable' and not inventory['holes']
    large=deepcopy(source)
    cylinder=next(f for f in large.cad_features if f['kind']=='cylinder')
    large.cad_features=[dict(cylinder,face_id=i) for i in range(MAX_CYLINDERS+1)]
    assert measure_holes(large)['status']=='budget_exceeded'


def test_split_walls_are_not_repeated_as_pocket_corners_and_raw_audit_survives(native):
    model=native['split-rotated'][0]
    direction=entry_choice(measure_holes(model)['holes'],(0,0,1))['direction']
    raw=review_machining(model,MachiningProfile(tool_diameter_mm=5,reach_mm=14),direction)
    source=deepcopy(raw)
    attach_verified_holes(raw,model)
    assert raw['native_hole_face_review']==next(f for f in source['findings'] if f['id']=='cnc_holes')
    holes=next(f for f in raw['findings'] if f['id']=='cnc_holes')
    corners=next(f for f in raw['findings'] if f['id']=='cnc_curved_corners')
    assert len(holes['measurements']['cylindrical_faces'])==3
    assert holes['measurements']['face_count']==6
    assert not corners['measurements']['cylindrical_faces']
    before=deepcopy(raw)
    attach_verified_holes(raw,model)
    assert raw==before


def test_blind_wrong_side_has_no_numeric_plan_then_entry_direction_rechecks(native,tmp_path):
    model=native['blind'][0]
    report=review_with_tool_recommendation(model,MachiningProfile(),(0,0,-1))
    assert all(h['axis_aligned'] and h['entry_blocked'] for h in report['verified_hole_inventory']['holes'])
    assert not report['tool_recommendation']['automatic_fields']
    blocked=next(f for f in report['findings'] if f['id']=='cnc_hole_entry')
    assert blocked['status']=='attention' and len(blocked['measurements']['cylindrical_faces'])==3
    result=recommend_plan(report,feedback_path=tmp_path/'absent.json')
    assert result['selected'] is None and result['entry_direction_required']
    choice=entry_choice(report['verified_hole_inventory']['holes'],report['direction'])
    checked=review_with_tool_recommendation(model,MachiningProfile(),choice['direction'])
    assert not any(f['id']=='cnc_hole_entry' for f in checked['findings'])
    assert checked['tool_recommendation']['values']==pytest.approx(dict(tool_diameter_mm=4.8,flute_length_mm=8.2,reach_mm=8.2))


def test_local_mouth_depth_avoids_remote_boss_envelope_and_keeps_user_tool(native):
    model=native['remote_boss'][0]
    report=review_with_tool_recommendation(model,MachiningProfile(tool_diameter_mm=2.5))
    tool=report['tool_recommendation']
    assert tool['values']==pytest.approx(dict(tool_diameter_mm=2.5,flute_length_mm=13,reach_mm=13))
    assert tool['fixed_fields']==['tool_diameter_mm']
    assert tool['constraints'][0]['reach_basis']=='verified_circular_mouth_to_end'
    assert tool['drill_requirements'][0]['nominal_diameter_mm']==6
    assert tool['drill_requirements'][0]['depth_mm']==12
    assert '구멍 1개' in hole_summary_html(report)


def test_circle_label_and_ring_follow_the_same_transformed_cad_location(native):
    from dfm.machining_view import machining_figure
    model=native['through-rotated'][0]
    report=review_with_tool_recommendation(model,MachiningProfile(),(0,0,1))
    h=report['verified_hole_inventory']['holes'][0]
    fig=machining_figure(model,report,'cnc_holes',cad_face_ids=h['face_ids'])
    rings=[t for t in fig.data if t.name=='구멍 입구']
    assert len(rings)==1
    ring=np.column_stack([rings[0].x,rings[0].y,rings[0].z])
    transform=np.array(report['current_orientation']['transform'])
    centers=[np.array(p)@transform[:3,:3].T+transform[:3,3] for p in h['entry_centers_mm']]
    # Exclude the duplicated closing vertex when averaging the circle.
    center=ring[:-1].mean(0)
    assert min(np.linalg.norm(center-c) for c in centers)<1e-7
    assert np.linalg.norm(ring-ring[0],axis=1)[-1]<1e-7
    assert np.linalg.norm(ring-center,axis=1)==pytest.approx(np.ones(65)*3)
    assert fig.data[0].opacity==.25
    assert fig.layout.scene.camera.projection.type=='orthographic'
    eye=np.array([fig.layout.scene.camera.eye[k] for k in 'xyz'])
    normals=[np.array(n)@transform[:3,:3].T for n in h['entry_directions']]
    assert max(eye @ n / np.linalg.norm(eye) for n in normals)>.9
    assert any(t.type=='scatter3d' and t.mode=='markers+text' and '구멍 1' in t.text[0] for t in fig.data)


def test_entry_choice_does_not_pretend_one_axis_covers_different_axes():
    holes=[dict(entry_directions=[[0,0,1],[0,0,-1]]),dict(entry_directions=[[0,0,1]]),dict(entry_directions=[[1,0,0]])]
    choice=entry_choice(holes,(1,0,0))
    assert choice==dict(direction=[0.,0.,1.],covered_count=2,total=3)


def test_neural_memory_error_does_not_destroy_independent_native_dimensions(native,tmp_path,monkeypatch):
    from scripts.benchmark_verified_holes import model_from_native
    from dfm import feature_instance_refinement
    def failed(_graph):raise MemoryError('forced low-memory counterexample')
    monkeypatch.setattr(feature_instance_refinement,'recognize_refined_features',failed)
    model=model_from_native(native['through'][1],tmp_path/'failed-neural')
    record=model.metadata['external_feature_recognition'][0]
    assert record['status']=='unavailable' and record['error_type']=='MemoryError'
    assert not record['candidates']
    inventory=measure_holes(model)
    assert len(inventory['holes'])==3
    assert all(h['diameter_mm']==pytest.approx(6) and h['depth_mm']==pytest.approx(12) for h in inventory['holes'])


def test_packaged_hole_demo_is_reachable_from_the_normal_app():
    root=Path(__file__).resolve().parents[1]
    app=AppTest.from_file(str(root/'app.py'),default_timeout=90).run()
    app.selectbox(key='source').select('절삭 시연용 형상').run()
    app.selectbox(key='demo_example').select('분할된 구멍 3개 · 기울어진 형상').run()
    app.selectbox(key='manufacturing_family').select('절삭가공').run()
    assert not app.exception and not app.error
    app.checkbox(key='cnc_visibility').uncheck().run()
    app.button(key='run_cnc_review').click().run()
    assert not app.exception and not app.error
    assert len(app.session_state['cnc_report']['verified_hole_inventory']['holes'])==3
    app.button(key='cnc_hole_apply_direction').click().run()
    assert not app.exception and not app.error
    assert all(h['entry_matches_direction'] for h in app.session_state['cnc_report']['verified_hole_inventory']['holes'])


def load_native_test_model(target):
    from amdfm.io import exact_weld
    from amdfm.models import Model
    target=Path(target)
    info=json.loads(target.with_suffix('.json').read_text(encoding='utf8'))
    features=info.pop('features')
    info.update(filename=target.stem+'.step',source_format='step',unit_status='declared_in_step',dimensions_confirmed=True)
    with np.load(target.with_suffix('.npz')) as a:
        return Model(exact_weld(a['vertices'],a['faces']),info,features,a['face_ids'].copy(),a['body_ids'].copy())


@pytest.mark.parametrize('name',['through-rotated','blind'])
def test_one_click_entry_rechecks_actual_report_and_opens_the_location(native,name):
    _,path,target=native[name]
    script=f'''
import streamlit as st
from tests_v3.test_verified_holes import load_native_test_model
from dfm.machining_view import render_machining
from pathlib import Path
model=load_native_test_model({str(target)!r})
if 'cnc_direction' not in st.session_state:
    st.session_state['cnc_direction']='−Z · 아래쪽에서'
    st.session_state['cnc_auto_review']=True
    st.session_state['cnc_visibility']=False
    st.session_state['cnc_diameter']=2.5
render_machining(model,{path.name!r},Path({str(path)!r}).read_bytes(),'hole-ui-test-1')
'''
    app=AppTest.from_string(script,default_timeout=60).run()
    assert not app.exception and not app.error
    before=app.session_state['cnc_report']
    assert len(before['verified_hole_inventory']['holes'])==3
    app.button(key='cnc_hole_apply_direction').click().run()
    assert not app.exception and not app.error
    after=app.session_state['cnc_report']
    assert all(h['entry_matches_direction'] for h in after['verified_hole_inventory']['holes'])
    assert after['profile']['tool_diameter_mm']==2.5
    assert app.session_state['cnc_diameter']==2.5
    assert app.session_state['cnc_location_details'] is True
    assert app.selectbox(key='cnc_finding').value=='cnc_holes'
    assert app.selectbox(key='cnc_location').value!='all'
    assert not any(f['id']=='cnc_hole_entry' for f in after['findings'])
    assert app.get('plotly_chart')
    assert any('깊이 (mm)' in df.value.columns and list(df.value.columns)[:2]==['지름 (mm)','깊이 (mm)'] for df in app.dataframe)
    from dfm.conclusion import summarize_conclusion
    summary=summarize_conclusion(after)
    assert '구멍 3개' in summary['title'] and '현재 공구와 맞습니다' in summary['title']
