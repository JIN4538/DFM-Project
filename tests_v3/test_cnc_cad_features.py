"""Independent dimensions of CAD boundaries used by CNC checks.

The oracles are construction dimensions and analytic formulas, not the feature
extractor's classifications. Surface/partial/budget cases must remain explicit.
"""
import json
import math

import numpy as np
import pytest

from amdfm.cad_features import BoundaryContext, trimmed_analytic_face
from amdfm.cad_worker import convert, integrated_properties, items


def _write_step(shape, path):
    from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
    from OCP.IFSelect import IFSelect_RetDone
    writer = STEPControl_Writer()
    assert writer.Transfer(shape, STEPControl_AsIs) == IFSelect_RetDone
    assert writer.Write(str(path)) == IFSelect_RetDone


def _convert(shape, tmp_path, name="part"):
    source, target = tmp_path / f"{name}.step", tmp_path / name
    _write_step(shape, source)
    source_bytes = source.read_bytes()
    convert(source, target, .05)
    assert source.read_bytes() == source_bytes
    result = json.loads(target.with_suffix(".json").read_text(encoding="utf-8"))
    # Explicitly prohibit NaN/Infinity so these fields can cross the worker boundary.
    json.dumps(result, allow_nan=False)
    with np.load(target.with_suffix(".npz")) as mesh:
        assert set(mesh["face_ids"]) <= {face["face_id"] for face in result["features"]}
    return result


def _pocket(*, rounded=False):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.gp import gp_Pnt
    stock = BRepPrimAPI_MakeBox(40, 30, 12).Shape()
    cutter = BRepPrimAPI_MakeBox(gp_Pnt(8, 7, 4), 18, 12, 12).Shape()
    if rounded:
        from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.TopAbs import TopAbs_EDGE
        from OCP.TopoDS import TopoDS
        fillet = BRepFilletAPI_MakeFillet(cutter)
        for raw in items(cutter, TopAbs_EDGE):
            edge = TopoDS.Edge_s(raw)
            curve = BRepAdaptor_Curve(edge)
            a = np.asarray(curve.Value(curve.FirstParameter()).Coord())
            b = np.asarray(curve.Value(curve.LastParameter()).Coord())
            if np.linalg.norm(a[:2] - b[:2]) < 1e-10 and abs(a[2] - b[2]) == pytest.approx(12):
                fillet.Add(2, edge)
        fillet.Build()
        assert fillet.IsDone()
        cutter = fillet.Shape()
    cut = BRepAlgoAPI_Cut(stock, cutter)
    cut.Build()
    assert cut.IsDone()
    return cut.Shape()


def _floor(result, expected_center=(17, 13, 4)):
    matches = [face for face in result["features"] if face["kind"] == "plane"
               and np.allclose(face["centroid_mm"], expected_center, atol=1e-8)]
    assert len(matches) == 1
    return matches[0]


def test_rectangular_pocket_exports_actual_floor_and_trimmed_top(tmp_path):
    result = _convert(_pocket(), tmp_path)
    floor = _floor(result)
    assert floor["area_mm2"] == pytest.approx(18 * 12)
    assert floor["normal"] == pytest.approx([0, 0, 1])
    assert floor["boundary_status"] == "complete"
    assert floor["material_normal_confirmed"] is True
    assert len(floor["boundary_wires"]) == 1
    wire = floor["boundary_wires"][0]
    assert wire["outer"] and wire["closed"] and wire["ordered"]
    assert wire["total_edge_count"] == 4
    assert sorted(e["length_mm"] for e in wire["edges"]) == pytest.approx([12, 12, 18, 18])
    for index, edge in enumerate(wire["edges"]):
        assert edge["kind"] == "line"
        assert edge["end_mm"] == pytest.approx(wire["edges"][(index + 1) % 4]["start_mm"])
        assert len(edge["adjacent_faces"]) == 1
        adjacent = edge["adjacent_faces"][0]
        assert adjacent["kind"] == "plane"
        inward = np.asarray(floor["centroid_mm"]) - np.asarray(edge["midpoint_mm"])
        assert np.dot(adjacent["normal"], inward) > 0
        wall = next(f for f in result["features"] if f["face_id"] == adjacent["face_id"])
        wall_heights = [point[2] for w in wall["boundary_wires"] for e in w["edges"]
                        for point in (e["start_mm"], e["end_mm"])]
        assert min(wall_heights) == pytest.approx(4)
        assert max(wall_heights) == pytest.approx(12)
    top = next(f for f in result["features"] if f["kind"] == "plane"
               and f["normal"] == pytest.approx([0, 0, 1]) and f["centroid_mm"][2] == pytest.approx(12))
    assert top["area_mm2"] == pytest.approx(40 * 30 - 18 * 12)
    assert sorted(w["outer"] for w in top["boundary_wires"]) == [False, True]
    assert top["boundary_total_edge_count"] == 8


