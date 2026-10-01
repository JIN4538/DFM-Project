"""Sidebar edits apply to either review button, without a separate form submit.

AppTest batches widget state more eagerly than the browser. Checking form_id
explicitly guards the observed browser bug as well as the numerical result.
"""
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import dfm.advisor_view as advisor_view


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def local_review_only(monkeypatch):
    monkeypatch.setattr(advisor_view, '_key', lambda: '')


def open_app():
    app = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=90).run()
    assert not app.exception
    return app


def test_am_sidebar_edit_applies_from_main_button_and_hides_stale_result():
    app = open_app()
    app.selectbox(key='cad_example').select('얇은 판 · 두께 0.3 mm').run()
    widget = app.number_input(key='wall_limit_MEX')
    assert widget.proto.form_id == ''
    widget.set_value(1.).run()
    assert not app.segmented_control
    app.button(key='start_from_model').click().run()
    assert not app.exception
    report = app.session_state['report']
    assert report['profile']['minimum_wall_mm'] == 1.
    assert report['details']['wall']['profile'] == report['profile']
    assert report['details']['wall']['measurements']['minimum_mm'] == pytest.approx(.3)
    assert report['details']['wall']['measurements']['below_limit_face_indices']
    assert app.session_state['highlight_finding'] == 'wall'
    assert app.toggle(key='am_location_details').value is False
    app.button(key='am_conclusion_location').click().run()
    assert app.selectbox(key='highlight_finding').value == 'wall'

    app.number_input(key='wall_limit_MEX').set_value(.2).run()
    assert not app.exception
    assert not app.segmented_control  # A previous 1 mm result must disappear.
    assert not app.get('download_button')
    app.button(key='start_from_model').click().run()
    assert not app.exception
    current = app.session_state['report']
    assert current['profile']['minimum_wall_mm'] == .2
    assert current['details']['wall']['profile'] == current['profile']
    assert not current['details']['wall']['measurements']['below_limit_face_indices']
    wall = next(x for x in current['learned_review']['items'] if x['finding_id'] == 'wall')
    assert wall['state'] == 'clear'


def test_cnc_sidebar_tool_edits_apply_from_main_button_and_hide_stale_result():
    app = open_app()
    app.selectbox(key='manufacturing_family').select('절삭가공').run()
    app.selectbox(key='source').select('절삭 검증 형상').run()
    cases = json.loads((ROOT / 'examples/machining/manifest.json').read_text(encoding='utf-8'))
    title = next(x['title'] for x in cases if x['id'] == '02_narrow_deep_pocket')
    app.selectbox(key='cnc_example').select(title).run()
    for key, value in (('cnc_diameter', 4.), ('cnc_flute', 8.), ('cnc_reach', 10.)):
        widget = app.number_input(key=key)
        assert widget.proto.form_id == ''
        widget.set_value(value).run()
        assert not app.exception
    app.button(key='cnc_start_from_model').click().run()
    assert not app.exception
    report = app.session_state['cnc_report']
    assert next(x for x in app.expander if x.label == '검토 조건').proto.expanded is False
    assert report['profile']['tool_diameter_mm'] == 4.
    assert report['profile']['flute_length_mm'] == 8.
    assert report['profile']['reach_mm'] == 10.
    pocket = next(x for x in report['findings'] if x['id'] == 'cnc_rectangular_pockets')['measurements']['pockets'][0]
    assert pocket['width_mm'] == pytest.approx(3.)
    assert pocket['width_too_small'] is True

    app.number_input(key='cnc_diameter').set_value(2.).run()
    assert not app.exception
    assert not app.get('download_button')
    assert not any(widget.key == 'cnc_finding' for widget in app.selectbox)
    app.button(key='cnc_start_from_model').click().run()
    assert not app.exception
    current = app.session_state['cnc_report']
    assert current['profile']['tool_diameter_mm'] == 2.
    assert current['profile']['flute_length_mm'] == 8.
    assert current['profile']['reach_mm'] == 10.
    pocket = next(x for x in current['findings'] if x['id'] == 'cnc_rectangular_pockets')['measurements']['pockets'][0]
    assert pocket['width_too_small'] is False
    assert pocket['exceeds_flute_length'] is True
    assert pocket['exceeds_reach'] is True
