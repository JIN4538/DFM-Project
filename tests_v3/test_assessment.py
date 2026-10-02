"""One-click orchestration keeps the original numerical and provenance contracts."""
import copy

import numpy as np
import pytest
import trimesh

from amdfm.analysis import review
import amdfm.assessment as assessment_module
from amdfm.assessment import attach_assessment, run_assessment
from amdfm.io import load_model
from amdfm.models import Model, plain
from amdfm.orientation import measure_orientation
from amdfm.profiles import Profile


def slab_model():
    return load_model(trimesh.creation.box(extents=[10, 5, 1]).export(file_type="stl"),
                      "automatic-slab.stl", dimensions_confirmed=True)


def unknown_result(model, profile, direction, **kwargs):
    orientation = measure_orientation(model.mesh, direction, profile)
    return plain(dict(mode=kwargs["mode"], fingerprint=model.fingerprint,
                      profile=profile.to_dict(), direction=orientation["direction"],
                      placement_transform=orientation["transform"],
                      status="unknown", reason="worker limit"))


@pytest.mark.parametrize("process", ["MEX", "VPP", "PBF_POLYMER", "PBF_METAL"])
def test_real_workers_complete_small_shape_and_preserve_analytic_values(process):
    model = slab_model()
    profile = Profile(process=process, minimum_wall_mm=1.2,
                      build_volume_mm=(15., 30., 40.), clearance_mm=1.)
    original_vertices = model.mesh.vertices.copy()
    report = review(model, profile, compare=False)
    events = []
    bundle = run_assessment(model, profile, on_progress=events.append)
    merged = attach_assessment(report, bundle)
    assert bundle["status"] == "complete"
    assert bundle["details"]["wall"]["measurements"]["minimum_mm"] == pytest.approx(1.)
    assert bundle["details"]["sections"]["volume_quadrature_estimate_mm3"] == pytest.approx(50.)
    wall = next(item for item in merged["findings"] if item["id"] == "wall")
    assert wall["status"] == "attention"
    section = next(item for item in merged["findings"] if item["id"] == "sections")
    assert "정밀 검토를 실행하세요" not in section["action"]
    assert "details" not in report
    assert "details" not in merged["automatic_assessment"]
    assert len(events) == 2 * len(bundle["planned_modes"])
    if process == "MEX":
        layers = bundle["details"]["layers"]
        assert layers["status"] == "complete"
        assert layers["expected_layers"] == 5
        assert layers["volume_estimate_mm3"] == pytest.approx(50.)
    else:
        assert "layers" not in bundle["details"]
    np.testing.assert_array_equal(model.mesh.vertices, original_vertices)


def test_layer_budget_refusal_is_preserved_while_other_queries_continue():
    model = slab_model()
    profile = Profile(layer_height_mm=.0005)
    bundle = run_assessment(model, profile)
    layers = bundle["details"]["layers"]
    assert layers["status"] == "unavailable"
    assert layers["expected_layers"] == 2000
    assert layers["examined_layers"] == 0
    assert layers["volume_estimate_mm3"] is None
    assert bundle["status"] == "partial"
    assert bundle["details"]["wall"]["status"] == "measured"
    assert bundle["details"]["sections"]["status"] == "complete"
    assert bundle["profile"]["layer_height_mm"] == .0005


def test_diagonal_placement_is_not_reused_from_another_orientation():
    model, profile = slab_model(), Profile(process="VPP")
    direction = [1., 1., 1.]
    report = review(model, profile, direction, compare=False)
    bundle = run_assessment(model, profile, direction)
    merged = attach_assessment(report, bundle)
    assert merged["details"]["sections"]["volume_quadrature_estimate_mm3"] == pytest.approx(50.)
    np.testing.assert_allclose(merged["details"]["sections"]["placement_transform"],
                               report["current_orientation"]["transform"], atol=1e-12)
    other_report = review(model, profile, [0, 0, 1], compare=False)
    with pytest.raises(ValueError, match="방향"):
        attach_assessment(other_report, bundle)


def test_shared_deadline_reserves_later_queries_and_exhaustion_stays_unknown(monkeypatch):
    model, profile = slab_model(), Profile()
    clock = [0.]
    monkeypatch.setattr(assessment_module.time, "monotonic", lambda: clock[0])
    calls = []

    def runner(model, profile, direction, **kwargs):
        calls.append(kwargs)
        # Deliberately include cleanup/serialization overhead beyond the worker
        # time: the next query must not get a fresh independent full budget.
        clock[0] += 100.
        return unknown_result(model, profile, direction, **kwargs)

    bundle = run_assessment(model, profile, budget_s=9., detail_runner=runner)
    assert len(calls) == 1
    assert calls[0]["timeout_s"] == pytest.approx(2.)
    assert bundle["details"]["layers"]["failure_code"] == "automatic_budget_exhausted"
    assert bundle["details"]["sections"]["failure_code"] == "automatic_budget_exhausted"
    assert bundle["status"] == "unknown"
    assert "measurements" not in bundle["details"]["wall"]


def test_worker_failure_does_not_skip_remaining_modes_or_change_sampling():
    model, profile = slab_model(), Profile()
    calls = []

    def runner(model, profile, direction, **kwargs):
        calls.append(kwargs)
        return unknown_result(model, profile, direction, **kwargs)

    bundle = run_assessment(model, profile, detail_runner=runner)
    assert [call["mode"] for call in calls] == ["wall", "layers", "sections"]
    for call, cap in zip(calls, [10., 20., 15.]):
        assert 0 < call["timeout_s"] <= cap
    assert calls[-1]["sampling"] == "auto"
    assert calls[-1]["sample_count"] == 64
    assert calls[-1]["max_event_samples"] == 8192
    assert bundle["status"] == "unknown"


