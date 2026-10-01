"""Independent boundary/coverage regressions for actual fitted local models."""
from copy import deepcopy
import hashlib
import json
import math

import pytest

import dfm.learned_review as learned


def report(task, measurements, *, status="observed", process="MEX", **profile):
    return dict(profile=dict(process=process, **profile), findings=[dict(id=task, status=status, measurements=measurements)])


def item(report):
    return learned.analyze_report(report)["items"][0]


@pytest.fixture(scope="module")
def model():
    return learned.load_model()


@pytest.mark.parametrize("task,values,expected", [
    ("wall", dict(minimum_mm=.3, limit_mm=1), 1),
    ("wall", dict(minimum_mm=1, limit_mm=1), 0),
    ("wall", dict(minimum_mm=4, limit_mm=1), 0),
    ("overhang", dict(area_mm2=23), 1),
    ("overhang", dict(area_mm2=0), 0),
    ("contact", dict(area_mm2=0), 1),
    ("contact", dict(area_mm2=20), 0),
    ("cavities", dict(shell_count=2), 1),
    ("cavities", dict(shell_count=0), 0),
    ("cad_holes", dict(diameter_mm=2, limit_mm=3, axis_dot=1., process="MEX"), 1),
    ("cad_holes", dict(diameter_mm=2, limit_mm=None, axis_dot=0., process="MEX"), 2),
    ("cad_holes", dict(diameter_mm=2, limit_mm=None, axis_dot=0., process="PBF_POLYMER"), 0),
    ("cnc_holes", dict(diameter_mm=3, length_mm=20, angle_deg=0, tool_mm=6, reach_mm=10, ratio_limit=5), 7),
    ("cnc_holes", dict(diameter_mm=3, length_mm=20, angle_deg=90, tool_mm=6, reach_mm=10, ratio_limit=5), 12),
    ("cnc_holes", dict(diameter_mm=6, length_mm=10, angle_deg=0, tool_mm=3, reach_mm=20, ratio_limit=5), 0),
    ("cnc_curved_corners", dict(radius_mm=2, tool_mm=5), 1),
    ("cnc_curved_corners", dict(radius_mm=2, tool_mm=3), 0),
    ("cnc_rectangular_pockets", dict(width_mm=3, height_mm=20, tool_mm=6, flute_mm=10, reach_mm=15), 15),
    ("cnc_rectangular_pockets", dict(width_mm=10, height_mm=5, tool_mm=6, flute_mm=10, reach_mm=15), 8),
    ("cnc_visibility", dict(normal_dot=.7, obstruction_mm=5), 1),
    ("cnc_visibility", dict(normal_dot=-.7, obstruction_mm=None), 0),
    ("layers", dict(thin_area=0, unsupported_area=2, single_layer_area=1), 6),
])
def test_actual_fitted_model_actions_match_independent_examples(model, task, values, expected):
    assert learned.teacher_mask(task, values) == expected
    assert learned.predict_mask(model, task, learned.features_for(task, values)) == expected


def test_artifact_is_real_fitted_json_and_sources_pinned(model):
    assert model["training_rows"] == 55000
    assert set(model["tasks"]) == set(learned.TASKS)
    assert model["teacher_sources"] == learned.source_hashes()
    assert "dfm/learned_review.py" in model["teacher_sources"]
    assert any(len(record["trees"][0]) > 3 for record in model["tasks"].values())
    assert model["artifact_sha256"] == hashlib.sha256(learned.MODEL_PATH.read_bytes()).hexdigest()


@pytest.mark.parametrize("task,values", [
    ("wall", dict(minimum_mm=-1, limit_mm=1)),
    ("wall", dict(minimum_mm=math.nan, limit_mm=1)),
    ("wall", dict(minimum_mm=True, limit_mm=1)),
    ("wall", dict(minimum_mm=1, limit_mm=0)),
    ("cavities", dict(shell_count=.5)),
    ("cnc_holes", dict(diameter_mm=1, length_mm=2, angle_deg=91)),
    ("cnc_curved_corners", dict(radius_mm=0, tool_mm=3)),
    ("cnc_visibility", dict(normal_dot=math.inf, obstruction_mm=None)),
    ("cad_holes", dict(diameter_mm=1, limit_mm=None, axis_dot=0, process="INJECTION")),
])
def test_invalid_inputs_never_zero_filled(task, values):
    with pytest.raises((ValueError, KeyError)):
        learned.features_for(task, values)


