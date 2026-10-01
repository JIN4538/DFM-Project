"""The CNC first screen gives one conclusion; evidence is requested explicitly."""
from copy import deepcopy
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


def _open(case="02_narrow_deep_pocket"):
    path = str(ROOT / "examples/machining" / f"{case}.step")
    app = AppTest.from_string(f'''
from pathlib import Path
import streamlit as st
from amdfm.io import load_model
from dfm.machining_view import render_machining
@st.cache_resource
def model():
    path = Path({path!r})
    return load_model(path.read_bytes(), path.name)
render_machining(model(), {case!r}, b"", "cnc-conclusion-flow")
''', default_timeout=90).run()
    assert not app.exception
    return app


def _submit(app, *, diameter=4., flute=8., reach=10.):
    for key, value in (("cnc_diameter", diameter), ("cnc_flute", flute), ("cnc_reach", reach)):
        app.number_input(key=key).set_value(value)
    app.button(key="run_cnc_review").click().run()
    assert not app.exception
    return app.session_state["cnc_report"]


def test_first_screen_hides_geometry_until_location_requested_and_keeps_real_dimensions():
    app = _open()
    report = _submit(app)
    pocket = next(item for item in report["findings"] if item["id"] == "cnc_rectangular_pockets")
    assert pocket["measurements"]["pockets"][0]["width_mm"] == pytest.approx(3.)
    assert pocket["measurements"]["pockets"][0]["wall_height_mm"] == pytest.approx(20.)
    assert app.session_state["cnc_location_details"] is False
    assert not app.get("plotly_chart")
    assert not any(widget.key == "cnc_finding" for widget in app.selectbox)
    assert not any("내장 AI 검토" in item.value for item in app.subheader)
    assert not any("전체 개선 항목" in item.label for item in app.expander)

    # Follow the first conclusion's actual location action, not a test-only
    # shortcut that changes selection state without running the callback.
    app.button(key="cnc_conclusion_location").click().run()
    assert not app.exception
    assert app.session_state["cnc_location_details"] is True
    assert app.get("plotly_chart")
    app.selectbox(key="cnc_finding").set_value("cnc_rectangular_pockets").run()
    expected_face = str(pocket["measurements"]["pockets"][0]["floor_face_id"])
    app.selectbox(key="cnc_location").set_value(expected_face).run()
    assert not app.exception
    table = next(item.value for item in app.dataframe if "바닥 폭 (mm)" in item.value.columns)
    assert table.iloc[0]["바닥 폭 (mm)"] == pytest.approx(3.)
    assert table.iloc[0]["벽 높이 (mm)"] == pytest.approx(20.)
    assert table.iloc[0]["입력 공구 지름 (mm)"] == pytest.approx(4.)
    assert table.iloc[0]["입력 절삭 날 길이 (mm)"] == pytest.approx(8.)
    assert table.iloc[0]["공구보다 좁음"] == "예"

    before = deepcopy(app.session_state["cnc_report"])
    app.toggle(key="cnc_location_details").set_value(False).run()
    assert not app.get("plotly_chart")
    assert app.session_state["cnc_report"] == before


def test_changed_conditions_clear_old_result_and_restart_at_conclusion():
    app = _open()
    _submit(app)
    app.toggle(key="cnc_location_details").set_value(True).run()
    assert app.get("plotly_chart")
    app.number_input(key="cnc_diameter").set_value(2.).run()
    assert not app.exception
    assert not app.get("download_button")
    report = _submit(app, diameter=2.)
    assert report["profile"]["tool_diameter_mm"] == 2.
    assert app.session_state["cnc_location_details"] is False
    assert not app.get("plotly_chart")
    pocket = next(item for item in report["findings"] if item["id"] == "cnc_rectangular_pockets")
    row = pocket["measurements"]["pockets"][0]
    assert row["width_too_small"] is False
    assert row["exceeds_flute_length"] is True

def test_external_feature_location_and_main_location_can_be_open_together():
    app=_open();_submit(app)
    # AppTest has no expander click API; this is the same tracked open state
    # emitted by the native expander. No second location button is required.
    assert not any(b.key == 'external_feature_show' for b in app.button)
    app.session_state['external_feature_panel']=True
    app.run()
    assert len(app.get('plotly_chart'))==1
    app.toggle(key='cnc_location_details').set_value(True)
    app.session_state['external_feature_panel']=True
    app.run()
    assert not app.exception
    assert len(app.get('plotly_chart'))==2


def test_omitted_measurement_and_missing_tool_remain_unknown_in_optional_evidence():
    app = _open("03_rounded_pocket")
    app.toggle(key="cnc_auto_tool").set_value(False)
    app.checkbox(key="cnc_visibility").uncheck()
    report = _submit(app, diameter=None, flute=None, reach=None)
    assert report["visibility"] is None
    corner = next(item for item in report["findings"] if item["id"] == "cnc_curved_corners")
    assert corner["status"] == "unknown"
    assert app.session_state["cnc_location_details"] is False
    app.toggle(key="cnc_location_details").set_value(True).run()
    app.selectbox(key="cnc_finding").set_value("cnc_curved_corners").run()
    table = next(item.value for item in app.dataframe if "공구 반경 (mm)" in item.value.columns)
    assert set(table["공구 반경 (mm)"]) == {"미입력·미비교"}
    app.selectbox(key="cnc_finding").set_value("cnc_visibility").run()
    assert not app.exception
    assert app.session_state["cnc_report"]["visibility"] is None
    assert "항목 전체 · 판단에 필요한 정보 부족" in [item.value for item in app.caption]
