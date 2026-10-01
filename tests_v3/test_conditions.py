"""Counterexamples for source -> condition -> engine contracts, not physics tests."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from dfm.conditions import ConditionError, ConditionLibrary, condition_html, load_library, load_literature


def bundle(process="MEX"):
    field = "tool_diameter_mm" if process == "CNC" else "build_volume_mm"
    return {"schema_version": 1, "sources": [{
        "id": "test-source", "title": "Independent synthetic validation fixture", "publisher": "Test only",
        "url": "https://example.org/test-only", "accessed": "2026-09-28", "locator": "Fixture table 1",
        "revision": "test-1", "verification": "primary_source_checked", "limitations": ["Synthetic test data"]}],
        "profiles": [{"id": "test-profile", "label": "Test-only dimensions", "process": process,
          "category": "tool" if process == "CNC" else "machine", "machine": "Test machine",
          "material": "미확정", "conditions": ["Synthetic fixture, not a source-backed production preset"],
          "limitations": ["No physical validation"], "source_ids": ["test-source"],
          "physical_validation": "not_validated_by_project",
          "parameters": {field: {"value": .25 if process == "CNC" else [10, 8, 6], "unit": "inch",
            "kind": "tool_specification" if process == "CNC" else "machine_specification",
            "source_ids": ["test-source"], "locator": "Fixture table 1", "conditions": [], "application": "automatic"}}}]}


def parameter(b):
    return next(iter(b["profiles"][0]["parameters"].values()))


def test_inch_conversion_exact_and_build_restriction_explicit():
    library = ConditionLibrary([bundle()])
    assert library.resolve("test-profile", "MEX")["values"]["build_volume_mm"] == pytest.approx([254., 203.2, 152.4])
    default = library.am_profile("test-profile")
    assert default.build_volume_mm is None
    assert default.minimum_wall_mm is None
    assert default.condition_evidence["fields"]["build_volume_mm"]["status"] == "disabled"
    assert library.am_profile("test-profile", enforce_build_volume=True).build_volume_mm == pytest.approx([254., 203.2, 152.4])


def test_tool_quarter_inch_is_6_35_and_reach_stays_unknown():
    profile = ConditionLibrary([bundle("CNC")]).machining_profile("test-profile")
    assert profile.tool_diameter_mm == 6.35
    assert profile.reach_mm is None
    assert profile.flute_length_mm is None
    assert profile.material == "미확정"


@pytest.mark.parametrize("unit,factor", [("mm", 1), ("cm", 10), ("m", 1000), ("um", .001), ("µm", .001)])
def test_units_are_normalized_not_guessed(unit, factor):
    b = bundle("CNC")
    parameter(b).update(unit=unit, value=2)
    profile = ConditionLibrary([b]).machining_profile("test-profile")
    assert profile.tool_diameter_mm == 2 * factor


@pytest.mark.parametrize("value", [0, -1, None, False, True, float("nan"), float("inf"), "4", [4]])
def test_invalid_engine_values_cannot_become_presets(value):
    b = bundle("CNC")
    parameter(b)["value"] = value
    with pytest.raises(ConditionError):
        ConditionLibrary([b])


@pytest.mark.parametrize("field,value", [("unit", "inch-ish"), ("application", "auto_guess"),
                                           ("source_ids", ["missing"]), ("source_ids", []),
                                           ("kind", "unknown"), ("locator", "")])
def test_incomplete_evidence_rejected(field, value):
    b = bundle("CNC")
    parameter(b)[field] = value
    with pytest.raises(ConditionError):
        ConditionLibrary([b])


def test_wrong_process_and_approximate_model_name_never_match():
    library = ConditionLibrary([bundle("CNC")])
    with pytest.raises(ConditionError):
        library.resolve("test-profile", "MEX")
    with pytest.raises(ConditionError):
        library.resolve("Test profile", "CNC")


@pytest.mark.parametrize("field", ["nozzle_diameter_mm", "overall_length_mm", "spindle_speed_rpm", "strength_mpa"])
def test_unimplemented_fields_can_only_be_reference_information(field):
    b = bundle("CNC")
    p = parameter(b)
    b["profiles"][0]["parameters"] = {field: p}
    with pytest.raises(ConditionError):
        ConditionLibrary([b])
    p["application"] = "reference_only"
    library = ConditionLibrary([b])
    assert field not in library.resolve("test-profile", "CNC")["values"]
    assert library.machining_profile("test-profile").reach_mm is None


def test_experimental_and_material_values_not_promoted_to_automatic_rules():
    for kind in ("material_property", "experimental_result"):
        b = bundle("CNC")
        parameter(b)["kind"] = kind
        with pytest.raises(ConditionError):
            ConditionLibrary([b])


def test_duplicate_ids_and_missing_sources_rejected():
    b = bundle()
    b["profiles"].append(deepcopy(b["profiles"][0]))
    with pytest.raises(ConditionError):
        ConditionLibrary([b])
    b = bundle()
    b["sources"].append(deepcopy(b["sources"][0]))
    with pytest.raises(ConditionError):
        ConditionLibrary([b])


def test_numeric_change_has_distinct_digest_and_report_override():
    b = bundle("CNC")
    old = ConditionLibrary([b])
    parameter(b)["value"] = .5
    new = ConditionLibrary([b])
    assert old.digest != new.digest
    profile = old.machining_profile("test-profile", overrides={"tool_diameter_mm": 4.0})
    record = profile.condition_evidence["fields"]["tool_diameter_mm"]
    assert record == {"expected": 6.35, "effective": 4.0, "overridden": True, "status": "user_override"}
    assert profile.condition_evidence["sources"]["test-source"]["locator"] == "Fixture table 1"
    assert "사용자 변경" in condition_html(profile.condition_evidence)


def test_stale_profile_snapshot_cannot_be_attached_to_changed_engine_conditions():
    profile = ConditionLibrary([bundle("CNC")]).machining_profile("test-profile")
    with pytest.raises(ConditionError):
        replace(profile, tool_diameter_mm=9).validate()


def test_added_user_wall_limit_does_not_inherit_machine_source_authority():
    profile = ConditionLibrary([bundle()]).am_profile("test-profile", overrides={"minimum_wall_mm": 1.0})
    assert "minimum_wall_mm" not in profile.condition_evidence["fields"]
    assert profile.condition_evidence["user_inputs"]["minimum_wall_mm"] == {
        "effective": 1.0, "status": "user_input_or_exploration_default"}
    assert "원자료에 없는" in condition_html(profile.condition_evidence)
    with pytest.raises(ConditionError):
        replace(profile, minimum_wall_mm=2.0).validate()


def test_adding_previously_unknown_limit_requires_fresh_snapshot():
    am = ConditionLibrary([bundle()]).am_profile("test-profile")
    with pytest.raises(ConditionError):
        replace(am, minimum_wall_mm=.6).validate()
    cnc = ConditionLibrary([bundle("CNC")]).machining_profile("test-profile")
    with pytest.raises(ConditionError):
        replace(cnc, reach_mm=50).validate()


def test_user_supplied_basis_is_preserved_by_factory():
    am = ConditionLibrary([bundle()]).am_profile("test-profile", overrides={"minimum_wall_mm": .6, "threshold_basis": "User experiment A"})
    assert am.threshold_basis == "User experiment A"
    cnc = ConditionLibrary([bundle("CNC")]).machining_profile("test-profile", overrides={"reach_mm": 50, "basis": "Measured mounting A"})
    assert cnc.basis == "Measured mounting A"


def test_slicer_metadata_cannot_leak_into_cnc_factory():
    b = bundle("CNC")
    b["profiles"][0]["slicer"] = "Wrong process setting"
    with pytest.raises(ConditionError):
        ConditionLibrary([b])


def test_export_escapes_source_strings():
    b = bundle("CNC")
    b["sources"][0]["title"] = '<script>alert("x")</script>'
    b["profiles"][0]["label"] = "<bad>"
    profile = ConditionLibrary([b]).machining_profile("test-profile")
    html = condition_html(profile.condition_evidence)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&lt;bad&gt;" in html


def test_resolve_returns_detached_snapshot():
    library = ConditionLibrary([bundle()])
    result = library.resolve("test-profile", "MEX")
    result["values"]["build_volume_mm"][0] = 9999
    result["evidence"]["sources"]["test-source"]["title"] = "changed"
    fresh = library.resolve("test-profile", "MEX")
    assert fresh["values"]["build_volume_mm"][0] == 254
    assert fresh["evidence"]["sources"]["test-source"]["title"] != "changed"


def test_library_missing_or_corrupt_is_explicit(tmp_path):
    with pytest.raises(ConditionError):
        load_library(tmp_path)
    (tmp_path / "broken.json").write_text("not JSON", encoding="utf-8")
    with pytest.raises(ConditionError):
        load_library(tmp_path)


def test_duplicate_json_fields_cannot_silently_replace_data(tmp_path):
    (tmp_path / "duplicate.json").write_text('{"schema_version": 1, "schema_version": 2}', encoding="utf-8")
    with pytest.raises(ConditionError, match="중복"):
        load_library(tmp_path)


@pytest.mark.parametrize("bad", [[], None, 5, "not an object"])
def test_wrong_json_structure_reports_actionable_error(bad):
    with pytest.raises(ConditionError):
        ConditionLibrary([bad])


def test_local_literature_index_cannot_supply_any_numeric_thresholds():
    records = load_literature()
    assert len(records) == 43
    assert all(r["automatic_parameters"] == {} for r in records)
    assert all(r["application"] == "background_only" for r in records)
    assert all(len(r["sha256"]) == 64 and r["reading_record_date"] == "2026-09-21" for r in records)


def test_batch_audit_fingerprint_includes_same_condition_data_as_engine():
    from amdfm.analysis import code_digest
    from scripts.audit_random_models import engine_digest as audit_digest
    from scripts.refresh_corpus_reports import engine_digest as refresh_digest
    root = Path(__file__).resolve().parents[1]
    assert audit_digest(root) == refresh_digest(root) == code_digest()
