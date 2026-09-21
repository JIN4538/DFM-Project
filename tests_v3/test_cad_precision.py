"""Analytic integral and deliberately non-solid STEP counterexamples."""
import json
import math

import numpy as np
import pytest

from amdfm.cad_worker import convert, integrated_properties, zero_parameter_area, items, mesh_topology, prepare_tessellation


def write_step(shape, path):
    from OCP.STEPControl import STEPControl_Writer, STEPControl_AsIs
    from OCP.IFSelect import IFSelect_RetDone
    writer = STEPControl_Writer()
    assert writer.Transfer(shape, STEPControl_AsIs) == IFSelect_RetDone
    assert writer.Write(str(path)) == IFSelect_RetDone


def test_bezier_prism_volume_against_polynomial_integral():
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge, BRepBuilderAPI_MakeWire, BRepBuilderAPI_MakeFace
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.Geom import Geom_BezierCurve
    from OCP.TColgp import TColgp_Array1OfPnt
    from OCP.gp import gp_Pnt, gp_Vec
    # x(t)=L*t, y(t)=3*H*t*(1-t), so integral y dx = L*H/2.
    length, height, depth = 17., 6., 4.
    poles = TColgp_Array1OfPnt(1, 4)
    for i, xyz in enumerate([(0,0,0), (length/3,height,0), (2*length/3,height,0), (length,0,0)], 1):
        poles.SetValue(i, gp_Pnt(*xyz))
    curve = BRepBuilderAPI_MakeEdge(Geom_BezierCurve(poles)).Edge()
    base = BRepBuilderAPI_MakeEdge(gp_Pnt(length,0,0), gp_Pnt(0,0,0)).Edge()
    wire = BRepBuilderAPI_MakeWire(curve, base).Wire()
    face = BRepBuilderAPI_MakeFace(wire).Face()
    prism = BRepPrimAPI_MakePrism(face, gp_Vec(0,0,depth)).Shape()
    result = integrated_properties(prism)
    assert result["volume_mm3"] == pytest.approx(length*height*depth/2, rel=1e-10)
    assert result["integration"]["volume_relative_error_estimate"] <= 1e-8


def test_sphere_area_and_volume_use_independent_analytic_values():
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeSphere
    r = 7.25
    result = integrated_properties(BRepPrimAPI_MakeSphere(r).Shape())
    assert result["volume_mm3"] == pytest.approx(4*math.pi*r**3/3, rel=1e-10)
    assert result["area_mm2"] == pytest.approx(4*math.pi*r*r, rel=1e-10)


def test_reversed_solid_does_not_get_positive_volume_invented():
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    shape = BRepPrimAPI_MakeBox(1,2,3).Shape()
    shape.Reverse()
    with pytest.raises(ValueError, match="체적"):
        integrated_properties(shape)


def test_open_planar_step_preserves_faces_without_inventing_solid(tmp_path):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.gp import gp_Pln, gp_Pnt, gp_Dir
    face = BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(0,0,0), gp_Dir(0,0,1)), 0,10,0,20).Face()
    source, target = tmp_path/"plane.step", tmp_path/"plane_result"
    write_step(face, source)
    convert(source, target, .05)
    result = json.loads(target.with_suffix(".json").read_text(encoding="utf-8"))
    assert result["cad_geometry_kind"] == "surface"
    assert result["solid_count"] == 0
    assert result["bodies"] == []
    assert result["exact_volume_mm3"] is None
    assert result["constituent_volume_sum_mm3"] is None
    assert result["cavity_shell_count"] is None
    assert result["exact_area_mm2"] == pytest.approx(200)
    assert result["cad_face_count"] == 1
    with np.load(target.with_suffix(".npz")) as mesh:
        assert len(mesh["faces"]) == 2
        assert set(mesh["face_ids"]) == {1}
        assert set(mesh["body_ids"]) == {0}


def test_cylindrical_surface_does_not_invent_inner_material_side(tmp_path):
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.gp import gp_Cylinder, gp_Ax3
    face = BRepBuilderAPI_MakeFace(gp_Cylinder(gp_Ax3(), 3), 0, 2*math.pi, 0,5).Face()
    face.Reverse()
    source, target = tmp_path/"surface.step", tmp_path/"surface_result"
    write_step(face, source)
    convert(source, target, .05)
    result = json.loads(target.with_suffix(".json").read_text(encoding="utf-8"))
    assert result["exact_area_mm2"] == pytest.approx(2*math.pi*3*5)
    cylinders = [f for f in result["features"] if f["kind"] == "cylinder"]
    assert len(cylinders) == 1
    assert cylinders[0]["diameter_mm"] == pytest.approx(6)
    assert cylinders[0]["role"] == "unknown"


