"""First-use inputs and direct result access, with real retained widget state."""
from pathlib import Path
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def settings_app():
    import streamlit as st
    from dfm.am_settings_view import render_am_settings
    process = st.selectbox('Process', ['MEX', 'VPP'], key='test_process')
    st.session_state['settings_result'] = render_am_settings(process)


def test_optional_settings_explain_thresholds_and_hide_unused_build_dimensions():
    app = AppTest.from_function(settings_app).run()
    assert not app.exception
    assert app.expander[0].proto.expanded is False
    wall = app.number_input(key='wall_limit_MEX')
    hole = app.number_input(key='hole_limit_MEX')
    assert wall.label == '이보다 얇은 벽 찾기 (mm)'
    assert '1.2 mm보다 얇은' in wall.proto.help
    assert hole.value is None and '비워 두면' in hole.proto.help
    assert app.session_state['settings_result']['minimum_wall_mm'] == 1.2
    assert app.session_state['settings_result']['build_volume_mm'] is None
    assert not any(w.key.startswith('build_') for w in app.number_input)
    app.checkbox(key='use_build_MEX').check().run()
    app.number_input(key='build_X_MEX').set_value(123.).run()
    app.checkbox(key='use_build_MEX').uncheck().run()
    assert app.session_state['settings_result']['build_volume_mm'] is None
    app.checkbox(key='use_build_MEX').check().run()
    assert app.number_input(key='build_X_MEX').value == 123.
    app.selectbox(key='test_process').select('VPP').run()
    assert app.session_state['settings_result']['minimum_wall_mm'] == .4
    assert app.session_state['settings_result']['build_volume_mm'] is None
    app.selectbox(key='test_process').select('MEX').run()
    assert app.session_state['settings_result']['build_volume_mm'][0] == 123.


def test_conclusion_reaches_another_issue_in_one_click_and_keeps_ready_measurements():
    app = AppTest.from_file(str(ROOT/'app.py'), default_timeout=90).run()
    app.selectbox(key='demo_example').select('수직 관통홀 · 지름 4 mm').run()
    app.number_input(key='wall_limit_MEX').set_value(30.)
    app.number_input(key='hole_limit_MEX').set_value(5.)
    app.checkbox(key='neural_direction_search').uncheck()
    app.button(key='start_from_model').click().run()
    assert not app.exception
    report = app.session_state['report']
    assert report['details']['wall']['measurements']
    assert any(widget.proto.label == '검토 보고서 저장' for widget in app.get('download_button'))
    first = report['conclusion']['first']['id']
    target = 'cad_holes' if first != 'cad_holes' else 'wall'
    app.button(key='am_quick_'+target).click().run()
    assert not app.exception
    assert app.selectbox(key='highlight_finding').value == target
    assert app.toggle(key='am_location_details').value is True
    if target == 'cad_holes':
        app.number_input(key='quick_hole_limit_MEX').set_value(3.)
        app.button(key='apply_hole_criterion').click().run()
        assert not app.exception
        assert app.session_state['report']['profile']['minimum_hole_mm'] == 3.
        assert app.number_input(key='hole_limit_MEX').value == 3.
        assert app.selectbox(key='highlight_finding').value == 'cad_holes'
        finding=next(x for x in app.session_state['report']['findings'] if x['id']=='cad_holes')
        assert finding['status'] != 'attention'
    before = app.session_state['report']['details']['wall']
    app.segmented_control(key='result_tab').set_value('정밀 검토').run()
    assert app.button(key='run_wall').label == '벽 다시 계산'
    assert app.session_state['report']['details']['wall'] == before
    app.segmented_control(key='detail_focus').set_value('단면').run()
    assert app.button(key='run_sections').label == '단면 다시 계산'
    assert not app.exception
    app.button(key='run_am_review').click().run()
    assert not app.exception
    assert app.segmented_control(key='result_tab').value == '설계 조치'
    assert app.toggle(key='am_location_details').value is False
    app.segmented_control(key='result_tab').set_value('수정 전후').run()
    app.button(key='save_baseline').click().run()
    same_shape=next(x for x in app.expander if x.label=='같은 형상의 비교 수치')
    assert same_shape.proto.expanded is False
    assert not any('출력 성공' in x.value for x in app.caption)
