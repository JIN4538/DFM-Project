from copy import deepcopy
import hashlib
import json

import numpy as np
import pytest
import trimesh

from amdfm import neural_orientation as neural
from amdfm.orientation import compare_orientations, measure_orientation
from amdfm.profiles import Profile


@pytest.fixture
def mesh():
    value = trimesh.creation.box(extents=[17, 8, .3])
    value.apply_transform(trimesh.transformations.euler_matrix(.42, .17, .83))
    return value


def baseline(mesh, profile=None):
    return compare_orientations(mesh, profile or Profile(), dense=True)


def test_exported_deep_model_tensor_contract_and_manifest():
    model = neural.load_model()
    assert model["schema"] == neural.SCHEMA
    assert len(model["networks"]["height"]["weights"]) >= 3
    assert len(model["networks"]["overhang"]["weights"]) >= 3
    assert model["sha256"] == hashlib.sha256(neural.MODEL_PATH.read_bytes()).hexdigest()
    assert model["feature_contract_sha256"] == neural.feature_contract_sha256()


def test_cached_model_rechecks_feature_source_identity(monkeypatch):
    neural.load_model()
    monkeypatch.setattr(neural, "feature_contract_sha256", lambda: "changed-runtime-contract")
    with pytest.raises(ValueError, match="feature contract mismatch"):
        neural.load_model()


def test_measured_neural_rows_match_independent_exact_remeasurement(mesh):
    profile = Profile(build_volume_mm=(50, 50, 50))
    rows = baseline(mesh, profile)
    original = deepcopy(rows)
    result = neural.enrich_orientations(mesh, profile, rows, max_proposals=5, timeout_s=30)
    assert result["metadata"]["status"] == "complete"
    assert result["metadata"]["added_count"] == 5
    assert result["metadata"]["predicted_values_used_as_measurements"] is False
    assert rows == original
    for row in result["rows"][len(rows):]:
        exact = measure_orientation(mesh, row["direction"], profile)
        assert row["candidate_role"] == "search"
        assert row["proposal_source"] in ("deep_neural_surrogate", "geometric_facet_seed")
        for key in ("height_mm", "overhang_projected_area_sum_mm2", "contact_triangle_area_mm2", "build_fit", "transform"):
            assert row[key] == exact[key]
        assert all(np.linalg.norm(np.asarray(row["direction"]) - np.asarray(old["direction"])) > 1e-8 for old in rows)
        assert isinstance(row["pareto"], (bool, np.bool_))


def test_changing_current_only_direction_does_not_change_proposals(mesh):
    rows = baseline(mesh)
    custom = measure_orientation(mesh, [.3, .4, .7], Profile())
    custom.update(name="현재 지정 방향", candidate_role="current_only")
    a = neural.enrich_orientations(mesh, Profile(), rows, max_proposals=4, timeout_s=30)
    b = neural.enrich_orientations(mesh, Profile(), rows + [custom], max_proposals=4, timeout_s=30)
    assert [r["direction"] for r in a["metadata"]["proposals"]] == [r["direction"] for r in b["metadata"]["proposals"]]


def test_missing_model_preserves_all_original_measurements(mesh, tmp_path):
    rows = baseline(mesh)
    result = neural.enrich_orientations(mesh, Profile(), rows, model_path=tmp_path / "absent.json")
    assert result["metadata"]["status"] == "unavailable"
    assert result["metadata"]["added_count"] == 0
    assert "model_sha256" not in result["metadata"]
    assert result["rows"] == rows


def test_corrupted_model_is_not_credited_as_neural(mesh, tmp_path):
    path = tmp_path / "model.json"
    path.write_bytes(neural.MODEL_PATH.read_bytes() + b" ")
    path.with_suffix(".manifest.json").write_bytes(neural.MODEL_PATH.with_suffix(".manifest.json").read_bytes())
    result = neural.enrich_orientations(mesh, Profile(), baseline(mesh), model_path=path)
    assert result["metadata"]["status"] == "unavailable"
    assert result["metadata"]["added_count"] == 0
    assert "hash mismatch" in result["metadata"]["reason"]


@pytest.mark.parametrize("angle", [20., 80.])
def test_untrained_angle_preserves_baseline(mesh, angle):
    profile = Profile(overhang_angle_deg=angle)
    rows = baseline(mesh, profile)
    result = neural.enrich_orientations(mesh, profile, rows)
    assert result["metadata"]["status"] == "unavailable"
    assert result["rows"] == rows


def test_normals_unknown_are_not_filled_in(mesh):
    rows = compare_orientations(mesh, Profile(), dense=True, reliable_normals=False)
    result = neural.enrich_orientations(mesh, Profile(), rows, reliable_normals=False)
    assert result["metadata"]["status"] == "unavailable"
    assert all(r["overhang_projected_area_sum_mm2"] is None for r in result["rows"])


