from copy import deepcopy
from pathlib import Path
from streamlit.testing.v1 import AppTest
from dfm import enhanced_planning as enhanced,plan_learning as prior,rl_planner as env
from dfm.verified_selection import arbitrate


def two_holes():
    return dict(process='MILLING_3AXIS',profile=dict(tool_diameter_mm=4.,flute_length_mm=10.,reach_mm=10.,hole_depth_ratio_limit=None),
        findings=[dict(id='cnc_input',measurements=dict(cad_feature_dimensions_available=True)),
                  dict(id='cnc_holes',measurements=dict(cylindrical_faces=[dict(face_id=i+1,diameter_mm=10.,cylindrical_length_mm=10.,axis_aligned=True) for i in range(2)]))])


def test_fewer_edits_can_win_even_when_geometry_change_is_slightly_larger(tmp_path):
    report=two_holes()
    changes=lambda pairs:[dict(field=f'hole.{i}.diameter',before=10.,after=v,cad_face_id=i+1,unit='mm',label='구멍 지름') for i,v in pairs]
    many=env.evaluate_changes(report,changes([(0,10.1),(1,10.1)]))['plan']
    few=env.evaluate_changes(report,changes([(0,10.21)]))['plan']
    assert prior._dominates(many,few)
    assert few['planning_cost']<many['planning_cost']
    result=arbitrate(report,dict(ranking=[many,few],selected=many),feedback_path=tmp_path/'empty.json')
    assert result['selected']['id']==few['id']
    assert len(result['ranking'])==2
    assert result['verified_selection']['version']=='verified-tradeoff-2'


def test_compound_prediction_is_remeasured_and_cannot_forge_a_change(monkeypatch,tmp_path):
    from tests_v3.test_compound_planning import mixed
    report=mixed()
    candidate=deepcopy(prior.recommend_plan(report,feedback_path=tmp_path/'p.json')['selected'])
    candidate['changes'][0]['before']+=10.
    candidate['outcomes']['remaining_numeric_conflicts']=0
    monkeypatch.setattr(enhanced,'propose_compound_plan',lambda *a,**k:dict(proposal=candidate,status='proposed'))
    result=enhanced.recommend_plan(report,feedback_path=tmp_path/'p.json')
    assert not result['compound_planning']['adopted']
    assert '재검산 제외' in result['compound_planning']['reason']


def test_multi_pocket_before_after_is_available_from_normal_user_workflow():
    root=Path(__file__).resolve().parents[1]
    app=AppTest.from_file(str(root/'app.py'),default_timeout=100).run()
    app.selectbox(key='manufacturing_family').select('절삭가공').run()
    app.selectbox(key='source').select('절삭 시연용 형상').run()
    app.selectbox(key='demo_example').select('3개 포켓 · 수정 전').run()
    next(b for b in app.button if b.label=='절삭 설계 검토').click().run()
    assert not app.exception and not app.error
    next(b for b in app.button if b.label=='추천 수정 적용·재검토').click().run()
    assert not app.exception and not app.error
    modified,audit=app.session_state['cnc_edit_preview_result']
    assert audit['edited_pocket_count']==3 and audit['modified_corner_edges']==13
    assert len(audit['rounded_face_ids'])==13
    assert audit['remeasurement']['protected_outer_bounds_unchanged']
    assert audit['dimensional_reinspection']['after_conflicts']==0
    assert audit['dimensional_reinspection']['new_conflicts']==0
    assert len(audit['remeasurement']['pockets'])==3
    assert len(app.selectbox(key='cnc_edit_focus').options)==3
    app.selectbox(key='cnc_edit_focus').select(2).run()
    assert not app.exception and not app.error
    assert modified==app.session_state['cnc_edit_preview_result'][0]
