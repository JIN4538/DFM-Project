"""Blank inputs produce measured proposals; manual overrides remain visible."""
import pytest

from test_cnc_conclusion_ui import _open, _submit
from dfm.machining_view import machining_html
from dfm.conditions import load_library, condition_html
from dfm.tool_recommendation import recommend_tool_dimensions


def test_blank_tool_inputs_need_only_one_review_and_export_same_values():
    app = _open()
    assert app.toggle(key="cnc_auto_tool").value is True
    app.checkbox(key="cnc_visibility").uncheck()
    report = _submit(app, diameter=None, flute=None, reach=None)
    profile = report["profile"]
    assert profile["tool_diameter_mm"] == pytest.approx(2.4)
    assert profile["flute_length_mm"] >= 20.
    assert profile["reach_mm"] >= profile["flute_length_mm"]
    assert set(report["tool_recommendation"]["automatic_fields"]) == {
        "tool_diameter_mm", "flute_length_mm", "reach_mm"}
    pocket = next(x for x in report["findings"] if x["id"] == "cnc_rectangular_pockets")
    measurement = pocket["measurements"]["pockets"][0]
    assert not measurement["width_too_small"]
    assert not measurement["exceeds_flute_length"]
    assert not measurement["exceeds_reach"]
    # An exact internal right angle still needs a separate geometry action.
    assert pocket["status"] == "attention"
    assert app.number_input(key="cnc_diameter").value is None
    metrics = {x.label: x.value for x in app.metric}
    assert metrics["엔드밀 지름 · 자동"] == "2.4 mm"
    assert not app.get("plotly_chart")
    portable = machining_html(report)
    assert "검토에 적용한 공구" in portable
    assert "2.4 mm" in portable and "(자동)" in portable


def test_partial_manual_tool_is_preserved_and_auto_switch_invalidates_report():
    app = _open()
    report = _submit(app, diameter=2., flute=None, reach=None)
    assert report["profile"]["tool_diameter_mm"] == 2.
    assert "tool_diameter_mm" not in report["tool_recommendation"]["automatic_fields"]
    assert {x.label: x.value for x in app.metric}["엔드밀 지름 · 입력"] == "2 mm"
    app.toggle(key="cnc_auto_tool").set_value(False).run()
    assert not [b for b in app.get("download_button") if b.key != "demo_download"]
    report = _submit(app, diameter=2., flute=None, reach=None)
    assert report["profile"]["flute_length_mm"] is None
    assert report["profile"]["reach_mm"] is None
    assert "tool_recommendation" not in report


def test_block_does_not_invent_tool_size_and_fixed_values_still_raise_conflicts():
    app = _open("10_plain_block")
    report = _submit(app, diameter=None, flute=None, reach=None)
    assert all(report["profile"][key] is None for key in ("tool_diameter_mm", "flute_length_mm", "reach_mm"))
    assert not report["tool_recommendation"]["automatic_fields"]
    app = _open()
    report = _submit(app, diameter=4., flute=8., reach=10.)
    assert report["profile"]["tool_diameter_mm"] == 4.
    assert report["profile"]["flute_length_mm"] == 8.
    assert report["profile"]["reach_mm"] == 10.
    row = next(x for x in report["findings"] if x["id"] == "cnc_rectangular_pockets")["measurements"]["pockets"][0]
    assert row["width_too_small"] and row["exceeds_flute_length"] and row["exceeds_reach"]


def test_generated_library_input_is_not_exported_as_manufacturer_or_user_value():
    from test_tool_recommendation import measured_report
    library = load_library()
    profile = library.machining_profile("cnc-datron-0068010e", overrides={
        "tool_diameter_mm": None, "flute_length_mm": None, "reach_mm": None})
    report = measured_report(profile=profile, pockets=[dict(floor_face_id=1, width_mm=12., wall_height_mm=5.)])
    generated = recommend_tool_dimensions(report)["proposed_profile"]
    portable = condition_html(generated["condition_evidence"])
    assert "형상에서 자동 제안" in portable
    assert all(key not in generated["condition_evidence"]["user_inputs"] for key in (
        "tool_diameter_mm", "flute_length_mm", "reach_mm"))


def test_automatic_policy_change_recomputes_without_replacing_manual_value():
    app = _open()
    _submit(app, diameter=None, flute=None, reach=None)
    app.number_input(key="cnc_auto_diameter_percent").set_value(50.).run()
    assert not [b for b in app.get("download_button") if b.key != "demo_download"]
    report = _submit(app, diameter=None, flute=None, reach=None)
    assert report["profile"]["tool_diameter_mm"] == pytest.approx(1.5)
    report = _submit(app, diameter=2., flute=None, reach=None)
    assert report["profile"]["tool_diameter_mm"] == 2.
