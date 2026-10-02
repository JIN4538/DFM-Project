"""Missing-input proposals checked against independently specified dimensions."""
from copy import deepcopy
from itertools import combinations
from pathlib import Path

import numpy as np
import pytest
import trimesh

from amdfm.io import load_model
from dfm.conditions import load_library
from dfm.machining import MachiningProfile, review_machining
from dfm.tool_recommendation import TOOL_FIELDS, recommend_tool_dimensions, review_with_tool_recommendation


CAD = Path(__file__).resolve().parents[1] / "examples/machining"


@pytest.fixture(scope="module")
def models():
    names = ("01_rectangular_pocket", "02_narrow_deep_pocket", "03_rounded_pocket", "04_vertical_hole", "05_side_hole", "12_two_solids")
    return {name: load_model((CAD / (name + ".step")).read_bytes(), name + ".step") for name in names}


def finding(report, key):
    return next(row for row in report["findings"] if row["id"] == key)


def measured_report(*, profile=None, holes=(), corners=(), pockets=()):
    return dict(process="MILLING_3AXIS", direction=[0, 0, 1], profile=(profile or MachiningProfile()).to_dict(),
        visibility={"status": "complete", "occluded_face_indices": []}, findings=[
            dict(id="cnc_input", status="observed", measurements={"cad_feature_dimensions_available": True}),
            dict(id="cnc_coverage", status="observed", measurements={}),
            dict(id="cnc_visibility", status="observed", face_indices=[]),
            dict(id="cnc_holes", status="observed", measurements={"cylindrical_faces": list(holes)}),
            dict(id="cnc_curved_corners", status="observed", measurements={"cylindrical_faces": list(corners)}),
            dict(id="cnc_rectangular_pockets", status="attention", measurements={"pockets": list(pockets)})])


def test_empty_pocket_input_gets_measured_starting_tool_and_keeps_sharp_corner(models):
    result = review_with_tool_recommendation(models["01_rectangular_pocket"], MachiningProfile())
    tool = result["tool_recommendation"]
    assert tool["values"] == pytest.approx(dict(tool_diameter_mm=9.6, flute_length_mm=9., reach_mm=9.))
    assert set(tool["automatic_fields"]) == set(TOOL_FIELDS)
    assert tool["complete"] and tool["recomputed"]
    assert tool["single_tool_dimension_match"] is False
    assert tool["geometry_changes"][0]["suggested_minimum_radius_mm"] == pytest.approx(4.8)
    pocket = finding(result, "cnc_rectangular_pockets")
    assert pocket["status"] == "attention"
    assert pocket["measurements"]["pockets"][0]["width_too_small"] is False
    assert pocket["measurements"]["pockets"][0]["exceeds_flute_length"] is False
    assert "학습" in tool["assumptions"]["provenance"]


@pytest.mark.parametrize("fixed", [c for n in range(1, 4) for c in combinations(TOOL_FIELDS, n)])
def test_every_partial_input_combination_is_locked(models, fixed):
    user_values = dict(tool_diameter_mm=3., flute_length_mm=12., reach_mm=20.)
    profile = MachiningProfile(**{key: user_values[key] for key in fixed})
    result = review_with_tool_recommendation(models["01_rectangular_pocket"], profile)
    proposed = result["tool_recommendation"]
    for key in fixed:
        assert proposed["values"][key] == user_values[key]
        assert key not in proposed["automatic_fields"]
    assert result["profile"]["flute_length_mm"] <= result["profile"]["reach_mm"]
    assert profile.to_dict() == proposed["original_profile"]


def test_too_short_fixed_reach_does_not_invent_valid_combination(models):
    result = review_with_tool_recommendation(models["02_narrow_deep_pocket"], MachiningProfile(reach_mm=10.))
    tool = result["tool_recommendation"]
    assert tool["status"] == "conflict"
    assert tool["values"]["reach_mm"] == 10
    assert tool["values"]["flute_length_mm"] is None
    assert tool["complete"] is False
    assert tool["single_tool_dimension_match"] is False
    assert any(row["field"] == "reach_mm" for row in tool["conflicts"])
    assert any(row["code"] == "flute_reach_incompatible" for row in tool["unresolved"])
    MachiningProfile(**result["profile"]).validate()


def test_fixed_reach_at_measured_depth_reduces_only_added_allowance(models):
    tool = review_with_tool_recommendation(models["01_rectangular_pocket"], MachiningProfile(reach_mm=8.))["tool_recommendation"]
    assert tool["values"]["flute_length_mm"] == 8
    assert tool["values"]["reach_mm"] == 8
    assert tool["conflicts"] == []
    assert any(row["code"] == "allowance_limited" for row in tool["unresolved"])
    assert any(row["numerical_boundary"] for row in tool["comparisons"])


