from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

import dfm.plan_learning as planning


def am_report(process="MEX"):
    values = [("A", [0, 0, 1], 0., 100., 100.), ("B", [1, 0, 0], 10., 40., 80.), ("C", [0, 1, 0], 20., 10., 0.)]
    rows = [dict(name=n, direction=d, height_mm=h, overhang_projected_area_sum_mm2=a,
                 contact_triangle_area_mm2=c, build_fit=None, candidate_role="search") for n, d, a, h, c in values]
    return dict(profile={"process": process, "machine": "test", "material": "test", "build_volume_mm": None},
                model={"unit_status": "declared"}, summary={"review_status": "geometry_review"}, findings=[],
                current_orientation=deepcopy(rows[0]), orientations=rows, review_context={"priority": "balanced"})


def cnc_report(clear=False):
    return dict(process="MILLING_3AXIS", profile=dict(machine="test-mill", material="test-material", tool_diameter_mm=5.,
                flute_length_mm=10., reach_mm=12., hole_depth_ratio_limit=None), review_context={"priority": "balanced"}, findings=[
        dict(id="cnc_input", status="observed", measurements={"cad_feature_dimensions_available": True}),
        dict(id="cnc_holes", status="observed" if clear else "attention", measurements={"cylindrical_faces": [
            dict(diameter_mm=8. if clear else 2., cylindrical_length_mm=5. if clear else 20., axis_aligned=True)]}),
        dict(id="cnc_curved_corners", status="not_detected", measurements={"cylindrical_faces": []}),
        dict(id="cnc_rectangular_pockets", status="not_detected" if clear else "attention", measurements={"pockets": [] if clear else [
            dict(width_mm=4., wall_height_mm=15.)]})])


def test_model_exists_is_fitted_and_json_only():
    model = planning.load_plan_model()
    assert model["schema"] == planning.SCHEMA
    assert model["training_groups"] > 10
    assert len(model["trees"]) >= 96
    assert model["sha256"] == hashlib.sha256(planning.MODEL_PATH.read_bytes()).hexdigest()


def test_actual_model_has_useful_nonbaseline_choice(tmp_path):
    result = planning.recommend_plan(am_report(), feedback_path=tmp_path / "prefs.json")
    assert result["selection_source"] == "learned"
    assert result["baseline_selected_id"] == "orientation:A"
    assert result["selected"]["id"] == "orientation:B"
    assert result["selection_changed"] is True


def test_removing_model_preserves_measurement_but_changes_selection(tmp_path):
    report = am_report()
    learned = planning.recommend_plan(report, feedback_path=tmp_path / "prefs.json")
    fallback = planning.recommend_plan(report, feedback_path=tmp_path / "prefs.json", model_path=tmp_path / "missing.json")
    assert learned["selected"]["id"] != fallback["selected"]["id"]
    assert fallback["selected"]["id"] == "orientation:A"
    assert {p["id"]: p["outcomes"] for p in learned["ranking"]} == {p["id"]: p["outcomes"] for p in fallback["ranking"]}


def test_model_really_controls_ranking_no_oracle_overwrite(monkeypatch, tmp_path):
    monkeypatch.setattr(planning, "predict_score", lambda model, x: -x[1])
    support = planning.recommend_plan(am_report(), feedback_path=tmp_path / "prefs.json")
    monkeypatch.setattr(planning, "predict_score", lambda model, x: -x[2])
    height = planning.recommend_plan(am_report(), feedback_path=tmp_path / "prefs.json")
    assert support["selected"]["id"] == "orientation:A"
    assert height["selected"]["id"] == "orientation:C"


def test_applying_orientation_does_not_flip_fixed_ranking(tmp_path):
    report = am_report()
    before = planning.recommend_plan(report, feedback_path=tmp_path / "prefs.json")
    report["current_orientation"] = deepcopy(before["selected"]["orientation"])
    report["orientations"].reverse()
    after = planning.recommend_plan(report, feedback_path=tmp_path / "prefs.json")
    assert before["selected"]["id"] == after["selected"]["id"]
    assert [p["id"] for p in before["ranking"]] == [p["id"] for p in after["ranking"]]
    assert after["status"] == "keep"


def test_same_selected_direction_in_legacy_adapter(tmp_path):
    report = am_report()
    result = planning.recommend_plan(report, feedback_path=tmp_path / "prefs.json")
    direction = planning.orientation_recommendation(report, result)
    assert direction["recommended"]["name"] == result["selected"]["orientation"]["name"]
    assert direction["keep_current"] == result["selected"]["keep_current"]
    assert direction["current_comparison"]["differences"][0]["recommended"] == 10.