def wall_report(minimum=.3, *, status="measured", complete=True, limit=1.):
    r = report("wall", {}, status="unknown", minimum_wall_mm=limit)
    r["details"] = dict(wall=dict(status=status, measurements=dict(minimum_mm=minimum,
        area_weighted_p05_mm=minimum, requested_samples=12, valid_samples=12 if complete else 8,
        missing_samples=0 if complete else 4)))
    return r


def test_wall_measured_issue_comes_from_numbers_and_does_not_mutate():
    r = wall_report()
    original = deepcopy(r)
    result = item(r)
    assert result["state"] == "confirmed" and result["origin"] == "learned_verified"
    assert result["action_ids"] == ["thicken_wall"] and result["predicted_issue"] is True
    assert "1 mm" in result["action"] and "0.3" in result["evidence"][0]
    assert r == original
    json.dumps(learned.analyze_report(r), allow_nan=False)


@pytest.mark.parametrize("minimum,expected", [(2, "review"), (.3, "confirmed")])
def test_partial_wall_never_cleared(minimum, expected):
    result = item(wall_report(minimum, status="partial", complete=False))
    assert result["state"] == expected and result["complete"] is False


def test_missing_wall_limit_preserved():
    result = item(wall_report(limit=None))
    assert result["state"] == "review" and result["predicted_issue"] is None


def test_existing_title_action_status_not_learned_input():
    r = report("overhang", {"projected_area_sum_mm2": 12})
    a = item(r)
    r["findings"][0].update(title="all clear", action="no action needed", status="attention", target=0)
    b = item(r)
    assert a["model_action_ids"] == b["model_action_ids"] == ["reduce_downward_faces"]
    assert b["state"] == "confirmed"


def test_disagreement_cannot_erase_issue(monkeypatch):
    monkeypatch.setattr(learned, "predict_mask", lambda *args: 0)
    result = item(wall_report())
    assert result["predicted_issue"] is False
    assert result["state"] == "confirmed" and result["origin"] == "rule_fallback"
    assert result["agreement"] is False and result["disagreement_rows"] == 1


def test_false_positive_is_rechecked(monkeypatch):
    monkeypatch.setattr(learned, "predict_mask", lambda *args: 1)
    result = item(wall_report(2))
    assert result["predicted_issue"] is True and result["state"] == "clear"
    assert result["action_ids"] == [] and result["model_action_ids"] == ["thicken_wall"]
    assert result["origin"] == "rule_fallback"


def test_out_of_domain_is_rule_fallback_not_model_confidence(model):
    assert learned.predict_mask(model, "wall", [1e100]) is None
    result = item(wall_report(1e8))
    assert result["origin"] == "rule_fallback" and result["agreement"] is None


def test_missing_or_changed_model_keeps_current_numeric_decision(tmp_path):
    result = learned.analyze_report(wall_report(), model_path=tmp_path / "missing.json")
    assert result["status"] == "unavailable"
    assert result["items"][0]["state"] == "confirmed"
    assert result["items"][0]["origin"] == "rule_fallback"


def test_teacher_source_change_invalidates_model(monkeypatch):
    monkeypatch.setattr(learned, "source_hashes", lambda: {})
    with pytest.raises(ValueError, match="재학습"):
        learned.load_model()
    assert item(wall_report())["origin"] == "rule_fallback"


