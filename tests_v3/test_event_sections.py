"""Analytic integrals and adversarial sampling cases, independent of CAD files."""
import math

import numpy as np
import pytest
import trimesh

import amdfm.event_sections as events
from amdfm.cross_sections import inspect_cross_sections


def plate_and_post():
    """Connected 1 mm square post with a 0.001 mm thick 10 by 20 mm plate."""
    xs = [-5., -.5, .5, 5.]
    ys = [-10., -.5, .5, 10.]
    zs = [0., 123.4562, 123.4572, 250.]
    occupied = {(i, j, k) for i in range(3) for j in range(3) for k in range(3)
                if k == 1 or (i == 1 and j == 1)}
    quads = [((1, 0, 0), [(1,0,0),(1,1,0),(1,1,1),(1,0,1)]),
             ((-1, 0, 0), [(0,0,0),(0,0,1),(0,1,1),(0,1,0)]),
             ((0, 1, 0), [(0,1,0),(0,1,1),(1,1,1),(1,1,0)]),
             ((0, -1, 0), [(0,0,0),(1,0,0),(1,0,1),(0,0,1)]),
             ((0, 0, 1), [(0,0,1),(1,0,1),(1,1,1),(0,1,1)]),
             ((0, 0, -1), [(0,0,0),(0,1,0),(1,1,0),(1,0,0)])]
    vertices, faces, ids = [], [], {}
    for i, j, k in sorted(occupied):
        for delta, quad in quads:
            if (i+delta[0], j+delta[1], k+delta[2]) in occupied:
                continue
            corners = []
            for a, b, c in quad:
                point = (xs[i+a], ys[j+b], zs[k+c])
                if point not in ids:
                    ids[point] = len(vertices)
                    vertices.append(point)
                corners.append(ids[point])
            faces.extend([[corners[0], corners[1], corners[2]],
                          [corners[0], corners[2], corners[3]]])
    return trimesh.Trimesh(vertices, faces, process=False), 250.+199*(zs[2]-zs[1])


def test_box_integrates_analytic_volume_and_preserves_uniform_row_contract():
    mesh = trimesh.creation.box([10, 5, 4])
    original = (mesh.vertices.copy(), mesh.faces.copy())
    r = events.inspect_event_sections(mesh)
    uniform = inspect_cross_sections(mesh, 2)
    assert r['status'] == 'complete'
    assert r['requested_samples'] == r['complete_samples'] == 2
    assert r['total_segments'] == r['planned_triangle_intersections'] == 16
    assert r['volume_quadrature_estimate_mm3'] == pytest.approx(200)
    assert r['sampled_max_area_mm2'] == pytest.approx(50)
    assert r['sampled_max_perimeter_mm'] == pytest.approx(30)
    assert r['sample_spacing_mm'] is None
    assert r['volume_midpoint_estimate_mm3'] is None
    assert r['sampling_method'] == 'vertex_events_gauss2'
    assert set(uniform['rows'][0]).issubset(r['rows'][0])
    assert r['unresolved_height_mm'] == r['omitted_interval_volume_envelope_mm3'] == 0
    assert np.array_equal(mesh.vertices, original[0])
    assert np.array_equal(mesh.faces, original[1])


def test_rotated_shifted_prism_has_analytic_volume_across_all_events():
    mesh = trimesh.creation.box([10, 20, 30])
    mesh.apply_transform(trimesh.transformations.rotation_matrix(.831, [1, 2, 3]))
    mesh.apply_translation([1e5, -2e5, 3e5])
    r = events.inspect_event_sections(mesh)
    assert r['status'] == 'complete'
    assert r['event_count'] == 8
    assert r['requested_samples'] == 14
    assert r['volume_quadrature_estimate_mm3'] == pytest.approx(6000, rel=1e-9)
    assert all(a['z_mm'] < b['z_mm'] for a, b in zip(r['rows'], r['rows'][1:]))


def test_thin_plate_missed_by_uniform_sampling_is_included_without_event_merging():
    mesh, analytic = plate_and_post()
    uniform = inspect_cross_sections(mesh, 64)
    r = events.inspect_event_sections(mesh)
    assert uniform['status'] == r['status'] == 'complete'
    assert uniform['volume_midpoint_estimate_mm3'] == pytest.approx(250.)
    assert analytic > 250.19
    assert r['volume_quadrature_estimate_mm3'] == pytest.approx(analytic, abs=1e-8)
    assert r['sampled_max_area_mm2'] == pytest.approx(200)
    assert r['minimum_event_interval_mm'] == pytest.approx(.001)
    assert r['requested_samples'] == 6


def test_polygon_cone_quadratic_integral_and_sample_maximum_is_not_global_maximum():
    sides, radius, height = 32, 10, 30
    mesh = trimesh.creation.cone(radius=radius, height=height, sections=sides)
    base_area = sides/2*radius**2*math.sin(2*math.pi/sides)
    r = events.inspect_event_sections(mesh)
    assert r['status'] == 'complete'
    assert r['volume_quadrature_estimate_mm3'] == pytest.approx(base_area*height/3, rel=1e-9)
    assert r['requested_samples'] == 2
    assert r['sampled_max_area_mm2'] < .7*base_area
    assert 'not global extrema' in r['scope']


