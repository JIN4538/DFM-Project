"""Partial estimates stay usable without promoting incomplete work to complete."""
from fractions import Fraction
import math

import numpy as np
import pytest
import trimesh

import amdfm.event_sections as events


@pytest.mark.parametrize("mesh", [
    pytest.param(trimesh.creation.icosphere(subdivisions=2, radius=10), id="sphere"),
    pytest.param(trimesh.creation.torus(major_radius=10, minor_radius=3), id="torus"),
])
def test_representation_only_omissions_expose_estimate_without_claiming_complete(mesh):
    result = events.inspect_event_sections(mesh)
    assert result["status"] == "partial"
    assert result["volume_quadrature_estimate_mm3"] is None
    assert result["representation_limit_only"] is True
    assert result["complete_event_intervals"] > 0
    assert result["unexamined_event_intervals"] == 0
    assert result["unresolved_interval_counts"]["representation_limit"] > 0
    assert result["unresolved_interval_counts"]["section_failure"] == 0
    assert all(item["complete"] or item["unresolved_cause"] == "representation_limit"
               for item in result["intervals"])
    triangles = mesh.triangles - mesh.bounds.mean(axis=0)
    tetrahedron_volume = math.fsum(np.einsum("ij,ij->i", triangles[:, 0],
                                           np.cross(triangles[:, 1], triangles[:, 2])) / 6)
    known = result["known_interval_volume_mm3"]
    assert known == pytest.approx(tetrahedron_volume, abs=1e-7)
    assert 0 < result["omitted_interval_volume_envelope_relative_to_known"] < 1e-12
    assert result["known_plus_omitted_envelope_mm3"] >= known
    assert "not certified total-volume lower and upper bounds" in result["envelope_scope"]


def test_missing_all_nodes_is_not_a_measured_zero_volume():
    mesh = trimesh.creation.box()
    upper = np.nextafter(1., 2.)
    mesh.vertices[:, 2] = np.where(mesh.vertices[:, 2] < 0, 1., upper)
    result = events.inspect_event_sections(mesh)
    assert result["representation_limit_only"] is True
    assert result["complete_event_intervals"] == 0
    assert result["status"] == "unknown"
    assert result["volume_quadrature_estimate_mm3"] is None
    assert result["omitted_interval_volume_envelope_relative_to_known"] is None
    assert result["known_plus_omitted_envelope_mm3"] > 0


def test_real_section_failure_is_not_disguised_as_representation_limit(monkeypatch):
    actual_section = events.section_mesh
    calls = 0

    def incomplete_first(*args, **kwargs):
        nonlocal calls
        section = actual_section(*args, **kwargs)
        calls += 1
        if calls == 1:
            section.diagnostics["complete"] = False
            # Reasons are descriptive text, never the machine discriminator.
            section.diagnostics["reason"] = "Gauss node section reconstruction failed"
        return section

    monkeypatch.setattr(events, "section_mesh", incomplete_first)
    result = events.inspect_event_sections(trimesh.creation.icosphere(subdivisions=2, radius=10))
    assert result["status"] == "partial"
    assert result["volume_quadrature_estimate_mm3"] is None
    assert result["unresolved_interval_counts"]["representation_limit"] > 0
    assert result["unresolved_interval_counts"]["section_failure"] == 1
    assert result["representation_limit_only"] is False
    assert result["unexamined_event_intervals"] == 0
    assert result["failure_code"] != "event_budget_exceeded"


@pytest.mark.parametrize("limits, reasons", [
    ({"max_samples": 1}, ["sample_budget"]),
    ({"max_total_segments": 15}, ["intersection_budget"]),
    ({"max_samples": 1, "max_total_segments": 15}, ["sample_budget", "intersection_budget"]),
])
def test_preflight_failure_is_machine_readable_without_fabricated_partial_estimate(monkeypatch, limits, reasons):
    def forbidden(*args, **kwargs):
        pytest.fail("Preflight rejection must precede section reconstruction")

    monkeypatch.setattr(events, "section_mesh", forbidden)
    result = events.inspect_event_sections(trimesh.creation.box(), **limits)
    assert result["failure_code"] == "event_budget_exceeded"
    assert result["budget_reasons"] == reasons
    assert result["unexamined_event_intervals"] == result["event_interval_count"] == 1
    assert result["known_interval_volume_mm3"] is None
    assert result["omitted_interval_volume_envelope_mm3"] is None
    assert result["known_plus_omitted_envelope_mm3"] is None
    assert result["representation_limit_only"] is False