@pytest.mark.parametrize("mutation", ["checksum", "duplicate", "cycle", "schema", "nonfinite", "list_root"])
def test_corrupt_json_models_are_rejected_without_execution(tmp_path, mutation):
    model = json.loads(learned.MODEL_PATH.read_text("utf-8"))
    if mutation == "cycle":
        model["tasks"]["wall"]["trees"][0][0][2] = 0
    elif mutation == "schema":
        model["schema"] = "other"
    raw = json.dumps(model).encode()
    if mutation == "duplicate":
        raw = raw.replace(b'{', b'{"schema":"other",', 1)
    elif mutation == "nonfinite":
        raw = raw.replace(b'{', b'{"invalid":NaN,', 1)
    elif mutation == "list_root":
        raw = b"[]"
    path = tmp_path / "model.json"
    path.write_bytes(raw)
    path.with_suffix(".manifest.json").write_text(json.dumps({"sha256": "0" * 64 if mutation == "checksum" else hashlib.sha256(raw).hexdigest()}))
    with pytest.raises(ValueError):
        learned.load_model(path)


@pytest.mark.parametrize("task,measurements", [
    ("cnc_holes", {"face_count": 2, "cylindrical_faces": []}),
    ("cnc_rectangular_pockets", {"count": 2, "pockets": []}),
    ("cnc_curved_corners", {"cylindrical_faces": []}),
])
def test_truncated_candidates_cannot_become_clear(task, measurements):
    result = item(report(task, measurements, status="attention", process="MILLING_3AXIS"))
    assert result["state"] == "review" and result["predicted_issue"] is None


def test_polymer_support_never_receives_mex_model():
    result = item(report("overhang", {"projected_area_sum_mm2": 10}, status="not_applicable", process="PBF_POLYMER"))
    assert result["state"] == "unavailable" and not result["action_ids"]


def test_empty_complete_features_explicitly_rule_scope():
    result = item(report("cnc_holes", {"face_count": 0, "cylindrical_faces": []}, status="not_detected", process="MILLING_3AXIS"))
    assert result["state"] == "clear" and result["origin"] == "rule_fallback"
    assert result["predicted_issue"] is False


def test_unaligned_cnc_hole_skips_tool_comparison():
    r = report("cnc_holes", {"face_count": 1, "cylindrical_faces": [dict(diameter_mm=2, cylindrical_length_mm=20, axis_angle_deg=90)]},
               status="attention", process="MILLING_3AXIS", tool_diameter_mm=10, reach_mm=1)
    result = item(r)
    assert result["action_ids"] == ["change_setup"]


@pytest.mark.parametrize("scale", [.0001, .1, 1, 1000])
def test_cnc_teacher_preserves_actual_numeric_tolerance(scale):
    from dfm.machining import _length_comparison
    for shift in (-2e-9, -1e-10, 0., 1e-10, 2e-9):
        tool = scale + shift
        if tool <= 0:
            continue
        values = dict(radius_mm=scale / 2, tool_mm=tool)
        assert learned.teacher_mask("cnc_curved_corners", values) == int(_length_comparison(tool, scale)[0])


def test_known_attention_with_zero_numeric_result_never_clears():
    result = item(report("overhang", {"projected_area_sum_mm2": 0}, status="attention"))
    assert result["state"] == "review"


def test_cad_hole_shape_axis_and_minimum_both_apply():
    r = report("cad_holes", {"inner_face_count": 1, "cylindrical_faces": [dict(role="inner", diameter_mm=2, axis=[1, 0, 0])]}, minimum_hole_mm=3)
    r["current_orientation"] = {"direction": [0, 0, 1]}
    result = item(r)
    assert result["state"] == "confirmed"
    assert result["action_ids"] == ["enlarge_hole", "reorient_hole"]


def test_visibility_partial_still_reports_witnessed_occlusion():
    r = report("cnc_visibility", {"selected_samples": 2}, status="attention", process="MILLING_3AXIS")
    r["visibility"] = dict(status="partial", samples=[
        dict(state="occluded", normal_dot_direction=1., obstruction_distance_mm=3., reason=None),
        dict(state="unknown", normal_dot_direction=1., obstruction_distance_mm=None, reason="time_budget_exceeded")])
    result = item(r)
    assert result["state"] == "confirmed" and result["complete"] is False


