"""Analytic geometric counterexamples; these are not physical machining trials."""
from unittest.mock import patch
import json
import subprocess

import numpy as np
import pytest
import trimesh

from dfm.accessibility import inspect_point_visibility, run_point_visibility


def _box(lower, upper):
    lower, upper = np.asarray(lower, float), np.asarray(upper, float)
    mesh = trimesh.creation.box(extents=upper - lower)
    mesh.apply_translation((lower + upper) / 2)
    return mesh


def _c_shape(gap=6.):
    """C cross-section: two shelves separated by an externally open gap."""
    return trimesh.boolean.union([
        _box([0, 0, 0], [10, 4, 2]),
        _box([0, 0, 0], [2, 4, 4 + gap]),
        _box([0, 0, 2 + gap], [10, 4, 4 + gap]),
    ], engine="manifold")


def _state_area(result, state):
    return sum(r["area_weight_mm2"] for r in result["samples"] if r["state"] == state)


def test_cube_has_visible_top_back_facing_bottom_and_undecided_side_milling():
    mesh = trimesh.creation.box(extents=[10, 10, 10])
    r = inspect_point_visibility(mesh)
    assert r["status"] == "complete"
    assert r["measurements"]["sample_state_counts"] == {
        "visible": 2, "occluded": 0, "back_facing": 2, "tangent": 8, "unknown": 0}
    assert r["measurements"]["area_weighted_sample_fractions"] == pytest.approx({
        "visible": 1 / 6, "occluded": 0, "back_facing": 1 / 6, "tangent": 4 / 6, "unknown": 0})
    assert all(row["point_mm"][2] == pytest.approx(5) for row in r["samples"] if row["state"] == "visible")
    assert r["numerical_policy"]["source_offset_mm"] == 0
    assert r["method"] == "point_visibility"
    assert "success_probability" not in r and "machinable" not in r


def test_rectangular_box_uses_area_not_triangle_count():
    r = inspect_point_visibility(trimesh.creation.box(extents=[10, 20, 30]))
    assert _state_area(r, "visible") == pytest.approx(200)
    assert r["measurements"]["area_weighted_sample_fractions"]["visible"] == pytest.approx(200 / 2200)


def test_occluded_upward_floor_of_c_shape_is_detected_without_reversing_normals():
    mesh = _c_shape()
    r = inspect_point_visibility(mesh)
    assert r["status"] == "complete"
    # Analytic areas of the 10 x 4 roof and (10 - 2) x 4 inner floor.
    assert _state_area(r, "visible") == pytest.approx(40)
    assert _state_area(r, "occluded") == pytest.approx(32)
    assert not r["unknown_face_indices"]
    for row in r["samples"]:
        if row["state"] == "occluded":
            assert row["normal_dot_direction"] == pytest.approx(1)
            assert row["point_mm"][2] == pytest.approx(2)
            # Both the underside (z=8) and upper surface (z=10) are valid
            # blockage witnesses. A first hit on a triangulation edge may be
            # ambiguous; the API explicitly does not promise nearest clearance.
            assert min(abs(row["obstruction_distance_mm"] - x) for x in (6, 8)) < 1e-9
            assert row["obstruction_face"] != row["source_face"]


def test_near_roof_is_not_skipped_by_a_ray_origin_offset():
    mesh = _c_shape()
    # Keep exact float64 coordinates: a gap AND roof thinner than a typical
    # origin offset. Casting this fixture through manifold's float32 would
    # change the independent expected dimensions before the query.
    mesh.vertices[np.isclose(mesh.vertices[:, 2], 8), 2] = 2 + 1e-6
    mesh.vertices[np.isclose(mesh.vertices[:, 2], 10), 2] = 2 + 2e-6
    r = inspect_point_visibility(mesh)
    assert _state_area(r, "occluded") == pytest.approx(32)
    rows = [x for x in r["samples"] if x["state"] == "occluded"]
    assert rows and all(0 < x["obstruction_distance_mm"] < 3e-6 for x in rows)


def test_ray_grazing_roof_edge_and_coplanar_side_is_unknown_not_visible():
    mesh = _c_shape()
    # Inner floor triangle centroid is analytically x=(2+2+10)/3.
    # Terminate the roof at exactly that x so its edge/vertical side touches
    # the upward ray. A coplanar triangle must not be silently ignored.
    mesh.vertices[(mesh.vertices[:, 2] >= 8) & np.isclose(mesh.vertices[:, 0], 10), 0] = 14 / 3
    r = inspect_point_visibility(mesh)
    row = next(x for x in r["samples"] if np.allclose(x["point_mm"], [14 / 3, 8 / 3, 2]))
    assert row["state"] == "unknown"
    assert row["reason"] == "grazing_or_near_surface_intersection"
    assert r["status"] == "partial"


