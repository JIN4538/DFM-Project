"""Replay a preserved CAD audit through a new learned-review adapter/model.

Geometry and measurements are reused, not recomputed. The original and current
teacher-source manifests must match for every source except the explicitly
allowed adapter file, dfm/learned_review.py. Original reports/code identities
remain unchanged; new adapter/model identities are recorded separately.

Writes a new directory only and verifies that every source artifact is intact.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.audit_learned_cad import learned_consistency_checks, missing_value_checks

ADAPTER_PATH = "dfm/learned_review.py"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def save(path, value):
    from amdfm.models import json_bytes
    with path.open("xb") as stream:
        stream.write(json_bytes(value))


def checked_teacher_changes(original, current):
    """Only the learned adapter may differ; absent/mismatched keys abort."""
    if not isinstance(original, dict) or not original or set(original) != set(current):
        raise ValueError("Original/current teacher-source manifest keys differ")
    changes = {name: dict(original_sha256=original[name], current_sha256=current[name])
               for name in current if original[name] != current[name]}
    forbidden = set(changes) - {ADAPTER_PATH}
    if forbidden:
        raise ValueError("Geometry/rule source changed; fresh geometry audit required: " + ", ".join(sorted(forbidden)))
    return changes


def unchanged_geometry(original, replayed):
    excluded = {"learned_review", "learned_replay"}
    return ({key: value for key, value in original.items() if key not in excluded}
            == {key: value for key, value in replayed.items() if key not in excluded})


def unlimited_build_check(report, analysis):
    if report["profile"].get("process") not in ("MEX", "VPP", "PBF_POLYMER", "PBF_METAL"):
        return None
    if report["profile"].get("build_volume_mm") is not None:
        return None
    item = next((row for row in analysis.get("items", []) if row.get("finding_id") == "build"), None)
    good = (item is not None and item.get("state") == "unavailable"
            and not item.get("action_ids") and item.get("evaluated_rows", 0) == 0
            and item.get("predicted_issue") is None)
    return dict(name="unrestricted_build_is_not_missing_input", status="pass" if good else "fail",
                state=item.get("state") if item else None, reason=item.get("reason") if item else None)


def replay(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if output == source or output.is_relative_to(source):
        raise ValueError("Replay output must be outside the preserved source directory")
    output.mkdir(parents=True, exist_ok=False)
    (output / "reports").mkdir()
    started = time.perf_counter()
    from amdfm.analysis import code_digest
    from dfm.learned_review import analyze_report, load_model

    source_run = json.loads((source / "run.json").read_text(encoding="utf-8"))
    source_summary = json.loads((source / "summary.json").read_text(encoding="utf-8"))
    source_records = [json.loads(line) for line in (source / "records.jsonl").read_text(encoding="utf-8").splitlines()]
    if (source_summary.get("status") != "passed"
            or len(source_records) != source_summary.get("planned_reports")
            or len(source_records) != source_summary.get("completed_reports")
            or any(record.get("status") != "passed" for record in source_records)):
        raise ValueError("Source must be a complete, passed CAD audit")
    original_code = source_run["code_sha256"]
    if source_summary.get("final_code_sha256") != original_code:
        raise ValueError("Source geometry audit mixed code revisions")
    model = load_model()
    current_teachers = model["teacher_sources"]
    model_sha = model["artifact_sha256"]
    current_code = code_digest()
    source_paths = [source / name for name in ("run.json", "summary.json", "records.jsonl")]
    entries, teacher_changes, original_adapters = [], {}, set()
    for record in source_records:
        path = (source / record["report_file"]).resolve()
        if not path.is_relative_to(source / "reports") or not path.is_file():
            raise ValueError("Source report is outside the preserved report directory")
        original = json.loads(path.read_text(encoding="utf-8"))
        prior_model = original.get("learned_review", {}).get("model", {})
        if prior_model.get("sha256") not in source_summary.get("model_sha256", []):
            raise ValueError("Original report model identity differs from source summary")
        original_teachers = prior_model.get("teacher_sha256")
        changes = checked_teacher_changes(original_teachers, current_teachers)
        teacher_changes.update(changes)
        original_adapters.add(original_teachers[ADAPTER_PATH])
        report_code = original.get("code_revision", original.get("provenance", {}).get("code_sha256"))
        if report_code != original_code or record.get("code_sha256") != original_code:
            raise ValueError("Original report geometry code identity differs from source run")
        if original.get("model_fingerprint") != record.get("model_fingerprint"):
            raise ValueError("Original report geometry identity differs from source record")
        if sha(Path(record["source_path"])) != record.get("source_sha256"):
            raise ValueError("Authored source STEP changed since original audit")
        source_paths.append(path)
        entries.append((record, path, original))
    if len(set(record["id"] for record, _, _ in entries)) != len(entries):
        raise ValueError("Duplicate original report IDs")
    original_hashes = {str(path): sha(path) for path in source_paths}
    header = dict(schema="learned-cad-adapter-replay/1", started_utc=utc_now(), source_audit=str(source),
                  source_run_sha256=original_hashes[str(source / "run.json")],
                  source_records_sha256=original_hashes[str(source / "records.jsonl")],
                  source_summary_sha256=original_hashes[str(source / "summary.json")],
                  original_geometry_code_sha256=original_code, current_code_sha256=current_code,
                  original_adapter_sha256=sorted(original_adapters), current_adapter_sha256=current_teachers[ADAPTER_PATH],
                  current_model_sha256=model_sha, teacher_source_changes=teacher_changes,
                  unchanged_teacher_sources={key: value for key, value in current_teachers.items() if key != ADAPTER_PATH},
                  geometry_recomputed=False, python=platform.python_version(), platform=platform.platform(),
                  scope="New adapter/model inference on preserved geometric measurements; not a fresh geometry run",
                  original_dimension_check_counts=source_summary.get("dimension_checks"),
                  planned_reports=len(entries))
    save(output / "run.json", header)
    records = []
    with (output / "records.jsonl").open("x", encoding="utf-8") as journal:
        for index, (source_record, path, original) in enumerate(entries, 1):
            case_started = time.perf_counter()
            record = dict(id=source_record["id"], timestamp_utc=utc_now(),
                          source_report=str(path), source_report_sha256=original_hashes[str(path)],
                          source_sha256=source_record["source_sha256"],
                          model_fingerprint=source_record["model_fingerprint"],
                          original_geometry_code_sha256=original_code, current_code_sha256=current_code,
                          original_model_sha256=original["learned_review"]["model"]["sha256"],
                          current_model_sha256=model_sha, geometry_recomputed=False)
            try:
                if code_digest() != current_code:
                    raise RuntimeError("Current code/model changed during replay")
                if sha(path) != original_hashes[str(path)]:
                    raise RuntimeError("Preserved source report changed during replay")
                analysis = analyze_report(original)
                if analysis.get("model", {}).get("sha256") != model_sha:
                    raise RuntimeError("Current model unavailable or changed during replay")
                conclusion = learned_consistency_checks(original, analysis)
                missing = missing_value_checks(original)
                build = unlimited_build_check(original, analysis)
                checks = conclusion + missing + ([build] if build else [])
                replayed = deepcopy(original)
                replayed["learned_review"] = analysis
                replayed["learned_replay"] = {**record,
                    "original_adapter_sha256": original["learned_review"]["model"]["teacher_sha256"][ADAPTER_PATH],
                    "current_adapter_sha256": current_teachers[ADAPTER_PATH]}
                if not unchanged_geometry(original, replayed):
                    raise RuntimeError("Replay altered preserved geometric measurements")
                record.update(status="failed" if any(row["status"] == "fail" for row in checks) else "passed",
                              conclusion_checks=conclusion, missing_value_checks=missing, unrestricted_build_check=build,
                              learned_status=analysis.get("status"), learned_summary=analysis.get("summary"),
                              learned_items=analysis.get("items", []),
                              report_file="reports/" + record["id"] + ".json", measurements_unchanged=True)
                save(output / record["report_file"], replayed)
            except Exception as exc:
                record.update(status="error", error_type=type(exc).__name__, error=str(exc), traceback=traceback.format_exc())
            record["elapsed_seconds"] = round(time.perf_counter() - case_started, 6)
            journal.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
            journal.flush()
            records.append(record)
            print(json.dumps(dict(index=index, total=len(entries), id=record["id"], status=record["status"])), flush=True)
            if code_digest() != current_code:
                break
    originals_unchanged = all(sha(Path(path)) == digest for path, digest in original_hashes.items())
    final_code = code_digest()
    states = Counter(record["status"] for record in records)
    items = [item for record in records for item in record.get("learned_items", [])]
    passed = (len(records) == len(entries) and not states["error"] and not states["failed"]
              and originals_unchanged and final_code == current_code)
    summary = dict(**header, finished_utc=utc_now(), elapsed_seconds=round(time.perf_counter() - started, 6),
                   status="passed" if passed else "failed", completed_reports=len(records), report_states=dict(states),
                   originals_unchanged=originals_unchanged, final_code_sha256=final_code,
                   learned_item_states=dict(Counter(item["state"] for item in items)),
                   learned_item_origins=dict(Counter(item["origin"] for item in items)),
                   evaluated_rows=sum(item.get("evaluated_rows", 0) for item in items),
                   learned_rows=sum(item.get("learned_rows", 0) for item in items),
                   raw_disagreement_rows=sum(item.get("disagreement_rows", 0) for item in items),
                   fallback_rows=sum(item.get("fallback_rows", 0) for item in items),
                   unpredicted_rows=sum(item.get("fallback_rows", 0) - item.get("disagreement_rows", 0) for item in items),
                   conclusion_checks=dict(Counter(check["status"] for row in records for check in row.get("conclusion_checks", []))),
                   missing_value_checks=dict(Counter(check["status"] for row in records for check in row.get("missing_value_checks", []))),
                   unrestricted_build_checks=dict(Counter(row["unrestricted_build_check"]["status"] for row in records
                                                       if row.get("unrestricted_build_check"))),
                   failed_cases=[row["id"] for row in records if row["status"] != "passed"])
    save(output / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, allow_nan=False), flush=True)
    return 0 if passed else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        return replay(args.source, args.out)
    except FileExistsError:
        parser.error("Output directory already exists; prior artifacts were preserved")
    except Exception as exc:
        output = args.out.resolve()
        # No error file is written inside the preserved source, even when the
        # caller accidentally chose it as an output destination.
        if (output.is_dir() and output != args.source.resolve()
                and not output.is_relative_to(args.source.resolve())
                and not (output / "fatal-error.json").exists()):
            save(output / "fatal-error.json", dict(timestamp_utc=utc_now(), error_type=type(exc).__name__,
                                                  error=str(exc), traceback=traceback.format_exc()))
        print(f"Replay error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
