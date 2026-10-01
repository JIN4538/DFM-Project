"""Independent geometry contracts for full-corpus training and localization."""
import numpy as np
import pytest
import trimesh
from amdfm.orientation import measure_orientation
from amdfm.profiles import Profile
from scripts.prepare_full_am import chunk_labels
from dfm.cad_graph import extract_graph
from dfm.feature_localization import edge_geometry, node_geometry, components


@pytest.mark.parametrize('shape', ['box', 'sphere', 'cylinder'])
def test_chunk_projection_matches_runtime_for_rotated_scaled_shapes(shape):
    mesh = (trimesh.creation.box([.3, 27, 41]) if shape == 'box' else trimesh.creation.icosphere(subdivisions=3) if shape == 'sphere' else trimesh.creation.cylinder(radius=3, height=19, sections=97))
    mesh.apply_transform(trimesh.transformations.euler_matrix(.31, .57, -.28))
    mesh.vertices = mesh.vertices*13 + [1e4, -2e4, 3e4]
    directions = np.array([[0, 0, 1], [1, -2, 3], [-.3, .9, .2]])
    directions /= np.linalg.norm(directions, axis=1)[:, None]
    angles = (25., 45., 75.)
    h, o = chunk_labels(mesh, directions, angles, block=17)
    for j, angle in enumerate(angles):
        for i, d in enumerate(directions):
            m = measure_orientation(mesh, d, Profile(overhang_angle_deg=angle))
            assert h[i] == pytest.approx(m['height_mm']/np.linalg.norm(mesh.extents), abs=1e-11)
            assert o[j, i] == pytest.approx(m['overhang_projected_area_sum_mm2']/mesh.area, abs=1e-11)


def test_edge_geometry_is_direction_symmetric_and_rigid_scale_invariant():
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    g = extract_graph(BRepPrimAPI_MakeBox(8., 13., 19.).Shape())
    geo = edge_geometry(g)
    e = g['edges']
    for i, pair in enumerate(e):
        reverse = int(np.flatnonzero((e == pair[::-1]).all(1))[0])
        assert geo[i] == pytest.approx(geo[reverse], abs=1e-7)
    rotate = trimesh.transformations.euler_matrix(.4, -.2, .7)[:3, :3]
    clone = dict(g)
    clone['scale_mm'] = g['scale_mm']*17
    clone['measurements'] = [dict(m, centroid_mm=(np.array(m['centroid_mm'])@rotate.T*17+[999, -20, 80]).tolist(),
        normal=(np.array(m['normal'])@rotate.T).tolist(), area_mm2=m['area_mm2']*17**2) for m in g['measurements']]
    assert edge_geometry(clone) == pytest.approx(geo, abs=1e-7)
    assert np.isfinite(node_geometry(e, geo, len(g['x']))).all()


def test_instance_boundaries_keep_adjacent_same_class_features_separate():
    # Labels alone would join the entire chain. Learned boundary decisions
    # retain two independent instances with their original face ordinals.
    e = np.array([[0, 1], [1, 0], [1, 2], [2, 1], [2, 3], [3, 2]])
    groups = components(e, [True, True, False, False, True, True], 4)
    assert groups == [[0, 1], [2, 3]]


def learned_pocket_report():
    return dict(process='MILLING_3AXIS', profile=dict(tool_diameter_mm=9., flute_length_mm=3., reach_mm=3., hole_depth_ratio_limit=None),
        findings=[dict(id='cnc_input', status='observed', measurements=dict(cad_feature_dimensions_available=True)),
            dict(id='cnc_learned_pockets', status='attention', measurements=dict(pockets=[dict(feature='triangular_pocket', floor_face_id=120,
                width_mm=12., entry_circle_diameter_mm=8., wall_height_mm=5.)]))])


def test_learned_polygon_pocket_enters_final_planning_and_uses_entry_disk():
    from dfm.plan_learning import _cnc_inputs, candidate_plans
    from dfm.rl_planner import make_problem, conflicts
    report = learned_pocket_report()
    _, _, _, pockets, _, _ = _cnc_inputs(report)
    assert pockets == [(8., 5., 0, 120)]
    plans, _, _ = candidate_plans(report)
    assert plans
    for p in plans:
        assert 'cnc_learned_pockets' in p['covered_finding_ids']
        assert p['outcomes']['remaining_numeric_conflicts'] == 0
        for edit in p['changes']:
            if edit['field'] == 'pocket.0.width':
                assert edit['label'] == '포켓 진입원 지름'
                assert edit['before'] == 8.
    problem = make_problem(report)
    assert problem['initial']['pockets'][0]['width'] == 8.
    assert {r['finding_id'] for r in conflicts(problem, problem['initial'])} == {'cnc_learned_pockets'}


def test_geometry_lock_keeps_polygon_corner_problem_visible():
    from dfm.plan_learning import candidate_plans
    plans, _, _ = candidate_plans(learned_pocket_report(), dict(preserve_geometry=True))
    assert plans
    for p in plans:
        assert 'cnc_learned_pockets' in p['remaining_finding_ids']
        assert not any(c['field'].startswith('pocket.') for c in p['changes'])
