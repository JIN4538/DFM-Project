"""Audit local learned review on held-out, dimensioned STEP examples.

This is a geometry-to-rule-to-model integration audit, not an independent
validation of every rule. CAD examples and their expected dimensions are never
training inputs. Each result retains raw predictions, verified actions, missing
measurements, and the exact source/code/model identities.

New output directory only. ``--quick`` uses the first two examples per family;
``--quick 1`` is a shorter smoke run. No existing audit is overwritten.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import platform
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PROCESSES = ("MEX", "VPP", "PBF_POLYMER", "PBF_METAL")
TOOL_CASES = {
    "small": dict(tool_diameter_mm=4., flute_length_mm=8., reach_mm=10.),
    "large": dict(tool_diameter_mm=12., flute_length_mm=15., reach_mm=25.),
    "missing": dict(tool_diameter_mm=None, flute_length_mm=None, reach_mm=None),
}
BASIS = "Held-out geometry integration audit; developer-supplied comparison values"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build_plan(am_cases, cnc_cases, quick=0):
    """Fixed scenarios; expected labels never determine a model input."""
    if quick:
        am_cases, cnc_cases = am_cases[:quick], cnc_cases[:quick]
    plan = []
    for case in am_cases:
        directions = [("z", (0, 0, 1))]
        if not quick and case["id"] in ("07_bracket", "09_cantilever"):
            directions += [("minus_z", (0, 0, -1)), ("diagonal", (1, 1, 1))]
        for process in PROCESSES:
            for direction_id, direction in directions:
                plan.append(dict(family="am", case=case, process=process,
                                 direction=list(direction), condition="limits",
                                 id=f"am_{case['id']}_{process}_{direction_id}_limits"))
            if not quick and case["id"] in ("01_box", "02_thin_plate"):
                plan.append(dict(family="am", case=case, process=process,
                                 direction=[0, 0, 1], condition="missing",
                                 id=f"am_{case['id']}_{process}_z_missing"))
    for case in cnc_cases:
        # All default approaches are fixed +Z, including fixtures authored in
        # other poses. Expected fixture directions are used only in checks.
        directions = [("z", (0, 0, 1))]
        if not quick and case["id"] in ("05_side_hole", "11_rotated_pocket"):
            directions.append(("x", (1, 0, 0)))
        for condition in TOOL_CASES:
            for direction_id, direction in directions:
                plan.append(dict(family="cnc", case=case, process="CNC",
                                 direction=list(direction), condition=condition,
                                 id=f"cnc_{case['id']}_{condition}_{direction_id}"))
    return plan


def numeric_check(name, actual, expected, *, absolute=1e-7, relative=1e-8):
    """Record independent authored dimensions separately from learned labels."""
    def match(left, right):
        if isinstance(right, (list, tuple)):
            return isinstance(left, (list, tuple)) and len(left) == len(right) and all(
                match(a, b) for a, b in zip(left, right))
        return (isinstance(left, (int, float)) and not isinstance(left, bool)
                and math.isfinite(left) and math.isclose(left, right, rel_tol=relative, abs_tol=absolute))
    return dict(name=name, status="pass" if match(actual, expected) else "fail",
                expected=expected, actual=actual, absolute_tolerance=absolute,
                relative_tolerance=relative)


def known_dimension_checks(model, case, report, family):
    expected, metadata, checks = case.get("expected", {}), model.metadata, []
    for key, field in (("volume_mm3", "exact_volume_mm3"),
                       ("constituent_volume_sum_mm3", "constituent_volume_sum_mm3"),
                       ("exact_area_mm2", "exact_area_mm2"), ("solid_count", "solid_count"),
                       ("internal_shell_count", "cavity_shell_count"),
                       ("cavity_shell_count", "cavity_shell_count")):
        if key in expected:
            checks.append(numeric_check(key, metadata.get(field), expected[key]))
    if "extents_mm" in expected:
        checks.append(numeric_check("extents_mm", model.mesh.extents.tolist(), expected["extents_mm"]))
    if "minimum_chord_mm" in expected and family == "am":
        detail = report.get("details", {}).get("wall", {})
        minimum = detail.get("measurements", {}).get("minimum_mm")
        if minimum is None:
            checks.append(dict(name="minimum_chord_mm", status="unavailable",
                               expected=expected["minimum_chord_mm"], actual=None,
                               reason=detail.get("reason", "No wall measurement")))
        else:
            checks.append(numeric_check("minimum_chord_mm", minimum, expected["minimum_chord_mm"]))
    full_cylinders = [row for row in model.cad_features
                      if row.get("kind") == "cylinder" and row.get("role") == "inner"
                      and row.get("full_circumference")]
    diameter = expected.get("cylinder_diameter_mm", expected.get("hole_diameter_mm"))
    if diameter is not None:
        if not full_cylinders:
            checks.append(dict(name="inner_cylinder_diameter_mm", status="fail",
                               expected=diameter, actual=[]))
        for row in full_cylinders:
            checks.append(numeric_check(f"diameter_mm_face_{row['face_id']}", row.get("diameter_mm"), diameter))
            if "cylindrical_length_mm" in expected:
                checks.append(numeric_check(f"length_mm_face_{row['face_id']}", row.get("axial_extent_mm"),
                                            expected["cylindrical_length_mm"]))
    if family == "cnc":
        for is_full, key in ((True, "internal_full_cylinder_face_count"),
                             (False, "internal_partial_cylinder_face_count")):
            if key in expected:
                count = sum(row.get("kind") == "cylinder" and row.get("role") == "inner"
                            and bool(row.get("full_circumference")) == is_full for row in model.cad_features)
                checks.append(numeric_check(key, count, expected[key]))
        direction_matches = all(math.isclose(a, b, abs_tol=1e-10)
                                for a, b in zip(report["direction"], expected.get("direction", [])))
        if len(expected.get("direction", [])) == 3 and direction_matches:
            finding = next(f for f in report["findings"] if f["id"] == "cnc_rectangular_pockets")
            rows = finding["measurements"].get("pockets", [])
            if metadata.get("solid_count") == 1:
                checks.append(numeric_check("rectangular_pocket_count", finding["measurements"].get("count"),
                                            expected["rectangular_pocket_count"]))
            if rows and "pocket_width_mm" in expected:
                for key, field in (("pocket_width_mm", "width_mm"), ("pocket_length_mm", "length_mm"),
                                   ("pocket_wall_height_mm", "wall_height_mm")):
                    checks.append(numeric_check(key, rows[0].get(field), expected[key]))
    return checks


def learned_consistency_checks(report, analysis):
    """Audit public conclusions against independently read report coverage.

    Does not call the learned engine's teacher/features/coverage helpers. Raw
    prediction disagreements are expected to be retained, not counted as an
    integration crash; clearing known issues or missing scope is a failure.
    """
    findings = {item["id"]: item for item in report["findings"]}
    checks = []
    for item in analysis.get("items", []):
        key, state = item["finding_id"], item["state"]
        finding = findings.get(key, {})
        reasons = []
        if state == "clear" and finding.get("status") in ("attention", "unknown", "not_applicable"):
            reasons.append("A known issue or incomplete rule finding was cleared")
        if state == "clear" and key == "wall":
            detail = report.get("details", {}).get("wall", {})
            measurements = detail.get("measurements", {})
            if (report["profile"].get("minimum_wall_mm") is None or detail.get("status") != "measured"
                    or measurements.get("minimum_mm") is None
                    or measurements.get("valid_samples") != measurements.get("requested_samples")
                    or measurements.get("missing_samples") != 0):
                reasons.append("Wall clear requires a criterion and all requested measurements")
        if state == "clear" and key == "cnc_visibility":
            visibility = report.get("visibility") or {}
            if visibility.get("status") != "complete":
                reasons.append("Visibility clear requires a completed sampled check")
        if item.get("origin") == "learned_verified" and item.get("disagreement_rows", 0):
            reasons.append("A disagreement was presented as a verified learned conclusion")
        checks.append(dict(finding_id=key, state=state, source_status=finding.get("status"),
                           status="fail" if reasons else "pass", reasons=reasons))
    return checks


def missing_value_checks(report):
    """Missing source conditions remain absent in actual comparison rows."""
    checks, profile = [], report["profile"]
    requirements = {"cnc_holes": (("tool_diameter_mm", "tool_too_large"),
                                  ("reach_mm", "segment_exceeds_reach")),
                    "cnc_curved_corners": (("tool_diameter_mm", "tool_too_large"),),
                    "cnc_rectangular_pockets": (("tool_diameter_mm", "width_too_small"),
                                                ("flute_length_mm", "exceeds_flute_length"),
                                                ("reach_mm", "exceeds_reach"))}
    for finding in report["findings"]:
        rows = finding.get("measurements", {}).get("cylindrical_faces", []) + finding.get("measurements", {}).get("pockets", [])
        for source, target in requirements.get(finding["id"], ()):
            if profile.get(source) is None:
                bad = [row for row in rows if row.get(target) is not None]
                checks.append(dict(finding_id=finding["id"], source=source, comparison=target,
                                   checked_rows=len(rows), status="fail" if bad else "pass"))
    return checks


def _save_json(path, value):
    from amdfm.models import json_bytes
    with path.open("xb") as stream:
        stream.write(json_bytes(value))


def audit(output, *, quick=0, wall_timeout=10.):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "reports").mkdir()
    started = time.perf_counter()
    # Import after output creation so dependency failures are retained as errors.
    from amdfm.analysis import code_digest, review
    from amdfm.detail import attach_detail, run_detail
    from amdfm.io import load_model
    from amdfm.models import plain
    from amdfm.profiles import Profile
    from dfm.machining import MachiningProfile, review_machining
    from dfm.learned_review import analyze_report

    manifests = {family: ROOT / "examples" / folder / "manifest.json"
                 for family, folder in (("am", "cad"), ("cnc", "machining"))}
    cases = {family: json.loads(path.read_text(encoding="utf-8")) for family, path in manifests.items()}
    plan = build_plan(cases["am"], cases["cnc"], quick)
    revision = code_digest()
    models, records = {}, []
    identities = {}
    header = dict(schema="learned-cad-integration-audit/1", started_utc=utc_now(),
                  code_sha256=revision, root=str(ROOT), python=platform.python_version(), platform=platform.platform(),
                  scope="Held-out CAD integration, authored dimensions, rule coverage, and raw model disagreements",
                  held_out="The authored STEP geometries/labels are not model training rows; training uses synthetic numeric feature vectors",
                  independent_scope="Authored dimensions only; rule agreement is not independent evidence of the rule itself",
                  am_wall_timeout_s=wall_timeout, cnc_visibility="Current production worker: 512 samples, 10-second bound",
                  quick_limit_per_family=quick or None, planned_reports=len(plan),
                  manifests={family: dict(path=str(path), sha256=file_sha(path)) for family, path in manifests.items()})
    _save_json(output / "run.json", header)
    with (output / "records.jsonl").open("x", encoding="utf-8") as journal:
        for index, spec in enumerate(plan, 1):
            case_started = time.perf_counter()
            family, case = spec["family"], spec["case"]
            path = (manifests[family].parent / case["file"]).resolve()
            record = dict(id=spec["id"], timestamp_utc=utc_now(), family=family, process=spec["process"],
                          case_id=case["id"], source_path=str(path), condition=spec["condition"],
                          requested_direction=spec["direction"], code_sha256=revision)
            try:
                if code_digest() != revision:
                    raise RuntimeError("Code/model identity changed during this audit")
                source_sha = file_sha(path)
                record["source_sha256"] = source_sha
                if source_sha != case["sha256"]:
                    raise ValueError("Authored fixture SHA changed: " + case["file"])
                identities[str(path)] = source_sha
                model_key = (family, case["id"])
                if model_key not in models:
                    models[model_key] = load_model(path.read_bytes(), path.name)
                model = models[model_key]
                if family == "am":
                    limit = None if spec["condition"] == "missing" else 1.
                    profile = Profile(process=spec["process"], minimum_wall_mm=limit,
                                      minimum_hole_mm=None if limit is None else 5.,
                                      build_volume_mm=None, threshold_basis=BASIS)
                    report = review(model, profile, spec["direction"], compare=False)
                    detail = run_detail(model, profile, spec["direction"], mode="wall", timeout_s=wall_timeout)
                    report = attach_detail(report, detail)
                else:
                    profile = MachiningProfile(**TOOL_CASES[spec["condition"]], basis=BASIS)
                    report = review_machining(model, profile, spec["direction"], visibility=True)
                    report["code_revision"] = revision
                analysis = analyze_report(report)
                report["learned_review"] = analysis
                dimensions = known_dimension_checks(model, case, report, family)
                consistency = learned_consistency_checks(report, analysis)
                missing = missing_value_checks(report)
                unavailable_model = analysis.get("model", {}).get("sha256") is None
                failures = sum(row["status"] == "fail" for row in dimensions + consistency + missing)
                statuses = {finding["id"]: finding["status"] for finding in report["findings"]}
                covered = {item["finding_id"] for item in analysis.get("items", [])}
                record.update(status="failed" if failures or unavailable_model else "passed",
                              model_fingerprint=model.fingerprint, model_sha256=analysis.get("model", {}).get("sha256"),
                              model_unavailable=unavailable_model, profile=report["profile"],
                              applied_direction=report.get("direction", report.get("current_orientation", {}).get("direction")),
                              dimension_checks=dimensions, conclusion_checks=consistency, missing_value_checks=missing,
                              source_finding_statuses=statuses,
                              unsupported_rule_findings={key: value for key, value in statuses.items() if key not in covered},
                              learned_status=analysis.get("status"), learned_summary=analysis.get("summary"),
                              # Entire per-item records retain raw predictions and
                              # model actions separately from verified actions.
                              learned_items=analysis.get("items", []),
                              report_file="reports/" + spec["id"] + ".json")
                _save_json(output / record["report_file"], report)
            except Exception as exc:
                record.update(status="error", error_type=type(exc).__name__, error=str(exc), traceback=traceback.format_exc())
            record["elapsed_seconds"] = round(time.perf_counter() - case_started, 6)
            record = plain(record)
            journal.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
            journal.flush()
            records.append(record)
            print(json.dumps(dict(index=index, total=len(plan), id=record["id"], status=record["status"],
                                  elapsed_seconds=record["elapsed_seconds"]), ensure_ascii=False), flush=True)
            if code_digest() != revision:
                break  # Do not mix revisions into later reports.
    current_revision = code_digest()
    originals_unchanged = all(file_sha(path) == digest for path, digest in identities.items())
    items = [item for record in records for item in record.get("learned_items", [])]
    counts = Counter(record["status"] for record in records)
    outcome = (len(records) == len(plan) and not counts["failed"] and not counts["error"]
               and current_revision == revision and originals_unchanged)
    summary = dict(**header, finished_utc=utc_now(), elapsed_seconds=round(time.perf_counter() - started, 6),
                   status="passed" if outcome else "failed", final_code_sha256=current_revision,
                   originals_unchanged=originals_unchanged, completed_reports=len(records), report_states=dict(counts),
                   model_sha256=sorted({row["model_sha256"] for row in records if row.get("model_sha256")}),
                   learned_item_states=dict(Counter(item["state"] for item in items)),
                   learned_item_origins=dict(Counter(item["origin"] for item in items)),
                   evaluated_rows=sum(item.get("evaluated_rows", 0) for item in items),
                   learned_rows=sum(item.get("learned_rows", 0) for item in items),
                   raw_disagreement_rows=sum(item.get("disagreement_rows", 0) for item in items),
                   fallback_rows=sum(item.get("fallback_rows", 0) for item in items),
                   unpredicted_rows=sum(item.get("fallback_rows", 0) - item.get("disagreement_rows", 0) for item in items),
                   dimension_checks=dict(Counter(check["status"] for row in records for check in row.get("dimension_checks", []))),
                   conclusion_checks=dict(Counter(check["status"] for row in records for check in row.get("conclusion_checks", []))),
                   missing_value_checks=dict(Counter(check["status"] for row in records for check in row.get("missing_value_checks", []))),
                   failed_cases=[row["id"] for row in records if row["status"] != "passed"])
    _save_json(output / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, allow_nan=False), flush=True)
    return 0 if outcome else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="New audit directory; existing paths are refused")
    parser.add_argument("--quick", nargs="?", const=2, default=0, type=int, metavar="N")
    parser.add_argument("--wall-timeout", default=10., type=float)
    args = parser.parse_args(argv)
    if args.quick < 0 or not math.isfinite(args.wall_timeout) or not 0 < args.wall_timeout <= 60:
        parser.error("quick must be nonnegative; wall timeout must be in (0, 60]")
    try:
        return audit(args.out, quick=args.quick, wall_timeout=args.wall_timeout)
    except FileExistsError:
        parser.error("Output directory already exists; prior audit was preserved")
    except Exception as exc:
        output = args.out.resolve()
        if output.is_dir() and not (output / "fatal-error.json").exists():
            _save_json(output / "fatal-error.json", dict(timestamp_utc=utc_now(), error_type=type(exc).__name__,
                       error=str(exc), traceback=traceback.format_exc()))
        print(f"Audit error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
