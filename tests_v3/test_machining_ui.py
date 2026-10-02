"""User workflows for the separate AM and fixed-axis machining results."""
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
CASES = {c["id"]: c["title"] for c in json.loads((ROOT / "examples/machining/manifest.json").read_text(encoding="utf-8"))}


def open_machining(case="01_rectangular_pocket"):
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=75).run()
    app.selectbox(key="manufacturing_family").select("절삭가공").run()
    app.selectbox(key="source").select("절삭 시연용 형상").run()
    app.selectbox(key="demo_example").select(CASES[case]).run()
    assert not app.exception
    return app


def submit(app):
    next(b for b in app.button if b.label == "절삭 설계 검토").click().run()
    assert not app.exception
    # Detailed measurements are now requested explicitly after the conclusion.
    app.toggle(key="cnc_location_details").set_value(True).run()
    assert not app.exception
    return app.session_state["cnc_report"]


def measured_table(app, required_column):
    """AI provenance has its own table; select the actual measurement table."""
    return next(element.value for element in app.dataframe if required_column in element.value.columns)


def test_cnc_measure_without_tool_and_stale_condition_results():
    app = open_machining()
    app.toggle(key="cnc_auto_tool").set_value(False)
    assert not [b for b in app.get("download_button") if b.key != "demo_download"]
    report = submit(app)
    pocket = next(f for f in report["findings"] if f["id"] == "cnc_rectangular_pockets")
    assert pocket["status"] == "attention"
    assert pocket["measurements"]["pockets"][0]["width_mm"] == pytest.approx(12)
    assert report["profile"]["tool_diameter_mm"] is None
    assert len([b for b in app.get("download_button") if b.key != "demo_download"]) == 3
    assert "미입력·미비교" in measured_table(app, "바닥 폭 (mm)").to_string()
    visible_text = "\n".join(element.value for element in list(app.markdown) + list(app.caption))
    assert "](None)" not in visible_text
    for source in report["sources"]:
        for key in ("scope", "locator", "access", "local_path"):
            if source.get(key):
                assert source[key] in visible_text
    app.selectbox(key="cnc_direction").select("+X").run()
    assert not app.exception and not [b for b in app.get("download_button") if b.key != "demo_download"]
    assert app.button(key="cnc_start_from_model")
    assert not any(item.label == "확인할 항목" for item in app.selectbox)
    changed = submit(app)
    assert changed["direction"] == [1., 0., 0.]
    pocket = next(f for f in changed["findings"] if f["id"] == "cnc_rectangular_pockets")
    # From +X, the x=10 internal wall is a potential floor, but its open side
    # and unequal adjacent spans do not meet the four-equal-wall recognizer.
    # Preserve this unmeasured location instead of reporting no pocket.
    assert pocket["status"] == "unknown"
    assert pocket["measurements"]["pockets"] == []
    assert pocket["measurements"]["unresolved_floor_face_ids"] == [10]


def test_cnc_tool_comparison_and_invalid_condition_no_export():
    app = open_machining("02_narrow_deep_pocket")
    app.number_input(key="cnc_diameter").set_value(4.)
    app.number_input(key="cnc_flute").set_value(8.)
    app.number_input(key="cnc_reach").set_value(10.)
    report = submit(app)
    pocket = next(f for f in report["findings"] if f["id"] == "cnc_rectangular_pockets")["measurements"]["pockets"][0]
    assert pocket["width_too_small"] and pocket["exceeds_flute_length"] and pocket["exceeds_reach"]
    app.number_input(key="cnc_flute").set_value(11.)
    next(b for b in app.button if b.label == "절삭 설계 검토").click().run()
    assert not app.exception
    assert any("날 길이" in x.value for x in app.error)
    assert not [b for b in app.get("download_button") if b.key != "demo_download"]


def test_changed_geometry_keeps_option_order_and_selected_result_consistent():
    app = open_machining()
    app.number_input(key="cnc_diameter").set_value(8.)
    app.number_input(key="cnc_flute").set_value(10.)
    app.number_input(key="cnc_reach").set_value(15.)
    submit(app)
    assert app.selectbox(key="cnc_finding").value == "cnc_rectangular_pockets"
    original_options = list(app.selectbox(key="cnc_finding").options)
    app.selectbox(key="demo_example").select(CASES["03_rounded_pocket"]).run()
    submit(app)
    # Optional automatic-tool conditions append an item; common CAD findings
    # retain their order and the active finding follows the new report.
    common_options = lambda options: [x for x in options if x != "자동 공구 치수 제안"]
    assert common_options(app.selectbox(key="cnc_finding").options) == common_options(original_options)
    assert app.selectbox(key="cnc_finding").value == "cnc_curved_corners"
    assert any("작은 반경은 4개" in x.value for x in app.markdown)
    app.number_input(key="cnc_diameter").set_value(4.)
    submit(app)
    assert common_options(app.selectbox(key="cnc_finding").options) == common_options(original_options)
    # A new review may focus an unresolved feature once the corner conflict is
    # resolved. The user can still inspect that resolved corner explicitly.
    app.selectbox(key="cnc_finding").set_value("cnc_curved_corners").run()
    assert any("작은 반경은 0개" in x.value for x in app.markdown)
    graph = json.loads(app.get("plotly_chart")[0].proto.spec)
    assert all(t["flatshading"] for t in graph["data"] if t["type"] == "mesh3d")


def test_visibility_shows_back_facing_and_tangent_samples_without_am_axis():
    app = open_machining("10_plain_block")
    app.checkbox(key="cnc_visibility").check()
    report = submit(app)
    assert report["visibility"]["status"] == "complete"
    counts = report["visibility"]["measurements"]["sample_state_counts"]
    assert counts["back_facing"] and counts["tangent"]
    app.selectbox(key="cnc_finding").set_value("cnc_visibility").run()
    assert not app.exception
    table = measured_table(app, "표본 분류")
    assert set(table["표본 분류"]) >= {"공구 반대쪽을 향한 표본", "공구축과 평행한 면의 표본"}
    spec = json.dumps(json.loads(app.get("plotly_chart")[0].proto.spec), ensure_ascii=False)
    assert "공구가 오는 쪽" in spec and "적층 +Z" not in spec
    app.selectbox(key="cnc_sample_state").set_value("back_facing").run()
    assert not app.exception
    graph = json.loads(app.get("plotly_chart")[0].proto.spec)
    assert any(t.get("name") == "공구 반대쪽을 향한 표본" for t in graph["data"])
    assert not any(t.get("name") == "앞이 가려진 표본" for t in graph["data"])


def test_switching_process_never_displays_other_process_report():
    app = open_machining()
    submit(app)
    app.selectbox(key="manufacturing_family").select("적층제조").run()
    assert not app.exception
    assert not any(b.label == "절삭 설계 검토" for b in app.button)
    assert not [b for b in app.get("download_button") if b.key != "demo_download"]
    next(b for b in app.button if b.label == "설계 검토").click().run()
    assert not app.exception
    assert app.session_state["report"]["profile"]["process"] == "MEX"
    app.selectbox(key="manufacturing_family").select("절삭가공").run()
    assert not app.exception
    assert not app.segmented_control
    assert not any(b.label == "설계 검토" for b in app.button)
