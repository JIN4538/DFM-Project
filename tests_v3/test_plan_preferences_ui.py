"""Real preference callbacks and permitted edits, through the conclusion UI.

These small report fixtures isolate interaction wiring from CAD calculation.
The production candidate generator, fitted model, preference fit and persistence
all run; only the feedback file is redirected to pytest's temporary directory.
"""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import dfm.advisor_view as advisor_view
import dfm.plan_learning as planning


ALLOWANCES = {
    "형상·공구 모두": {"preserve_geometry": False, "allow_tool_change": True},
    "공구만 · 원래 형상 유지": {"preserve_geometry": True, "allow_tool_change": True},
    "형상만 · 현재 공구 유지": {"preserve_geometry": False, "allow_tool_change": False},
}
TOOL_FIELDS = {"tool_diameter_mm", "flute_length_mm", "reach_mm"}


def am_report():
    rows = [
        dict(name="A", direction=[0, 0, 1], height_mm=100.,
             overhang_projected_area_sum_mm2=0., contact_triangle_area_mm2=100.),
        dict(name="B", direction=[1, 0, 0], height_mm=40.,
             overhang_projected_area_sum_mm2=10., contact_triangle_area_mm2=80.),
        dict(name="C", direction=[0, 1, 0], height_mm=10.,
             overhang_projected_area_sum_mm2=20., contact_triangle_area_mm2=0.),
    ]
    for row in rows:
        row.update(build_fit=None, candidate_role="search")
    return dict(profile=dict(process="MEX", machine="test", material="test", build_volume_mm=None),
                model={"unit_status": "declared"}, summary={"review_status": "geometry_review"},
                findings=[], current_orientation=deepcopy(rows[0]), orientations=rows)


def cnc_report():
    return dict(process="MILLING_3AXIS", profile=dict(machine="test-mill", material="test-material",
                tool_diameter_mm=5., flute_length_mm=10., reach_mm=12., hole_depth_ratio_limit=None),
                findings=[
        dict(id="cnc_input", status="observed", measurements={"cad_feature_dimensions_available": True}),
        dict(id="cnc_holes", status="attention", measurements={"cylindrical_faces": [
            dict(face_id=12, diameter_mm=2., cylindrical_length_mm=20., axis_aligned=True,
                 axis_angle_deg=0.)]}),
        dict(id="cnc_curved_corners", status="not_detected", measurements={"cylindrical_faces": []}),
        dict(id="cnc_rectangular_pockets", status="attention", measurements={"pockets": [
            dict(floor_face_id=30, width_mm=4., wall_height_mm=15.)]}),
    ])


def preference_app(original, process, prefix):
    """Use real controls; recomputing a plan must not mutate measured geometry."""
    from copy import deepcopy
    import streamlit as st
    from dfm.advisor_view import render_advisor
    from dfm.conclusion_view import render_conclusion

    machine_key, material_key = (("cnc_machine", "cnc_material") if process == "CNC"
                                else (f"machine_{process}", f"material_{process}"))
    st.session_state.setdefault(machine_key, original["profile"]["machine"])
    st.session_state.setdefault(material_key, original["profile"]["material"])
    context = render_advisor(process, None)
    report = deepcopy(st.session_state.get("fixture_report", original))
    report["review_context"] = context
    report["profile"].update(machine=context["equipment"], material=context["material"])
    render_conclusion(report, key_prefix=prefix)
    st.session_state["test_report"] = report


@pytest.fixture
def preference_backend(monkeypatch, tmp_path):
    path = tmp_path / "preferences.json"
    monkeypatch.setattr(planning, "_feedback_path", lambda explicit=None: Path(explicit) if explicit else path)
    monkeypatch.setattr(advisor_view, "_key", lambda: "")

    def unexpected_request(*args, **kwargs):
        pytest.fail("Choosing an internal recommendation must not make an external AI request")

    monkeypatch.setattr(advisor_view, "parse_intent", unexpected_request)
    calls = {"recommend_plan": [], "record_plan_preference": [], "reset_plan_preferences": []}

    # Delegate to the actual engine while checking that UI context crosses each
    # boundary explicitly; default-valued preferences alone could hide a lost kwarg.
    def capture(name, original):
        def wrapped(*args, **kwargs):
            calls[name].append(deepcopy(kwargs))
            return original(*args, **kwargs)
        return wrapped

    for name in calls:
        # The UI records verified sequential candidates through the new wrapper;
        # the underlying prior and reset still use the unchanged model backend.
        from dfm import enhanced_planning
        target = enhanced_planning if name == 'record_plan_preference' else planning
        monkeypatch.setattr(target, name, capture(name, getattr(target, name)))
    return path, calls


def open_app(report, process, prefix):
    app = AppTest.from_function(preference_app, args=(report, process, prefix), default_timeout=30).run()
    assert not app.exception
    assert [heading.value for heading in app.subheader] == ["종합 결론"]
    return app


