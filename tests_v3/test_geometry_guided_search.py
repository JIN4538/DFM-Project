import time
import numpy as np
import trimesh

from amdfm.geometry_guided_search import rank_geometry_guided_queries
from amdfm.proposal_selector import cheap_geometry, objective_values, select_indices
from amdfm.full_search import MODEL_PATH
from amdfm.neural_orientation import load_model, baseline_descriptor, proposal_pool, predict_surrogates
from amdfm.orientation import compare_orientations, measure_orientation
from amdfm.profiles import Profile


def test_optional_api_matches_frozen_acquisition_formula():
    mesh = trimesh.creation.box((31., 13., 7.))
    mesh.apply_transform(trimesh.transformations.euler_matrix(.32, .73, -.16))
    profile = Profile(process="MEX")
    baseline = compare_orientations(mesh, profile, dense=True)
    descriptor = baseline_descriptor(mesh, baseline)
    directions, _ = proposal_pool(mesh, baseline)
    model = load_model(MODEL_PATH)
    result = rank_geometry_guided_queries(mesh, model, descriptor, directions, profile)
    geometry = cheap_geometry(mesh, directions)
    neural = predict_surrogates(model, descriptor, directions, 45.)
    scores = objective_values(geometry["height"], neural["overhang"], geometry["contact"], "MEX", "balanced")
    assert result["indices"] == select_indices(directions, scores)
    assert result["requested_full_queries"] == 6
    measured = [measure_orientation(mesh, d, profile) for d in result["directions"]]
    np.testing.assert_allclose(result["exact_height_mm"], [r["height_mm"] for r in measured], atol=1e-10)
    np.testing.assert_allclose(result["exact_contact_triangle_area_mm2"], [r["contact_triangle_area_mm2"] for r in measured], atol=1e-10)


def test_scope_and_deadline_fallback_preserve_original_path():
    mesh = trimesh.creation.box((3., 2., 1.))
    model = load_model(MODEL_PATH)
    rows = compare_orientations(mesh, Profile(), dense=True)
    descriptor = baseline_descriptor(mesh, rows)
    directions, _ = proposal_pool(mesh, rows)
    assert rank_geometry_guided_queries(mesh, model, descriptor, directions, Profile(overhang_angle_deg=60.)) is None
    assert rank_geometry_guided_queries(mesh, model, descriptor, directions, Profile(build_volume_mm=(200., 200., 200.))) is None
    assert rank_geometry_guided_queries(mesh, model, descriptor, directions, Profile(), priority="contact") is None
    assert rank_geometry_guided_queries(mesh, model, descriptor, directions, Profile(), budget=3) is None
    assert rank_geometry_guided_queries(mesh, model, descriptor, directions, Profile(), deadline=time.monotonic()-1) is None
    assert rank_geometry_guided_queries(mesh, model, descriptor, directions, Profile(), reliable_normals=False) is None
    assert rank_geometry_guided_queries(mesh, model, {**descriptor, "area_mm2": descriptor["area_mm2"]*2}, directions, Profile()) is None
    changed = {**model, "sha256": "changed"}
    assert rank_geometry_guided_queries(mesh, changed, descriptor, directions, Profile()) is None


def test_polymer_choices_are_geometric_without_learned_area_claim():
    mesh = trimesh.creation.box((3., 2., 1.))
    profile = Profile(process="PBF_POLYMER")
    rows = compare_orientations(mesh, profile, dense=True)
    descriptor = baseline_descriptor(mesh, rows, require_overhang=False)
    directions, _ = proposal_pool(mesh, rows)
    result = rank_geometry_guided_queries(mesh, load_model(MODEL_PATH), descriptor, directions, profile, priority="height")
    assert result["neural_overhang_projected_area_sum_mm2"] is None
    assert result["learned_component"] is None
