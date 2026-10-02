"""Independent geometry contracts for arbitrary build directions and detail placement."""
import copy
import math

import numpy as np
import pytest
from scipy.spatial.transform import Rotation
import trimesh

from amdfm.analysis import review
from amdfm.detail import attach_detail, run_detail
from amdfm.models import Model
from amdfm.profiles import Profile


def model_from_mesh(mesh):
    # Keep double precision here: binary STL serialization itself rounds vertices.
    return Model(mesh, {"source_format":"stl", "unit_status":"confirmed",
                       "surface_component_count":1, "filename":"analytic-box.stl"})


def rotated_slab():
    slab = trimesh.creation.box(extents=[10.,5.,1.])
    rotation = Rotation.from_rotvec([.31,-.72,.18]).as_matrix()
    mesh = trimesh.Trimesh(vertices=slab.vertices@rotation.T+[120.,-340.,100.],
                           faces=slab.faces.copy(), process=False)
    return model_from_mesh(mesh), rotation@[0.,0.,1.]


@pytest.mark.parametrize("scale", [1.,1e-300,1e300])
def test_rotated_translated_slab_has_same_physical_layers_at_any_vector_scale(scale):
    model,direction = rotated_slab()
    profile = Profile(layer_height_mm=.2)
    report = review(model,profile,direction*scale,compare=False)
    detail = run_detail(model,profile,direction*scale,mode="layers")
    assert detail["status"] == "complete"
    assert detail["coordinate_frame"] == "build_mm"
    assert detail["direction"] == pytest.approx(direction,abs=1e-14)
    assert np.asarray(detail["placement_transform"]) == pytest.approx(
        np.asarray(report["current_orientation"]["transform"]),abs=1e-10)
    assert detail["expected_layers"] == 5
    assert [row["z_mm"] for row in detail["layers"]] == pytest.approx(
        [.1,.3,.5,.7,.9],abs=1e-10)
    assert [row["area_mm2"] for row in detail["layers"]] == pytest.approx([50.]*5,abs=1e-7)
    assert detail["volume_estimate_mm3"] == pytest.approx(50.,abs=1e-7)
    assert attach_detail(report,detail)["details"]["layers"]["status"] == "complete"


def test_detail_uses_the_final_yaw_for_build_fit():
    model = model_from_mesh(trimesh.creation.box(extents=[8.,3.,1.]))
    profile = Profile(build_volume_mm=(4.,10.,2.),layer_height_mm=.2)
    report = review(model,profile,compare=False)
    detail = run_detail(model,profile,mode="layers")
    assert report["current_orientation"]["xy_yaw_deg"] == 90
    assert report["current_orientation"]["build_fit"] is True
    matrix = np.asarray(detail["placement_transform"])
    placed = model.mesh.vertices@matrix[:3,:3].T+matrix[:3,3]
    assert np.ptp(placed,axis=0) == pytest.approx([3.,8.,1.],abs=1e-12)
    assert placed[:,2].min() == pytest.approx(0.,abs=1e-12)
    assert detail["layers"][0]["z_mm"] == pytest.approx(.1,abs=1e-12)
    assert detail["volume_estimate_mm3"] == pytest.approx(24.,abs=1e-7)
    assert attach_detail(report,detail)["details"]["layers"]["status"] == "complete"


def test_near_axis_tilt_is_not_silently_replaced_by_z():
    # 1e-8 radians looks negligible but raises this long plate by .01 mm,
    # changing the requested layer count. This caught legacy allclose(+Z).
    dimensions = np.array([1e6,2.,.4])
    model = model_from_mesh(trimesh.creation.box(extents=dimensions))
    direction = np.array([1e-8,0.,1.])
    expected_height = float(dimensions@np.abs(direction/np.linalg.norm(direction)))
    profile = Profile(layer_height_mm=.2)
    detail = run_detail(model,profile,direction,mode="layers")
    assert detail["expected_layers"] == math.ceil(expected_height/.2) == 3
    assert detail["examined_layers"] == 3
    assert sum(row["thickness_mm"] for row in detail["layers"]) == pytest.approx(expected_height,abs=1e-9)


def test_changed_placement_is_rejected_even_when_axis_is_the_same():
    model,direction = rotated_slab()
    profile = Profile()
    report = review(model,profile,direction,compare=False)
    detail = run_detail(model,profile,direction,mode="layers")
    changed = copy.deepcopy(detail)
    changed["placement_transform"][0][3] += 1.
    with pytest.raises(ValueError,match="배치"):
        attach_detail(report,changed)


def test_non_mex_scope_still_retains_the_direction_and_placement_contract():
    model,direction = rotated_slab()
    profile = Profile(process="PBF_POLYMER")
    report = review(model,profile,direction,compare=False)
    detail = run_detail(model,profile,direction,mode="layers")
    assert detail["status"] == "not_applicable"
    assert "layers" not in detail and "volume_estimate_mm3" not in detail
    assert attach_detail(report,detail)["details"]["layers"]["status"] == "not_applicable"
