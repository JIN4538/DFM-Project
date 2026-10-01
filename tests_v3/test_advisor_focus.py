"""A fresh review follows its priority; manual focus survives ordinary reruns.

Use real STEP geometry and production detail/visibility workers. The cached
geometry timestamps deliberately stay the same when only user intent changes.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from amdfm.workflow import action_plan
import dfm.advisor_view as advisor_view
from dfm.machining_view import machining_decisions


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def forbid_ai_requests(monkeypatch):
    """These manual-priority scenarios must never load keys or call an API."""
    monkeypatch.setattr(advisor_view, "_key", lambda: "")

    def unexpected_request(*args, **kwargs):
        pytest.fail("A manual priority change must not make an AI request")

    monkeypatch.setattr(advisor_view, "parse_intent", unexpected_request)


def open_app():
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=90).run()
    assert not app.exception
    return app


def submit(app, label, report_key):
    next(button for button in app.button if button.label == label).click().run()
    assert not app.exception
    key = "cnc_location_details" if report_key == "cnc_report" else "am_location_details"
    assert app.toggle(key=key).value is False
    app.toggle(key=key).set_value(True).run()
    assert not app.exception
    return deepcopy(app.session_state[report_key])


def test_am_priority_change_refocuses_cached_geometry_but_keeps_manual_selection():
    app = open_app()
    app.selectbox(key="cad_example").select("브래킷 · 두께 4 mm").run()
    app.selectbox(key="build_direction").select("-Z").run()
    app.number_input(key="wall_limit_MEX").set_value(5.)
    before = submit(app, "설계 검토", "report")
    candidates = {item["id"] for item in action_plan(before)["actions"]
                  if item["action_kind"] == "candidate"}
    assert {"wall", "overhang"} <= candidates
    assert before["review_context"]["priority"] == "balanced"
    assert action_plan(before)["primary"]["id"] == "wall"
    assert app.selectbox(key="highlight_finding").value == "wall"

    # Inspecting another item is a user choice and must survive a normal rerun.
    app.selectbox(key="highlight_finding").select("overhang").run()
    app.run()
    assert app.selectbox(key="highlight_finding").value == "overhang"
    app.selectbox(key="highlight_finding").select("wall").run()

    app.selectbox(key="advisor_priority_MEX").select("support").run()
    assert not app.segmented_control
    after = submit(app, "설계 검토", "report")
    assert after["model_fingerprint"] == before["model_fingerprint"]
    assert after["profile"] == before["profile"]
    assert after["current_orientation"] == before["current_orientation"]
    assert after["timestamp_utc"] == before["timestamp_utc"]
    assert after["review_context"]["priority"] == "support"
    assert action_plan(after)["primary"]["id"] == "overhang"
    assert app.selectbox(key="highlight_finding").value == "overhang"

    app.selectbox(key="highlight_finding").select("wall").run()
    app.run()
    assert not app.exception
    assert app.selectbox(key="highlight_finding").value == "wall"


def test_cnc_priority_change_refocuses_cached_geometry_but_keeps_manual_selection():
    app = open_app()
    app.selectbox(key="manufacturing_family").select("절삭가공").run()
    app.selectbox(key="source").select("절삭 검증 형상").run()
    cases = json.loads((ROOT / "examples/machining/manifest.json").read_text(encoding="utf-8"))
    title = next(row["title"] for row in cases if row["id"] == "05_side_hole")
    app.selectbox(key="cnc_example").select(title).run()
    app.number_input(key="cnc_diameter").set_value(4.)
    app.number_input(key="cnc_flute").set_value(8.)
    app.number_input(key="cnc_reach").set_value(10.)
    before = submit(app, "절삭 설계 검토", "cnc_report")
    findings = {item["id"]: item for item in before["findings"]}
    assert findings["cnc_holes"]["status"] == "attention"
    assert findings["cnc_visibility"]["status"] == "attention"
    assert before["visibility"]["measurements"]["sample_state_counts"]["occluded"] > 0
    assert before["review_context"]["priority"] == "balanced"
    assert machining_decisions(before)["cards"][0]["id"] == "cnc_holes"
    assert app.selectbox(key="cnc_finding").value == "cnc_holes"

    app.selectbox(key="cnc_finding").select("cnc_visibility").run()
    app.run()
    assert app.selectbox(key="cnc_finding").value == "cnc_visibility"
    app.selectbox(key="cnc_finding").select("cnc_holes").run()

    app.selectbox(key="advisor_priority_CNC").select("tool_access").run()
    assert not app.get("download_button")
    after = submit(app, "절삭 설계 검토", "cnc_report")
    assert after["model_fingerprint"] == before["model_fingerprint"]
    assert after["profile"] == before["profile"]
    assert after["direction"] == before["direction"]
    assert after["created_utc"] == before["created_utc"]
    assert after["review_context"]["priority"] == "tool_access"
    assert machining_decisions(after)["cards"][0]["id"] == "cnc_visibility"
    assert app.selectbox(key="cnc_finding").value == "cnc_visibility"

    app.selectbox(key="cnc_finding").select("cnc_holes").run()
    app.run()
    assert not app.exception
    assert app.selectbox(key="cnc_finding").value == "cnc_holes"
