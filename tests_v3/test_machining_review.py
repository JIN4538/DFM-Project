"""Machining checks against independently dimensioned STEP fixtures.

These verify the stated geometric checks, not successful physical machining,
toolpath generation, strength, surface quality, or process capability.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
import trimesh

from amdfm.io import load_model
from dfm.machining import MachiningProfile, rectangular_pocket_floors, review_machining


CAD = Path(__file__).resolve().parents[1] / "examples/machining"
CASES = json.loads((CAD / "manifest.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def models():
    return {case["id"]: load_model((CAD / case["file"]).read_bytes(), case["file"]) for case in CASES}


def finding(report, identifier):
    return next(item for item in report["findings"] if item["id"] == identifier)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_cad_fixture_dimensions_and_identity(models, case):
    expected = case["expected"]
    model = models[case["id"]]
    assert hashlib.sha256((CAD / case["file"]).read_bytes()).hexdigest() == case["sha256"]
    assert model.metadata["solid_count"] == expected["solid_count"]
    if "volume_mm3" in expected:
        assert model.metadata["exact_volume_mm3"] == pytest.approx(expected["volume_mm3"], rel=1e-9)
    if "constituent_volume_sum_mm3" in expected:
        assert model.metadata["exact_volume_mm3"] is None
        assert model.metadata["constituent_volume_sum_mm3"] == pytest.approx(expected["constituent_volume_sum_mm3"], rel=1e-9)
    if "cavity_shell_count" in expected:
        assert model.metadata["cavity_shell_count"] == expected["cavity_shell_count"]
    cylinders = [f for f in model.cad_features if f["kind"] == "cylinder" and f["role"] == "inner"]
    full = [f for f in cylinders if f["full_circumference"]]
    partial = [f for f in cylinders if not f["full_circumference"]]
    assert len(full) == expected["internal_full_cylinder_face_count"]
    assert len(partial) == expected["internal_partial_cylinder_face_count"]
    for cylinder in full:
        assert cylinder["diameter_mm"] == pytest.approx(expected["cylinder_diameter_mm"])
        assert cylinder["axial_extent_mm"] == pytest.approx(expected["cylindrical_length_mm"])
        assert abs(np.dot(cylinder["axis"], expected["cylinder_axis"])) == pytest.approx(1)
    for cylinder in partial:
        assert cylinder["diameter_mm"] / 2 == pytest.approx(expected["internal_partial_cylinder_radius_mm"])
        assert cylinder["u_span_rad"] == pytest.approx(expected["internal_partial_cylinder_span_rad"])
    if "floor_area_mm2" in expected:
        floor = next(f for f in model.cad_features if f["kind"] == "plane"
                     and np.allclose(f["centroid_mm"], expected["floor_center_mm"], atol=1e-8))
        assert floor["area_mm2"] == pytest.approx(expected["floor_area_mm2"])


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
def test_rectangular_floor_recognition_and_negative_counterexamples(models, case):
    model, expected = models[case["id"]], case["expected"]
    pockets = rectangular_pocket_floors(model.cad_features, expected["direction"])
    assert len(pockets) == expected.get("raw_rectangular_pocket_count", expected["rectangular_pocket_count"])
    if "pocket_width_mm" not in expected:
        return
    pocket = pockets[0]
    assert pocket["width_mm"] == pytest.approx(expected["pocket_width_mm"])
    assert pocket["length_mm"] == pytest.approx(expected["pocket_length_mm"])
    assert pocket["wall_height_mm"] == pytest.approx(expected["pocket_wall_height_mm"])
    assert pocket["center_mm"] == pytest.approx(expected["pocket_floor_center_mm"], abs=1e-8)
    assert pocket["internal_corner_radius_mm"] == 0
    floor = next(f for f in model.cad_features if f["face_id"] == pocket["floor_face_id"])
    assert floor["area_mm2"] == pytest.approx(expected["pocket_floor_area_mm2"])


def test_pocket_limits_report_measured_geometry_and_selected_tool_conflicts(models):
    profile = MachiningProfile(tool_diameter_mm=4, flute_length_mm=10, reach_mm=15)
    report = review_machining(models["02_narrow_deep_pocket"], profile)
    result = finding(report, "cnc_rectangular_pockets")
    assert result["status"] == "attention"
    assert result["measurements"]["count"] == 1
    pocket = result["measurements"]["pockets"][0]
    assert pocket["width_too_small"] is True
    assert pocket["exceeds_flute_length"] is True
    assert pocket["exceeds_reach"] is True
    assert result["cad_face_ids"] == [pocket["floor_face_id"]]
    assert set(models["02_narrow_deep_pocket"].face_ids[result["face_indices"]]) == {pocket["floor_face_id"]}
    assert "success_probability" not in report
    assert "score" not in report


def test_exact_tool_dimension_boundary_is_not_exceeded_but_sharp_corner_remains(models):
    report = review_machining(models["01_rectangular_pocket"],
                              MachiningProfile(tool_diameter_mm=12, flute_length_mm=8, reach_mm=8))
    result = finding(report, "cnc_rectangular_pockets")
    pocket = result["measurements"]["pockets"][0]
    assert pocket["width_too_small"] is False
    assert pocket["exceeds_flute_length"] is False
    assert pocket["exceeds_reach"] is False
    assert result["status"] == "attention"  # Sharp internal corners remain independently.


@pytest.mark.parametrize("diameter,status,too_large", [(6, "observed", False), (6.001, "attention", True)])
def test_partial_cylinder_radius_constraint_is_not_a_full_hole(models, diameter, status, too_large):
    report = review_machining(models["03_rounded_pocket"], MachiningProfile(tool_diameter_mm=diameter))
    result = finding(report, "cnc_curved_corners")
    assert result["status"] == status
    rows = result["measurements"]["cylindrical_faces"]
    assert len(rows) == 4
    assert all(row["radius_mm"] == pytest.approx(3) and row["tool_too_large"] is too_large for row in rows)
    assert finding(report, "cnc_holes")["measurements"]["face_count"] == 0
    assert finding(report, "cnc_rectangular_pockets")["measurements"]["count"] == 0


def test_hole_misalignment_changes_with_approach_but_not_its_dimensions(models):
    profile = MachiningProfile(tool_diameter_mm=3, reach_mm=45)
    reports = [review_machining(models["05_side_hole"], profile, direction) for direction in [(0, 0, 1), (1, 0, 0)]]
    rows = [finding(report, "cnc_holes")["measurements"]["cylindrical_faces"][0] for report in reports]
    assert [row["axis_aligned"] for row in rows] == [False, True]
    assert [finding(report, "cnc_holes")["status"] for report in reports] == ["attention", "observed"]
    assert all(row["diameter_mm"] == pytest.approx(4) and row["cylindrical_length_mm"] == pytest.approx(40) for row in rows)
    assert all("hole_depth_mm" not in row and "drill_depth_mm" not in row for row in rows)


def test_missing_tool_conditions_remain_unknown_for_measured_hole(models):
    report = review_machining(models["04_vertical_hole"], MachiningProfile())
    result = finding(report, "cnc_holes")
    assert result["status"] == "unknown"
    row = result["measurements"]["cylindrical_faces"][0]
    assert row["diameter_mm"] == pytest.approx(6)
    assert row["cylindrical_length_mm"] == pytest.approx(15)
    assert row["tool_too_large"] is None
    assert row["segment_exceeds_reach"] is None


def test_multibody_review_requires_selection_then_retains_pocket(models):
    model = models["12_two_solids"]
    report = review_machining(model, MachiningProfile(tool_diameter_mm=4, reach_mm=20))
    for identifier in ("cnc_input", "cnc_holes", "cnc_curved_corners", "cnc_rectangular_pockets"):
        assert finding(report, identifier)["status"] == "unknown"
    selected = model.select_body(1)
    selected_report = review_machining(selected, MachiningProfile())
    assert finding(selected_report, "cnc_input")["status"] == "observed"
    assert finding(selected_report, "cnc_rectangular_pockets")["measurements"]["count"] == 1


def test_incomplete_floor_or_wall_boundary_is_not_a_complete_pocket(models):
    original = models["01_rectangular_pocket"].cad_features
    pocket = rectangular_pocket_floors(original, (0, 0, 1))[0]
    for affected_id in (pocket["floor_face_id"], pocket["wall_face_ids"][0]):
        features = deepcopy(original)
        next(f for f in features if f["face_id"] == affected_id)["boundary_status"] = "partial"
        assert rectangular_pocket_floors(features, (0, 0, 1)) == []


def test_stl_cannot_silently_supply_analytic_cad_dimensions():
    model = load_model(trimesh.creation.box([10, 20, 30]).export(file_type="stl"), "box.stl", dimensions_confirmed=True)
    report = review_machining(model, MachiningProfile(tool_diameter_mm=4, reach_mm=20))
    assert finding(report, "cnc_input")["status"] == "unknown"
    assert finding(report, "cnc_holes")["status"] == "unknown"
    assert finding(report, "cnc_rectangular_pockets")["status"] == "unknown"


@pytest.mark.parametrize("kwargs", [dict(tool_diameter_mm=0), dict(tool_diameter_mm=True),
    dict(flute_length_mm=-1), dict(reach_mm=float("inf")), dict(hole_depth_ratio_limit=float("nan")),
    dict(flute_length_mm=20, reach_mm=10)])
def test_invalid_tool_conditions_are_rejected(kwargs):
    with pytest.raises(ValueError):
        MachiningProfile(**kwargs).validate()


def test_fixture_generator_does_not_overwrite_preserved_artifacts():
    from scripts.generate_machining_examples import generate
    before = (CAD / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        generate(CAD)
    assert (CAD / "manifest.json").read_bytes() == before