def test_mixed_solid_and_surface_is_not_silently_truncated(tmp_path):
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.gp import gp_Pln, gp_Pnt, gp_Dir
    compound, builder = TopoDS_Compound(), BRep_Builder()
    builder.MakeCompound(compound)
    builder.Add(compound, BRepPrimAPI_MakeBox(1,2,3).Shape())
    builder.Add(compound, BRepBuilderAPI_MakeFace(gp_Pln(gp_Pnt(0,0,10),gp_Dir(0,0,1)),0,5,0,5).Face())
    source = tmp_path/"mixed.step"
    write_step(compound, source)
    with pytest.raises(ValueError, match="독립 곡면"):
        convert(source, tmp_path/"mixed", .05)


def test_exactly_collapsed_trim_is_distinct_from_tiny_real_face():
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.gp import gp_Cylinder, gp_Ax3
    surface = gp_Cylinder(gp_Ax3(), 3)
    collapsed = BRepBuilderAPI_MakeFace(surface, .1,.2,4,4).Face()
    small = BRepBuilderAPI_MakeFace(surface, .1,.2,4,4.00001).Face()
    assert zero_parameter_area(collapsed)
    assert not zero_parameter_area(small)


def test_zero_trim_does_not_change_separate_integration_geometry():
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.gp import gp_Cylinder, gp_Ax3
    compound, builder = TopoDS_Compound(), BRep_Builder()
    builder.MakeCompound(compound)
    builder.Add(compound, BRepPrimAPI_MakeBox(1,2,3).Shape())
    builder.Add(compound, BRepBuilderAPI_MakeFace(gp_Cylinder(gp_Ax3(),3),.1,.2,4,4).Face())
    result = integrated_properties(compound)
    assert result["volume_mm3"] == pytest.approx(6)
    assert result["area_mm2"] == pytest.approx(22)
    assert result["integration"]["exactly_zero_parameter_area_faces_excluded"] == 1


def test_more_than_one_hundred_solids_keep_body_mapping(tmp_path):
    from OCP.BRep import BRep_Builder
    from OCP.TopoDS import TopoDS_Compound
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.gp import gp_Pnt
    compound, builder = TopoDS_Compound(), BRep_Builder()
    builder.MakeCompound(compound)
    for i in range(109):
        builder.Add(compound, BRepPrimAPI_MakeBox(gp_Pnt(2*i,0,0),1,1,1).Shape())
    source, target = tmp_path/"many.step", tmp_path/"many_result"
    write_step(compound, source)
    convert(source, target, .05)
    result = json.loads(target.with_suffix(".json").read_text(encoding="utf-8"))
    assert result["solid_count"] == 109
    assert len(result["bodies"]) == 109
    assert result["exact_volume_mm3"] is None
    assert result["constituent_volume_sum_mm3"] == pytest.approx(109)
    with np.load(target.with_suffix(".npz")) as mesh:
        assert set(mesh["body_ids"]) == set(range(1,110))


@pytest.mark.parametrize("budget,adopt", [(12,True), (11,False)])
def test_finer_tessellation_recovers_missing_cell_without_changing_source(budget, adopt):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.BRep import BRep_Tool
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS
    from OCP.Poly import Poly_Triangle
    shape = BRepPrimAPI_MakeBox(1,2,3).Shape()
    BRepMesh_IncrementalMesh(shape,.05,False,.15,False)
    original_faces = [TopoDS.Face_s(f) for f in items(shape,TopAbs_FACE)]
    tri = BRep_Tool.Triangulation_s(original_faces[0],TopLoc_Location())
    # Deliberately damage one cached tessellation cell while leaving B-rep intact.
    tri.SetTriangle(1,Poly_Triangle(1,1,1))
    assert mesh_topology(shape)["boundary_edges"] == 3
    candidate, record = prepare_tessellation(shape,.05,budget)
    assert record["adopted_refinement"] is adopt
    assert mesh_topology(shape)["boundary_edges"] == 3  # Source cache unchanged.
    if adopt:
        assert mesh_topology(candidate)["ready"]
        assert integrated_properties(candidate)["volume_mm3"] == pytest.approx(6)
        # Topological copy keeps face traversal order, so face IDs stay meaningful.
        old = [BRepAdaptor_Surface(f).Plane().Location().Coord() for f in original_faces]
        new = [BRepAdaptor_Surface(TopoDS.Face_s(f)).Plane().Location().Coord() for f in items(candidate,TopAbs_FACE)]
        np.testing.assert_allclose(old,new,atol=0,rtol=0)
    else:
        assert candidate.IsSame(shape)
        assert record["retry"]["not_adopted_reason"] == "triangle_budget"
