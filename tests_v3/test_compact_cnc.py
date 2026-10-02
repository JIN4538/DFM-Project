"""Compact CNC presentation keeps blockers and unlearned findings reachable."""
from streamlit.testing.v1 import AppTest


def open_decisions(findings, profile=None, learned=None):
    report = {"profile": profile or {}, "findings": findings}
    script = f'''
from dfm.machining_view import render_machining_decisions
render_machining_decisions({report!r}, learned_display={learned!r})
'''
    app = AppTest.from_string(script).run()
    assert not app.exception
    return app


def finding(identifier, status, title, *, measures=None, action="조건을 확인하세요"):
    return dict(id=identifier, title=title, status=status, measurements=measures or {},
                reason="측정 결과", action=action, face_indices=[], cad_face_ids=[])


def test_learned_cards_are_not_repeated_but_unlearned_issues_and_locations_remain():
    app = open_decisions([
        finding("cnc_holes", "attention", "구멍 축", measures={"cylindrical_faces": [
            dict(face_id=8, axis_aligned=False, axis_angle_deg=90.)]}),
        finding("cnc_visibility", "attention", "표면 가림", measures={
            "sample_state_counts": {"occluded": 4}}),
    ], learned={"rendered": True, "displayed_ids": ["cnc_holes"]})
    assert any(item.value == "추가 규칙 검토 · 표면 가림" for item in app.caption)
    details = next(item for item in app.expander if "전체 개선 항목" in item.label)
    assert details.proto.expanded is False
    # A learned item still has its complete measurement and face selection in
    # the optional rule details; an unlearned finding has the same navigation.
    app.button(key="cnc_focus_cnc_holes").click().run()
    assert app.session_state["cnc_finding"] == "cnc_holes"
    assert app.session_state["cnc_pending_location"] == "8"
    app.button(key="cnc_focus_cnc_visibility").click().run()
    assert app.session_state["cnc_finding"] == "cnc_visibility"
    assert app.session_state["cnc_sample_state"] == "all"


def test_input_blocker_is_visible_even_when_learned_summary_is_available():
    app = open_decisions([
        finding("cnc_input", "unknown", "CAD 입력 확인", action="단일 솔리드 STEP을 입력하세요"),
    ], learned={"rendered": True, "displayed_ids": []})
    assert any("단일 솔리드 STEP을 입력하세요" in item.value for item in app.error)
    assert app.button(key="cnc_pending_cnc_input")


def test_missing_tool_values_are_visible_and_rule_fallback_opens_actions():
    app = open_decisions([
        finding("cnc_rectangular_pockets", "attention", "포켓", measures={"pockets": [
            dict(floor_face_id=9, width_mm=3., wall_height_mm=20., width_too_small=None,
                 exceeds_flute_length=None, exceeds_reach=None)]}),
    ], learned={"rendered": False, "displayed_ids": []})
    assert any("공구 지름 · 날 길이 · 장착 후 돌출 길이" in item.value for item in app.info)
    details = next(item for item in app.expander if "전체 개선 항목" in item.label)
    assert details.proto.expanded is True
    assert app.button(key="cnc_focus_cnc_rectangular_pockets")
