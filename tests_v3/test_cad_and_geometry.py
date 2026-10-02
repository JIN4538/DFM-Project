from pathlib import Path
import json
import math

import numpy as np
import pytest
import trimesh

from amdfm.analysis import review
from amdfm.detail_worker import normal_chords
from amdfm.io import load_model
from amdfm.orientation import measure_orientation, compare_orientations
from amdfm.profiles import Profile
from src.core.mesh_diagnostics import inspect_mesh

CAD=Path(__file__).resolve().parents[1]/"examples/cad"
MANIFEST=json.loads((CAD/"manifest.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def models():
    return {c["id"]:load_model((CAD/c["file"]).read_bytes(),c["file"]) for c in MANIFEST}


@pytest.mark.parametrize("case",MANIFEST,ids=lambda x:x["id"])
def test_cad_against_independent_analytic_oracle(models,case):
    model=models[case["id"]]
    expected=case["expected"]
    meta=model.metadata
    if "volume_mm3" in expected:
        assert meta["exact_volume_mm3"]==pytest.approx(expected["volume_mm3"],rel=1e-9)
    if "extents_mm" in expected:
        assert model.mesh.extents==pytest.approx(expected["extents_mm"],abs=.001)
    if "exact_area_mm2" in expected:
        assert meta["exact_area_mm2"]==pytest.approx(expected["exact_area_mm2"],rel=1e-9)
    if "internal_shell_count" in expected:
        assert meta["cavity_shell_count"]==expected["internal_shell_count"]
    if "hole_diameter_mm" in expected:
        holes=[f for f in model.cad_features if f["kind"]=="cylinder" and f["role"]=="inner"]
        assert len(holes)==1
        assert holes[0]["diameter_mm"]==pytest.approx(expected["hole_diameter_mm"],abs=1e-10)
        assert abs(np.dot(holes[0]["axis"],expected["hole_axis"]))==pytest.approx(1)
    if "outer_diameter_mm" in expected:
        outer=[f for f in model.cad_features if f["kind"]=="cylinder" and f["role"]=="outer"]
        assert any(f["diameter_mm"]==pytest.approx(expected["outer_diameter_mm"],abs=1e-9) for f in outer)
    if "unsupported_horizontal_projection_mm2" in expected:
        measured=measure_orientation(model.mesh,(0,0,1),Profile())
        assert measured["overhang_projected_area_sum_mm2"]==pytest.approx(expected["unsupported_horizontal_projection_mm2"],abs=1e-7)
    assert len(model.face_ids)==len(model.mesh.faces)
    assert set(model.face_ids)<=set(f["face_id"] for f in model.cad_features)
    assert inspect_mesh(model.mesh)["topology_ready"]


def test_inch_step_is_normalized_once(models):
    model=models["10_inch_box"]
    assert any("inch" in u.lower() for u in model.metadata["declared_step_units"])
    assert model.mesh.extents==pytest.approx([25.4]*3,abs=1e-9)


def test_separate_solids_never_invent_assembly_union_volume(models):
    assembly=models["11_two_bodies"]
    assert assembly.metadata["solid_count"]==2
    assert assembly.metadata["exact_volume_mm3"] is None
    assert review(assembly,Profile())["geometry"]["mesh_signed_volume_mm3"] is None
    for body in (1,2):
        part=assembly.select_body(body)
        assert part.metadata["exact_volume_mm3"]==pytest.approx(1000)
        assert part.mesh.volume==pytest.approx(1000)
        assert part.mesh.extents==pytest.approx([10]*3)
        assert all(f["body_id"]==body for f in part.cad_features)
        assert part.fingerprint!=assembly.fingerprint


@pytest.mark.parametrize("name,expected",[("01_box",10),("02_thin_plate",.3),("14_thin_plate_improved",1.2)])
def test_normal_chords_parallel_planes(models,name,expected):
    result=normal_chords(models[name].mesh,.4)
    assert result["status"]=="measured"
    assert result["measurements"]["minimum_mm"]==pytest.approx(expected,abs=1e-8)
    assert bool(result["measurements"]["below_limit_face_indices"])==(expected<.4)


def test_surface_angle_definition_and_bottom_exclusion(models):
    r=measure_orientation(models["01_box"].mesh,(0,0,1),Profile())
    assert r["overhang_projected_area_sum_mm2"]==0
    assert r["contact_triangle_area_mm2"]==pytest.approx(200)
    # A triangular wedge with a sloped underside exactly 45 degrees.
    v=np.array([[0,0,0],[5,0,0],[15,0,10],[0,0,10],[0,5,0],[5,5,0],[15,5,10],[0,5,10]])
    hull=trimesh.convex.convex_hull(v)
    assert measure_orientation(hull,(0,0,1),Profile(overhang_angle_deg=44))["overhang_projected_area_sum_mm2"]==0
    assert measure_orientation(hull,(0,0,1),Profile(overhang_angle_deg=46))["overhang_projected_area_sum_mm2"]==pytest.approx(50)


def test_yaw_fit_agrees_with_export_transform():
    mesh=trimesh.creation.box(extents=[180,80,20])
    p=Profile(build_volume_mm=(100,200,100))
    r=measure_orientation(mesh,(0,0,1),p)
    assert r["build_fit"] is True and r["xy_yaw_deg"]==90
    transformed=mesh.copy()
    transformed.apply_transform(r["transform"])
    assert transformed.extents==pytest.approx([80,180,20])
    assert transformed.bounds[0,2]==pytest.approx(0)


def test_translation_tessellation_and_face_order_invariance(models):
    original=models["09_cantilever"].mesh
    baseline=measure_orientation(original,(0,0,1),Profile())
    variants=[original.copy(),original.subdivide(),original.copy()]
    variants[0].apply_translation([101,-87,43])
    variants[2].faces=variants[2].faces[::-1]
    for mesh in variants:
        r=measure_orientation(mesh,(0,0,1),Profile())
        for k in ("overhang_projected_area_sum_mm2","contact_triangle_area_mm2","height_mm"):
            assert r[k]==pytest.approx(baseline[k],abs=1e-7)


def test_rotating_model_and_direction_preserves_geometry(models):
    model=models["09_cantilever"].mesh.copy()
    rotation=trimesh.transformations.rotation_matrix(.831,[1,2,3])
    baseline=measure_orientation(model,(0,0,1),Profile())
    model.apply_transform(rotation)
    r=measure_orientation(model,rotation[:3,:3]@[0,0,1],Profile())
    assert r["overhang_projected_area_sum_mm2"]==pytest.approx(baseline["overhang_projected_area_sum_mm2"],abs=1e-6)
    assert r["height_mm"]==pytest.approx(baseline["height_mm"],abs=1e-6)


def test_process_applicability_and_no_success_score(models):
    for process in ("MEX","VPP","PBF_POLYMER","PBF_METAL"):
        report=review(models["08_bridge"],Profile(process=process))
        assert not any(k in report for k in ("score","grade","success_probability"))
        overhang=next(f for f in report["findings"] if f["id"]=="overhang")
        if process=="PBF_POLYMER":
            assert overhang["status"]=="not_applicable"
            assert all(r["overhang_projected_area_sum_mm2"] is None for r in report["orientations"])
        else:
            assert overhang["status"]=="attention"


def test_pareto_does_not_recommend_infeasible_fit(models):
    rows=compare_orientations(models["01_box"].mesh,Profile(build_volume_mm=(21,31,11)))
    assert any(r["pareto"] for r in rows)
    assert all(not r["pareto"] for r in rows if r["build_fit"] is False)


def test_horizontal_hole_support_group_is_process_specific(models):
    model=models["04_horizontal_hole"]
    for process,expected in (("MEX","attention"),("PBF_POLYMER","observed")):
        report=review(model,Profile(process=process))
        hole=next(f for f in report["findings"] if f["id"]=="cad_holes")
        assert hole["measurements"]["transverse_inner_face_count"]==1
        assert hole["status"]==expected
    small=review(model,Profile(process="PBF_POLYMER",minimum_hole_mm=7))
    assert next(f for f in small["findings"] if f["id"]=="cad_holes")["status"]=="attention"


@pytest.mark.parametrize("kwargs",[{"layer_height_mm":float("nan")},{"overhang_angle_deg":0},
    {"minimum_wall_mm":-1},{"build_volume_mm":(10,10,-1)},{"line_width_mm":float("inf")},
    {"build_volume_mm":(10,10,10),"clearance_mm":5}])
def test_invalid_profiles_fail_explicitly(kwargs):
    with pytest.raises(ValueError):Profile(**kwargs).validate()