def test_fixed_oversize_diameter_stays_conflicting_after_recomputation(models):
    result = review_with_tool_recommendation(models["02_narrow_deep_pocket"], MachiningProfile(tool_diameter_mm=4.))
    tool = result["tool_recommendation"]
    assert tool["values"]["tool_diameter_mm"] == 4
    assert tool["status"] == "conflict"
    assert finding(result, "cnc_rectangular_pockets")["measurements"]["pockets"][0]["width_too_small"] is True


def test_rounded_corner_lengths_require_matching_original_cad(models):
    model = models["03_rounded_pocket"]
    raw = review_machining(model, MachiningProfile())
    partial = recommend_tool_dimensions(raw)
    assert partial["values"]["tool_diameter_mm"] == pytest.approx(4.8)
    assert partial["values"]["flute_length_mm"] is None
    assert partial["complete"] is False
    with_cad = recommend_tool_dimensions(raw, model=model)
    assert with_cad["values"] == pytest.approx(dict(tool_diameter_mm=4.8, flute_length_mm=9., reach_mm=9.))
    assert with_cad["constraints"][0]["length_basis"] == "cylindrical_interval"
    with pytest.raises(ValueError, match="형상"):
        recommend_tool_dimensions(raw, model=models["01_rectangular_pocket"])


def test_hole_milling_tool_and_drill_requirement_are_distinct(models):
    result = review_with_tool_recommendation(models["04_vertical_hole"], MachiningProfile())
    tool = result["tool_recommendation"]
    assert tool["values"] == pytest.approx(dict(tool_diameter_mm=4.8, flute_length_mm=16., reach_mm=16.))
    drill = tool["drill_requirements"][0]
    assert drill["nominal_diameter_mm"] == pytest.approx(6)
    assert drill["measured_cylindrical_interval_mm"] == pytest.approx(15)
    assert "hole_depth_mm" not in drill
    assert "원호 밀링" in tool["assumptions"]["hole_strategy"]
    row = finding(result, "cnc_holes")["measurements"]["cylindrical_faces"][0]
    assert row["tool_too_large"] is False and row["segment_exceeds_reach"] is False


def test_other_axis_is_not_used_to_fill_tool_dimensions(models):
    model = models["05_side_hole"]
    wrong_axis = review_with_tool_recommendation(model, MachiningProfile())["tool_recommendation"]
    assert all(value is None for value in wrong_axis["values"].values())
    assert wrong_axis["drill_requirements"][0]["status"] == "other_axis"
    aligned = review_with_tool_recommendation(model, MachiningProfile(), (1, 0, 0))["tool_recommendation"]
    assert aligned["values"] == pytest.approx(dict(tool_diameter_mm=3.2, flute_length_mm=41., reach_mm=41.))


def test_feature_intersection_uses_smallest_opening_largest_length_not_average():
    report = measured_report(holes=[dict(face_id=3, diameter_mm=10., cylindrical_length_mm=8., axis_aligned=True),
                                    dict(face_id=8, diameter_mm=2., cylindrical_length_mm=30., axis_aligned=True)],
                             pockets=[dict(floor_face_id=9, width_mm=12., wall_height_mm=17.)])
    tool = recommend_tool_dimensions(report)
    assert tool["values"] == dict(tool_diameter_mm=1.6, flute_length_mm=31., reach_mm=31.)
    assert len(tool["drill_requirements"]) == 2
    assert len(tool["comparisons"]) == 9
    assert tool["conflicts"] == []
    assert tool["geometry_changes"]


def test_zero_radius_never_creates_zero_diameter():
    report = measured_report(corners=[dict(face_id=1, radius_mm=0.)])
    tool = recommend_tool_dimensions(report)
    assert tool["values"]["tool_diameter_mm"] is None
    assert tool["geometry_changes"][0]["code"] == "sharp_corner"
    assert tool["single_tool_dimension_match"] is False


def test_invalid_and_missing_measured_dimensions_preserve_unresolved():
    tool = recommend_tool_dimensions(measured_report(
        holes=[dict(face_id=1, diameter_mm=float("nan"), cylindrical_length_mm=5., axis_aligned=True)],
        pockets=[dict(floor_face_id=2, width_mm=-2., wall_height_mm=8.)]))
    assert all(value is None for value in tool["values"].values())
    assert {row["code"] for row in tool["unresolved"]} >= {"missing_hole_dimensions", "missing_pocket_dimensions"}