def test_rounded_pocket_keeps_arcs_and_true_trimmed_area(tmp_path):
    result = _convert(_pocket(rounded=True), tmp_path)
    floor = _floor(result)
    assert floor["area_mm2"] == pytest.approx(18 * 12 - (4 - math.pi) * 2**2, rel=1e-10)
    edges = floor["boundary_wires"][0]["edges"]
    assert len(edges) == 8
    arcs = [e for e in edges if e["kind"] == "circle"]
    assert len(arcs) == 4
    for arc in arcs:
        assert arc["radius_mm"] == pytest.approx(2)
        assert arc["sweep_rad"] == pytest.approx(math.pi / 2)
        assert arc["length_mm"] == pytest.approx(math.pi)
    assert sum(e["length_mm"] for e in edges) == pytest.approx(2 * (18 + 12) - 8 * 2 + 2 * math.pi * 2)
    # Radius belongs to an edge/analytic surface; no hole or pocket count is invented.
    assert "pocket_count" not in floor
    partial_cylinders = [f for f in result["features"] if f["kind"] == "cylinder"]
    assert len(partial_cylinders) == 4
    assert all(f["full_circumference"] is False for f in partial_cylinders)
    assert all(f["u_span_rad"] == pytest.approx(math.pi / 2) for f in partial_cylinders)


def test_rotated_translated_pocket_has_world_coordinates_and_same_lengths(tmp_path):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Trsf, gp_Ax1, gp_Dir, gp_Pnt, gp_Vec
    angle, axis = .713, np.asarray([1., 2., 3.]) / math.sqrt(14)
    translation = np.asarray([101., -71., 39.])
    skew = np.asarray([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
    rotation = np.eye(3) * math.cos(angle) + (1 - math.cos(angle)) * np.outer(axis, axis) + math.sin(angle) * skew
    transform = gp_Trsf()
    transform.SetRotation(gp_Ax1(gp_Pnt(), gp_Dir(*axis)), angle)
    transform.SetTranslationPart(gp_Vec(*translation))
    shape = BRepBuilderAPI_Transform(_pocket(), transform, True).Shape()
    result = _convert(shape, tmp_path)
    floor = _floor(result, rotation @ [17, 13, 4] + translation)
    assert floor["normal"] == pytest.approx(rotation @ [0, 0, 1], abs=1e-10)
    assert floor["area_mm2"] == pytest.approx(216)
    edges = floor["boundary_wires"][0]["edges"]
    expected_corners = [rotation @ p + translation for p in ([8, 7, 4], [26, 7, 4], [26, 19, 4], [8, 19, 4])]
    for edge in edges:
        assert any(np.allclose(edge["start_mm"], point, atol=1e-8) for point in expected_corners)
        assert np.dot(edge["adjacent_faces"][0]["normal"], np.asarray(floor["centroid_mm"]) - edge["midpoint_mm"]) > 0


@pytest.mark.parametrize("angle", [2 * math.pi, math.pi / 2])
def test_cylinder_axis_endpoints_and_angular_span_are_face_dimensions(tmp_path, angle):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    from OCP.gp import gp_Ax2, gp_Pnt, gp_Dir
    axis = np.asarray([1., 2., -2.]) / 3
    origin = np.asarray([15., 22., -9.])
    shape = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(*origin), gp_Dir(*axis)), 3, 8, angle).Shape()
    result = _convert(shape, tmp_path)
    cylinders = [f for f in result["features"] if f["kind"] == "cylinder"]
    assert len(cylinders) == 1
    cylinder = cylinders[0]
    assert cylinder["u_span_rad"] == pytest.approx(angle)
    assert cylinder["area_mm2"] == pytest.approx(3 * 8 * angle)
    assert cylinder["diameter_mm"] == pytest.approx(6)
    assert cylinder["axial_extent_mm"] == pytest.approx(8)
    assert cylinder["axis_endpoints_mm"] == pytest.approx(np.asarray([origin, origin + 8 * axis]))
    assert cylinder["full_circumference"] is (angle == 2 * math.pi)


