"""Actions must reach their promised result after a real settings change."""
from pathlib import Path

from streamlit.testing.v1 import AppTest


APP = Path(__file__).resolve().parents[1] / 'app.py'


def test_next_action_selects_the_requested_finding_after_detail_tab_reanalysis():
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    app.selectbox(key='cad_example').select('수직 관통홀 · 지름 4 mm').run()
    app.sidebar.button[0].click().run()
    assert not app.exception
    first = app.session_state['report']

    # Recomputing from another tab must not replace a requested location with
    # the default highlight when the result tab is opened for the first time.
    app.segmented_control(key='result_tab').set_value('정밀 검토').run()
    app.number_input(key='layer_MEX').set_value(.25)
    app.sidebar.button[0].click().run()
    assert not app.exception
    assert app.segmented_control(key='result_tab').value == '정밀 검토'
    report = app.session_state['report']
    assert report['model_fingerprint'] == first['model_fingerprint']
    assert report['profile']['layer_height_mm'] == .25
    assert report['profile'] != first['profile']
    hole_title = next(row['title'] for row in report['findings'] if row['id'] == 'cad_holes')
    assert hole_title in app.button(key='next_review_action').label

    app.button(key='next_review_action').click().run()
    assert not app.exception
    assert app.segmented_control(key='result_tab').value == '설계 조치'
    assert app.selectbox(key='highlight_finding').value == 'cad_holes'
    assert any('홀 기준 미입력' in entry.value for entry in app.info)

    # The previous jump is consumed once: it must not keep overriding a later
    # manual selection on ordinary reruns of the same result.
    app.selectbox(key='highlight_finding').select('overhang').run()
    assert not app.exception
    assert app.selectbox(key='highlight_finding').value == 'overhang'


def test_all_directions_exceeding_space_are_explained_and_clear_after_unlimiting():
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    app.selectbox(key='cad_example').select('직육면체 · 10×20×30 mm').run()
    app.checkbox(key='use_build_MEX').set_value(True)
    for axis in 'XYZ':
        app.number_input(key=f'build_{axis}_MEX').set_value(1.)
    app.sidebar.button[0].click().run()
    assert not app.exception
    report = app.session_state['report']
    assert len(report['orientations']) >= 26
    assert all(row['build_fit'] is False for row in report['orientations'])

    app.segmented_control(key='result_tab').set_value('방향 비교').run()
    assert not app.exception
    assert any('비교한 방향 중' in entry.value and '들어가는 후보가 없습니다' in entry.value
               for entry in app.warning)
    assert any('장비 공간 또는 부품 분할' in entry.value for entry in app.warning)

    # Removing the optional space restriction must remove the old all-directions
    # failure and evaluate every direction under the newly selected scope.
    app.checkbox(key='use_build_MEX').set_value(False)
    app.sidebar.button[0].click().run()
    assert not app.exception
    assert app.session_state['report']['profile']['build_volume_mm'] is None
    assert all(row['build_fit'] is None for row in app.session_state['report']['orientations'])
    assert not any('들어가는 후보가 없습니다' in entry.value for entry in app.warning)
