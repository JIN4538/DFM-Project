"""Actions must reach their promised result after a real settings change."""
from pathlib import Path

from streamlit.testing.v1 import AppTest


APP = Path(__file__).resolve().parents[1] / 'app.py'


def test_next_action_selects_the_requested_finding_after_detail_tab_reanalysis():
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    app.selectbox(key='cad_example').select('수직 관통홀 · 지름 4 mm').run()
    # This focused navigation test deliberately uses the optional quick mode.
    # The automatic one-click flow has separate real-worker coverage.
    app.checkbox(key='initial_wall').uncheck()
    next(b for b in app.sidebar.button if b.label == "설계 검토").click().run()
    assert not app.exception
    first = app.session_state['report']

    # An explicit new review returns to the conclusion, then the requested
    # location must take precedence over the default highlight.
    app.segmented_control(key='result_tab').set_value('정밀 검토').run()
    app.number_input(key='layer_MEX').set_value(.25)
    next(b for b in app.sidebar.button if b.label == "설계 검토").click().run()
    assert not app.exception
    assert app.segmented_control(key='result_tab').value == '설계 조치'
    report = app.session_state['report']
    assert report['model_fingerprint'] == first['model_fingerprint']
    assert report['profile']['layer_height_mm'] == .25
    assert report['profile'] != first['profile']
    # A new result is summarized in one place. The requested location must win
    # over the initial highlight when following its conclusion action.
    app.segmented_control(key='result_tab').set_value('설계 조치').run()
    assert app.toggle(key='am_location_details').value is False
    app.button(key='am_learned_cad_holes').click().run()
    assert not app.exception
    assert app.segmented_control(key='result_tab').value == '설계 조치'
    assert app.selectbox(key='highlight_finding').value == 'cad_holes'
    assert any('구멍 지름 비교 기준이 필요합니다' in entry.value for entry in app.info)
    assert app.number_input(key='quick_hole_limit_MEX').value is None

    # The previous jump is consumed once: it must not keep overriding a later
    # manual selection on ordinary reruns of the same result.
    app.selectbox(key='highlight_finding').select('overhang').run()
    assert not app.exception
    assert app.selectbox(key='highlight_finding').value == 'overhang'


def test_all_directions_exceeding_space_are_explained_and_clear_after_unlimiting():
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    app.selectbox(key='cad_example').select('직육면체 · 10×20×30 mm').run()
    app.checkbox(key='use_build_MEX').set_value(True).run()
    for axis in 'XYZ':
        app.number_input(key=f'build_{axis}_MEX').set_value(1.)
    next(b for b in app.sidebar.button if b.label == "설계 검토").click().run()
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
    next(b for b in app.sidebar.button if b.label == "설계 검토").click().run()
    assert not app.exception
    assert app.session_state['report']['profile']['build_volume_mm'] is None
    assert all(row['build_fit'] is None for row in app.session_state['report']['orientations'])
    assert not any('들어가는 후보가 없습니다' in entry.value for entry in app.warning)
