"""Refresh quick-review wording/scope while retaining explicitly sourced details.

The original audit remains untouched. Cached geometry is fingerprint-checked.
Any geometric measurement, direction result, face selection, or unexpected
finding-state change blocks that case instead of relabeling old detail results.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import html
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import traceback


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def engine_digest(root):
    digest = hashlib.sha256()
    for path in sorted((root / "amdfm").glob("*.py")) + sorted((root / "src" / "core").glob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def save(path, value):
    from amdfm.models import json_bytes
    path.write_bytes(json_bytes(value))


def numeric_leaves(value, prefix=""):
    if isinstance(value, dict):
        return {key: child for name, item in value.items() for key, child in numeric_leaves(item, prefix+"/"+name).items()}
    if isinstance(value, list):
        result = {prefix+"/length": len(value)}
        for i, item in enumerate(value):
            result.update(numeric_leaves(item, prefix+f"/{i}"))
        return result
    if value is None or isinstance(value, (bool, int, float)):
        return {prefix: value}
    return {}


def same_numeric_value(before, after):
    # Python considers True == 1 and False == 0. A review status is not a
    # measurement, so either-direction boolean/number changes must be blocked.
    if isinstance(before, bool) or isinstance(after, bool):
        return isinstance(before, bool) and isinstance(after, bool) and before == after
    if before is None or after is None:
        return before is after
    return before == after


def assert_measurements_unchanged(old, new):
    difference, max_float_delta = [], 0.
    for category in ("geometry", "current_orientation", "orientations"):
        first, second = numeric_leaves(old[category]), numeric_leaves(new[category])
        if first.keys() != second.keys():
            difference.append({"category": category, "reason": "numeric structure changed"})
            continue
        for key, before in first.items():
            after = second[key]
            if isinstance(before, float) and isinstance(after, (int, float)) and not isinstance(after, bool):
                max_float_delta = max(max_float_delta, abs(after-before))
                okay = math.isclose(before, after, rel_tol=1e-12, abs_tol=1e-10)
            else:
                okay = same_numeric_value(before, after)
            if not okay:
                difference.append({"category": category, "field": key, "before": before, "after": after})
    previous = {f["id"]: f for f in old["findings"]}
    current = {f["id"]: f for f in new["findings"]}
    if previous.keys() != current.keys():
        difference.append({"category": "findings", "reason": "finding IDs changed"})
    allowed_changes = []
    for identifier in previous.keys() & current.keys():
        before, after = previous[identifier], current[identifier]
        for field in ("measurements", "face_indices", "cad_face_ids"):
            first, second = numeric_leaves(before[field]), numeric_leaves(after[field])
            # Inspection diagnostics and CAD feature identities should reproduce
            # exactly on the cached mesh. Strings may clarify scope/wording.
            if first.keys() != second.keys() or any(not same_numeric_value(value, second[key]) for key, value in first.items()):
                difference.append({"category": identifier, "field": field, "reason": "numeric measurements/selection changed"})
        if before["status"] != after["status"]:
            allowed = (identifier == "overhang" and old["profile"]["process"] == "PBF_POLYMER"
                and old["model"].get("cad_geometry_kind") == "surface" and old["model"].get("solid_count") == 0
                and before["status"] == "unknown" and after["status"] == "not_applicable")
            change = {"finding": identifier, "before": before["status"], "after": after["status"]}
            (allowed_changes if allowed else difference).append(change)
    if difference:
        raise ValueError(json.dumps({"unexpected_changes": difference}, ensure_ascii=False))
    return dict(max_float_absolute_difference=max_float_delta, relative_tolerance=1e-12,
        absolute_tolerance=1e-10, numeric_geometry_and_orientations_unchanged=True,
        finding_measurements_and_face_selections_exact=True, allowed_status_changes=allowed_changes)


def assert_refreshed_report_unchanged(old, new):
    """Check the attached full report as well as the separately checked quick one."""
    previous = {finding["id"]: finding for finding in old["findings"]}
    findings = []
    for finding in new["findings"]:
        measurements = dict(finding["measurements"])
        original = previous.get(finding["id"], {}).get("measurements", {})
        for field in ("source_code_sha256", "recomputed_in_report_refresh", "original_detail_sha256"):
            if field not in original:
                measurements.pop(field, None)
        findings.append(dict(finding, measurements=measurements))
    return assert_measurements_unchanged(old, dict(new, findings=findings))


def worker(args):
    import numpy as np
    import trimesh
    from amdfm.analysis import review, code_digest
    from amdfm.detail import attach_detail
    from amdfm.models import Model
    from amdfm.presentation import html_report
    from amdfm.profiles import Profile
    source = args.audit / args.file_id
    old_record = json.loads((source / "record.json").read_text(encoding="utf-8"))
    record = dict(file_id=args.file_id, source=old_record["source"],
        source_sha256=old_record["source_sha256"], old_file_status=old_record["status"],
        current_quick_code_sha256=code_digest(), source_audit_record_sha256=sha(source / "record.json"),
        status="running", cases=[])
    save(args.out / "record.json", record)
    if not (source / "model.npz").exists():
        record.update(status="no_cached_geometry", reason=old_record.get("error", old_record.get("reason")))
        save(args.out / "record.json", record)
        return 0
    info = json.loads((source / "model.json").read_text(encoding="utf-8"))
    with np.load(source / "model.npz", allow_pickle=False) as arrays:
        model = Model(trimesh.Trimesh(vertices=arrays["vertices"], faces=arrays["faces"], process=False),
            info["metadata"], info["cad_features"], arrays["face_ids"].copy() if "face_ids" in arrays else None,
            arrays["body_ids"].copy() if "body_ids" in arrays else None)
    for old_case in old_record.get("cases", []):
        case = dict(name=old_case["name"], body=old_case["body"], process=old_case["process"], status="running")
        record["cases"].append(case)
        try:
            if old_case["status"] != "reviewed":
                case.update(status="old_case_incomplete", reason="Original detail/report generation did not complete; no successful report is implied.")
                continue
            selected = model.select_body(case["body"])
            old_full = json.loads((source / old_case["report_json"]).read_text(encoding="utf-8"))
            old_quick_path = source / old_case.get("quick_json", case["name"]+"_quick.json")
            old_quick = json.loads(old_quick_path.read_text(encoding="utf-8"))
            if selected.fingerprint != old_full["model_fingerprint"]:
                raise ValueError("Cached geometry fingerprint differs from the source report.")
            report = review(selected, Profile(**old_full["profile"]), old_full["current_orientation"]["direction"],
                dense=old_quick["orientation_search"]["base_candidates"] == 26,
                extended=old_quick["orientation_search"]["include_major_faces"])
            comparison = assert_measurements_unchanged(old_quick, report)
            save(args.out / f"{case['name']}_quick.json", report)
            reused = {}
            for mode, detail in old_full.get("details", {}).items():
                original = source / f"{case['name']}_{mode}.json"
                annotated = dict(detail, source_code_sha256=old_full["provenance"]["code_sha256"],
                    recomputed_in_report_refresh=False,
                    original_detail_sha256=sha(original) if original.exists() else sha(source / old_case["report_json"]))
                report = attach_detail(report, annotated)
                reused[mode] = dict(source_code_sha256=annotated["source_code_sha256"],
                    original_detail_sha256=annotated["original_detail_sha256"], status=detail["status"], recomputed=False)
            if "audit_section_volume_comparison" in old_full:
                report["audit_section_volume_comparison"] = old_full["audit_section_volume_comparison"]
            full_comparison = assert_refreshed_report_unchanged(old_full, report)
            report["audit_refresh_provenance"] = dict(timestamp_utc=datetime.now(timezone.utc).isoformat(),
                current_quick_code_sha256=code_digest(),
                mesh_import_source_code_sha256=old_full["provenance"]["code_sha256"],
                cached_model_fingerprint=selected.fingerprint, original_quick_report_sha256=sha(old_quick_path),
                original_full_report_sha256=sha(source / old_case["report_json"]),
                reused_details=reused, invariant_comparison=comparison,
                full_report_invariant_comparison=full_comparison,
                scope="Only quick review was rerun. Cached geometry and prior detailed measurements are reused with their original code/hash. Numerical geometry/directions/face selections must match; approved PBF surface N/A wording and evidence may change.")
            save(args.out / f"{case['name']}.json", report)
            page = html_report(report).decode("utf-8")
            notice = ("<section><h2>이 보고서의 재검토 범위</h2><p>빠른 검토만 현재 코드로 다시 계산했습니다. "
                "가져온 메시와 벽·층·단면 상세 수치는 원감사의 결과를 재사용했습니다. 상세 계산을 다시 실행한 결과가 아닙니다.</p>"
                f"<p>현재 빠른 검토 코드: {html.escape(code_digest())}</p>"
                f"<p>메시·상세 계산 원코드: {html.escape(old_full['provenance']['code_sha256'])}</p>"
                f"<p>기하·방향 수치와 문제면 선택의 불변성 확인: {html.escape(str(comparison))}</p></section>")
            (args.out / f"{case['name']}.html").write_text(page.replace("</html>", notice+"</html>"), encoding="utf-8")
            case.update(status="refreshed", comparison=comparison,
                full_report_comparison=full_comparison, reused_details=reused,
                report_json=f"{case['name']}.json", report_html=f"{case['name']}.html")
        except Exception as exc:
            case.update(status="blocked_by_difference", error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
        finally:
            save(args.out / "record.json", record)
    record["status"] = "refreshed" if all(c["status"] == "refreshed" for c in record["cases"]) else "partial"
    save(args.out / "record.json", record)
    return 0


def run_one(file_id, args):
    out = args.out / file_id
    out.mkdir()
    command = [sys.executable, str(args.out / "refresh_script.py"), "--worker", "--audit", str(args.audit),
        "--out", str(out), "--file-id", file_id, "--engine-root", str(args.engine_root)]
    with (out / "stdout.log").open("wb") as stdout, (out / "stderr.log").open("wb") as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr, cwd=args.engine_root)
        timed_out = False
        try:
            process.wait(timeout=args.file_timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
            else:
                process.kill()
            process.wait(timeout=30)
    path = out / "record.json"
    record = json.loads(path.read_text(encoding="utf-8")) if path.exists() else dict(file_id=file_id, cases=[])
    if timed_out or process.returncode:
        record.update(status="worker_timeout" if timed_out else "worker_failed")
    save(path, record)
    print(json.dumps(dict(file_id=file_id, status=record["status"], cases=len(record["cases"])), ensure_ascii=True), flush=True)
    return record


def main(args):
    from amdfm.analysis import code_digest
    if args.out.exists():
        raise SystemExit("Choose a fresh output path; original and earlier reports are preserved.")
    summary = json.loads((args.audit / "summary.json").read_text(encoding="utf-8"))
    if summary["completed_files"] != summary["planned_files"]:
        raise SystemExit("Finish the source audit before refreshing the whole corpus.")
    args.out.mkdir(parents=True)
    shutil.copy2(Path(__file__), args.out / "refresh_script.py")
    original_root, digest = args.engine_root, code_digest()
    args.engine_root = args.out / "engine-source"
    args.engine_root.mkdir()
    for package in ("amdfm", "src"):
        shutil.copytree(original_root / package, args.engine_root / package,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if engine_digest(original_root) != digest or engine_digest(args.engine_root) != digest:
        raise SystemExit("Engine changed during snapshot. Preserve this attempt and retry with a fresh output path.")
    save(args.out / "manifest.json", dict(source_audit=str(args.audit), original_engine_root=str(original_root),
        quick_engine_root=str(args.engine_root), quick_code_sha256=digest,
        original_summary_sha256=sha(args.audit / "summary.json"), script_sha256=sha(Path(__file__)),
        scope="Quick review rerun on fingerprint-matched cached geometry; detailed results reused with explicit old code/hash provenance."))
    results = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(run_one, record["id"], args) for record in summary["results"]]
        for future in as_completed(futures):
            results.append(future.result())
            save(args.out / "summary.json", dict(completed_files=len(results), planned_files=len(summary["results"]),
                results=sorted(results, key=lambda x:x["file_id"])))
    links = []
    for record in sorted(results, key=lambda x:x["file_id"]):
        links.append(f"<li>{html.escape(record.get('source', record['file_id']))}: {record['status']}<ul>")
        for case in record["cases"]:
            if case.get("report_html"):
                links.append(f"<li><a href='{record['file_id']}/{case['report_html']}'>{html.escape(case['name'])}</a></li>")
            else:
                links.append(f"<li>{html.escape(case['name'])}: {html.escape(case.get('error', case['status']))}</li>")
        links.append("</ul></li>")
    (args.out / "index.html").write_text("<!doctype html><meta charset='utf-8'><title>Refreshed audit reports</title>"
        "<h1>빠른 검토·근거 갱신 보고서</h1><p>원감사의 상세 수치는 출처를 명시해 재사용했습니다. "
        "현재 빠른 검토 수치·면 선택의 불변성을 확인한 보고서만 제공합니다.</p><ul>" + "".join(links) + "</ul>", encoding="utf-8")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--engine-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--file-timeout", type=float, default=1200)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--file-id", help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.audit, args.out, args.engine_root = args.audit.resolve(), args.out.resolve(), args.engine_root.resolve()
    if args.jobs < 1 or args.file_timeout <= 0:
        parser.error("Positive process and time budgets are required.")
    sys.path.insert(0, str(args.engine_root))
    raise SystemExit(worker(args) if args.worker else main(args))