def test_dominated_candidate_cannot_be_promoted_by_model(monkeypatch, tmp_path):
    report = am_report()
    report["orientations"].append(dict(name="D", direction=[0, 0, -1], height_mm=150., overhang_projected_area_sum_mm2=30.,
                                      contact_triangle_area_mm2=0., build_fit=None, candidate_role="search"))
    monkeypatch.setattr(planning, "predict_score", lambda model, x: sum(x))
    result = planning.recommend_plan(report, feedback_path=tmp_path / "prefs.json")
    assert "orientation:D" not in {p["id"] for p in result["ranking"]}


def test_missing_metric_cannot_rank_as_good(tmp_path):
    report = am_report()
    report["orientations"][1]["height_mm"] = None
    result = planning.recommend_plan(report, feedback_path=tmp_path / "prefs.json")
    assert result["status"] == "unavailable" and result["selected"] is None


def test_space_failure_excluded_and_polymer_scope_respected(tmp_path):
    report = am_report("PBF_POLYMER")
    for row in report["orientations"]:
        row["overhang_projected_area_sum_mm2"] = None
        row["contact_triangle_area_mm2"] = None
    result = planning.recommend_plan(report, feedback_path=tmp_path / "prefs.json")
    assert result["selected"]["id"] == "orientation:C"
    assert set(result["selected"]["outcomes"]) == {"height_mm"}
    report["profile"]["build_volume_mm"] = [10, 10, 10]
    for row in report["orientations"]: row["build_fit"] = False
    report["current_orientation"]["build_fit"] = False
    assert planning.recommend_plan(report, feedback_path=tmp_path / "prefs.json")["selected"] is None


def test_cnc_plans_jointly_recalculate_tool_and_geometry_constraints(tmp_path):
    report = cnc_report()
    original = deepcopy(report)
    result = planning.recommend_plan(report, feedback_path=tmp_path / "prefs.json")
    assert result["selected"]
    assert all(p["outcomes"]["remaining_numeric_conflicts"] == 0 for p in result["ranking"])
    assert all(p["verified"] is True for p in result["ranking"])
    assert "수정 CAD" in result["selected"]["verification_scope"]
    assert "실제 보유 공구 아님" in result["selected"]["availability"]
    assert {"cnc_holes", "cnc_rectangular_pockets"} <= set(result["selected"]["covered_finding_ids"])
    assert report == original
    json.dumps(result, allow_nan=False)


def test_geometry_preservation_is_hard_gate(tmp_path):
    result = planning.recommend_plan(cnc_report(), preferences={"preserve_geometry": True}, feedback_path=tmp_path / "prefs.json")
    assert result["selected"]
    assert all("." not in change["field"] for plan in result["ranking"] for change in plan["changes"])
    assert result["selected"]["outcomes"]["remaining_numeric_conflicts"] > 0  # Internal right angle remains.


def test_tool_preservation_is_hard_gate(tmp_path):
    result = planning.recommend_plan(cnc_report(), preferences={"allow_tool_change": False}, feedback_path=tmp_path / "prefs.json")
    assert result["selected"]
    assert all("." in change["field"] for plan in result["ranking"] for change in plan["changes"])


def test_no_changes_allowed_does_not_present_conflicted_keep_as_recommendation(tmp_path):
    result = planning.recommend_plan(cnc_report(), preferences={"allow_tool_change": False, "preserve_geometry": True}, feedback_path=tmp_path / "prefs.json")
    assert result["status"] == "unavailable" and result["selected"] is None


def test_clear_cnc_never_changes_tools_arbitrarily(tmp_path):
    result = planning.recommend_plan(cnc_report(clear=True), feedback_path=tmp_path / "prefs.json")
    assert result["status"] == "keep" and result["selected"]["changes"] == []


def test_user_choice_changes_next_ranking_and_reset_restores_it(tmp_path):
    path = tmp_path / "preferences.json"
    report = am_report()
    original = planning.recommend_plan(report, feedback_path=path)
    recorded = planning.record_plan_preference(report, "orientation:C", feedback_path=path)
    after = planning.recommend_plan(report, feedback_path=path)
    assert recorded["choices"] == 1 and after["learning"]["choices"] == 1
    assert after["selected"]["id"] == "orientation:C"
    assert after["selection_source"] == "learned+preference"
    reset = planning.reset_plan_preferences(report, feedback_path=path)
    assert reset["removed_choices"] == 1
    assert planning.recommend_plan(report, feedback_path=path)["selected"]["id"] == original["selected"]["id"]


