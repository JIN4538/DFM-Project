"""Audit safeguards are independent of fitted-model labels and feature code."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from scripts.audit_learned_cad import (audit, build_plan, learned_consistency_checks,
                                     missing_value_checks, numeric_check)

ROOT = Path(__file__).resolve().parents[1]


def manifests():
    return [json.loads((ROOT / "examples" / name / "manifest.json").read_text(encoding="utf-8"))
            for name in ("cad", "machining")]


def test_audit_covers_processes_missing_conditions_and_fixed_alternate_directions():
    am, cnc = manifests()
    rows = build_plan(am, cnc)
    assert len(rows) == 122
    assert len({row["id"] for row in rows}) == len(rows)
    assert {row["process"] for row in rows if row["family"] == "am"} == {
        "MEX", "VPP", "PBF_POLYMER", "PBF_METAL"}
    assert {tuple(row["direction"]) for row in rows} >= {(0, 0, 1), (0, 0, -1), (1, 1, 1), (1, 0, 0)}
    assert sum(row["condition"] == "missing" for row in rows if row["family"] == "am") == 8
    assert sum(row["condition"] == "missing" for row in rows if row["family"] == "cnc") == 14
    assert len(build_plan(am, cnc, quick=2)) == 14


def test_expected_fixture_labels_never_choose_model_inputs():
    am, cnc = manifests()
    original = build_plan(am, cnc)
    changed_am, changed_cnc = deepcopy(am), deepcopy(cnc)
    for case in changed_am + changed_cnc:
        case["expected"] = {"direction": [-1, -2, -3], "volume_mm3": -100,
                            "invented_rule_status": "all_clear"}
    changed = build_plan(changed_am, changed_cnc)
    # Expectations travel as evidence but never choose process/direction/profile.
    without_case = lambda rows: [{k: v for k, v in row.items() if k != "case"} for row in rows]
    assert without_case(original) == without_case(changed)


@pytest.mark.parametrize("source_status", ["attention", "unknown", "not_applicable"])
def test_audit_detects_false_clear_from_known_issue_or_missing_scope(source_status):
    report = {"findings": [dict(id="cnc_holes", status=source_status)], "profile": {}}
    analysis = {"items": [dict(finding_id="cnc_holes", state="clear", origin="learned_verified")]}
    before = deepcopy((report, analysis))
    result = learned_consistency_checks(report, analysis)
    assert result[0]["status"] == "fail"
    assert (report, analysis) == before


def test_wall_clear_needs_real_criterion_and_full_measurement_coverage():
    report = {"findings": [dict(id="wall", status="observed")],
              "profile": {"minimum_wall_mm": None},
              "details": {"wall": {"status": "partial", "measurements": {
                  "minimum_mm": 2., "valid_samples": 4, "requested_samples": 8, "missing_samples": 4}}}}
    analysis = {"items": [dict(finding_id="wall", state="clear", origin="rule_fallback")]}
    assert learned_consistency_checks(report, analysis)[0]["status"] == "fail"


def test_raw_prediction_disagreement_is_retained_and_verified_fallback_is_allowed():
    report = {"findings": [dict(id="cnc_holes", status="attention")], "profile": {}}
    item = dict(finding_id="cnc_holes", state="confirmed", origin="rule_fallback",
                predicted_issue=False, disagreement_rows=2)
    analysis = {"items": [item]}
    assert learned_consistency_checks(report, analysis)[0]["status"] == "pass"
    item["origin"] = "learned_verified"
    assert learned_consistency_checks(report, analysis)[0]["status"] == "fail"


def test_missing_tool_dimension_must_not_become_a_false_comparison():
    row = {"diameter_mm": 5., "tool_too_large": None, "segment_exceeds_reach": None}
    report = {"profile": {"tool_diameter_mm": None, "reach_mm": None},
              "findings": [dict(id="cnc_holes", measurements={"cylindrical_faces": [row]})]}
    assert all(item["status"] == "pass" for item in missing_value_checks(report))
    row["tool_too_large"] = False
    assert next(item for item in missing_value_checks(report) if item["source"] == "tool_diameter_mm")["status"] == "fail"


def test_existing_audit_directory_is_refused_before_any_geometry_or_model_load(tmp_path):
    marker = tmp_path / "preserve.txt"
    marker.write_text("prior result", encoding="utf-8")
    with pytest.raises(FileExistsError):
        audit(tmp_path, quick=1)
    assert marker.read_text(encoding="utf-8") == "prior result"
    assert list(tmp_path.iterdir()) == [marker]


def test_authored_dimension_check_rejects_missing_nonfinite_and_boolean_values():
    for value in (None, float("nan"), float("inf"), True):
        assert numeric_check("dimension", value, 1)["status"] == "fail"
    assert numeric_check("extents", [10., 20., 30.], [10., 20., 30.])["status"] == "pass"
    assert numeric_check("extents", [10., 20., 31.], [10., 20., 30.])["status"] == "fail"