def result(app):
    assert not app.exception
    return deepcopy(app.session_state["test_report"]["plan_recommendation"])


def measurements(app):
    report = app.session_state["test_report"]
    return {key: deepcopy(report.get(key)) for key in ("profile", "findings", "orientations", "current_orientation")}


def scores(plan):
    return {row["id"]: row["score"] for row in plan["ranking"]}


def outcomes(plan):
    return {row["id"]: row["outcomes"] for row in plan["ranking"]}


def test_explicit_am_preference_rescores_recommends_and_reset_restores(preference_backend):
    path, calls = preference_backend
    app = open_app(am_report(), "MEX", "am")
    before = result(app)
    original_measurements = measurements(app)
    assert before["selection_source"] == "verified_policy"
    assert before["learning"]["choices"] == 0
    assert not path.exists()
    assert before["selected"]["id"] != "orientation:C"

    # Rendering or inspecting results never implicitly becomes training data.
    app.run()
    assert not path.exists()
    app.button(key="am_prefer_orientation:C").click().run()
    after = result(app)
    assert after["selected"]["id"] == "orientation:C"
    assert after["selection_source"] == "verified_policy+preference"
    assert after["learning"]["choices"] == 1
    assert scores(after) != scores(before)
    assert outcomes(after) == outcomes(before)
    assert measurements(app) == original_measurements
    assert app.session_state["test_report"]["conclusion"]["orientation"]["recommended"]["name"] == "C"
    assert any("선호를 반영했습니다" in notice.value for notice in app.success)
    assert len(calls["record_plan_preference"]) == 1
    stored = json.loads(path.read_text("utf-8"))
    assert stored["scopes"][after["learning"]["scope"]]["choices"] == 1

    app.run()
    assert result(app)["selected"]["id"] == "orientation:C"
    assert len(calls["record_plan_preference"]) == 1
    app.button(key="am_reset_preference").click().run()
    reset = result(app)
    assert reset["learning"]["choices"] == 0
    assert reset["selection_source"] == "verified_policy"
    assert reset["selected"]["id"] == before["selected"]["id"]
    assert scores(reset) == scores(before)
    assert measurements(app) == original_measurements
    assert json.loads(path.read_text("utf-8"))["scopes"] == {}
    assert "am_reset_preference" not in [button.key for button in app.button]
    assert len(calls["reset_plan_preferences"]) == 1


@pytest.mark.parametrize("allowance", list(ALLOWANCES))
def test_cnc_allowance_reaches_recommendation_and_limits_edits(allowance, preference_backend):
    path, calls = preference_backend
    app = open_app(cnc_report(), "CNC", "cnc")
    original_measurements = measurements(app)
    app.selectbox(key="cnc_plan_allowance").select(allowance).run()
    plan = result(app)
    prefs = ALLOWANCES[allowance]
    assert app.session_state["test_report"]["review_context"]["plan_preferences"] == prefs
    assert calls["recommend_plan"][-1]["preferences"] == prefs
    assert plan["selection_source"] == "verified_policy"
    assert plan["selected"] and all(row["verified"] for row in plan["ranking"])
    assert measurements(app) == original_measurements
    fields = {change["field"] for row in plan["ranking"] for change in row["changes"]}
    assert fields
    if prefs["preserve_geometry"]:
        assert fields <= TOOL_FIELDS
        # Tool substitution cannot remove the existing pocket's internal corner.
        assert plan["selected"]["outcomes"]["remaining_numeric_conflicts"] == 1
        assert "포켓 내부 직각" in plan["selected"]["remaining"]
        assert "cnc_rectangular_pockets" in plan["selected"]["remaining_finding_ids"]
        assert any("포켓 내부 직각" in caption.value for caption in app.caption)
        assert any(notice.value == "공구 조건 변경" for notice in app.warning)
        # A remaining corner must not resurrect generic geometry-edit advice
        # beside a recommendation that explicitly preserves the original part.
        assert app.session_state["test_report"]["conclusion"]["visible_actions"] == []
    else:
        assert all(row["outcomes"]["remaining_numeric_conflicts"] == 0 for row in plan["ranking"])
        assert any(field.startswith("pocket.") for field in fields)
        if not prefs["allow_tool_change"]:
            assert fields.isdisjoint(TOOL_FIELDS)
            for row in plan["ranking"]:
                assert {field: row["outcomes"][field] for field in TOOL_FIELDS} == {
                    field: original_measurements["profile"][field] for field in TOOL_FIELDS}
            all_changes = next(block for block in app.expander if block.label == "전체 변경 5개")
            # The fifth edit must remain discoverable, with its actual CAD face.
            assert [item.value for item in all_changes.markdown] == [
                "구멍 지름 (CAD 면 12) · 2 → 5 mm",
                "원통 구간 (CAD 면 12) · 20 → 12 mm",
                "포켓 폭 (CAD 면 30) · 4 → 5 mm",
                "포켓 벽 높이 (CAD 면 30) · 15 → 10 mm",
                "포켓 내부 반경 (CAD 면 30) · 0 → 2.5 mm",
            ]
        else:
            assert fields & TOOL_FIELDS
            assert any("." in field for field in fields)
    assert not path.exists()
    assert not calls["record_plan_preference"]
    assert not calls["reset_plan_preferences"]


