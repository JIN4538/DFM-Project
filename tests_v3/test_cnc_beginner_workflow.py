"""A selected CAD location must show its own measurements without extra actions."""
from copy import deepcopy

import pytest
from streamlit.testing.v1 import AppTest

from dfm.machining_view import selected_location_finding, measurement_display_table, machining_display_text


@pytest.mark.parametrize("identifier,key,identity", [
    ("cnc_curved_corners", "cylindrical_faces", "face_id"),
    ("cnc_learned_pockets", "pockets", "floor_face_id"),
])
def test_selected_cad_location_preserves_measurements_unknowns_and_full_report(identifier, key, identity):
    rows = [{identity: 12, "radius_mm": 2., "tool_too_large": True},
            {identity: 18, "radius_mm": 5., "tool_too_large": None}]
    finding = dict(id=identifier, measurements={key: rows}, status="attention")
    original = deepcopy(finding)
    selected = selected_location_finding(finding, "18")
    assert selected["measurements"][key] == [rows[1]]
    assert selected["measurements"][key][0]["tool_too_large"] is None
    assert selected_location_finding(finding, "all") == original
    assert selected_location_finding(finding, "99")["measurements"][key] == []
    assert finding == original


def test_recognized_feature_opens_immediately_and_updates_without_second_button():
    app = AppTest.from_string('''
import streamlit as st
from tests_v3.test_machining_ux_reaudit import _export_fixture
from dfm.feature_learning_view import render_feature_candidates
import numpy as np
model, report = _export_fixture()
model.face_ids = np.array([17] * 6 + [19] * 6)
report['external_feature_recognition'] = {
    'candidates': [dict(label='첫 번째 홈', face_ids=[17], area_mm2=30.),
                   dict(label='두 번째 홈', face_ids=[19], area_mm2=45.)],
    'verified_pockets': []}
render_feature_candidates(model, report, (0, 0, 1))
''', default_timeout=30).run()
    assert not app.exception
    assert not app.get('plotly_chart')
    app.session_state['external_feature_panel'] = True
    app.run()
    assert not app.exception
    assert len(app.get('plotly_chart')) == 1
    assert not app.button
    assert app.metric[0].value == '30 mm²'
    app.selectbox(key='external_feature_selected').set_value(1)
    # AppTest does not serialize expander widgets, so repeat the browser's
    # tracked open value along with the changed selection.
    app.session_state['external_feature_panel'] = True
    app.run()
    assert not app.exception
    assert len(app.get('plotly_chart')) == 1
    assert app.metric[0].value == '45 mm²'
    app.session_state['external_feature_panel'] = False
    app.run()
    assert not app.get('plotly_chart')


def test_display_rounds_measurements_without_changing_source_values_or_unknowns():
    import pandas as pd
    rows = [{"바닥 CAD 면": 10, "바닥 폭 (mm)": 9.999999999999778,
             "입력 날 길이 (mm)": None, "바닥 진입원 지름 (mm)": 17.32050807568877,
             "벽 높이 > 날 길이": None, "공구 지름 > 진입원 지름": False}]
    original = deepcopy(rows)
    table = measurement_display_table(rows)
    assert table.iloc[0]["바닥 폭 (mm)"] == 10.
    assert table.iloc[0]["포켓에 들어가는 원의 지름 (mm)"] == 17.32
    assert pd.isna(table.iloc[0]["입력 절삭 날 길이 (mm)"])
    assert pd.isna(table.iloc[0]["벽 높이 > 절삭 날 길이"])
    assert not table.iloc[0]["공구가 포켓에 들어가는 원보다 큼"]
    assert rows == original and rows[0]["입력 날 길이 (mm)"] is None


def test_display_explains_radius_and_flute_length_without_changing_stored_text():
    source = "내부 코너를 R 4 mm 이상으로 바꾸세요. 날 길이는 7 mm 이상으로 검토하세요."
    shown = machining_display_text(source)
    assert shown == "안쪽 코너를 둥근 반경 4 mm 이상으로 바꾸세요. 절삭 날 길이는 7 mm 이상으로 검토하세요."
    assert "R 4 mm" in source
    assert machining_display_text(shown) == shown
