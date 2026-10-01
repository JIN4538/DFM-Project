"""Apply real catalog records to independent analytic and STEP fixtures."""
from pathlib import Path

import pytest
import trimesh

from amdfm.analysis import review
from amdfm.io import load_model
from amdfm.models import Model, json_bytes
from amdfm.presentation import html_report
from dfm.conditions import load_library
from dfm.machining import review_machining

ROOT = Path(__file__).resolve().parents[1]
LIBRARY = load_library()
AM = [p for p in LIBRARY.profiles.values() if p["process"] != "CNC"]
TOOLS = [p for p in LIBRARY.profiles.values() if p["category"] == "tool" and p["process"] == "CNC"]


@pytest.fixture(scope="module")
def box():
    path = ROOT / "examples/cad/01_box.step"
    return load_model(path.read_bytes(), path.name)


@pytest.fixture(scope="module")
def narrow_pocket():
    path = ROOT / "examples/machining/02_narrow_deep_pocket.step"
    return load_model(path.read_bytes(), path.name)


@pytest.mark.parametrize("record", AM, ids=lambda p: p["id"])
def test_every_am_record_preserves_source_context_in_engine(box, record):
    profile = LIBRARY.am_profile(record["id"])
    report = review(box, profile, compare=False)
    assert report["current_orientation"]["height_mm"] == pytest.approx(30)
    assert report["current_orientation"]["build_fit"] is None
    assert report["profile"]["condition_evidence"]["profile_id"] == record["id"]
    assert report["profile"]["condition_evidence"]["database_sha256"] == LIBRARY.digest
    assert report["profile"]["minimum_wall_mm"] is None  # conditional guides are not universal walls
    assert "success_probability" not in report
    assert b"not_validated_by_project" in json_bytes(report)
    assert "조건 DB" in html_report(report).decode("utf-8")


@pytest.mark.parametrize("record", [p for p in AM if p["parameters"].get("build_volume_mm", {}).get("application") == "automatic"], ids=lambda p: p["id"])
def test_machine_build_constraint_changes_only_when_enabled(record):
    profile = LIBRARY.am_profile(record["id"], enforce_build_volume=True)
    limits = profile.build_volume_mm
    mesh = trimesh.creation.box(extents=[limits[0] + 1, 10, 10])
    model = Model(mesh=mesh, metadata={"source_format": "stl"})
    constrained = review(model, profile, compare=False)
    unrestricted = review(model, LIBRARY.am_profile(record["id"]), compare=False)
    assert constrained["current_orientation"]["build_fit"] is False
    assert unrestricted["current_orientation"]["build_fit"] is None


@pytest.mark.parametrize("record", TOOLS, ids=lambda p: p["id"])
def test_every_catalog_tool_against_independent_3mm_width_20mm_depth(narrow_pocket, record):
    profile = LIBRARY.machining_profile(record["id"])
    report = review_machining(narrow_pocket, profile)
    result = next(f for f in report["findings"] if f["id"] == "cnc_rectangular_pockets")
    pocket = result["measurements"]["pockets"][0]
    assert pocket["width_mm"] == pytest.approx(3)
    assert pocket["wall_height_mm"] == pytest.approx(20)
    assert pocket["width_too_small"] == (profile.tool_diameter_mm > 3)
    assert pocket["exceeds_flute_length"] == (profile.flute_length_mm < 20)
    assert pocket["exceeds_reach"] is None
    assert report["profile"]["condition_evidence"]["database_sha256"] == LIBRARY.digest
    assert report["profile"]["reach_mm"] is None


def test_form4_and_fuse_wall_guides_not_misapplied_to_other_materials():
    form = LIBRARY.profiles["am-form4-grey-v5-005"]
    assert form["parameters"]["supported_wall_guidance_mm"]["value"] == .2
    assert form["parameters"]["supported_wall_guidance_mm"]["application"] == "reference_only"
    fuse = LIBRARY.profiles["am-fuse-nylon12"]
    assert fuse["parameters"]["vertical_wall_guidance_mm"]["value"] == .6
    assert fuse["parameters"]["horizontal_wall_guidance_mm"]["value"] == .3
    assert LIBRARY.am_profile(fuse["id"]).minimum_wall_mm is None
    assert LIBRARY.am_profile("am-fuse-nylon12gf").minimum_wall_mm is None


def test_known_catalog_disagreement_is_not_published_as_verified_tool():
    assert "cnc-datron-0068080e" not in LIBRARY.profiles


def test_catalog_reach_not_used_as_mounted_length_and_dimensions_not_inherited():
    profile = LIBRARY.machining_profile("cnc-harvey-677761")
    assert profile.tool_diameter_mm == 4
    assert profile.flute_length_mm == 12
    assert profile.reach_mm is None
    assert "catalog_overall_reach_mm" not in profile.condition_evidence["expected_values"]


def test_exact_slicer_selection_changes_layer_and_nominal_width_only():
    profile = LIBRARY.am_profile("am-prusa-mk4-pla-015")
    assert profile.layer_height_mm == .15
    assert profile.line_width_mm == .45
    assert profile.minimum_wall_mm is None
    assert profile.build_volume_mm is None
    assert "nozzle_temperature_c" not in profile.condition_evidence["expected_values"]
    assert profile.condition_evidence["parameters"]["nozzle_temperature_c"]["application"] == "reference_only"
