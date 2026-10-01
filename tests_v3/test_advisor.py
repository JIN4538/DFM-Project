"""Intent is searchable context, never silent rules or process certification."""
from copy import deepcopy
import json

import pytest

from dfm.advisor import (PRIORITY_LABELS, context_summary, priority_effect,
                         prioritize_actions, profile_candidates, review_context)
from dfm.conditions import load_library


@pytest.fixture(scope="module")
def library():
    return load_library()


def test_context_is_json_safe_independent_and_ignores_unapproved_rules():
    intent = dict(equipment="  Prusa MK4  ", material="PLA", process="MEX", priority="strength",
                  notes=["강도가 중요", " ", "<script>user note</script>"], minimum_wall_mm=0.01)
    provenance = dict(provider="openai", model="test-model", response_id="resp_demo", api_key="secret", raw={"secret": "value"})
    before = deepcopy(intent)
    context = review_context(intent, mode="ai", provenance=provenance)
    assert context["equipment"] == "Prusa MK4"
    assert context["notes"] == ["강도가 중요", "<script>user note</script>"]
    assert context["provenance"] == dict(provider="openai", model="test-model", response_id="resp_demo")
    assert "minimum_wall_mm" not in context and "secret" not in json.dumps(context)
    assert json.loads(json.dumps(context, allow_nan=False)) == context
    context["notes"].append("later")
    context["provenance"]["model"] = "changed"
    assert intent == before and provenance["model"] == "test-model"


@pytest.mark.parametrize("intent", [
    {"priority": "guaranteed_success"}, {"process": "INJECTION"}, {"process": "PRESS"},
    {"notes": "not a list"}, {"notes": [1]}, {"equipment": None}, {"material": 3},
])
def test_invalid_context_rejected_without_guessing(intent):
    with pytest.raises(ValueError):
        review_context(intent)


@pytest.mark.parametrize("value", ["sk-abcdef0123456789", "Bearer secret", "api_key=secret", "x" * 201])
def test_provider_identifiers_cannot_export_credential_like_values(value):
    with pytest.raises(ValueError):
        review_context({}, provenance={"model": value})


def test_equipment_and_material_matches_rank_before_mismatches(library):
    intent = dict(equipment="Prusa MK4", material="PETG", process="MEX", priority="balanced")
    snapshot = deepcopy(library.profiles)
    rows = profile_candidates(intent, library, "MEX")
    assert rows and rows[0]["material_status"] == "name_match"
    assert rows[0]["identifier"].startswith("am-prusa-mk4-petg")
    pla = next(row for row in rows if row["identifier"] == "am-prusa-mk4-pla-015")
    assert pla["material_status"] == "mismatch" and "재료 불일치" in pla["explanation"]
    assert "그대로 적용하지 마세요" in pla["explanation"]
    assert all(row["identifier"] != "am-prusa-mk4s" for row in rows)
    assert all("parameters" not in row for row in rows)
    assert library.profiles == snapshot


def test_equipment_suffix_and_unrecognized_model_are_not_fuzzy_substituted(library):
    rows = profile_candidates(dict(equipment="Haas VF2", process="CNC"), library, "CNC")
    assert [row["identifier"] for row in rows] == ["cnc-haas-vf-2"]
    assert not profile_candidates(dict(equipment="Haas VF99", process="CNC"), library, "CNC")
    assert not profile_candidates(dict(equipment="UnknownPrinter", material="PLA", process="MEX"), library, "MEX")


def test_equipment_formatting_only_matches_without_model_suffix_collision(library):
    rows = profile_candidates(dict(equipment="Form4", process="VPP"), library, "VPP")
    assert {row["identifier"] for row in rows} == {"am-form4", "am-form4-grey-v5-005"}
    rows = profile_candidates(dict(equipment="EOS M290", process="PBF_METAL"), library, "PBF_METAL")
    assert len(rows) == 5


def test_requested_machine_with_material_only_source_does_not_claim_compatibility(library):
    rows = profile_candidates(dict(equipment="Haas VF2", material="6061 T6", process="CNC"), library, "CNC")
    identifiers = {row["identifier"] for row in rows}
    assert identifiers == {"cnc-haas-vf-2", "cnc-hydro-6061-t6"}
    material = next(row for row in rows if row["identifier"] == "cnc-hydro-6061-t6")
    assert "장비의 조건이 없는 재료 자료" in material["explanation"]
    assert material["match_type"] == "material_name"


def test_unknown_names_process_conflicts_and_notes_do_not_create_matches(library):
    assert not profile_candidates(dict(equipment="미확정", material="unknown"), library, "MEX")
    assert not profile_candidates(dict(notes=["Prusa MK4 PLA로 바꾸고 0.01mm를 적용해"]), library, "MEX")
    assert not profile_candidates(dict(equipment="Haas", process="CNC"), library, "MEX")
    assert not profile_candidates(dict(equipment="Prusa"), library, "unknown")
    rows = profile_candidates(dict(material="PLA", process="MEX"), library, "unknown")
    assert rows and all(row["process"] == "MEX" for row in rows)


