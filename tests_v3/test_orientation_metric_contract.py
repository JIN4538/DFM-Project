"""Independent counterexamples for the meaning of contact and angle boundaries."""
from math import radians, sin, sqrt

import numpy as np
import pytest
import trimesh

from amdfm.analysis import review
from amdfm.io import load_model
from amdfm.orientation import direction_from_angles, measure_orientation
from amdfm.profiles import Profile


def wedge():
    # 10 mm rise over 10 mm run, 5 mm breadth: slope is exactly 45 degrees,
    # area 50*sqrt(2), projected area 50. The separate horizontal base is 25.
    vertices = np.array([[0, 0, 0], [5, 0, 0], [15, 0, 10], [0, 0, 10],
                         [0, 5, 0], [5, 5, 0], [15, 5, 10], [0, 5, 10]])
    return trimesh.convex.convex_hull(vertices)


@pytest.mark.parametrize("scale", [.01, 1., 1000.])
def test_tiny_real_tilt_keeps_zero_plane_contact_and_explains_touching_faces(scale):
    mesh = trimesh.creation.box(extents=np.array([40., 40., 10.]) * scale)
    horizontal = measure_orientation(mesh, [0, 0, 1], Profile())
    result = measure_orientation(mesh, direction_from_angles(.001, 0), Profile())
    assert horizontal["contact_triangle_area_mm2"] == pytest.approx(1600 * scale**2)
    assert horizontal["contact_nonplanar_bottom_face_count"] == 0
    assert result["contact_triangle_area_mm2"] == 0
    assert result["contact_nonplanar_bottom_face_count"] > 0
    assert result["contact_nonplanar_bottom_min_tilt_deg"] == pytest.approx(.001, abs=1e-12)
    assert result["contact_nonplanar_bottom_max_height_mm"] >= 40 * scale * sin(radians(.001))
    assert result["contact_plate_tolerance_mm"] == pytest.approx(max(1e-9, 40 * scale * 1e-10), rel=5e-6)
    # Contact is geometric and must not depend on a chosen printer layer height.
    coarse = measure_orientation(mesh, direction_from_angles(.001, 0), Profile(layer_height_mm=1.))
    assert coarse["contact_triangle_area_mm2"] == result["contact_triangle_area_mm2"]
    assert coarse["contact_nonplanar_bottom_min_tilt_deg"] == result["contact_nonplanar_bottom_min_tilt_deg"]


@pytest.mark.parametrize("noise, expected_contact", [(1e-9, 1600.), (1e-7, 0.)])
def test_nonplanar_bottom_noise_is_not_mislabeled_as_first_layer_area(noise, expected_contact):
    mesh = trimesh.creation.box(extents=[40, 40, 10])
    vertices = mesh.vertices.copy()
    bottom = vertices[:, 2] < 0
    vertices[bottom, 2] += np.arange(bottom.sum()) * noise
    mesh.vertices = vertices
    result = measure_orientation(mesh, [0, 0, 1], Profile())
    assert result["contact_triangle_area_mm2"] == pytest.approx(expected_contact)
    assert bool(result["contact_nonplanar_bottom_face_count"]) is (expected_contact == 0)
    assert result["contact_plate_tolerance_mm"] == pytest.approx(4e-9)
    assert "not first-layer" in result["contact_scope"]


@pytest.mark.parametrize("threshold, expected_projection, expected_boundary_count", [
    (44.99, 0., 0), (45., 0., 2), (45.01, 50., 0),
])
def test_exact_and_near_angle_thresholds_remain_distinct(threshold, expected_projection, expected_boundary_count):
    result = measure_orientation(wedge(), [0, 0, 1], Profile(overhang_angle_deg=threshold))
    assert result["contact_triangle_area_mm2"] == pytest.approx(25.)
    assert result["overhang_projected_area_sum_mm2"] == pytest.approx(expected_projection)
    assert result["overhang_threshold_equal_face_count"] == expected_boundary_count
    assert result["overhang_threshold_equal_surface_area_mm2"] == pytest.approx(50 * sqrt(2) if expected_boundary_count else 0.)
    assert result["overhang_threshold_equal_projected_area_sum_mm2"] == pytest.approx(50 if expected_boundary_count else 0.)
    assert result["overhang_threshold_cosine_tolerance"] == 1e-12
    low, high = result["overhang_threshold_equal_angle_range_deg"]
    assert low < threshold < high
    assert high - low < 2e-10


