"""Independent analytic checks for arbitrary build vectors, not print physics."""
from itertools import product
from math import cos, radians, sqrt

import numpy as np
import pytest
import trimesh

from amdfm.analysis import review
from amdfm.io import load_model
from amdfm.orientation import (
    candidates,
    compare_orientations,
    direction_angles,
    direction_from_angles,
    measure_orientation,
    placement,
    unit_direction,
)
from amdfm.presentation import placed_stl
from amdfm.profiles import Profile


def test_thousand_arbitrary_directions_match_independent_box_formulas():
    # For an axis-aligned box the directional span is sum(L_i * abs(d_i)).
    # One face of area product(other L) is downward on each nonzero axis.
    # Every random direction has point contact, so no entire face is excluded.
    lengths = np.array([7.0, 13.0, 29.0])
    side_areas = np.array([13.0 * 29.0, 7.0 * 29.0, 7.0 * 13.0])
    mesh = trimesh.creation.box(extents=lengths)
    profile = Profile(overhang_angle_deg=63.0)
    vectors = np.random.default_rng(824).normal(size=(1000, 3))
    vectors /= np.linalg.norm(vectors, axis=1)[:, None]
    threshold = cos(radians(63.0))
    for d in vectors:
        measured = measure_orientation(mesh, d, profile)
        selected = np.abs(d) > threshold
        expected_projection = float(np.dot(side_areas[selected], np.abs(d[selected])))
        expected_surface = float(side_areas[selected].sum())
        assert measured["height_mm"] == pytest.approx(np.dot(lengths, np.abs(d)), abs=1e-10)
        assert measured["overhang_projected_area_sum_mm2"] == pytest.approx(expected_projection, abs=1e-9)
        assert measured["overhang_surface_area_mm2"] == pytest.approx(expected_surface, abs=1e-9)
        assert measured["contact_triangle_area_mm2"] == 0
        matrix = np.asarray(measured["transform"])
        rotation = matrix[:3, :3]
        np.testing.assert_allclose(rotation @ d, [0, 0, 1], atol=2e-13, rtol=0)
        np.testing.assert_allclose(rotation @ rotation.T, np.eye(3), atol=2e-13, rtol=0)
        assert np.linalg.det(rotation) == pytest.approx(1.0, abs=2e-13)


@pytest.mark.parametrize("scale", [1.0, 1e-250, 1e250, 1e-308, 1e308])
def test_vector_magnitude_cannot_change_direction(scale):
    # Scaling by max(abs(d)) first avoids both squaring overflow and underflow.
    direction = np.array([0.5, -0.25, 1.0]) * scale
    expected = np.array([2.0, -1.0, 4.0]) / sqrt(21.0)
    actual = unit_direction(direction)
    assert np.isfinite(actual).all()
    np.testing.assert_allclose(actual, expected, atol=2e-15, rtol=0)


@pytest.mark.parametrize("direction", [
    [0, 0, 0], [np.nan, 0, 1], [0, np.inf, 1], [0, 0, -np.inf],
    [1, 2], [1, 2, 3, 4], [[1, 2, 3]],
])
def test_invalid_vectors_are_explicit_errors(direction):
    with pytest.raises(ValueError):
        unit_direction(direction)


@pytest.mark.parametrize("tilt,azimuth,expected", [
    (0, 0, [0, 0, 1]), (0, 217, [0, 0, 1]),
    (180, 0, [0, 0, -1]), (180, 217, [0, 0, -1]),
    (90, 0, [1, 0, 0]), (90, 90, [0, 1, 0]),
    (90, 180, [-1, 0, 0]), (90, 270, [0, -1, 0]),
    (90, 360, [1, 0, 0]),
    (45, 0, [sqrt(0.5), 0, sqrt(0.5)]),
])
def test_angle_convention_matches_named_model_axes(tilt, azimuth, expected):
    np.testing.assert_allclose(direction_from_angles(tilt, azimuth), expected, atol=2e-15, rtol=0)


@pytest.mark.parametrize("tilt,azimuth", [(12.345, 87.654), (90, 270), (179.99, 359.99)])
def test_angles_round_trip_without_changing_direction(tilt, azimuth):
    direction = direction_from_angles(tilt, azimuth)
    recovered_tilt, recovered_azimuth = direction_angles(direction)
    assert recovered_tilt == pytest.approx(tilt, abs=1e-10)
    assert recovered_azimuth == pytest.approx(azimuth, abs=1e-10)
    np.testing.assert_allclose(direction_from_angles(recovered_tilt, recovered_azimuth), direction, atol=2e-13, rtol=0)


@pytest.mark.parametrize("tilt,azimuth", [
    (-0.01, 0), (180.01, 0), (0, -0.01), (0, 360.01),
    (np.nan, 0), (0, np.inf),
])
def test_invalid_angles_are_explicit_errors(tilt, azimuth):
    with pytest.raises(ValueError):
        direction_from_angles(tilt, azimuth)


@pytest.mark.parametrize("direction", [
    [0, 0, 1], [0, 0, -1], [1e-8, 0, 1], [0, -1e-8, -1],
    [1e-12, -2e-12, -1], [1, 2, 3],
])
def test_placement_remains_a_rigid_rotation_near_both_poles(direction):
    mesh = trimesh.creation.box(extents=[7, 13, 29])
    mesh.vertices = mesh.vertices + [127, -31, 43]
    xyz, matrix = placement(mesh, direction)
    d = np.asarray(direction, dtype=float)
    d /= np.linalg.norm(d)
    rotation = np.asarray(matrix)[:3, :3]
    np.testing.assert_allclose(rotation @ d, [0, 0, 1], atol=3e-15, rtol=0)
    np.testing.assert_allclose(rotation @ rotation.T, np.eye(3), atol=3e-15, rtol=0)
    assert np.linalg.det(rotation) == pytest.approx(1.0, abs=3e-15)
    assert np.ptp(xyz[:, 2]) == pytest.approx(np.dot([7, 13, 29], np.abs(d)), abs=1e-11)
    assert xyz[:, 2].min() == pytest.approx(0.0, abs=1e-12)
    np.testing.assert_allclose(xyz, mesh.vertices @ rotation.T + np.asarray(matrix)[:3, 3], atol=1e-12, rtol=0)


