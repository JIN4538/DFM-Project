"""User decisions retain missing data and navigate actual measured locations."""
from copy import deepcopy
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from dfm.machining_view import machining_decisions


ROOT = Path(__file__).resolve().parents[1]


def record(identifier, status, measures):
    return dict(id=identifier, title=identifier, status=status, measurements=measures,
                reason="측정한 범위", action="원래의 조건부 조치", face_indices=[], cad_face_ids=[])


def test_problem_and_missing_information_are_separate_without_mutating_report():
    pocket = dict(floor_face_id=19, width_mm=3., wall_height_mm=20., width_too_small=True,
                  exceeds_flute_length=None, exceeds_reach=None)
    report = dict(profile=dict(tool_diameter_mm=4., flute_length_mm=None, reach_mm=None), findings=[
        record("cnc_coverage", "unknown", {}),
        record("cnc_rectangular_pockets", "attention", {"pockets": [pocket]})])
    before = deepcopy(report)
    result = machining_decisions(report)
    assert [r["id"] for r in result["cards"]] == ["cnc_rectangular_pockets"]
    assert [r["id"] for r in result["pending"]] == ["cnc_coverage"]
    assert result["missing_inputs"] == ["날 길이", "장착 후 돌출 길이"]
    assert result["cards"][0]["face_id"] == 19
    assert any("3 / 4 mm" in x for x in result["cards"][0]["comparisons"])
    assert report == before


def test_first_card_targets_an_offending_face_not_the_first_measured_face():
    report = dict(profile=dict(tool_diameter_mm=8.), findings=[
        record("cnc_curved_corners", "attention", {"cylindrical_faces": [
            dict(face_id=3, radius_mm=8., tool_too_large=False),
            dict(face_id=17, radius_mm=3., tool_too_large=True)]})])
    card = machining_decisions(report)["cards"][0]
    assert card["face_id"] == 17
    assert card["comparisons"] == ["형상 반경 3 mm / 공구 반경 4 mm"]


def test_axis_mismatch_does_not_fabricate_size_comparison():
    report = dict(profile=dict(tool_diameter_mm=8., reach_mm=10.), findings=[
        record("cnc_holes", "attention", {"cylindrical_faces": [dict(
            face_id=8, axis_aligned=False, axis_angle_deg=90., diameter_mm=6.,
            cylindrical_length_mm=15., tool_too_large=None, segment_exceeds_reach=None)]})])
    card = machining_decisions(report)["cards"][0]
    assert card["comparisons"] == ["선택한 공구축과 원통축의 차이 90° · 치수 비교 보류"]
    assert not machining_decisions(report)["missing_inputs"]


def test_unmeasured_visibility_is_pending_not_a_zero_problem_count():
    report = dict(profile={}, findings=[record("cnc_visibility", "unknown", {})])
    result = machining_decisions(report)
    assert not result["cards"]
    assert result["pending"][0]["id"] == "cnc_visibility"
    assert not result["missing_inputs"]


def test_deep_narrow_pocket_actions_address_each_observed_tool_conflict():
    pocket = dict(floor_face_id=19, width_mm=3., wall_height_mm=20., width_too_small=True,
                  exceeds_flute_length=True, exceeds_reach=True)
    report = dict(profile=dict(tool_diameter_mm=4., flute_length_mm=8., reach_mm=10.), findings=[
        record("cnc_rectangular_pockets", "attention", {"pockets": [pocket]})])
    before = deepcopy(report)
    action = machining_decisions(report)["cards"][0]["action"]
    assert "폭 3 mm" in action and "더 작은 공구" in action and "포켓 폭을 넓히세요" in action
    assert "재고정·장착 조건" in action and "홀더 여유를 CAM" in action
    assert "분할 절입·목부 공구" in action and "긴 공구가 항상 해결책은 아닙니다" in action
    assert "내부 직각에는 반경이나 코너 여유" in action
    assert report == before


