"""Independent geometry and query acquisition checks for the research selector."""
import json
import hashlib
import numpy as np
import pytest
import trimesh

from amdfm.proposal_selector import (cheap_geometry, select_indices, objective_values,
                                   portable_predict, SCHEMA, FEATURES, load_selector, feature_sha256)
from amdfm.orientation import measure_orientation
from amdfm.profiles import Profile
from amdfm.neural_orientation import fibonacci_directions


@pytest.mark.parametrize("rotation", [(0., 0., 0.), (.31, -.56, 1.24)])
def test_hull_extrema_and_contact_match_original_mesh(rotation):
    # An offset raised block creates both bottom and non-bottom parallel faces.
    a = trimesh.creation.box((30., 20., 4.))
    b = trimesh.creation.box((6., 8., 14.))
    b.apply_translation((8., 0., 9.))
    mesh = trimesh.util.concatenate((a, b))
    transform = trimesh.transformations.euler_matrix(*rotation)
    mesh.apply_transform(transform)
    axis = np.concatenate((np.eye(3), -np.eye(3)))@transform[:3, :3].T
    directions = np.concatenate((axis, fibonacci_directions(37)))
    observed = cheap_geometry(mesh, directions)
    expected = [measure_orientation(mesh, direction, Profile()) for direction in directions]
    np.testing.assert_allclose(observed["height"], [r["height_mm"]/np.linalg.norm(mesh.extents) for r in expected], rtol=0, atol=1e-12)
    np.testing.assert_allclose(observed["contact"], [r["contact_triangle_area_mm2"]/mesh.area for r in expected], rtol=0, atol=1e-12)
    assert observed["hull_vertices"] < observed["original_vertices"]


def test_declared_objective_separates_process_and_priority():
    height = np.array([1., 2., 3.])
    overhang = np.array([3., 2., 1.])
    contact = np.array([0., 1., 0.])
    np.testing.assert_allclose(objective_values(height, overhang, contact, "PBF_POLYMER", "height"), [0., .5, 1.])
    mex = objective_values(height, overhang, contact, "MEX", "balanced")
    assert mex[1] < mex[0] and mex[1] < mex[2]
    vpp = objective_values(height, overhang, contact, "VPP", "support")
    assert vpp[2] < vpp[0]


def test_six_queries_are_unique_and_uncertainty_changes_acquisition():
    d = fibonacci_directions(40)
    means = np.arange(40, dtype=float)
    uncertainty = np.zeros(40); uncertainty[-1] = 100.
    greedy = select_indices(d, means, uncertainty)
    exploring = select_indices(d, means, uncertainty, exploration=.5)
    assert len(set(greedy)) == len(set(exploring)) == 6
    assert 39 not in greedy and 39 in exploring
    with pytest.raises(ValueError):
        select_indices(d, means, budget=0)
    with pytest.raises(ValueError):
        select_indices(d, means, np.full(40, -1.))


def test_portable_tree_and_checksum_gate(tmp_path):
    member = dict(intercept=.4, trees=[[[0, .5, 1, 2, 0.], [-2, 0., -1, -1, -.1], [-2, 0., -1, -1, .2]]])
    np.testing.assert_allclose(portable_predict(member, [[.2], [.5], [.8]]), [.3, .3, .6])
    document = dict(schema=SCHEMA, features=FEATURES, feature_sha256=feature_sha256(), members=[member])
    path = tmp_path/"selector.json"
    raw = json.dumps(document).encode(); path.write_bytes(raw)
    path.with_suffix(".manifest.json").write_text(json.dumps(dict(sha256=hashlib.sha256(raw).hexdigest())))
    assert load_selector(path)["members"] == [member]
    path.write_bytes(raw+b" ")
    with pytest.raises(ValueError, match="checksum"):
        load_selector(path)