def test_runtime_budget_keeps_remaining_height_in_envelope_and_separate_from_preflight(monkeypatch):
    first = trimesh.creation.box([2, 3, 4])
    second = first.copy()
    first.apply_translation([0, 0, 2])
    second.apply_translation([0, 0, 10])
    mesh = trimesh.util.concatenate([first, second])
    actual_section = events.section_mesh
    calls = 0

    def exceed_after_first_interval(*args, **kwargs):
        nonlocal calls
        section = actual_section(*args, **kwargs)
        calls += 1
        if calls == 3:
            section.diagnostics["segment_count"] = 1001
        return section

    monkeypatch.setattr(events, "section_mesh", exceed_after_first_interval)
    result = events.inspect_event_sections(mesh, max_total_segments=1000)
    assert result["failure_code"] == "event_runtime_budget_exceeded"
    assert result["budget_reasons"] == ["runtime_intersection_budget"]
    assert result["unexamined_event_intervals"] == 1
    assert result["unresolved_interval_counts"]["runtime_budget"] == 1
    assert result["representation_limit_only"] is False
    assert result["complete_event_intervals"] == 1
    assert result["known_interval_volume_mm3"] == pytest.approx(24)
    assert result["unresolved_height_mm"] == 8
    assert result["omitted_interval_volume_envelope_mm3"] == 48
    assert result["known_plus_omitted_envelope_mm3"] == pytest.approx(72)
    assert Fraction(result["known_plus_omitted_envelope_mm3"]) >= (
        Fraction(result["known_interval_volume_mm3"])+Fraction(48))
    assert result["status"] == "partial"
    assert result["volume_quadrature_estimate_mm3"] is None


def test_topology_rejection_has_no_omission_scope_or_automatic_budget_fallback():
    mesh = trimesh.creation.box()
    mesh.update_faces(np.arange(11))
    result = events.inspect_event_sections(mesh)
    assert result["failure_code"] == "input_topology"
    assert result["budget_exceeded"] is False
    assert result["representation_limit_only"] is False
    assert result["unexamined_event_intervals"] is None
    assert result["known_plus_omitted_envelope_mm3"] is None


def test_omitted_bbox_envelope_is_not_rounded_below_exact_input_coordinate_product():
    vertices = np.array([[-0.7, 0.1, 0], [0.2, 0.4, 1]])
    ranges = [(0.2, np.nextafter(0.2, 1.)), (0.4, 0.9)]
    exact_width = sum((Fraction(hi)-Fraction(lo) for lo, hi in ranges), Fraction())
    exact_volume = (Fraction(0.2)-Fraction(-0.7)) * (Fraction(0.4)-Fraction(0.1)) * exact_width
    width, envelope = events._omission_envelope(vertices, ranges)
    assert Fraction(width) >= exact_width
    assert Fraction(np.nextafter(width, 0.)) < exact_width
    assert Fraction(envelope) >= exact_volume
    assert Fraction(np.nextafter(envelope, 0.)) < exact_volume


def test_subnormal_contribution_is_positive_and_overflow_is_unavailable():
    tiny = np.nextafter(0., 1.)
    _, envelope = events._omission_envelope(np.array([[0., 0., 0.], [.5, .5, 1.]]), [(0., tiny)])
    assert envelope == tiny
    _, too_large = events._omission_envelope(np.array([[0., 0., 0.], [1e308, 1e308, 1.]]), [(0., 1e308)])
    assert too_large is None


def test_complete_mesh_has_no_omission_label():
    result = events.inspect_event_sections(trimesh.creation.box([10, 5, 4]))
    assert result["status"] == "complete"
    assert result["representation_limit_only"] is False
    assert result["unexamined_event_intervals"] == 0
    assert result["complete_event_intervals"] == result["event_interval_count"] == 1
    assert result["known_plus_omitted_envelope_mm3"] == result["volume_quadrature_estimate_mm3"] == 200
    assert result["omitted_interval_volume_envelope_relative_to_known"] == 0
