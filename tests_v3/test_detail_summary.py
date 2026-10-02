"""Decisions must distinguish measured candidates, unknowns and scoped absence."""
import copy
import math

import pytest

from amdfm.detail_summary import summarize_layers, summarize_wall


def wall_result(minimum=4., limit=None):
    return dict(status="measured", measurements=dict(minimum_mm=minimum,
        area_weighted_p05_mm=minimum, minimum_wall_mm=limit,
        requested_samples=24, valid_samples=24, missing_samples=0,
        below_limit_face_indices=list(range(24)) if limit and minimum < limit else [],
        thinnest_face_indices=list(range(24)),
        samples=[dict(normal_chord_mm=minimum, source_face=i) for i in range(24)]))


def layer_result(count=3):
    rows = [dict(index=i, z_mm=.1 + i*.2, complete=True,
                 **{key + "_candidate_area_mm2": 0. for key in ("thin", "unsupported", "single_layer")},
                 **{key + "_full_scope": True for key in ("thin", "unsupported", "single_layer")})
            for i in range(count)]
    return dict(status="complete", layers=rows, expected_layers=count,
                examined_layers=count, complete_layers=count)


def test_wall_screenshot_measurement_without_criterion_does_not_pass():
    result = summarize_wall(wall_result())
    assert result["status"] == "criterion_needed"
    assert result["level"] == "info"
    assert result["minimum_mm"] == 4
    assert "기준이 없습니다" in result["title"]
    assert "기준(mm)과 근거" in result["next_action"]
    assert result["counts"]["below_limit"] is None


def test_wall_criterion_scoped_result_and_exact_boundary():
    result = summarize_wall(wall_result(limit=4))
    assert result["level"] == "success"
    assert result["status"] == "within_criterion"
    assert "검사한 표본" in result["title"]
    assert result["counts"]["below_limit"] == 0
    assert "전체 최소 벽두께" in result["scope"]


def test_wall_below_criterion_points_to_the_measured_faces():
    result = summarize_wall(wall_result(.3, 1.))
    assert result["status"] == "attention"
    assert result["level"] == "warning"
    assert result["counts"]["below_limit"] == 24
    assert result["highlight_face_indices"] == list(range(24))
    assert "벽 보강" in result["next_action"]


def test_wall_supplied_criterion_is_compared_to_samples_not_stale_face_list():
    result = summarize_wall(wall_result(4., 1.), minimum_wall_mm=5.)
    assert result["status"] == "attention"
    assert result["counts"]["below_limit"] == 24


@pytest.mark.parametrize("key,value", [("requested_samples", 25), ("missing_samples", 1),
    ("valid_samples", None), ("minimum_mm", math.nan), ("minimum_mm", 0),
    ("area_weighted_p05_mm", .1), ("valid_samples", True)])
def test_wall_inconsistent_or_unknown_measurement_never_passes(key, value):
    detail = wall_result(limit=1.)
    detail["measurements"][key] = value
    assert summarize_wall(detail)["level"] != "success"


def test_wall_partial_with_valid_above_criterion_values_is_still_partial():
    detail = wall_result(limit=1.)
    detail["status"] = "partial"
    detail["measurements"].update(requested_samples=25, missing_samples=1)
    result = summarize_wall(detail)
    assert result["status"] == "partial"
    assert result["counts"]["missing"] == 1
    assert "미확인" in result["next_action"]


def test_wall_partial_below_criterion_keeps_the_candidate_and_missing_scope():
    detail = wall_result(.5, 1.)
    detail["status"] = "partial"
    detail["measurements"].update(requested_samples=25, missing_samples=1)
    result = summarize_wall(detail)
    assert result["status"] == "attention"
    assert "미확인" in result["observation"]
    assert not result["complete"]


def test_wall_inconsistent_raw_samples_never_pass():
    detail = wall_result(limit=1.)
    detail["measurements"]["samples"][0]["normal_chord_mm"] = .01
    assert summarize_wall(detail)["level"] != "success"


def test_wall_tiny_positive_below_criterion_is_not_rounded_away():
    result = summarize_wall(wall_result(1e-12, 2e-12))
    assert result["status"] == "attention"
    assert "1e-12" in result["observation"]


def test_wall_unrun_and_failure_are_separate():
    assert summarize_wall(None)["status"] == "not_run"
    failed = summarize_wall(dict(status="unknown", reason="단일 솔리드를 선택하세요."))
    assert failed["status"] == "unknown"
    assert failed["minimum_mm"] is None
    assert "단일 솔리드" in failed["observation"]


def test_layer_screenshot_all_200_layers_zero_has_scoped_clear_message():
    result = summarize_layers(layer_result(200))
    assert result["status"] == "no_candidates"
    assert result["level"] == "success"
    assert "200개 층" in result["title"]
    assert result["counts"]["candidate_layers"] == 0
    assert result["affected_rows"] == []
    assert all(c["candidate_layers"] == 0 for c in result["checks"])
    assert "실제 슬라이서" in result["next_action"]