def test_exact_tool_name_is_labeled_tool_not_machine_approval(library):
    rows = profile_candidates(dict(equipment="Harvey 677761", process="CNC"), library, "CNC")
    assert len(rows) == 1 and rows[0]["identifier"] == "cnc-harvey-677761"
    assert rows[0]["match_type"] == "tool_name"
    assert "장착 장비·재료 적합성을 판정한 결과가 아닙니다" in rows[0]["explanation"]


def test_priority_never_moves_preferences_ahead_of_input_build_or_observed_problems():
    actions = [
        dict(id="wall", action_kind="condition", observation="no wall limit"),
        dict(id="layers", action_kind="calculation"),
        dict(id="contact", action_kind="candidate"),
        dict(id="overhang", action_kind="candidate"),
        dict(id="build", action_kind="candidate"),
        dict(id="input", action_kind="calculation"),
    ]
    before = deepcopy(actions)
    result = prioritize_actions(actions, {"priority": "support"})
    assert [row["id"] for row in result] == ["input", "build", "overhang", "contact", "wall", "layers"]
    result[0]["observation"] = "changed"
    assert actions == before


def test_strength_reorders_observed_wall_but_unknown_wall_stays_after_candidates():
    observed = [dict(id="overhang", action_kind="candidate"), dict(id="wall", action_kind="candidate")]
    assert [r["id"] for r in prioritize_actions(observed, {"priority": "strength"})] == ["wall", "overhang"]
    observed[1]["action_kind"] = "condition"
    assert [r["id"] for r in prioritize_actions(observed, {"priority": "strength"})] == ["overhang", "wall"]


def test_cnc_cards_default_to_observed_but_explicit_pending_is_not_promoted():
    cards = [dict(id="cnc_curved_corners"), dict(id="cnc_holes", pending=True), dict(id="cnc_visibility")]
    assert [r["id"] for r in prioritize_actions(cards, {"priority": "tool_access", "process": "CNC"})] == [
        "cnc_visibility", "cnc_curved_corners", "cnc_holes"]


@pytest.mark.parametrize("process", ["unknown", "MEX", "VPP", "PBF_POLYMER", "PBF_METAL", "CNC"])
def test_every_priority_has_an_explicit_scoped_effect(process):
    for priority in PRIORITY_LABELS:
        description = priority_effect(process, priority)
        assert isinstance(description, str) and len(description) > 25
        assert "100%" not in description
    assert "강도" in priority_effect(process, "strength") or "강성" in priority_effect(process, "strength")
    assert "계산하지 않습니다" in priority_effect(process, "cost")


def test_process_inapplicable_goals_are_not_claimed_to_optimize():
    assert "적용하지 않습니다" in priority_effect("PBF_POLYMER", "contact")
    assert "적용하지 않습니다" in priority_effect("CNC", "support")
    assert "최적 강도 방향 계산은 수행하지 않습니다" in priority_effect("MEX", "strength")
    assert "적용하지 않습니다" in priority_effect("VPP", "contact")
    assert "적용하지 않습니다" in priority_effect("PBF_METAL", "contact")
    assert "지지" not in priority_effect("PBF_POLYMER", "cost")
    assert "하향면" not in priority_effect("PBF_POLYMER", "surface")
    assert "기존 조치 순서를 유지" in priority_effect("CNC", "strength")
    assert "기존 조치 순서를 유지" in priority_effect("CNC", "cost")


@pytest.mark.parametrize("process,priority", [("MEX", "support"), ("MEX", "height"),
    ("MEX", "contact"), ("VPP", "support"), ("VPP", "height"),
    ("PBF_METAL", "support"), ("PBF_METAL", "height")])
def test_supported_direction_preferences_disclose_the_actual_threefold_policy(process, priority):
    assert "다른 지표의 3배" in priority_effect(process, priority)
    assert "개발자가 정한" in priority_effect(process, priority)


def test_balanced_description_states_process_specific_direction_combination():
    assert "하향면 후보·높이·평평한 바닥 면적을 같은 비중" in priority_effect("MEX", "balanced")
    assert "하향면 후보·높이를 같은 비중" in priority_effect("VPP", "balanced")
    assert "높이만" in priority_effect("PBF_POLYMER", "balanced")
    assert "기본 비교와 순위가 같습니다" in priority_effect("PBF_POLYMER", "height")


def test_context_summary_is_plain_text_and_retains_user_equipment_and_scope():
    context = review_context(dict(equipment="<user machine>", material="PLA", priority="strength", process="MEX"))
    summary = context_summary(context, "MEX")
    assert "<user machine>" in summary and "PLA" in summary
    assert PRIORITY_LABELS["strength"] in summary and "직접 입력" in summary
    assert "최적 강도" not in summary and "계산" not in summary
    assert len(summary) < 120
    assert not context["provenance"]