def test_user_choice_storage_has_no_file_cad_or_machine_text_and_scope_isolated(tmp_path):
    path = tmp_path / "preferences.json"
    report = am_report()
    report["profile"]["machine"] = "private-machine-name"
    report["input"] = {"filename": "secret-part.step", "vertices": [[1, 2, 3]]}
    planning.record_plan_preference(report, "orientation:C", feedback_path=path)
    stored = path.read_text("utf-8")
    assert "private-machine-name" not in stored and "secret-part" not in stored and "vertices" not in stored
    report["profile"]["machine"] = "other-machine"
    assert planning.recommend_plan(report, feedback_path=path)["learning"]["choices"] == 0
    assert planning.recommend_plan(cnc_report(), feedback_path=path)["learning"]["choices"] == 0


def test_explicit_preference_transfers_to_different_measured_candidate_values(tmp_path):
    path = tmp_path / "preferences.json"
    training = am_report()
    planning.record_plan_preference(training, "orientation:C", feedback_path=path)
    unseen = am_report()
    for row, height, contact, area in zip(unseen["orientations"], (110., 55., 18.), (110., 65., 10.), (0., 12., 28.)):
        row.update(height_mm=height, contact_triangle_area_mm2=contact, overhang_projected_area_sum_mm2=area)
    unseen["current_orientation"] = deepcopy(unseen["orientations"][0])
    without = planning.recommend_plan(unseen, feedback_path=tmp_path / "empty.json")
    with_preference = planning.recommend_plan(unseen, feedback_path=path)
    assert without["selected"]["id"] == "orientation:B"
    assert with_preference["selected"]["id"] == "orientation:C"
    assert without["selected"]["outcomes"]["height_mm"] == 55.
    assert training["orientations"][1]["height_mm"] == 40.


def test_invalid_or_dominated_choice_cannot_train(tmp_path):
    path = tmp_path / "preferences.json"
    with pytest.raises(ValueError): planning.record_plan_preference(am_report(), "unknown", feedback_path=path)
    assert not path.exists()


@pytest.mark.parametrize("kind", ["checksum", "schema", "cycle", "nonfinite", "metadata", "rate", "huge_leaf"])
def test_corrupt_model_falls_back_without_crashing(tmp_path, kind):
    path = tmp_path / "model.json"
    model = json.loads(planning.MODEL_PATH.read_text("utf-8"))
    if kind == "schema": model["schema"] = "wrong"
    if kind == "cycle": model["trees"][0][0][2] = 0
    if kind == "nonfinite": model["intercept"] = float("nan")
    if kind == "metadata": del model["training_scope"]
    if kind == "rate": model["learning_rate"] = -1.
    if kind == "huge_leaf": model["trees"][0][-1][4] = 1e308
    raw = json.dumps(model).encode()
    path.write_bytes(raw)
    path.with_suffix(".manifest.json").write_text(json.dumps({"sha256": "wrong" if kind == "checksum" else hashlib.sha256(raw).hexdigest()}))
    result = planning.recommend_plan(am_report(), feedback_path=tmp_path / "prefs.json", model_path=path)
    assert result["selection_source"] == "rule_fallback"
    assert result["selected"]["id"] == "orientation:A"


def test_source_change_invalidates_model(monkeypatch, tmp_path):
    monkeypatch.setattr(planning, "source_hashes", lambda: {})
    assert planning.recommend_plan(am_report(), feedback_path=tmp_path / "prefs.json")["selection_source"] == "rule_fallback"


def test_malformed_feedback_does_not_break_review(tmp_path):
    path = tmp_path / "prefs.json"
    path.write_text("{broken")
    result = planning.recommend_plan(am_report(), feedback_path=path)
    assert result["selected"] is not None and result["learning"]["choices"] == 0


@pytest.mark.parametrize("row", [[], None, 7, {"choices": 1, "weights": None}, {"choices": 1, "weights": [0.] * len(planning.FEATURES), "pairs": [None]}])
def test_structurally_malformed_feedback_fails_soft(tmp_path, row):
    path = tmp_path / "prefs.json"
    path.write_text(json.dumps({"schema": planning.SCHEMA, "scopes": {"0" * 64: row}}))
    result = planning.recommend_plan(am_report(), feedback_path=path)
    assert result["selected"] and result["learning"]["choices"] == 0