@pytest.mark.parametrize("key,value", [
    ("thin_candidate_area_mm2", None), ("thin_candidate_area_mm2", math.nan),
    ("thin_candidate_area_mm2", math.inf), ("thin_candidate_area_mm2", -1),
    ("thin_candidate_area_mm2", True), ("thin_full_scope", False),
    ("unsupported_full_scope", False), ("single_layer_full_scope", False),
    ("complete", False), ("index", 2), ("index", True), ("z_mm", None), ("z_mm", .5)])
def test_layer_any_unknown_incomplete_or_misidentified_zero_row_never_passes(key, value):
    detail = layer_result()
    detail["layers"][0][key] = value
    result = summarize_layers(detail)
    assert result["level"] != "success"
    assert not result["complete"]


@pytest.mark.parametrize("key,value", [("status", "partial"), ("expected_layers", 4),
    ("expected_layers", 0), ("expected_layers", None), ("examined_layers", 2),
    ("complete_layers", 2)])
def test_layer_aggregate_declarations_cannot_hide_missing_scope(key, value):
    detail = layer_result()
    detail[key] = value
    assert summarize_layers(detail)["level"] != "success"


def test_layer_candidate_rows_are_1_based_filter_only_affected_and_keep_tiny_areas():
    detail = layer_result()
    detail["layers"][1]["thin_candidate_area_mm2"] = 1e-14
    detail["layers"][1]["unsupported_candidate_area_mm2"] = 2
    result = summarize_layers(detail)
    assert result["status"] == "attention"
    assert result["counts"]["candidate_layers"] == 1
    assert result["default_row_index"] == 1
    assert len(result["affected_rows"]) == 1
    row = result["affected_rows"][0]
    assert row["display_layer"] == 2
    assert row["thin_candidate_area_mm2"] == 1e-14
    assert len(row["types"]) == 2
    assert "슬라이서" in row["action"]


def test_layer_partial_positive_keeps_observation_and_unknown_notice():
    detail = layer_result()
    detail["layers"][1]["thin_candidate_area_mm2"] = 2
    detail["layers"][1]["thin_full_scope"] = False
    result = summarize_layers(detail)
    assert result["status"] == "attention"
    assert "미확인" in result["observation"]
    assert not result["affected_rows"][0]["full_scope"]


def test_layer_all_missing_is_not_an_observed_zero():
    detail = layer_result()
    for row in detail["layers"]:
        for key in ("thin", "unsupported", "single_layer"):
            row[key + "_candidate_area_mm2"] = None
    result = summarize_layers(detail)
    assert result["counts"]["candidate_layers"] is None
    assert all(c["candidate_layers"] is None for c in result["checks"])
    assert "면적값이 없습니다" in result["observation"]


def test_layer_non_mex_is_not_a_failure_or_clear_result():
    result = summarize_layers(dict(status="not_applicable", reason="현재 공정 VPP"))
    assert result["status"] == "not_applicable"
    assert result["level"] == "info"
    assert result["counts"]["candidate_layers"] is None


def test_layer_unrun_failure_and_limit_exceeded_are_distinct_from_zero():
    assert summarize_layers(None)["status"] == "not_run"
    result = summarize_layers(dict(status="unavailable", expected_layers=2000,
                                  reason="층 한도 초과"))
    assert result["status"] == "unknown"
    assert result["counts"]["candidate_layers"] is None
    assert result["counts"]["unresolved"] == 2000
    assert "한도 초과" in result["observation"]


def test_summaries_do_not_change_original_measurements_or_report_lists():
    wall, layers = wall_result(4., 1.), layer_result()
    layers["layers"][0]["thin_candidate_area_mm2"] = .5
    original_wall, original_layers = copy.deepcopy(wall), copy.deepcopy(layers)
    summarize_wall(wall, 5.)
    summarize_layers(layers)
    assert wall == original_wall
    assert layers == original_layers


def test_real_box_wall_and_layers_use_the_actual_detail_schema():
    import trimesh
    from amdfm.detail_worker import normal_chords
    from src.core.layer_review import inspect_layers

    mesh = trimesh.creation.box(extents=[4., 4., 4.])
    wall = summarize_wall(normal_chords(mesh, limit=1.))
    assert wall["status"] == "within_criterion"
    assert wall["minimum_mm"] == pytest.approx(4.)
    layers = summarize_layers(inspect_layers(mesh, layer_height=1., line_width=.4))
    assert layers["complete"]
    # This constant square section is wider than the requested line width and
    # supported by each adjacent layer; all three candidate areas are zero.
    assert layers["status"] == "no_candidates"
    assert layers["checks"][0]["candidate_layers"] == 0
