"""Real app requirement flow with an offline AI boundary and real DFM engines."""
from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pytest
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.errors import AppTestError

import dfm.advisor_view as advisor_view
from dfm.ai_client import parse_intent as real_parse_intent


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
FAKE_KEY = "sk-offline-ui-test-not-a-real-key"
REQUEST = "Prusa MK4S로 PLA를 FDM 출력하고 서포트를 줄이고 싶어."
INTENT = dict(equipment="Prusa MK4S", material="PLA", priority="support", process="MEX",
              notes=["서포트를 줄이고 싶어"])
PROVENANCE = dict(provider="openai", model="gpt-4.1-mini-2025-04-14", response_id="resp_offline_ui")


@pytest.fixture
def fake_ai(monkeypatch):
    """Never load a user's environment/secrets key or send an external request."""
    state = {"calls": [], "intent": deepcopy(INTENT), "network_failure": False}
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(advisor_view, "_key",
                        lambda: advisor_view.st.session_state.get("advisor_api_key", "").strip())

    def parse(text, *, api_key, model):
        state["calls"].append(dict(text=text, api_key=api_key, model=model))
        if state["network_failure"]:
            def failed_transport(*args, **kwargs):
                raise RuntimeError("RAW_PRIVATE_PROVIDER_BODY " + FAKE_KEY)
            # Exercise the real boundary's sanitization as well as the UI's
            # error handling, while replacing its only network operation.
            return real_parse_intent(text, api_key=api_key, model=model, transport=failed_transport)
        return dict(intent=deepcopy(state["intent"]), provenance=deepcopy(PROVENANCE))
    monkeypatch.setattr(advisor_view, "parse_intent", parse)
    return state


def open_app():
    app = AppTest.from_file(str(APP), default_timeout=90).run()
    assert not app.exception
    return app


def input_name(app, key, value):
    # AppTest 1.63 cannot encode a newly typed selectbox option without adding
    # the frontend-created label to its local list; the server still receives
    # the new string and runs the real name-change callback.
    widget = app.selectbox(key=key)
    if value not in widget.options:
        widget.options.append(value)
    widget.set_value(value).run()


def am_review(app):
    next(button for button in app.button if button.label == "설계 검토").click().run()
    assert not app.exception
    return app.session_state["report"]


def interpret(app, text=REQUEST):
    app.text_input(key="advisor_api_key").set_value(FAKE_KEY).run()
    app.text_area(key="advisor_request").set_value(text).run()
    app.button(key="advisor_interpret").click().run()
    assert not app.exception


def test_no_key_disables_ai_and_ordinary_reruns_never_make_requests(fake_ai):
    app = open_app()
    app.text_area(key="advisor_request").set_value(REQUEST).run()
    assert app.button(key="advisor_interpret").disabled and fake_ai["calls"] == []
    app.text_input(key="advisor_api_key").set_value(FAKE_KEY).run()
    assert not app.button(key="advisor_interpret").disabled
    app.selectbox(key="advisor_priority_MEX").select("height").run()
    app.run()
    assert fake_ai["calls"] == []
    app.button(key="advisor_interpret").click().run()
    assert len(fake_ai["calls"]) == 1
    app.run()
    input_name(app, "material_MEX", "PETG")
    assert len(fake_ai["calls"]) == 1 and not app.exception
    app.button(key="advisor_forget_key").click().run()
    assert app.text_input(key="advisor_api_key").value == ""
    assert app.button(key="advisor_interpret").disabled
    assert len(fake_ai["calls"]) == 1


