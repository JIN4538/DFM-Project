import copy
import math

import pytest
import trimesh

from scripts.audit_random_models import sampling_volume_comparison
from scripts.refine_corpus_sections import ranking
from scripts.refresh_corpus_reports import assert_measurements_unchanged, assert_refreshed_report_unchanged
from scripts.inspect_section_events import independent_section


def report(*, surface=False, process="PBF_POLYMER"):
    return dict(geometry={"extents_mm": [10., 20., 30.], "mesh_signed_volume_mm3": None if surface else 6000.},
        current_orientation={"height_mm": 30., "direction": [0., 0., 1.], "build_fit": None},
        orientations=[{"height_mm": 30., "pareto": True, "direction": [0., 0., 1.]}],
        profile={"process": process}, model={"solid_count": 0 if surface else 1,
            "cad_geometry_kind": "surface" if surface else "solid"},
        findings=[{"id": "overhang", "status": "unknown", "measurements": {"area_mm2": None},
            "face_indices": [], "cad_face_ids": []}])


def test_report_refresh_blocks_numeric_and_unknown_to_zero_changes():
    previous = report()
    changed = copy.deepcopy(previous)
    changed["current_orientation"]["height_mm"] = 30.001
    with pytest.raises(ValueError, match="unexpected_changes"):
        assert_measurements_unchanged(previous, changed)
    changed = copy.deepcopy(previous)
    changed["findings"][0]["measurements"]["area_mm2"] = 0.
    with pytest.raises(ValueError, match="unexpected_changes"):
        assert_measurements_unchanged(previous, changed)
    changed = copy.deepcopy(previous)
    changed["orientations"][0]["pareto"] = 1
    with pytest.raises(ValueError, match="unexpected_changes"):
        assert_measurements_unchanged(previous, changed)


def test_report_refresh_only_allows_documented_surface_polymer_scope_change():
    for surface, process, allowed in ((True, "PBF_POLYMER", True), (False, "PBF_POLYMER", False), (True, "VPP", False)):
        previous = report(surface=surface, process=process)
        changed = copy.deepcopy(previous)
        changed["findings"][0]["status"] = "not_applicable"
        if allowed:
            comparison = assert_measurements_unchanged(previous, changed)
            assert len(comparison["allowed_status_changes"]) == 1
            assert comparison["max_float_absolute_difference"] == 0
        else:
            with pytest.raises(ValueError):
                assert_measurements_unchanged(previous, changed)


@pytest.mark.parametrize("before,after", [(1, True), (False, 0), (0, False)])
def test_report_refresh_preserves_boolean_and_measurement_distinction(before, after):
    for category in ("geometry", "measurements"):
        previous = report()
        target = previous["geometry"] if category == "geometry" else previous["findings"][0]["measurements"]
        target["checked_value"] = before
        changed = copy.deepcopy(previous)
        target = changed["geometry"] if category == "geometry" else changed["findings"][0]["measurements"]
        target["checked_value"] = after
        with pytest.raises(ValueError, match="unexpected_changes"):
            assert_measurements_unchanged(previous, changed)


def test_partial_sections_never_gain_a_whole_volume_from_partial_value():
    result = sampling_volume_comparison({"status": "partial", "requested_samples": 64,
        "volume_midpoint_estimate_mm3": 12.}, {"independent_tetra_volume_mm3": 20.}, {"exact_cad_volume_mm3": 20.})
    assert result["volume_midpoint_estimate_mm3"] is None
    assert result["resampling_priority_relative_difference"] is None
    missed = sampling_volume_comparison({"status": "complete", "requested_samples": 64,
        "volume_midpoint_estimate_mm3": 0.}, {"independent_tetra_volume_mm3": 20.}, {"exact_cad_volume_mm3": 20.})
    assert missed["resampling_priority_relative_difference"] == 1.


def test_full_report_refresh_checks_attached_values_while_accepting_provenance():
    previous = report()
    changed = copy.deepcopy(previous)
    measurements = changed["findings"][0]["measurements"]
    measurements.update(source_code_sha256="source", original_detail_sha256="detail", recomputed_in_report_refresh=False)
    assert assert_refreshed_report_unchanged(previous, changed)["finding_measurements_and_face_selections_exact"]
    measurements["area_mm2"] = 0.
    with pytest.raises(ValueError, match="unexpected_changes"):
        assert_refreshed_report_unchanged(previous, changed)


def test_refinement_rank_does_not_spend_top_five_on_one_body_four_times():
    cases = [dict(body=1, process=process, section_status="complete", report_json=process+".json",
        section_volume_comparison={"resampling_priority_relative_difference": .2})
        for process in ("MEX", "VPP", "PBF_POLYMER", "PBF_METAL")]
    cases.append(dict(body=2, process="MEX", section_status="complete", report_json="body2.json",
        section_volume_comparison={"resampling_priority_relative_difference": .3}))
    cases.append(dict(body=3, process="MEX", section_status="unknown"))
    ordered, unranked = ranking({"results": [{"id": "file_001", "relative_path": "part.step", "cases": cases}]})
    assert [row["body"] for row in ordered] == [2, 1]
    assert unranked == 1


def test_independent_section_matches_analytic_polygon_ring():
    # The mesh cross-section is two regular 64-gons, whose area/perimeter have
    # exact trigonometric formulas independent of the checker implementation.
    sides, outer, inner = 64, 2., 1.
    mesh = trimesh.creation.annulus(r_min=inner, r_max=outer, height=5., sections=sides)
    measured = independent_section(mesh, .138671875)
    area = sides/2 * math.sin(2*math.pi/sides) * (outer**2-inner**2)
    perimeter = 2*sides * math.sin(math.pi/sides) * (outer+inner)
    assert measured["area_mm2"] == pytest.approx(area, rel=1e-12)
    assert measured["perimeter_mm"] == pytest.approx(perimeter, rel=1e-12)
    assert measured["rings"] == 2
    assert measured["endpoint_join_max_adjustment_mm"] < 1e-12


def test_independent_section_rejects_an_open_material_contour():
    mesh = trimesh.creation.box([10., 20., 30.])
    keep = [i for i, normal in enumerate(mesh.face_normals) if normal[0] < .5]
    mesh.update_faces(keep)
    with pytest.raises(ValueError, match="closed degree-two"):
        independent_section(mesh, 0.)