def test_cube_face_subdivision_and_order_do_not_create_source_self_occlusions():
    mesh = trimesh.creation.box(extents=[10, 20, 30])
    base = inspect_point_visibility(mesh)
    subdivided = mesh.subdivide()
    reversed_order = trimesh.Trimesh(vertices=mesh.vertices.copy(), faces=mesh.faces[::-1].copy(), process=False)
    for variant in (subdivided, reversed_order):
        r = inspect_point_visibility(variant)
        assert r["status"] == "complete"
        assert r["measurements"]["area_weighted_sample_fractions"] == pytest.approx(
            base["measurements"]["area_weighted_sample_fractions"])
        assert not r["occluded_face_indices"] and not r["unknown_face_indices"]


def test_annulus_vertical_hole_is_tangent_not_globally_clear():
    mesh = trimesh.creation.annulus(r_min=2, r_max=6, height=10, sections=32)
    r = inspect_point_visibility(mesh, max_samples=512)
    assert r["status"] == "complete"
    centers, normals = mesh.triangles_center, mesh.face_normals
    inner = set(np.flatnonzero(np.einsum("ij,ij->i", centers[:, :2], normals[:, :2]) < -.1).tolist())
    assert inner and inner <= set(r["tangent_face_indices"])
    assert not r["occluded_face_indices"]
    side = inspect_point_visibility(mesh, direction=[1, 0, 0])
    assert set(side["occluded_face_indices"]) & inner
    assert not (set(side["visible_face_indices"]) & inner)


@pytest.mark.parametrize("direction", [[0, 0, 1], [1, 2, 3], [-1, .1, 2]])
def test_rotation_and_translation_preserve_sample_states(direction):
    mesh = _c_shape()
    r = inspect_point_visibility(mesh, direction)
    transform = trimesh.transformations.rotation_matrix(.819, [2, 1, 3])
    transform[:3, 3] = [1234, -892, 354]
    rotated = mesh.copy()
    rotated.apply_transform(transform)
    other = inspect_point_visibility(rotated, transform[:3, :3] @ direction)
    assert [x["state"] for x in other["samples"]] == [x["state"] for x in r["samples"]]
    assert other["measurements"]["area_weighted_sample_fractions"] == pytest.approx(
        r["measurements"]["area_weighted_sample_fractions"], abs=1e-10)
    assert np.asarray([x["point_mm"] for x in other["samples"]]) == pytest.approx(
        trimesh.transform_points([x["point_mm"] for x in r["samples"]], transform), abs=1e-9)


@pytest.mark.parametrize("factor", [1e-5, 1e-2, 1e3, 1e6])
def test_scale_invariance_and_distance_units(factor):
    mesh = _c_shape()
    mesh.apply_scale(factor)
    r = inspect_point_visibility(mesh)
    assert _state_area(r, "occluded") == pytest.approx(32 * factor ** 2)
    rows = [x for x in r["samples"] if x["state"] == "occluded"]
    assert rows and all(min(abs(x["obstruction_distance_mm"] / factor - y) for y in (6, 8)) < 1e-8 for x in rows)


def test_signed_internal_cavity_is_unknown_even_with_valid_total_volume():
    outer, cavity = trimesh.creation.box(extents=[20] * 3), trimesh.creation.box(extents=[16] * 3)
    cavity.invert()
    mesh = trimesh.util.concatenate([outer, cavity])
    assert mesh.is_watertight and mesh.volume == pytest.approx(3904)
    r = inspect_point_visibility(mesh)
    assert r["status"] == "unknown" and "multiple_surface_components" in r["reasons"]
    assert r["measurements"]["area_weighted_sample_fractions"] is None
    assert not r["visible_face_indices"]


def test_separate_or_intersecting_shells_are_not_assumed_single_material():
    for offset in ([10, 0, 0], [.2, 0, 0]):
        first, second = trimesh.creation.box(), trimesh.creation.box()
        second.apply_translation(offset)
        r = inspect_point_visibility(trimesh.util.concatenate([first, second]))
        assert r["status"] == "unknown"
        assert r["reasons"] == ["multiple_surface_components"]


@pytest.mark.parametrize("damage", ["open", "duplicate", "inverted", "nonfinite", "empty", "degenerate"])
def test_invalid_mesh_never_becomes_clear(damage):
    mesh = trimesh.creation.box()
    if damage == "open":
        mesh.update_faces(np.arange(11))
    elif damage == "duplicate":
        mesh.faces = np.concatenate([mesh.faces, mesh.faces[:1]])
    elif damage == "inverted":
        mesh.invert()
    elif damage == "nonfinite":
        mesh.vertices[0, 0] = np.nan
    elif damage == "empty":
        mesh = trimesh.Trimesh()
    else:
        mesh.faces = np.concatenate([mesh.faces, [[0, 0, 1]]])
    r = inspect_point_visibility(mesh)
    assert r["status"] == "unknown"
    assert r["measurements"]["area_weighted_sample_fractions"] is None
    assert not r["visible_face_indices"]