def test_ai_draft_requires_acceptance_and_changes_context_without_inventing_limits(fake_ai):
    app = open_app()
    app.selectbox(key="cad_example").select("직육면체 · 10×20×30 mm").run()
    before = deepcopy(am_review(app))
    interpret(app)
    assert len(fake_ai["calls"]) == 1
    assert app.session_state["advisor_draft"]["intent"] == INTENT
    assert app.session_state["report"] == before
    assert app.selectbox(key="machine_MEX").value == before["profile"]["machine"]
    assert app.selectbox(key="advisor_priority_MEX").value == "balanced"
    app.button(key="advisor_accept").click().run()
    assert not app.exception
    assert app.selectbox(key="machine_MEX").value == "Prusa MK4S"
    assert app.selectbox(key="material_MEX").value == "PLA"
    assert app.selectbox(key="advisor_priority_MEX").value == "support"
    # Acceptance changes inputs; it does not silently bill another AI request,
    # start a geometry run, or apply a similar-looking library profile.
    assert len(fake_ai["calls"]) == 1
    assert app.session_state["report"] == before
    assert not app.segmented_control
    assert app.number_input(key="wall_limit_MEX").value == 1.2
    assert app.number_input(key="hole_limit_MEX").value is None
    assert app.number_input(key="line_width").value == .4
    report = am_review(app)
    context = report["review_context"]
    assert context["mode"] == "ai" and context["priority"] == "support"
    assert context["provenance"] == PROVENANCE and context["notes"] == INTENT["notes"]
    assert report["profile"]["machine"] == "Prusa MK4S" and report["profile"]["material"] == "PLA"
    assert report["profile"]["minimum_wall_mm"] == 1.2
    assert report["profile"]["layer_height_mm"] == before["profile"]["layer_height_mm"]
    policy = report["orientation_recommendation"]["policy"]
    assert policy["requested_priority"] == "support" and policy["effective_priority"] == "support"
    assert FAKE_KEY not in json.dumps(report, ensure_ascii=False)
    assert len(fake_ai["calls"]) == 1


def test_changed_request_invalidates_draft_and_cannot_apply_stale_text(fake_ai):
    app = open_app()
    interpret(app)
    old_machine = app.selectbox(key="machine_MEX").value
    app.text_area(key="advisor_request").set_value("장비를 바꾸었어. 다시 검토할게.").run()
    assert app.button(key="advisor_accept").disabled
    assert any("문장이 바뀌었습니다" in item.value for item in app.warning)
    # AppTest, like the browser, refuses interaction with this disabled button.
    with pytest.raises(AppTestError, match="Cannot update a disabled"):
        app.button(key="advisor_accept").click()
    assert not app.exception
    assert app.selectbox(key="machine_MEX").value == old_machine
    assert app.selectbox(key="advisor_priority_MEX").value == "balanced"
    assert len(fake_ai["calls"]) == 1


def test_failed_ai_removes_old_draft_without_echoing_provider_body_or_key(fake_ai):
    app = open_app()
    interpret(app)
    assert app.button(key="advisor_accept")
    fake_ai["network_failure"] = True
    app.button(key="advisor_interpret").click().run()
    assert not app.exception and len(fake_ai["calls"]) == 2
    assert not any(button.key == "advisor_accept" for button in app.button)
    assert any("연결하지 못했습니다" in item.value for item in app.error)
    visible = "\n".join(item.value for item in list(app.error) + list(app.markdown) + list(app.caption))
    assert "RAW_PRIVATE_PROVIDER_BODY" not in visible and FAKE_KEY not in visible
    app.run()
    assert len(fake_ai["calls"]) == 2


def test_priority_change_invalidates_result_and_recommendation_apply_preserves_it(fake_ai):
    app = open_app()
    app.selectbox(key="cad_example").select("직육면체 · 10×20×30 mm").run()
    before = deepcopy(am_review(app))
    app.selectbox(key="advisor_priority_MEX").select("height").run()
    assert not app.segmented_control and not app.get("download_button")
    report = am_review(app)
    assert report["review_context"]["priority"] == "height"
    recommendation = report["orientation_recommendation"]
    assert recommendation["policy"]["effective_priority"] == "height"
    assert not recommendation["keep_current"]
    expected = recommendation["recommended"]["direction"]
    app.button(key="am_apply_plan").click().run()
    assert not app.exception
    applied = app.session_state["report"]
    np.testing.assert_allclose(applied["current_orientation"]["direction"], expected, atol=1e-12)
    assert applied["review_context"]["priority"] == "height"
    assert applied["orientation_recommendation"]["policy"]["effective_priority"] == "height"
    assert app.selectbox(key="advisor_priority_MEX").value == "height"
    assert applied["current_orientation"]["height_mm"] < before["current_orientation"]["height_mm"]
    assert fake_ai["calls"] == []


