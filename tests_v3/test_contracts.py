import copy
import json
from pathlib import Path
import subprocess
from unittest.mock import patch

import numpy as np
import pytest
import trimesh

from amdfm.analysis import review
from amdfm.detail import attach_detail, run_detail
from amdfm.io import load_model
from amdfm.models import Model, json_bytes
from amdfm.presentation import html_report, placed_stl
from amdfm.profiles import Profile


def box_model():
    return load_model(trimesh.creation.box(extents=[10,20,30]).export(file_type="stl"),"box.stl",dimensions_confirmed=True)


def test_stl_units_and_scale_assumptions():
    data=trimesh.creation.box(extents=[1,2,3]).export(file_type="stl")
    a=load_model(data,"a.stl",unit="inch")
    assert a.metadata["unit_status"]=="assumed"
    assert a.mesh.extents==pytest.approx([25.4,50.8,76.2])
    b=load_model(data,"a.stl",target_longest_mm=60,dimensions_confirmed=True)
    assert b.mesh.extents==pytest.approx([20,40,60])
    assert b.metadata["source_sha256"]==a.metadata["source_sha256"]
    assert b.fingerprint!=a.fingerprint
    assert next(f for f in review(a,Profile())["findings"] if f["id"]=="scale")["status"]=="attention"


def test_nonfinite_empty_and_bad_inputs_are_rejected():
    for data,name in [(b"","x.stl"),(b"bad file","x.stl"),(b"anything","x.obj")]:
        with pytest.raises(ValueError):load_model(data,name)
    with pytest.raises(ValueError):load_model(b"invalid STEP","x.step")
    mesh=trimesh.creation.box()
    mesh.vertices[0,0]=np.nan
    with pytest.raises(ValueError):load_model(mesh.export(file_type="stl"),"x.stl")


def test_corrupted_mesh_never_becomes_clear_or_volume_zero():
    mesh=trimesh.creation.box()
    mesh.update_faces(np.arange(11))
    model=load_model(mesh.export(file_type="stl"),"open.stl")
    original=model.mesh.vertices.copy(),model.mesh.faces.copy()
    report=review(model,Profile())
    assert report["summary"]["review_status"]=="partial_geometry"
    assert report["geometry"]["mesh_signed_volume_mm3"] is None
    overhang=next(f for f in report["findings"] if f["id"]=="overhang")
    assert overhang["status"]=="unknown"
    assert overhang["measurements"]["projected_area_sum_mm2"] is None
    assert np.array_equal(model.mesh.vertices,original[0]) and np.array_equal(model.mesh.faces,original[1])


def test_detail_identity_profile_and_direction_guard():
    model=box_model()
    report=review(model,Profile())
    with pytest.raises(ValueError):attach_detail(report,{"fingerprint":"wrong"})
    detail={"fingerprint":model.fingerprint,"profile":{**report["profile"],"machine":"different"}}
    with pytest.raises(ValueError):attach_detail(report,detail)
    detail={"fingerprint":model.fingerprint,"direction":[1,0,0]}
    with pytest.raises(ValueError):attach_detail(report,detail)


@pytest.mark.parametrize("failure",[subprocess.TimeoutExpired("worker",.01),OSError("worker isolation failed")])
def test_worker_failure_is_unknown_and_preserves_quick_report(failure):
    model=box_model()
    report=review(model,Profile())
    with patch("amdfm.detail.run_bounded",side_effect=failure):
        detail=run_detail(model,Profile(),timeout_s=.01)
    merged=attach_detail(report,detail)
    assert next(f for f in merged["findings"] if f["id"]=="wall")["status"]=="unknown"
    assert merged["geometry"]==report["geometry"]
    assert "details" not in report


def test_cad_worker_launch_failure_is_an_explained_input_error():
    with patch("amdfm.io.run_bounded",side_effect=OSError("worker isolation failed")):
        with pytest.raises(ValueError,match="worker isolation failed"):
            load_model(b"input reaches the isolated worker","part.step")


def test_detail_worker_end_to_end_and_layer_volume():
    model=load_model(trimesh.creation.box(extents=[10,5,1]).export(file_type="stl"),"slab.stl",dimensions_confirmed=True)
    profile=Profile(minimum_wall_mm=1.2,layer_height_mm=.2)
    wall=run_detail(model,profile,mode="wall")
    assert wall["measurements"]["minimum_mm"]==pytest.approx(1.)
    attached=attach_detail(review(model,profile),wall)
    assert next(f for f in attached["findings"] if f["id"]=="wall")["status"]=="attention"
    layers=run_detail(model,profile,mode="layers")
    assert layers["status"]=="complete"
    assert layers["expected_layers"]==5
    assert layers["volume_estimate_mm3"]==pytest.approx(50,abs=1e-7)
    assert all(r["unsupported_area_mm2"]==0 for r in layers["layers"])


def test_failed_repeat_clears_stale_wall_measurement():
    model=box_model()
    profile=Profile()
    measured=attach_detail(review(model,profile),run_detail(model,profile))
    assert next(f for f in measured["findings"] if f["id"]=="wall")["measurements"]
    failed={"mode":"wall","status":"unknown","fingerprint":model.fingerprint,"reason":"timeout"}
    report=attach_detail(measured,failed)
    wall=next(f for f in report["findings"] if f["id"]=="wall")
    assert wall["status"]=="unknown" and wall["measurements"]=={} and wall["face_indices"]==[]


def test_overlapping_stl_components_do_not_imply_material_union():
    left=trimesh.creation.box(extents=[10]*3)
    right=left.copy()
    right.apply_translation([5,0,0])
    model=load_model(trimesh.util.concatenate([left,right]).export(file_type="stl"),"overlap.stl",dimensions_confirmed=True)
    assert model.metadata["surface_component_count"]==2
    report=review(model,Profile())
    assert report["geometry"]["mesh_signed_volume_mm3"] is None
    assert next(f for f in report["findings"] if f["id"]=="shells")["status"]=="attention"
    for mode in ("wall","layers"):
        assert run_detail(model,Profile(),mode=mode)["status"]=="unknown"


def test_layer_budget_is_not_silent_subsampling():
    model=box_model()
    result=run_detail(model,Profile(layer_height_mm=.005),mode="layers")
    assert result["status"]=="unavailable"
    assert result["expected_layers"]==6000
    assert result["examined_layers"]==0


def test_exports_are_strict_safe_reproducible_and_same_placement():
    model=box_model()
    profile=Profile(machine='<img src=x onerror="alert(1)">')
    report=review(model,profile,(1,0,0))
    payload=json.loads(json_bytes(report))
    assert payload["model"]["source_sha256"]==model.metadata["source_sha256"]
    assert json.loads(json_bytes({"x":np.nan}))=={"x":None}
    html=html_report(report).decode()
    assert "<img src=x" not in html and "&lt;img src=x" in html
    assert "<script" not in html
    stl=placed_stl(model,report)
    oriented=load_model(stl,"placed.stl",dimensions_confirmed=True)
    assert oriented.mesh.extents[2]==pytest.approx(10)
    assert oriented.mesh.bounds[0,2]==pytest.approx(0)
    assert oriented.mesh.volume==pytest.approx(model.mesh.volume,rel=1e-6)