def test_temporary_file_failure_preserves_explicit_unknown_and_runs_siblings():
    calls = []
    def runner(model, profile, direction, **kwargs):
        calls.append(kwargs["mode"])
        if kwargs["mode"] == "wall":
            raise OSError("temporary write failed")
        return unknown_result(model, profile, direction, **kwargs)
    bundle = run_assessment(slab_model(), Profile(), detail_runner=runner)
    assert calls == ["wall", "layers", "sections"]
    assert bundle["details"]["wall"]["failure_code"] == "automatic_worker_failed"
    assert "temporary write failed" in bundle["details"]["wall"]["reason"]


def test_cancellation_keeps_returned_partial_and_marks_remaining_queries_unknown():
    model, profile = slab_model(), Profile()
    cancelled = [False]

    def runner(model, profile, direction, **kwargs):
        cancelled[0] = True
        result = unknown_result(model, profile, direction, **kwargs)
        result.update(status="partial", measurements={"valid_samples": 1, "minimum_mm": .25})
        return result

    bundle = run_assessment(model, profile, detail_runner=runner,
                            cancel_requested=lambda: cancelled[0])
    assert bundle["cancelled"] and bundle["status"] == "partial"
    assert bundle["details"]["wall"]["measurements"]["minimum_mm"] == .25
    assert bundle["details"]["wall"]["status"] == "partial"
    assert bundle["details"]["layers"]["failure_code"] == "automatic_cancelled"
    assert bundle["details"]["sections"]["failure_code"] == "automatic_cancelled"


@pytest.mark.parametrize("budget", [True, 0, -1, float("nan"), float("inf")])
def test_invalid_time_budget_is_rejected_before_worker(budget):
    with pytest.raises(ValueError, match="시간 예산"):
        run_assessment(slab_model(), Profile(), budget_s=budget,
                       detail_runner=lambda *args, **kwargs: pytest.fail("worker called"))


@pytest.mark.parametrize("mutation", ["model", "profile", "direction", "placement", "code", "missing", "wrong_process", "mixed_detail"])
def test_bundle_rejects_stale_or_mixed_result(mutation):
    model, profile = slab_model(), Profile()
    report = review(model, profile, compare=False)
    bundle = run_assessment(model, profile, detail_runner=unknown_result)
    if mutation == "model":
        bundle["fingerprint"] = "other"
    elif mutation == "profile":
        bundle["profile"]["layer_height_mm"] *= 2
    elif mutation == "direction":
        bundle["direction"] = [1, 0, 0]
    elif mutation == "placement":
        bundle["placement_transform"][0][3] += 1
    elif mutation == "code":
        bundle["code_sha256"] = "old"
    elif mutation == "missing":
        del bundle["details"]["layers"]
    elif mutation == "wrong_process":
        bundle["planned_modes"] = ["wall", "sections"]
    elif mutation == "mixed_detail":
        bundle["details"]["wall"]["direction"] = [1, 0, 0]
    with pytest.raises(ValueError):
        attach_assessment(report, bundle)


def test_matching_old_report_and_bundle_are_rejected_after_code_update(monkeypatch):
    model, profile = slab_model(), Profile()
    report = review(model, profile, compare=False)
    bundle = run_assessment(model, profile, detail_runner=unknown_result)
    monkeypatch.setattr(assessment_module, "code_digest", lambda: "changed-runtime")
    with pytest.raises(ValueError, match="코드 또는 조건 DB"):
        attach_assessment(report, bundle)


def test_failed_fresh_assessment_clears_previous_automatic_measurements():
    model, profile = slab_model(), Profile()
    report = review(model, profile, compare=False)
    report["details"] = dict(wall={"status": "measured", "measurements": {"minimum_mm": 99}},
                             layers={"status": "complete", "volume_estimate_mm3": 99})
    wall = next(item for item in report["findings"] if item["id"] == "wall")
    wall.update(status="observed", measurements={"minimum_mm": 99}, face_indices=[1])
    unchanged = copy.deepcopy(report)
    bundle = run_assessment(model, profile, detail_runner=unknown_result)
    merged = attach_assessment(report, bundle)
    wall = next(item for item in merged["findings"] if item["id"] == "wall")
    assert wall["status"] == "unknown" and wall["measurements"] == {} and wall["face_indices"] == []
    assert "volume_estimate_mm3" not in merged["details"]["layers"]
    assert report == unchanged


def test_surface_input_remains_unknown_for_every_automatic_query():
    model = Model(trimesh.creation.box(), {"source_format": "step", "cad_geometry_kind": "surface"})
    bundle = run_assessment(model, Profile())
    assert bundle["status"] == "unknown"
    assert all(result["status"] == "unknown" for result in bundle["details"].values())
    assert all("재료 내부" in result["reason"] for result in bundle["details"].values())


def test_wrong_mode_runner_result_is_rejected():
    def runner(model, profile, direction, **kwargs):
        result = unknown_result(model, profile, direction, **kwargs)
        result["mode"] = "other"
        return result
    with pytest.raises(ValueError, match="다른 결과"):
        run_assessment(slab_model(), Profile(), detail_runner=runner)