@pytest.mark.parametrize("flag,boundary", [(None, False), (False, False), (False, True)])
def test_unmeasured_or_nonexceeding_pocket_does_not_suggest_tool_changes(flag, boundary):
    pocket = dict(floor_face_id=19, width_mm=4., wall_height_mm=8., width_too_small=flag,
                  exceeds_flute_length=flag, exceeds_reach=flag)
    if boundary:
        pocket["numerical_boundary_comparisons"] = ["width_too_small", "exceeds_flute_length", "exceeds_reach"]
    profile = dict(tool_diameter_mm=None if flag is None else 4.,
                   flute_length_mm=None if flag is None else 8., reach_mm=None if flag is None else 8.)
    report = dict(profile=profile, findings=[
        record("cnc_rectangular_pockets", "attention", {"pockets": [pocket]})])
    before = deepcopy(report)
    result = machining_decisions(report)
    assert result["cards"][0]["action"] == "원래의 조건부 조치"
    assert result["missing_inputs"] == (["공구 지름", "날 길이", "장착 후 돌출 길이"] if flag is None else [])
    assert report == before


def open_view(case):
    path = str(ROOT / "examples/machining" / (case + ".step"))
    script = f'''
from pathlib import Path
import streamlit as st
from amdfm.io import load_model
from dfm.machining_view import render_machining
@st.cache_resource
def model():
    path = Path({path!r})
    return load_model(path.read_bytes(), path.name)
render_machining(model(), {case!r}, b"", "decision-ui-test")
'''
    app = AppTest.from_string(script, default_timeout=75).run()
    assert not app.exception
    return app


def submit(app):
    next(button for button in app.button if button.label == "절삭 설계 검토").click().run()
    assert not app.exception
    return app.session_state["cnc_report"]


def test_first_review_computes_visibility_and_location_button_selects_measured_floor():
    app = open_view("02_narrow_deep_pocket")
    assert app.checkbox(key="cnc_visibility").value is True
    app.number_input(key="cnc_diameter").set_value(4.)
    app.number_input(key="cnc_flute").set_value(8.)
    app.number_input(key="cnc_reach").set_value(10.)
    report = submit(app)
    assert report["visibility"] is not None
    assert report["visibility"]["budget"]["timeout_s"] == 10.
    pocket = next(f for f in report["findings"] if f["id"] == "cnc_rectangular_pockets")
    expected_face = pocket["measurements"]["pockets"][0]["floor_face_id"]
    assert app.session_state["cnc_location_details"] is False
    app.button(key="cnc_learned_cnc_rectangular_pockets").click().run()
    assert not app.exception
    table = next(element.value for element in app.dataframe if "바닥 폭 (mm)" in element.value.columns)
    assert table.iloc[0]["바닥 폭 (mm)"] == pytest.approx(3.)
    assert table.iloc[0]["입력 공구 지름 (mm)"] == pytest.approx(4.)
    assert table.iloc[0]["벽 높이 (mm)"] == pytest.approx(20.)
    assert table.iloc[0]["입력 절삭 날 길이 (mm)"] == pytest.approx(8.)
    assert table.iloc[0]["입력 돌출 길이 (mm)"] == pytest.approx(10.)
    app.selectbox(key="cnc_finding").set_value("cnc_input").run()
    app.button(key="cnc_learned_cnc_rectangular_pockets").click().run()
    assert not app.exception
    assert app.selectbox(key="cnc_finding").value == "cnc_rectangular_pockets"
    assert app.selectbox(key="cnc_location").value == str(expected_face)
    assert app.session_state["cnc_report"] == report


def test_missing_tool_input_is_visible_and_user_can_opt_out_of_visibility():
    app = open_view("01_rectangular_pocket")
    app.toggle(key="cnc_auto_tool").set_value(False)
    app.checkbox(key="cnc_visibility").uncheck()
    report = submit(app)
    assert report["visibility"] is None
    measurements = {item.label: item.value for item in app.metric}
    assert measurements["엔드밀 지름"] == "미입력"
    assert measurements["날 길이"] == "미입력"
    assert measurements["장착 후 돌출 길이"] == "미입력"
    assert any("추가 확인" in x.value for x in app.caption)
    app.button(key="cnc_learned_cnc_visibility").click().run()
    assert not app.exception
    assert app.selectbox(key="cnc_finding").value == "cnc_visibility"
    assert app.session_state["cnc_report"]["visibility"] is None