def test_geometry_scale_and_unit_must_be_validated_before_model():
    r = report("build", {"placed_extents_mm": [10, 10, 10]}, build_volume_mm=[5, 5, 5], clearance_mm=5)
    result = item(r)
    assert result["state"] == "review" and result["predicted_issue"] is None


@pytest.mark.parametrize("limit", [1., .1, 10., 1000.])
def test_nextafter_length_teacher_matches_production_even_when_ratio_rounds_equal(limit):
    from dfm.machining import _length_comparison
    boundary = limit + max(1e-9, limit * 1e-10)
    for tool in (math.nextafter(boundary, -math.inf), boundary, math.nextafter(boundary, math.inf)):
        values = dict(radius_mm=limit / 2, tool_mm=tool)
        assert learned.teacher_mask("cnc_curved_corners", values) == int(_length_comparison(tool, limit)[0])
    if limit == 1:
        assert learned.teacher_mask("cnc_curved_corners", dict(radius_mm=.5, tool_mm=1.000000001)) == 1


def test_axis_teacher_tracks_production_near_alignment_boundary():
    import numpy as np
    from dfm.machining import _axis_angle_and_alignment
    for sine in (0., math.nextafter(1e-8, 0), 1e-8, math.nextafter(1e-8, math.inf), 1e-7):
        angle, aligned = _axis_angle_and_alignment(np.array([sine, 0., math.sqrt(1 - sine * sine)]), np.array([0., 0., 1.]))
        values = dict(diameter_mm=10., length_mm=5., angle_deg=angle, tool_mm=2., reach_mm=10., ratio_limit=None)
        mask = learned.teacher_mask("cnc_holes", values)
        # The angle round-trip can straddle the machine-precision band. It must
        # never erase an existing attention result in the report adapter.
        r = report("cnc_holes", {"face_count": 1, "cylindrical_faces": [dict(diameter_mm=10., cylindrical_length_mm=5., axis_angle_deg=angle)]},
                   status="observed" if aligned else "attention", process="MILLING_3AXIS", tool_diameter_mm=2., reach_mm=10.)
        if not aligned:
            assert item(r)["state"] != "clear"
        if abs(sine - 1e-8) > 1e-20:
            assert bool(mask & 8) == (not aligned)


def test_cnc_evidence_shows_values_not_only_counts():
    r = report("cnc_rectangular_pockets", {"count": 1, "pockets": [dict(width_mm=3., wall_height_mm=20.)]},
               status="attention", process="MILLING_3AXIS", tool_diameter_mm=6., flute_length_mm=10., reach_mm=15.)
    result = item(r)
    assert "3 mm" in result["evidence"][0] and "6 mm" in result["evidence"][0]
    assert "20 mm" in result["evidence"][1] and "10 mm" in result["evidence"][1]
    assert len(result["recommendations"]) == 4
    assert result["title"] == "포켓 · 개선 4가지"


def test_unsupported_process_cannot_reuse_model():
    result = item(report("overhang", {"projected_area_sum_mm2": 10}, process="PRESS"))
    assert result["state"] == "unavailable" and result["predicted_issue"] is None


def test_unrestricted_build_is_not_a_pending_condition():
    r = report("build", {"placed_extents_mm": [1., 2., 3.]}, status="unknown", build_volume_mm=None)
    result = item(r)
    assert result["state"] == "unavailable"
    assert result["reason"] == "크기 제한 미적용"
    assert result["predicted_issue"] is None


def test_visibility_missing_sample_state_cannot_become_complete_clear():
    r = report("cnc_visibility", {"selected_samples": 1}, process="MILLING_3AXIS")
    r["visibility"] = dict(status="complete", samples=[dict(normal_dot_direction=1., obstruction_distance_mm=None, reason=None)])
    result = item(r)
    assert result["state"] == "review"
    assert result["predicted_issue"] is None