def test_custom_current_dominating_search_displays_current_measured_outcome(tmp_path):
    report = am_report()
    report["current_orientation"] = dict(name="custom", direction=[1, 1, 1], height_mm=5.,
        overhang_projected_area_sum_mm2=0., contact_triangle_area_mm2=120., build_fit=None)
    result = planning.recommend_plan(report, feedback_path=tmp_path / "prefs.json")
    assert result["status"] == "keep"
    assert result["selected"]["changes"] == []
    assert result["selected"]["outcomes"] == {"height_mm": 5., "overhang_projected_area_sum_mm2": 0., "contact_triangle_area_mm2": 120.}
    assert result["selected"]["remaining"] == []
    assert result["alternatives"] == []
    adapter = planning.orientation_recommendation(report, result)
    assert all(row["delta"] == 0 for row in adapter["current_comparison"]["differences"])


def test_keep_equivalent_candidate_uses_actual_current_axis_name(tmp_path):
    report = am_report()
    row = dict(height_mm=10., overhang_projected_area_sum_mm2=0., contact_triangle_area_mm2=100., build_fit=None, candidate_role="search")
    report["orientations"] = [dict(row, name="+Z", direction=[0,0,1]), dict(row, name="+X", direction=[1,0,0])]
    report["current_orientation"] = dict(row, direction=[1,0,0])
    result = planning.recommend_plan(report, feedback_path=tmp_path / "prefs.json")
    assert result["status"] == "keep"
    assert result["selected"]["orientation"]["name"] == "+X"
    assert result["selected"]["orientation"]["direction"] == [1,0,0]
    assert planning.orientation_recommendation(report, result)["recommended"]["name"] == "+X"


def test_cnc_partial_coverage_survives_attention_and_edits_keep_source_face_id(tmp_path):
    report = cnc_report()
    holes = report["findings"][1]["measurements"]
    holes["cylindrical_faces"] = [dict(face_id=2, diameter_mm=8., cylindrical_length_mm=9., axis_aligned=False),
        dict(face_id=12, diameter_mm=2., cylindrical_length_mm=20., axis_aligned=True)]
    holes["unresolved_cylinder_face_ids"] = [80]
    report["findings"][3]["measurements"]["unresolved_floor_face_ids"] = [90]
    result = planning.recommend_plan(report, preferences={"allow_tool_change": False}, feedback_path=tmp_path / "prefs.json")
    assert {"cnc_holes", "cnc_rectangular_pockets"} <= set(result["selected"]["remaining_finding_ids"])
    changes = [c for c in result["selected"]["changes"] if c["field"].startswith("hole.")]
    assert changes and all(c["field"].startswith("hole.1.") and c["cad_face_id"] == 12 for c in changes)
    assert any("미확인" in r for r in result["selected"]["remaining"])


def test_shared_evaluation_tie_policy_matches_runtime(tmp_path, monkeypatch):
    from scripts.train_plan_model import evaluate
    report = am_report()
    monkeypatch.setattr(planning, "predict_score", lambda model, x: .12345678904)
    result = planning.recommend_plan(report, feedback_path=tmp_path / "prefs.json")
    plans, _, baseline = planning.candidate_plans(report)
    q = dict(features=[p["_features"] for p in plans], stable_keys=[planning._stable(p) for p in plans],
        targets=[0. if p["id"] == result["selected"]["id"] else -1. for p in plans],
        baseline_index=next(i for i, p in enumerate(plans) if p["id"] == baseline))
    assert evaluate([q], lambda xs: [.12345678904] * len(xs))["exact_objective_best"] == 1


@pytest.mark.parametrize("cad_file", ["07_bracket.step", "03_vertical_hole.step", "12_sphere.step"])
def test_actual_cad_am_report_integration(cad_file, tmp_path):
    from amdfm.analysis import review
    from amdfm.io import load_model
    from amdfm.profiles import Profile
    path = Path(__file__).resolve().parents[1] / "examples/cad" / cad_file
    model = load_model(path.read_bytes(), path.name)
    report = review(model, Profile(), dense=True)
    result = planning.recommend_plan(report, feedback_path=tmp_path / "prefs.json")
    assert result["selected"] is not None
    assert result["selected"]["verified"] is True
    assert result["selected"]["orientation"]["name"] in {r["name"] for r in report["orientations"]}


def test_actual_cad_cnc_narrow_pocket_report_integration(tmp_path):
    from amdfm.io import load_model
    from dfm.machining import MachiningProfile, review_machining
    path = Path(__file__).resolve().parents[1] / "examples/machining/02_narrow_deep_pocket.step"
    model = load_model(path.read_bytes(), path.name)
    report = review_machining(model, MachiningProfile(tool_diameter_mm=12., flute_length_mm=4., reach_mm=6.))
    result = planning.recommend_plan(report, feedback_path=tmp_path / "prefs.json")
    assert result["selected"] is not None
    assert result["selected"]["outcomes"]["remaining_numeric_conflicts"] == 0
