"""One review reveals actionable evidence and a stable, optional direction change."""
from pathlib import Path
import copy

import pytest
from streamlit.testing.v1 import AppTest

from amdfm.analysis import review
from amdfm.io import load_model
from amdfm.profiles import Profile
from amdfm.workflow import action_plan
from amdfm.presentation import html_report

ROOT = Path(__file__).resolve().parents[1]


def test_single_click_populates_details_and_reveals_wall_and_layers_on_request():
    app = AppTest.from_file(str(ROOT/'app.py'), default_timeout=90).run()
    app.selectbox(key='cad_example').set_value('직육면체 · 10×20×30 mm').run()
    app.button(key='start_from_model').click().run()
    assert not app.exception
    report = app.session_state['report']
    assert report['details']['wall']['status']=='measured'
    assert report['details']['layers']['status']=='complete'
    assert report['details']['sections']['status']=='complete'
    assert app.segmented_control(key='result_tab').value=='설계 조치'
    assert app.toggle(key='am_location_details').value is False
    assert not app.get('plotly_chart')
    app.toggle(key='am_location_details').set_value(True).run()
    app.selectbox(key='highlight_finding').set_value('wall').run()
    assert app.selectbox(key='wall_sample').value==0
    original = copy.deepcopy(report)
    app.selectbox(key='highlight_finding').set_value('layers').run()
    assert not app.exception
    assert app.segmented_control(key='result_tab').value=='설계 조치'
    assert any('150개 층' in x.value for x in app.success)
    assert app.session_state['report']==original  # viewing detail does not recompute


def test_thin_feature_is_selected_and_actionable_without_second_run():
    app = AppTest.from_file(str(ROOT/'app.py'), default_timeout=90).run()
    app.selectbox(key='cad_example').set_value('얇은 판 · 두께 0.3 mm').run()
    app.number_input(key='wall_limit_MEX').set_value(1.)
    app.button(key='start_from_model').click().run()
    assert not app.exception
    report = app.session_state['report']
    assert report['details']['wall']['measurements']['minimum_mm']==pytest.approx(.3)
    assert app.session_state['highlight_finding']=='wall'
    assert not app.get('plotly_chart')
    app.button(key='am_conclusion_location').click().run()
    assert app.selectbox(key='highlight_finding').value=='wall'
    assert any('벽 기준보다 작은 구간' in x.value for x in app.warning)
    assert app.button(key='am_learned_wall')
    assert len(app.get('plotly_chart'))>=1
    assert action_plan(report)['primary']['action_kind']=='candidate'


def test_app_recommendation_apply_is_stable_and_rebuilds_detail_context():
    app = AppTest.from_file(str(ROOT/'app.py'), default_timeout=90).run()
    app.selectbox(key='cad_example').set_value('직육면체 · 10×20×30 mm').run()
    app.checkbox(key='initial_wall').uncheck()
    app.button(key='start_from_model').click().run()
    before = app.session_state['report']
    recommended = before['orientation_recommendation']['recommended']
    assert not before.get('details')
    assert before['orientation_recommendation']['action']=='apply'
    assert app.button(key='am_apply_plan')
    app.segmented_control(key='result_tab').set_value('방향 비교').run()
    app.button(key='directions_apply_recommendation').click().run()
    assert not app.exception
    assert app.segmented_control(key='result_tab').value=='설계 조치'
    after = app.session_state['report']
    assert after['current_orientation']['direction']==recommended['direction']
    assert after['orientation_recommendation']['recommended']['direction']==recommended['direction']
    assert after['orientation_recommendation']['keep_current']
    assert app.checkbox(key='initial_wall').value
    for detail in after['details'].values():
        assert detail['direction']==after['current_orientation']['direction']
        assert detail['profile']==after['profile']
    assert any('현재 방향 유지' in x.value for x in app.caption)
    assert not any(button.key=='am_apply_plan' for button in app.button)


def test_calculation_failure_is_not_counted_as_geometric_candidate_and_html_matches():
    model = load_model((ROOT/'examples/cad/01_box.step').read_bytes(),'01_box.step')
    report = review(model,Profile(),dense=True)
    report['details']={'wall':{'status':'unknown','reason':'계산 시간 한도',
                              'execution_trigger':'automatic_assessment'}}
    before=copy.deepcopy(report)
    plan=action_plan(report)
    wall=next(x for x in plan['actions'] if x['id']=='wall')
    assert wall['action_kind']=='calculation'
    assert plan['candidate_count']==0
    assert '추가 계산' in wall['next_action']
    document=html_report(report,model).decode()
    assert '종합 결론' in document and '판단 근거·전체 항목' in document
    assert '추가 확인' in document and '계산 시간 한도' in document
    assert '정밀 검토를 다시 실행하세요' not in document
    assert report==before