def test_unknown_faces_and_incomplete_pockets_are_preserved(models):
    report = review_machining(models["01_rectangular_pocket"], MachiningProfile())
    finding(report, "cnc_coverage")["measurements"]["unsupported_face_ids"] = [99]
    finding(report, "cnc_rectangular_pockets")["measurements"]["unresolved_floor_face_ids"] = [100]
    tool = recommend_tool_dimensions(report)
    assert tool["status"] == "conditional"
    assert {row.get("cad_face_id") for row in tool["unresolved"]} >= {99, 100}
    assert tool["dimension_coverage_complete"] is False
    assert tool["single_tool_dimension_match"] is False  # Sharp corners are still present.


def test_unknown_faces_cannot_report_single_tool_match():
    report = measured_report(holes=[dict(face_id=1, diameter_mm=10., cylindrical_length_mm=8., axis_aligned=True)])
    finding(report, "cnc_coverage")["measurements"]["unsupported_face_ids"] = [99]
    tool = recommend_tool_dimensions(report)
    assert tool["dimension_coverage_complete"] is False
    assert tool["single_tool_dimension_match"] is None


def test_cylindrical_intervals_without_entry_positions_stay_conditional():
    report = measured_report(holes=[dict(face_id=1, diameter_mm=10., cylindrical_length_mm=10., axis_aligned=True),
                                    dict(face_id=2, diameter_mm=5., cylindrical_length_mm=10., axis_aligned=True)])
    tool = recommend_tool_dimensions(report)
    assert tool["values"]["reach_mm"] == 11  # A disclosed interval-based starting value only.
    assert tool["status"] == "conditional"
    assert tool["single_tool_dimension_match"] is None
    assert tool["dimension_coverage_complete"] is False
    assert sum(row["code"] == "entry_depth_unmeasured" for row in tool["unresolved"]) == 2


def test_occluded_pocket_is_not_source_of_automatic_dimensions(models):
    model = models["01_rectangular_pocket"]
    report = review_machining(model, MachiningProfile())
    floor = finding(report, "cnc_rectangular_pockets")["measurements"]["pockets"][0]["floor_face_id"]
    triangle = int(np.flatnonzero(model.face_ids == floor)[0])
    report["visibility"] = dict(status="complete", occluded_face_indices=[triangle])
    tool = recommend_tool_dimensions(report, model=model)
    assert tool["constraints"] == []
    assert tool["automatic_fields"] == []
    assert any(row["code"] == "occluded_feature" for row in tool["unresolved"])


def test_stl_and_multibody_never_supply_analytic_dimensions(models):
    stl = load_model(trimesh.creation.box([10, 20, 30]).export(file_type="stl"), "box.stl", dimensions_confirmed=True)
    for model in (stl, models["12_two_solids"]):
        tool = review_with_tool_recommendation(model, MachiningProfile())["tool_recommendation"]
        assert tool["status"] == "unavailable"
        assert tool["automatic_fields"] == []


def test_input_report_and_profile_are_not_mutated(models):
    report = review_machining(models["01_rectangular_pocket"], MachiningProfile())
    before = deepcopy(report)
    recommend_tool_dimensions(report, model=models["01_rectangular_pocket"])
    assert report == before


def test_condition_database_evidence_retained_and_generated_value_not_source_value(models):
    library = load_library()
    profile = library.machining_profile("cnc-datron-0068010e")
    before = profile.to_dict()
    result = review_with_tool_recommendation(models["01_rectangular_pocket"], profile)
    tool, evidence = result["tool_recommendation"], result["profile"]["condition_evidence"]
    assert tool["automatic_fields"] == ["reach_mm"]
    assert tool["values"]["tool_diameter_mm"] == 1
    assert tool["values"]["flute_length_mm"] == 4
    assert tool["status"] == "conflict"  # This selected SKU's flute is too short.
    assert evidence["sources"] == before["condition_evidence"]["sources"]
    assert evidence["fields"]["tool_diameter_mm"]["status"] == "source_value"
    assert evidence["generated_inputs"]["reach_mm"]["status"] == "geometry_proposal"
    assert "reach_mm" not in evidence["user_inputs"]
    assert evidence["input_snapshot"]["reach_mm"] == 9
    MachiningProfile(**result["profile"]).validate()
    assert profile.to_dict() == before


@pytest.mark.parametrize("options", [dict(diameter_fraction=0), dict(diameter_fraction=1),
                                      dict(diameter_fraction=True), dict(length_allowance_mm=-1),
                                      dict(length_allowance_mm=float("inf"))])
def test_invalid_policy_parameters_are_rejected(options):
    with pytest.raises(ValueError):
        recommend_tool_dimensions(measured_report(), **options)