def test_sample_limit_keeps_omitted_face_area_and_does_not_claim_whole_mesh_coverage():
    mesh = trimesh.creation.icosphere(subdivisions=2)
    r = inspect_point_visibility(mesh, max_samples=7)
    m = r["measurements"]
    assert m["requested_samples"] == 7 and 1 <= m["selected_samples"] <= 7
    assert m["omitted_face_count"] == len(mesh.faces) - m["selected_samples"]
    assert 0 < m["sampled_face_area_fraction"] < .1
    selected = [row["source_face"] for row in r["samples"]]
    selected_area = mesh.area_faces[selected].sum()
    assert m["selected_face_area_mm2"] == pytest.approx(selected_area)
    assert m["omitted_face_area_mm2"] == pytest.approx(mesh.area - selected_area)
    assert sum(m["area_weighted_sample_fractions"].values()) == pytest.approx(1)


def test_ray_budget_preserves_unresolved_sample_mass():
    mesh = trimesh.creation.box()
    r = inspect_point_visibility(mesh, max_ray_triangle_tests=1)
    assert r["status"] == "partial" and "ray_budget_exceeded" in r["reasons"]
    assert r["measurements"]["ray_triangle_tests"] <= 1
    assert r["measurements"]["area_weighted_sample_fractions"]["unknown"] == pytest.approx(1 / 6)
    assert not r["visible_face_indices"]
    assert r["measurements"]["evaluated_samples"] == 10


def test_face_cap_prevents_expensive_diagnostics():
    with patch("dfm.accessibility.inspect_mesh", side_effect=AssertionError("must not run")):
        r = inspect_point_visibility(trimesh.creation.box(), max_faces=4)
    assert r["status"] == "unknown" and r["reasons"] == ["face_budget_exceeded"]


def test_vertex_cap_rejects_large_unreferenced_arrays_before_worker_serialization():
    box = trimesh.creation.box()
    mesh = trimesh.Trimesh(vertices=np.concatenate([box.vertices, np.zeros((50, 3))]),
                           faces=box.faces, process=False)
    with patch("dfm.accessibility.inspect_mesh", side_effect=AssertionError("must not inspect")), \
         patch("dfm.accessibility.np.savez", side_effect=AssertionError("must not serialize")):
        for operation in (inspect_point_visibility, run_point_visibility):
            r = operation(mesh, max_faces=12)
            assert r["status"] == "unknown" and r["reasons"] == ["vertex_budget_exceeded"]


def test_deadline_returns_unknown_rows_without_zeroing_unexamined_area():
    with patch("dfm.accessibility.time.perf_counter", side_effect=[0.] + [10.] * 20):
        r = inspect_point_visibility(trimesh.creation.box(), timeout_s=1)
    assert r["status"] == "partial"
    assert r["measurements"]["area_weighted_sample_fractions"]["unknown"] == 1
    assert r["measurements"]["evaluated_samples"] == 0


def test_source_faces_and_vertices_are_never_changed():
    mesh = _c_shape()
    vertices, faces = mesh.vertices.copy(), mesh.faces.copy()
    r = inspect_point_visibility(mesh)
    assert np.array_equal(vertices, mesh.vertices) and np.array_equal(faces, mesh.faces)
    # The complete output is plain JSON, including all unknown and boundary states.
    json.dumps(r, allow_nan=False)


@pytest.mark.parametrize("kwargs", [
    {"direction": [0, 0, 0]}, {"direction": [np.nan, 0, 1]}, {"direction": [1, 2]},
    {"max_samples": True}, {"max_samples": 0}, {"max_samples": 2.3},
    {"max_ray_triangle_tests": np.inf}, {"timeout_s": np.nan}, {"timeout_s": 0},
])
def test_invalid_controls_raise_instead_of_silently_changing_request(kwargs):
    with pytest.raises(ValueError):
        inspect_point_visibility(trimesh.creation.box(), **kwargs)


def test_hard_worker_timeout_and_failure_are_unknown():
    for failure, code in ((subprocess.TimeoutExpired("worker", 1), "worker_timeout"),
                          (OSError("worker unavailable"), "worker_failed")):
        with patch("amdfm.processes.run_bounded", side_effect=failure):
            r = run_point_visibility(trimesh.creation.box(), timeout_s=1)
        assert r["status"] == "unknown" and r["reasons"] == [code]
        assert r["measurements"]["area_weighted_sample_fractions"] is None


def test_worker_result_matches_direct_geometric_result():
    mesh = _c_shape()
    direct = inspect_point_visibility(mesh)
    bounded = run_point_visibility(mesh, timeout_s=20)
    assert bounded["status"] == direct["status"]
    assert bounded["samples"] == direct["samples"]
    assert bounded["measurements"] == direct["measurements"]
