import math
import numpy as np
import pytest
from dfm.cad_edit_pairs import round_corners, bounds
from dfm.cad_graph import extract_graph
from dfm.external_features_review import pocket_dimensions


def cavity(sides):
    from OCP.gp import gp_Pnt, gp_Vec
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakePrism
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    polygon = BRepBuilderAPI_MakePolygon()
    for i in range(sides):
        angle = 2*math.pi*i/sides
        polygon.Add(gp_Pnt(25+10*math.cos(angle), 30+10*math.sin(angle), 14))
    polygon.Close()
    tool = BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(polygon.Wire()).Face(), gp_Vec(0, 0, 10)).Shape()
    shape = BRepAlgoAPI_Cut(BRepPrimAPI_MakeBox(50., 60., 20.).Shape(), tool).Shape()
    graph = extract_graph(shape)
    faces = [m for m in graph['measurements'] if abs(m['centroid_mm'][2]-14) < 1e-7 or abs(m['centroid_mm'][2]-17) < 1e-7]
    candidate = dict(feature={3:'triangular_pocket',4:'rectangular_pocket',6:'6sides_pocket'}[sides],
        face_ids=[m['face_id'] for m in faces], measured_faces=faces)
    pocket = pocket_dimensions(candidate, [0, 0, 1])
    assert pocket is not None
    pocket['direction'] = [0, 0, 1]
    return shape, pocket


@pytest.mark.parametrize('sides,constant', [(3, 3*math.sqrt(3)-math.pi), (4, 4-math.pi), (6, 2*math.sqrt(3)-math.pi)])
def test_actual_before_after_cad_material_matches_independent_prism_formula(sides, constant):
    shape, pocket = cavity(sides)
    before_bounds = bounds(shape)
    after, meta = round_corners(shape, pocket, 1.)
    assert meta['modified_corner_edges'] == sides
    assert meta['measured_material_addition_mm3'] == pytest.approx(constant*6, abs=1e-6)
    expected_before = 50*60*20 - sides*.5*100*math.sin(2*math.pi/sides)*6
    assert meta['before_volume_mm3'] == pytest.approx(expected_before, abs=1e-6)
    assert bounds(shape) == pytest.approx(before_bounds)
    assert bounds(after) == pytest.approx(before_bounds)


def test_incomplete_face_group_and_excessive_radius_are_rejected():
    shape, pocket = cavity(4)
    broken = dict(pocket, face_ids=pocket['face_ids'][:-1])
    with pytest.raises(ValueError):
        round_corners(shape, broken, 1.)
    with pytest.raises(ValueError):
        round_corners(shape, pocket, pocket['entry_circle_diameter_mm'])