def test_26_candidates_are_all_axis_edge_and_corner_directions():
    mesh = trimesh.creation.box(extents=[2, 3, 7])
    plain = candidates(mesh)
    assert len(plain) == 6
    dense = candidates(mesh, dense=True)
    assert len(dense) == 26
    actual = np.asarray(list(dense.values()), dtype=float)
    assert np.isfinite(actual).all()
    np.testing.assert_allclose(np.linalg.norm(actual, axis=1), 1.0, atol=2e-15, rtol=0)
    expected = []
    for triple in product((-1, 0, 1), repeat=3):
        if triple == (0, 0, 0):
            continue
        expected.append(np.array(triple, dtype=float) / sqrt(sum(x * x for x in triple)))
    distances = np.linalg.norm(actual[:, None, :] - np.asarray(expected)[None, :, :], axis=2)
    assert np.all(distances.min(axis=0) < 2e-15)
    assert len(np.unique(actual.round(13), axis=0)) == 26
    assert len(candidates(mesh, include_face_normals=True, dense=True)) == 26


def test_custom_direction_is_included_once_and_reports_match_the_selected_vector():
    mesh = trimesh.creation.box(extents=[2, 3, 7])
    profile = Profile()
    custom = np.array([1.0, 2.0, 3.0]) / sqrt(14.0)
    rows = compare_orientations(mesh, profile, dense=True, current_direction=[1, 2, 3])
    assert len(rows) == 27
    matches = [row for row in rows if np.linalg.norm(np.asarray(row["direction"]) - custom) < 1e-13]
    assert len(matches) == 1
    assert matches[0]["height_mm"] == pytest.approx(29.0 / sqrt(14.0), abs=1e-11)
    assert len(compare_orientations(mesh, profile, dense=True, current_direction=[0, 0, 1e250])) == 26
    # For this box ±X have the smallest height, no overhang, and largest base.
    # Thus the answer is known without reimplementing a Pareto comparison.
    pareto = [row for row in rows if row["pareto"]]
    assert len(pareto) == 2
    assert {tuple(row["direction"]) for row in pareto} == {(1.0, 0.0, 0.0), (-1.0, 0.0, 0.0)}
    for row in rows:
        assert np.isfinite(np.asarray(row["transform"])).all()
        assert np.isfinite(row["height_mm"])
        assert np.isfinite(row["overhang_projected_area_sum_mm2"])


def test_review_preserves_arbitrary_direction_in_current_and_candidate_results():
    mesh = trimesh.creation.box(extents=[2, 3, 7])
    model = load_model(mesh.export(file_type="stl"), "arbitrary-box.stl", dimensions_confirmed=True)
    expected = np.array([1.0, 2.0, 3.0]) / sqrt(14.0)
    report = review(model, Profile(), [1, 2, 3], dense=True)
    np.testing.assert_allclose(report["current_orientation"]["direction"], expected, atol=2e-15, rtol=0)
    matches = [row for row in report["orientations"] if np.linalg.norm(np.asarray(row["direction"]) - expected) < 1e-13]
    assert len(matches) == 1
    assert matches[0]["height_mm"] == report["current_orientation"]["height_mm"]


def test_current_near_axis_direction_is_not_deduplicated_by_angular_tolerance():
    mesh = trimesh.creation.box(extents=[1e7, 2, .4])
    direction = [9e-15, 0, 1]
    rows = compare_orientations(mesh, Profile(), current_direction=direction)
    assert len(rows) == 7
    current = next(row for row in rows if row["name"] == "현재 지정 방향")
    assert current["direction"] == direction
    assert current["height_mm"] > .4 + 8e-8


@pytest.mark.parametrize("direction", [[1, 2, 3], [1e-8, 0, 1], [0, -1e-8, -1]])
def test_export_vertices_agree_with_report_transform_with_float32_precision(direction):
    source = trimesh.creation.box(extents=[10, 20, 30])
    source.vertices = source.vertices + [0, 0, 15]
    model = load_model(source.export(file_type="stl"), "on-plate.stl", dimensions_confirmed=True)
    report = review(model, Profile(), direction, compare=False)
    matrix = np.asarray(report["current_orientation"]["transform"])
    expected = model.mesh.vertices @ matrix[:3, :3].T + matrix[:3, 3]
    exported = load_model(placed_stl(model, report), "placed.stl", dimensions_confirmed=True)
    # Binary STL stores coordinates as float32; vertex ordering is immaterial.
    # Compute the representable coordinates directly rather than allowing the
    # tiny rotation to disappear inside a broad geometry-size relative tolerance.
    representable = expected.astype(np.float32).astype(np.float64)
    distances = np.linalg.norm(exported.mesh.vertices[:, None, :] - representable[None, :, :], axis=2)
    np.testing.assert_allclose(distances.min(axis=0), 0.0, atol=1e-12, rtol=0)
    np.testing.assert_allclose(distances.min(axis=1), 0.0, atol=1e-12, rtol=0)
    assert exported.mesh.extents[2] == pytest.approx(report["current_orientation"]["height_mm"], abs=4e-6)
    assert exported.mesh.bounds[0, 2] == pytest.approx(0, abs=1e-12)