@pytest.mark.parametrize("delta_deg, boundary_count, area", [
    (-1e-11, 2, 0.), (1e-11, 2, 0.), (-1e-8, 0, 0.), (1e-8, 0, 50.),
])
def test_documented_numerical_band_is_excluded_on_both_sides(delta_deg, boundary_count, area):
    result = measure_orientation(wedge(), [0, 0, 1], Profile(overhang_angle_deg=45 + delta_deg))
    assert result["overhang_threshold_equal_face_count"] == boundary_count
    assert result["overhang_projected_area_sum_mm2"] == pytest.approx(area)


@pytest.mark.parametrize("process,reliable", [("MEX", False), ("PBF_POLYMER", True)])
def test_missing_and_inapplicable_angle_data_are_not_zero(process, reliable):
    result = measure_orientation(wedge(), [0, 0, 1], Profile(process=process), reliable_normals=reliable)
    assert result["overhang_threshold_equal_face_count"] is None
    assert result["overhang_threshold_equal_surface_area_mm2"] is None
    assert result["overhang_threshold_equal_projected_area_sum_mm2"] is None
    if not reliable:
        assert result["contact_nonplanar_bottom_face_count"] is None
        assert result["contact_nonplanar_bottom_min_tilt_deg"] is None
        assert result["contact_nonplanar_bottom_max_height_mm"] is None


def test_angle_boundary_explanation_reaches_findings_without_becoming_failure():
    model = load_model(wedge().export(file_type="stl"), "45-degree-wedge.stl", dimensions_confirmed=True)
    report = review(model, Profile(), compare=False)
    finding = next(f for f in report["findings"] if f["id"] == "overhang")
    assert finding["status"] == "not_detected"
    assert finding["measurements"]["threshold_equal_face_count"] == 2
    assert "수치 허용차 내" in finding["reason"]
    assert "출력 가능 여부는 판정하지 않습니다" in finding["reason"]


def test_tiny_tilt_explanation_reaches_findings_without_invented_adhesion_failure():
    mesh = trimesh.creation.box(extents=[40, 40, 10])
    model = load_model(mesh.export(file_type="stl"), "tilted.stl", dimensions_confirmed=True)
    report = review(model, Profile(), direction_from_angles(.001, 0), compare=False)
    finding = next(f for f in report["findings"] if f["id"] == "contact")
    assert finding["measurements"]["area_mm2"] == 0
    assert finding["measurements"]["nonplanar_bottom_min_tilt_deg"] == pytest.approx(.001)
    assert "출력 불가를 뜻하지 않습니다" in finding["reason"]
    assert "슬라이서 첫 층" in finding["action"]


def test_first_layer_triangle_selection_would_miss_crossing_triangles():
    # Proposed zmax <= layer_height/2 excludes the whole sloped underside,
    # although the actual z=0.1 section has area (5+0.1)*5 = 25.5 mm².
    # This independent section is why geometric contact must not be renamed.
    mesh = wedge()
    path = mesh.section(plane_origin=[0, 0, .1], plane_normal=[0, 0, 1])
    # This convex prism's section is an axis-aligned rectangle, so its two
    # spans give the area without a second polygon assembly implementation.
    section_area = float(np.prod(np.ptp(path.vertices[:, :2], axis=0)))
    result = measure_orientation(mesh, [0, 0, 1], Profile(layer_height_mm=.2))
    assert section_area == pytest.approx(25.5)
    assert result["contact_triangle_area_mm2"] == pytest.approx(25.)
    assert section_area != result["contact_triangle_area_mm2"]