def test_ai_can_select_cnc_context_while_tool_dimensions_remain_user_inputs(fake_ai):
    app = open_app()
    fake_ai["intent"] = dict(equipment="Haas VF-2", material="6061", priority="tool_access", process="CNC",
                              notes=["공구 접근을 중점으로"])
    interpret(app, "Haas VF-2로 6061을 절삭하고 공구 접근을 중점으로 검토해줘.")
    app.button(key="advisor_accept").click().run()
    assert not app.exception
    assert app.selectbox(key="manufacturing_family").value == "절삭가공"
    assert app.selectbox(key="cnc_machine").value == "Haas VF-2"
    assert app.selectbox(key="cnc_material").value == "6061"
    assert app.selectbox(key="advisor_priority_CNC").value == "tool_access"
    assert app.number_input(key="cnc_diameter").value is None
    assert app.number_input(key="cnc_flute").value is None
    assert app.number_input(key="cnc_reach").value is None
    app.selectbox(key="source").select("절삭 검증 형상").run()
    cases = json.loads((ROOT / "examples/machining/manifest.json").read_text(encoding="utf-8"))
    title = next(row["title"] for row in cases if row["id"] == "02_narrow_deep_pocket")
    app.selectbox(key="cnc_example").select(title).run()
    app.number_input(key="cnc_diameter").set_value(4.)
    app.number_input(key="cnc_flute").set_value(8.)
    app.number_input(key="cnc_reach").set_value(10.)
    next(button for button in app.button if button.label == "절삭 설계 검토").click().run()
    assert not app.exception
    report = app.session_state["cnc_report"]
    assert report["review_context"]["priority"] == "tool_access"
    assert report["review_context"]["mode"] == "ai"
    assert report["review_context"]["provenance"] == PROVENANCE
    assert report["profile"]["tool_diameter_mm"] == 4.
    pocket = next(item for item in report["findings"] if item["id"] == "cnc_rectangular_pockets")
    assert pocket["measurements"]["pockets"][0]["width_too_small"]
    assert any("공구 접근" in item.value for item in app.caption)
    assert FAKE_KEY not in json.dumps(report, ensure_ascii=False)
    assert len(fake_ai["calls"]) == 1


@pytest.mark.parametrize("name_change", ["ai", "manual"])
def test_am_name_change_clears_old_source_limits_but_priority_only_keeps_them(fake_ai, name_change):
    app = open_app()
    app.selectbox(key="condition_preview_MEX").select("am-prusa-mk4s").run()
    app.button(key="apply_condition_MEX").click().run()
    assert not app.exception
    source_machine = app.selectbox(key="machine_MEX").value
    source_material = app.selectbox(key="material_MEX").value
    app.checkbox(key="use_build_MEX").check()
    app.number_input(key="wall_limit_MEX").set_value(2.)
    before = deepcopy(am_review(app))
    assert before["profile"]["condition_evidence"]["profile_id"] == "am-prusa-mk4s"
    assert before["profile"]["build_volume_mm"] is not None

    # A request about priority alone has no authority to replace equipment or
    # erase the deliberately selected manufacturing conditions.
    fake_ai["intent"] = dict(equipment="", material="", priority="height", process="unknown", notes=[])
    interpret(app, "높이를 낮추는 것을 먼저 봐줘")
    app.button(key="advisor_accept").click().run()
    assert app.selectbox(key="machine_MEX").value == source_machine
    assert app.selectbox(key="material_MEX").value == source_material
    assert app.number_input(key="wall_limit_MEX").value == 2.
    assert app.checkbox(key="use_build_MEX").value
    assert app.session_state["applied_condition_MEX"]["profile_id"] == "am-prusa-mk4s"

    if name_change == "ai":
        fake_ai["intent"] = dict(equipment="다른 프린터", material="", priority="height", process="MEX", notes=[])
        app.text_area(key="advisor_request").set_value("다른 프린터로 바꿨어").run()
        app.button(key="advisor_interpret").click().run()
        app.button(key="advisor_accept").click().run()
    else:
        input_name(app, "machine_MEX", "다른 프린터")
    assert not app.exception
    assert app.selectbox(key="machine_MEX").value == "다른 프린터"
    assert app.selectbox(key="material_MEX").value == source_material
    assert app.number_input(key="wall_limit_MEX").value == 1.2
    assert app.number_input(key="hole_limit_MEX").value is None
    assert not app.checkbox(key="use_build_MEX").value
    assert not app.segmented_control and not app.get("download_button")
    report = am_review(app)
    assert report["profile"]["machine"] == "다른 프린터"
    assert report["profile"]["build_volume_mm"] is None
    assert report["profile"]["minimum_wall_mm"] == 1.2
    assert report["profile"]["condition_evidence"] == {}
    assert report["review_context"]["priority"] == "height"
    assert len(fake_ai["calls"]) == (2 if name_change == "ai" else 1)