def test_polymer_uses_only_learned_height_and_keeps_inapplicable_values(mesh):
    profile = Profile(process="PBF_POLYMER", overhang_angle_deg=90.)
    rows = compare_orientations(mesh, profile, dense=True, reliable_normals=False)
    result = neural.enrich_orientations(mesh, profile, rows, reliable_normals=False, max_proposals=3, timeout_s=30)
    assert result["metadata"]["status"] == "complete"
    assert result["metadata"]["targets"] == ["height_mm"]
    for row in result["rows"][len(rows):]:
        assert row["overhang_projected_area_sum_mm2"] is None
        assert row["contact_triangle_area_mm2"] is None
        assert row["build_fit"] is None
    assert all(set(p["predicted"]) == {"height_mm"} for p in result["metadata"]["proposals"])


def test_fit_failure_is_retained_and_not_marked_pareto(mesh):
    profile = Profile(build_volume_mm=(.1, .1, .1))
    result = neural.enrich_orientations(mesh, profile, baseline(mesh, profile), max_proposals=3, timeout_s=30)
    assert result["metadata"]["added_count"] == 3
    assert all(row["build_fit"] is False and not row["pareto"] for row in result["rows"])


def test_descriptor_scale_and_translation_invariance(mesh):
    original = neural.baseline_descriptor(mesh, baseline(mesh))
    altered = mesh.copy()
    altered.apply_scale(271.)
    altered.apply_translation([1800, -2200, 500])
    shifted = neural.baseline_descriptor(altered, baseline(altered))
    np.testing.assert_allclose(original["height"], shifted["height"], atol=1e-12)
    np.testing.assert_allclose(original["overhang"], shifted["overhang"], atol=1e-12)
    assert shifted["diagonal_mm"] == pytest.approx(original["diagonal_mm"] * 271)
    assert shifted["area_mm2"] == pytest.approx(original["area_mm2"] * 271**2)


def test_budget_zero_does_not_measure_or_load_model(mesh, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("zero budget must not load neural model")
    monkeypatch.setattr(neural, "load_model", unexpected)
    rows = baseline(mesh)
    for kwargs in ({"max_proposals": 0}, {"timeout_s": 0.}):
        result = neural.enrich_orientations(mesh, Profile(), rows, **kwargs)
        assert result["metadata"]["status"] == "skipped"
        assert result["rows"] == rows


def test_partial_measurement_preserves_done_rows(mesh, monkeypatch):
    original = neural.measure_orientation
    count = 0
    def fail_second(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise ValueError("forced second measurement failure")
        return original(*args, **kwargs)
    monkeypatch.setattr(neural, "measure_orientation", fail_second)
    rows = baseline(mesh)
    result = neural.enrich_orientations(mesh, Profile(), rows, max_proposals=4, timeout_s=30)
    assert result["metadata"]["status"] == "partial"
    assert result["metadata"]["added_count"] == 1
    assert len(result["rows"]) == len(rows) + 1
    assert "pareto" in result["rows"][-1]
    assert result["rows"][-1]["objectives"]


def test_insufficient_base_directions_declines_without_faking_measurements(mesh):
    rows = compare_orientations(mesh, Profile(), dense=False)
    result = neural.enrich_orientations(mesh, Profile(), rows)
    assert result["metadata"]["status"] == "unavailable"
    assert result["rows"] == rows


def test_direction_features_unit_normalize_and_reject_nan(mesh):
    descriptor = neural.baseline_descriptor(mesh, baseline(mesh))
    a = neural.feature_arrays(descriptor, [[1, 2, 3]])
    b = neural.feature_arrays(descriptor, [[10, 20, 30]])
    np.testing.assert_allclose(a["height"], b["height"])
    with pytest.raises(ValueError):
        neural.feature_arrays(descriptor, [[np.nan, 0, 1]])


def test_network_weights_change_query_selection(mesh):
    descriptor = neural.baseline_descriptor(mesh, baseline(mesh))
    directions, _ = neural.proposal_pool(mesh, baseline(mesh))
    actual = neural.predict_surrogates(neural.load_model(), descriptor, directions)
    neural_choice = neural.choose_proposals(directions, neural.proposal_scores(actual, descriptor), 12)
    # A constant model is a genuine ablation: it returns stable pool order.
    constant = {key: np.full(len(directions), .5) for key in ("height", "overhang")}
    ablated = neural.choose_proposals(directions, neural.proposal_scores(constant, descriptor), 12)
    assert neural_choice != ablated


def test_hybrid_search_separates_geometric_seeds_from_neural_queries(mesh):
    result = neural.enrich_orientations(mesh, Profile(), baseline(mesh), max_proposals=12, timeout_s=30)
    metadata = result["metadata"]
    assert metadata["facet_query_count"] == 6
    assert metadata["neural_query_count"] == 6
    assert metadata["added_count"] == metadata["facet_query_count"] + metadata["neural_query_count"]
    for proposal in metadata["proposals"]:
        if proposal["selection_source"] == "geometric_facet_seed":
            assert proposal["name"].startswith("면 탐색")
        else:
            assert proposal["name"].startswith("AI 탐색")
