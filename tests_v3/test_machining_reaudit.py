"""Independent CAD counterexamples for the 2026-09-20 machining re-audit.

Construction dimensions, transformations and separate area formulas are the
oracles. These are numerical/geometric checks, not physical machining trials.
"""
import json
import math

import numpy as np
import pytest

from amdfm.cad_worker import convert
from amdfm.io import exact_weld
from amdfm.models import Model
from dfm.machining import MachiningProfile, review_machining


def _box(dx, dy, dz, origin=(0, 0, 0)):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    return BRepPrimAPI_MakeBox(gp_Pnt(*origin), dx, dy, dz).Shape()


def _cylinder(radius, height, origin):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt
    return BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*origin), gp_Dir(0, 0, 1)), radius, height).Shape()


def _cut(stock, tool):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    operation = BRepAlgoAPI_Cut(stock, tool)
    operation.Build()
    assert operation.IsDone()
    return operation.Shape()


def _model(shape, directory, name, *, inch=False):
    from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.Interface import Interface_Static
    source, target = directory / (name + ".step"), directory / name
    writer = STEPControl_Writer()
    Interface_Static.SetCVal_s("write.step.unit", "INCH" if inch else "MM")
    try:
        assert writer.Transfer(shape, STEPControl_AsIs) == IFSelect_RetDone
        assert writer.Write(str(source)) == IFSelect_RetDone
    finally:
        Interface_Static.SetCVal_s("write.step.unit", "MM")
    source_before = source.read_bytes()
    convert(source, target, .01)
    assert source.read_bytes() == source_before
    meta = json.loads(target.with_suffix(".json").read_text(encoding="utf-8"))
    with np.load(target.with_suffix(".npz")) as arrays:
        mesh = exact_weld(arrays["vertices"], arrays["faces"])
        face_ids, body_ids = arrays["face_ids"].copy(), arrays["body_ids"].copy()
    features = meta.pop("features")
    meta.update(source_format="step", coordinate_unit="mm", filename=source.name)
    return Model(mesh, meta, features, face_ids, body_ids)