def test_configurable_policy_has_exact_numeric_effect_without_touching_user_values():
    report = measured_report(profile=MachiningProfile(flute_length_mm=30.),
        holes=[dict(face_id=1, diameter_mm=10., cylindrical_length_mm=8., axis_aligned=True)])
    tool = recommend_tool_dimensions(report, diameter_fraction=.6, length_allowance_mm=2.)
    assert tool["values"] == dict(tool_diameter_mm=6., flute_length_mm=30., reach_mm=30.)
    assert tool["assumptions"]["diameter_fraction"] == .6
    assert tool["assumptions"]["length_allowance_mm"] == 2.


def test_stepped_hole_reach_covers_both_segments_and_conclusion_keeps_entry_uncertainty(tmp_path):
    from scripts.generate_cad_examples import box, cylinder, cut, export_step
    from dfm.conclusion import summarize_conclusion
    shape = cut(cut(box(30, 30, 25), cylinder(2.5, 22, (15, 15, 4))), cylinder(5, 12, (15, 15, 14)))
    path = tmp_path / "stepped_hole.step"
    export_step(shape, path)
    model = load_model(path.read_bytes(), path.name)
    report = review_with_tool_recommendation(model, MachiningProfile(), visibility=True)
    tool = report["tool_recommendation"]
    assert tool["values"] == pytest.approx(dict(tool_diameter_mm=4., flute_length_mm=12., reach_mm=22.))
    assert max(row["reach_min_mm"] for row in tool["constraints"]) == pytest.approx(11)
    assert max(row["reach_candidate_mm"] for row in tool["constraints"]) == pytest.approx(21)
    assert tool["status"] == "conditional"
    assert tool["single_tool_dimension_match"] is None
    assert finding(report, "cnc_tool_recommendation")["status"] == "unknown"
    assert summarize_conclusion(report, plan_result={})["level"] != "success"


def test_distant_boss_envelope_is_not_a_hard_reach_conflict(tmp_path):
    from scripts.generate_cad_examples import box, cut, fuse, export_step
    shape = fuse(cut(box(40, 30, 10), box(10, 10, 9, (20, 10, 2))), box(5, 5, 20, (0, 0, 10)))
    path = tmp_path / "pocket_with_distant_boss.step"
    export_step(shape, path)
    model = load_model(path.read_bytes(), path.name)
    automatic = review_with_tool_recommendation(model, MachiningProfile())["tool_recommendation"]
    assert automatic["values"]["reach_mm"] == pytest.approx(29)
    tool = review_with_tool_recommendation(model, MachiningProfile(reach_mm=12.))["tool_recommendation"]
    assert tool["values"]["reach_mm"] == 12
    assert not any(row["field"] == "reach_mm" for row in tool["conflicts"])
    assert any(row["code"] == "envelope_clearance_unverified" for row in tool["unresolved"])
    assert max(row["reach_min_mm"] for row in tool["constraints"]) == pytest.approx(8)


def test_short_flute_on_hole_is_a_strategy_question_and_cannot_clear_conclusion(models):
    from dfm.conclusion import summarize_conclusion
    result = review_with_tool_recommendation(models["04_vertical_hole"],
        MachiningProfile(tool_diameter_mm=4., flute_length_mm=1., reach_mm=20.), visibility=True)
    tool = result["tool_recommendation"]
    assert tool["automatic_fields"] == []
    assert tool["conflicts"] == []
    assert any(row["code"] == "full_height_flute_unverified" for row in tool["unresolved"])
    assert finding(result, "cnc_tool_recommendation")["status"] == "unknown"
    assert summarize_conclusion(result, plan_result={})["level"] != "success"


def test_new_recommendation_finding_preserves_feature_locations(models):
    result = review_with_tool_recommendation(models["02_narrow_deep_pocket"], MachiningProfile(tool_diameter_mm=4.))
    entry = finding(result, "cnc_tool_recommendation")
    assert entry["status"] == "attention"
    assert entry["cad_face_ids"]
    assert entry["face_indices"]
    assert set(models["02_narrow_deep_pocket"].face_ids[entry["face_indices"]]) == set(entry["cad_face_ids"])
    assert entry["measurements"]["conflicts"]
    assert {"reason", "action", "method", "evidence", "limitations", "severity"} <= entry.keys()


def test_no_recognized_internal_features_keeps_tool_proposal_not_applicable(tmp_path):
    from scripts.generate_cad_examples import box, export_step
    path = tmp_path / "plain_box.step"
    export_step(box(10, 20, 30), path)
    model = load_model(path.read_bytes(), path.name)
    report = review_with_tool_recommendation(model, MachiningProfile())
    tool = report["tool_recommendation"]
    assert tool["status"] == "not_applicable"
    assert tool["values"] == dict.fromkeys(TOOL_FIELDS)
    assert finding(report, "cnc_tool_recommendation")["status"] == "not_applicable"