def test_polygonal_annulus_preserves_cavity_and_analytic_material_volume():
    sides = 64
    mesh = trimesh.creation.annulus(r_min=2, r_max=5, height=10, sections=sides)
    area = sides/2*math.sin(2*math.pi/sides)*(25-4)
    r = events.inspect_event_sections(mesh)
    assert r['status'] == 'complete'
    assert r['volume_quadrature_estimate_mm3'] == pytest.approx(area*10, rel=1e-9)
    assert all(row['internal_loops'] == 1 and row['material_regions'] == 1 for row in r['rows'])


@pytest.mark.parametrize('limits', [dict(max_samples=1), dict(max_total_segments=15)])
def test_each_budget_is_checked_before_any_section_is_constructed(monkeypatch, limits):
    def forbidden(*args, **kwargs):
        pytest.fail('Preflight limit must prevent section construction')
    monkeypatch.setattr(events, 'section_mesh', forbidden)
    r = events.inspect_event_sections(trimesh.creation.box(), **limits)
    assert r['status'] == 'unknown'
    assert r['budget_exceeded']
    assert r['requested_samples'] == 2
    assert r['examined_samples'] == 0
    assert r['volume_quadrature_estimate_mm3'] is None
    assert r['known_interval_volume_mm3'] is None
    assert r['rows'] == []


def test_unrepresentable_gauss_nodes_remain_unknown_without_merging_or_zero_volume():
    mesh = trimesh.creation.box()
    upper = np.nextafter(1., 2.)
    mesh.vertices[:, 2] = np.where(mesh.vertices[:, 2] < 0, 1., upper)
    r = events.inspect_event_sections(mesh)
    assert r['input_diagnostics']['topology_ready']
    assert r['status'] == 'unknown'
    assert r['event_count'] == 2
    assert r['requested_samples'] == 2 and r['examined_samples'] == 0
    assert r['volume_quadrature_estimate_mm3'] is None
    assert r['unresolved_height_mm'] == upper-1
    assert r['omitted_interval_volume_envelope_mm3'] == upper-1
    assert 'not a bound on total error' in r['envelope_scope']


def test_sphere_nearly_identical_heights_are_reported_partial_and_not_silently_merged():
    mesh = trimesh.creation.icosphere(subdivisions=3, radius=10)
    r = events.inspect_event_sections(mesh)
    assert r['status'] == 'partial'
    assert r['volume_quadrature_estimate_mm3'] is None
    assert r['requested_samples'] > r['complete_samples'] > 0
    assert r['unresolved_height_mm'] > 0
    # The tetrahedron sum is a separate, global closed-boundary integral.
    p = mesh.triangles - mesh.bounds.mean(axis=0)
    volume = math.fsum(np.einsum('ij,ij->i', p[:, 0], np.cross(p[:, 1], p[:, 2]))/6)
    assert r['known_interval_volume_mm3'] == pytest.approx(volume, abs=1e-7)


def test_unused_vertex_does_not_add_a_false_material_event():
    box = trimesh.creation.box([10, 5, 4])
    mesh = trimesh.Trimesh(np.vstack([box.vertices, [0, 0, .123456]]), box.faces, process=False)
    r = events.inspect_event_sections(mesh)
    assert r['status'] == 'complete'
    assert r['event_count'] == 2
    assert r['volume_quadrature_estimate_mm3'] == pytest.approx(200)


def test_one_incomplete_section_blocks_full_volume_and_retains_unresolved_height(monkeypatch):
    real_section = events.section_mesh
    calls = 0
    def unresolved_first(*args, **kwargs):
        nonlocal calls
        section = real_section(*args, **kwargs)
        calls += 1
        if calls == 1:
            section.diagnostics.update(complete=False, unresolved_length_mm=.01)
        return section
    monkeypatch.setattr(events, 'section_mesh', unresolved_first)
    r = events.inspect_event_sections(trimesh.creation.box([10, 5, 4]))
    assert r['status'] == 'partial'
    assert r['complete_samples'] == 1
    assert r['volume_quadrature_estimate_mm3'] is None
    assert r['known_interval_volume_mm3'] == 0
    assert r['unresolved_height_mm'] == 4
    assert r['omitted_interval_volume_envelope_mm3'] == 200
    assert r['rows'][0]['area_mm2'] is None
    assert r['rows'][1]['symmetric_change_from_previous_mm2'] is None


def test_open_boundary_remains_unknown():
    mesh = trimesh.creation.box()
    mesh.update_faces(np.arange(11))
    r = events.inspect_event_sections(mesh)
    assert r['status'] == 'unknown'
    assert r['examined_samples'] == 0
    assert r['volume_quadrature_estimate_mm3'] is None


@pytest.mark.parametrize('limit', [0, -1, 1.5, True, float('nan'), float('inf')])
@pytest.mark.parametrize('name', ['max_samples', 'max_total_segments'])
def test_invalid_budget_is_rejected(limit, name):
    with pytest.raises(ValueError):
        events.inspect_event_sections(trimesh.creation.box(), **{name: limit})