def _transform(shape, angle, shift):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Trsf, gp_Ax1, gp_Dir, gp_Pnt, gp_Vec
    axis = np.asarray([1., 2., 3.]) / math.sqrt(14)
    cross = np.asarray([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    # Independent Rodrigues formula for the expected rotated machining axis.
    rot = math.cos(angle) * np.eye(3) + (1 - math.cos(angle)) * np.outer(axis, axis) + math.sin(angle) * cross
    transform = gp_Trsf()
    transform.SetRotation(gp_Ax1(gp_Pnt(), gp_Dir(*axis)), angle)
    transform.SetTranslationPart(gp_Vec(shift, -shift, shift))
    return BRepBuilderAPI_Transform(shape, transform, True).Shape(), rot @ [0, 0, 1]


def _pocket():
    return _cut(_box(40, 30, 15), _box(20, 12, 10, (10, 9, 7)))


def _finding(report, identifier):
    return next(row for row in report["findings"] if row["id"] == identifier)


@pytest.mark.parametrize("angle,shift", [(0., 0.), (.713, 0.), (.713, 1000.)])
def test_equal_tool_dimensions_do_not_become_conflicts_after_step_rotation(tmp_path, angle, shift):
    shape, direction = _transform(_pocket(), angle, shift)
    model = _model(shape, tmp_path, "equal_dimensions")
    report = review_machining(model, MachiningProfile(tool_diameter_mm=12, flute_length_mm=8, reach_mm=8), direction)
    finding = _finding(report, "cnc_rectangular_pockets")
    rows = finding["measurements"]["pockets"]
    assert len(rows) == 1
    row = rows[0]
    assert row["width_mm"] == pytest.approx(12, abs=1e-8)
    assert row["wall_height_mm"] == pytest.approx(8, abs=1e-8)
    assert row["width_too_small"] is False
    assert row["exceeds_flute_length"] is False
    assert row["exceeds_reach"] is False
    assert set(row["numerical_boundary_comparisons"]) == {"width_too_small", "exceeds_flute_length", "exceeds_reach"}
    assert finding["status"] == "attention"  # Independent sharp-corner issue remains.
    assert "machining clearance" in report["numerical_policy"]["boundary_scope"]


def test_real_dimension_difference_is_not_erased_by_numeric_boundary_policy(tmp_path):
    shape, direction = _transform(_pocket(), .713, 1000)
    model = _model(shape, tmp_path, "real_difference")
    report = review_machining(model, MachiningProfile(tool_diameter_mm=12.001, flute_length_mm=7.999, reach_mm=7.999), direction)
    row = _finding(report, "cnc_rectangular_pockets")["measurements"]["pockets"][0]
    assert row["width_too_small"] and row["exceeds_flute_length"] and row["exceeds_reach"]
    assert not row.get("numerical_boundary_comparisons")


@pytest.mark.parametrize("shift", [1e6, 1e8])
def test_large_coordinate_transfer_retains_unresolved_floor_location(tmp_path, shift):
    shape, direction = _transform(_pocket(), .819, shift)
    model = _model(shape, tmp_path, "large_coordinate")
    report = review_machining(model, MachiningProfile(tool_diameter_mm=4, flute_length_mm=10, reach_mm=15), direction)
    finding = _finding(report, "cnc_rectangular_pockets")
    # STEP precision changes boundary agreement at these translations. The
    # imported floor must not silently vanish into 'no feature detected'.
    assert finding["measurements"]["count"] == 0
    assert len(finding["measurements"]["unresolved_floor_face_ids"]) == 1
    assert finding["status"] == "unknown"
    assert finding["cad_face_ids"] == finding["measurements"]["unresolved_floor_face_ids"]
    assert len(finding["face_indices"]) > 0
    assert "미측정" in finding["reason"]


@pytest.mark.parametrize("kind", ["island", "channel", "sealed"])
def test_unsupported_inward_floors_keep_unknown_without_becoming_pockets(tmp_path, kind):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
    if kind == "island":
        shape = BRepAlgoAPI_Fuse(_pocket(), _box(3, 3, 8, (18, 13, 7))).Shape()
    elif kind == "channel":
        shape = _cut(_box(40, 30, 15), _box(42, 12, 10, (-1, 9, 7)))
    else:
        shape = _cut(_box(40, 30, 15), _box(20, 12, 8, (10, 9, 3)))
    model = _model(shape, tmp_path, kind)
    result = _finding(review_machining(model, MachiningProfile()), "cnc_rectangular_pockets")
    assert result["status"] == "unknown"
    assert result["measurements"]["count"] == 0
    assert len(result["measurements"]["unresolved_floor_face_ids"]) == 1
    assert not result["measurements"]["pockets"]
    assert any("열린 포켓으로 확정한 수가 아닙니다" in text for text in result["limitations"])


@pytest.mark.parametrize("shape_kind", ["block", "boss"])
def test_exterior_planes_are_not_promoted_to_unresolved_inward_floors(tmp_path, shape_kind):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Fuse
    shape = _box(40, 30, 15) if shape_kind == "block" else BRepAlgoAPI_Fuse(
        _box(40, 30, 5), _box(20, 12, 10, (10, 9, 5))).Shape()
    model = _model(shape, tmp_path, shape_kind)
    result = _finding(review_machining(model, MachiningProfile()), "cnc_rectangular_pockets")
    assert result["status"] == "not_detected"
    assert result["measurements"]["count"] == 0
    assert result["measurements"]["unresolved_floor_face_ids"] == []


def test_inch_declared_step_uses_millimetres_for_pocket_and_tool_comparison(tmp_path):
    model = _model(_pocket(), tmp_path, "inch_pocket", inch=True)
    result = _finding(review_machining(model, MachiningProfile(tool_diameter_mm=12, flute_length_mm=8, reach_mm=8)), "cnc_rectangular_pockets")
    row = result["measurements"]["pockets"][0]
    assert row["width_mm"] == pytest.approx(12)
    assert row["length_mm"] == pytest.approx(20)
    assert row["wall_height_mm"] == pytest.approx(8)
    assert row["width_too_small"] is False and row["exceeds_reach"] is False


def test_cross_window_keeps_cylindrical_span_without_claiming_complete_hole(tmp_path):
    stock = _cut(_box(20, 20, 12), _cylinder(3, 14, (10, 10, -1)))
    shape = _cut(stock, _box(2, 10, 2, (9, 12, 4)))
    model = _model(shape, tmp_path, "cross_window")
    full = [f for f in model.cad_features if f.get("kind") == "cylinder" and f.get("role") == "inner" and f.get("full_circumference")]
    assert len(full) == 1
    face = full[0]
    assert face["diameter_mm"] == pytest.approx(6)
    assert face["axial_extent_mm"] == pytest.approx(12)
    assert face["area_mm2"] < 2 * math.pi * 3 * 12
    result = _finding(review_machining(model, MachiningProfile(tool_diameter_mm=4, reach_mm=20)), "cnc_holes")
    assert "360°" in result["reason"] and "완전한" not in result["reason"]
    assert any("모든 높이에 원통 벽이 있다는 뜻이 아닙니다" in text for text in result["limitations"])
    row = result["measurements"]["cylindrical_faces"][0]
    assert row["cylindrical_length_mm"] == pytest.approx(12)
    assert "through_hole" not in row and "hole_depth_mm" not in row


def test_blind_and_through_cylinders_are_face_measurements_not_connectivity_certificates(tmp_path):
    for name, depth, bottom in [("blind", 8, 4), ("through", 12, -1)]:
        shape = _cut(_box(20, 20, 12), _cylinder(3, depth + 2, (10, 10, bottom)))
        model = _model(shape, tmp_path, name)
        report = review_machining(model, MachiningProfile(tool_diameter_mm=4, reach_mm=20))
        result = _finding(report, "cnc_holes")
        assert len(result["measurements"]["cylindrical_faces"]) == 1
        assert result["measurements"]["cylindrical_faces"][0]["cylindrical_length_mm"] == pytest.approx(depth)
        assert "막힘" in result["action"]
        assert any("입구·막힘" in text for text in result["limitations"])


def test_finding_evidence_matches_calculation_and_does_not_claim_cad_for_mesh_rays(tmp_path):
    model = _model(_pocket(), tmp_path, "provenance")
    report = review_machining(model, MachiningProfile())
    assert _finding(report, "cnc_input")["evidence"] == []
    assert _finding(report, "cnc_coverage")["evidence"] == []
    assert "CNC_FACE_RECOGNITION" in _finding(report, "cnc_holes")["evidence"]
    visibility = _finding(report, "cnc_visibility")
    assert "sampled mesh" in visibility["method"]
    assert visibility["evidence"] == ["CNC_ACCESS_SCOPE"]
    source = next(row for row in report["sources"] if row["id"] == "CNC_ACCESS_SCOPE")
    assert "does not validate" in source["scope"]


def test_small_real_hole_axis_tilt_is_not_rounded_into_axis_alignment(tmp_path):
    shape = _cut(_box(20, 20, 12), _cylinder(3, 14, (10, 10, -1)))
    model = _model(shape, tmp_path, "small_tilt")
    theta = math.radians(.005)
    report = review_machining(model, MachiningProfile(tool_diameter_mm=4, reach_mm=20),
                              [math.sin(theta), 0, math.cos(theta)])
    result = _finding(report, "cnc_holes")
    row = result["measurements"]["cylindrical_faces"][0]
    assert row["axis_angle_deg"] == pytest.approx(.005, abs=1e-10)
    assert row["axis_aligned"] is False
    assert row["tool_too_large"] is None and row["segment_exceeds_reach"] is None
    assert result["status"] == "attention"
    # The prior cosine policy accepted this actual tilt (.005 < .0081 deg).
    assert math.cos(theta) >= 1 - 1e-8


def test_split_cylindrical_wall_is_not_presented_as_two_complete_holes(tmp_path):
    from OCP.ShapeUpgrade import ShapeUpgrade_ShapeDivideClosed
    shape = _cut(_box(20, 20, 12), _cylinder(3, 14, (10, 10, -1)))
    splitter = ShapeUpgrade_ShapeDivideClosed(shape)
    splitter.SetNbSplitPoints(1)
    assert splitter.Perform()
    model = _model(splitter.Result(), tmp_path, "split_cylinder")
    inner = [f for f in model.cad_features if f.get("kind") == "cylinder" and f.get("role") == "inner"]
    assert len(inner) == 2
    assert all(not face["full_circumference"] for face in inner)
    assert sum(face["area_mm2"] for face in inner) == pytest.approx(2 * math.pi * 3 * 12)
    report = review_machining(model, MachiningProfile(tool_diameter_mm=4, reach_mm=20))
    assert _finding(report, "cnc_holes")["measurements"]["face_count"] == 0
    corners = _finding(report, "cnc_curved_corners")
    assert len(corners["measurements"]["cylindrical_faces"]) == 2
    assert all(row["radius_mm"] == pytest.approx(3) for row in corners["measurements"]["cylindrical_faces"])
    assert any("포켓 코너로 확정하지 않습니다" in text for text in corners["limitations"])


@pytest.mark.parametrize("relative_tilt,aligned", [(.5e-8, True), (2e-8, False)])
@pytest.mark.parametrize("rotation,shift", [(0., 0.), (.713, 1000.)])
def test_axis_alignment_numeric_band_sides_are_rotation_invariant(tmp_path, relative_tilt, aligned, rotation, shift):
    shape = _cut(_box(20, 20, 12), _cylinder(3, 14, (10, 10, -1)))
    shape, axis = _transform(shape, rotation, shift)
    model = _model(shape, tmp_path, "axis_band")
    # Rotate toward a perpendicular vector so its relative angle is analytic.
    perpendicular = np.cross(axis, [1., 0, 0])
    perpendicular /= np.linalg.norm(perpendicular)
    direction = axis * math.cos(relative_tilt) + perpendicular * math.sin(relative_tilt)
    report = review_machining(model, MachiningProfile(tool_diameter_mm=4, reach_mm=20), direction)
    result = _finding(report, "cnc_holes")
    row = result["measurements"]["cylindrical_faces"][0]
    assert row["axis_aligned"] is aligned
    assert math.radians(row["axis_angle_deg"]) == pytest.approx(relative_tilt, abs=1e-11)
    if not aligned:
        assert row["tool_too_large"] is None and row["segment_exceeds_reach"] is None
        assert "보류" in result["action"]


def test_corner_action_changes_after_large_tool_conflict_is_resolved(tmp_path):
    from OCP.ShapeUpgrade import ShapeUpgrade_ShapeDivideClosed
    # Two semicylindrical inner faces independently give an R3 comparator.
    shape = _cut(_box(20, 20, 12), _cylinder(3, 14, (10, 10, -1)))
    splitter = ShapeUpgrade_ShapeDivideClosed(shape)
    splitter.SetNbSplitPoints(1)
    assert splitter.Perform()
    model = _model(splitter.Result(), tmp_path, "corner_actions")
    reports = {diameter: review_machining(model, MachiningProfile(tool_diameter_mm=diameter)) for diameter in (None, 8, 6, 4)}
    bad = _finding(reports[8], "cnc_curved_corners")
    assert bad["status"] == "attention" and "더 작은 공구" in bad["action"]
    resolved = _finding(reports[4], "cnc_curved_corners")
    assert resolved["status"] == "observed"
    assert "줄여야 할 조건은 관측되지 않았습니다" in resolved["action"]
    assert "더 작은 공구 또는" not in resolved["action"]
    boundary = _finding(reports[6], "cnc_curved_corners")
    assert "수치 경계" in boundary["action"]
    missing = _finding(reports[None], "cnc_curved_corners")
    assert missing["status"] == "unknown" and "지름을 입력" in missing["action"]