def test_cnc_preference_is_scoped_to_allowed_changes_and_reset_to_current_context(preference_backend):
    path, calls = preference_backend
    app = open_app(cnc_report(), "CNC", "cnc")
    before = result(app)
    original_measurements = measurements(app)
    prefs = ALLOWANCES["형상·공구 모두"]
    alternative = before["alternatives"][0]
    app.button(key="cnc_prefer_" + alternative["id"]).click().run()
    after = result(app)
    assert after["learning"]["choices"] == 1
    assert after["selection_source"] == "verified_policy+preference"
    assert scores(after) != scores(before)
    assert outcomes(after) == outcomes(before)
    assert calls["record_plan_preference"][-1]["preferences"] == prefs
    saved_scope = after["learning"]["scope"]
    saved_content = path.read_bytes()

    for allowance in ("공구만 · 원래 형상 유지", "형상만 · 현재 공구 유지"):
        app.selectbox(key="cnc_plan_allowance").select(allowance).run()
        constrained = result(app)
        assert constrained["learning"]["scope"] != saved_scope
        assert constrained["learning"]["choices"] == 0
        assert calls["recommend_plan"][-1]["preferences"] == ALLOWANCES[allowance]
        assert path.read_bytes() == saved_content
    app.selectbox(key="cnc_plan_allowance").select("형상·공구 모두").run()
    restored = result(app)
    assert restored["learning"]["scope"] == saved_scope
    assert restored["learning"]["choices"] == 1
    assert scores(restored) == scores(after)

    # A second user context has its own fitted preferences. Reset must remove
    # only this context, preserving the previously stored balanced selection.
    app.selectbox(key="advisor_priority_CNC").select("tool_access").run()
    other = result(app)
    assert other["learning"]["choices"] == 0
    assert other["learning"]["scope"] != saved_scope
    app.button(key="cnc_prefer_" + other["alternatives"][0]["id"]).click().run()
    trained_other = result(app)
    assert trained_other["learning"]["choices"] == 1
    assert len(json.loads(path.read_text("utf-8"))["scopes"]) == 2
    app.button(key="cnc_reset_preference").click().run()
    reset = result(app)
    assert reset["learning"]["choices"] == 0
    assert scores(reset) == scores(other)
    assert calls["reset_plan_preferences"][-1]["preferences"] == prefs
    assert set(json.loads(path.read_text("utf-8"))["scopes"]) == {saved_scope}
    app.selectbox(key="advisor_priority_CNC").select("balanced").run()
    assert result(app)["learning"]["choices"] == 1
    assert scores(result(app)) == scores(after)
    assert measurements(app) == original_measurements


def test_preference_reset_remains_available_when_new_part_has_only_one_candidate(preference_backend):
    path, calls = preference_backend
    app = open_app(cnc_report(), "CNC", "cnc")
    app.button(key="cnc_prefer_" + result(app)["alternatives"][0]["id"]).click().run()
    scope = result(app)["learning"]["scope"]
    assert result(app)["learning"]["choices"] == 1

    clear_part = cnc_report()
    clear_part["findings"][1].update(status="observed", measurements={"cylindrical_faces": [
        dict(face_id=12, diameter_mm=8., cylindrical_length_mm=5., axis_aligned=True, axis_angle_deg=0.)]})
    clear_part["findings"][3].update(status="not_detected", measurements={"pockets": []})
    app.session_state["fixture_report"] = clear_part
    app.run()
    single = result(app)
    assert single["status"] == "keep" and single["selected"]["changes"] == []
    assert len(single["ranking"]) == 1 and single["alternatives"] == []
    assert single["learning"] == {"choices": 1, "scope": scope}
    assert "다른 개선안 비교" not in [block.label for block in app.expander]
    records = next(block for block in app.expander if block.label == "추천·학습 기록")
    assert records.button(key="cnc_reset_preference").label == "저장한 선호 초기화"
    app.button(key="cnc_reset_preference").click().run()
    assert result(app)["learning"]["choices"] == 0
    assert result(app)["selected"]["changes"] == []
    assert calls["reset_plan_preferences"][-1]["preferences"] == ALLOWANCES["형상·공구 모두"]
    assert json.loads(path.read_text("utf-8"))["scopes"] == {}