def test_multiple_solids_keep_adjacency_in_same_body(tmp_path):
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    builder, compound = BRep_Builder(), TopoDS_Compound()
    builder.MakeCompound(compound)
    builder.Add(compound, _pocket())
    builder.Add(compound, BRepPrimAPI_MakeBox(gp_Pnt(60, 0, 0), 5, 6, 7).Shape())
    result = _convert(compound, tmp_path)
    lookup = {f["face_id"]: f for f in result["features"]}
    assert result["solid_count"] == 2
    for face in lookup.values():
        for wire in face.get("boundary_wires", []):
            for index, edge in enumerate(wire["edges"]):
                assert edge["end_mm"] == pytest.approx(wire["edges"][(index + 1) % len(wire["edges"])]["start_mm"])
                for adjacent in edge["adjacent_faces"]:
                    assert lookup[adjacent["face_id"]]["body_id"] == face["body_id"]
    assert _floor(result)["area_mm2"] == pytest.approx(216)


def test_surface_face_keeps_unconfirmed_material_side(tmp_path):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.gp import gp_Pln, gp_Pnt, gp_Dir
    face = BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(), gp_Dir(0, 0, 1)), 0, 10, 0, 20).Face()
    result = _convert(face, tmp_path)
    feature = result["features"][0]
    assert feature["area_mm2"] == pytest.approx(200)
    assert feature["boundary_status"] == "complete"
    assert feature["material_normal_confirmed"] is False
    assert all(e["adjacent_faces"] == [] for w in feature["boundary_wires"] for e in w["edges"])


def test_boundary_budget_does_not_report_truncated_loops_as_complete(monkeypatch):
    import amdfm.cad_features as module
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopoDS import TopoDS
    shape = BRepPrimAPI_MakeBox(2, 3, 4).Shape()
    face = TopoDS.Face_s(next(items(shape, TopAbs_FACE)))
    monkeypatch.setattr(module, "MAX_FACE_BOUNDARY_EDGES", 2)
    result = trimmed_analytic_face(face, BoundaryContext(shape, 0))
    assert result["area_mm2"] == pytest.approx(12)
    assert result["boundary_status"] == "partial"
    assert result["boundary_total_edge_count"] == 4
    wire = result["boundary_wires"][0]
    assert len(wire["edges"]) == 2
    assert wire["unresolved_edge_count"] == 2
    assert wire["ordered"] is False


def test_boundary_budget_is_shared_across_solids(tmp_path, monkeypatch):
    import amdfm.cad_features as module
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    builder, compound = BRep_Builder(), TopoDS_Compound()
    builder.MakeCompound(compound)
    builder.Add(compound, BRepPrimAPI_MakeBox(2, 3, 4).Shape())
    builder.Add(compound, BRepPrimAPI_MakeBox(gp_Pnt(10, 0, 0), 2, 3, 4).Shape())
    monkeypatch.setattr(module, "MAX_MODEL_BOUNDARY_EDGES", 5)
    result = _convert(compound, tmp_path)
    assert result["analytic_boundary_geometry"]["processed_edges"] == 5
    assert result["cad_face_count"] == 12
    assert all(f["boundary_status"] == "partial" for f in result["features"] if f["body_id"] == 2)
    assert sum(len(w["edges"]) for f in result["features"] for w in f["boundary_wires"]) == 5


def test_extraction_leaves_brep_dimensions_and_orientation_unchanged():
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopoDS import TopoDS
    shape = _pocket(rounded=True)
    before = integrated_properties(shape)
    faces = [TopoDS.Face_s(f) for f in items(shape, TopAbs_FACE)]
    orientations = [face.Orientation() for face in faces]
    context = BoundaryContext(shape, 0)
    for face in faces:
        trimmed_analytic_face(face, context)
    after = integrated_properties(shape)
    assert after == before
    assert [face.Orientation() for face in faces] == orientations
