"""Resample the largest complete-section volume discrepancies in a corpus audit.

Reuses that audit's frozen engine and exact cached mesh, never the current edited
checkout. Ranks geometric targets once across processes because these sections
are process-neutral geometry. A discrepancy is not a printer or kernel failure.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


def save(path, value):
    from amdfm.models import json_bytes
    path.write_bytes(json_bytes(value))


def ranking(summary):
    candidates = {}
    unranked_cases = 0
    for record in summary["results"]:
        for case in record.get("cases", []):
            comparison = case.get("section_volume_comparison", {})
            priority = comparison.get("resampling_priority_relative_difference")
            if priority is None or case.get("section_status") != "complete":
                unranked_cases += 1
                continue
            key = (record["id"], case["body"])
            candidate = dict(file_id=record["id"], source=record["relative_path"], body=case["body"],
                representative_process=case["process"], report_json=case["report_json"],
                baseline_comparison=comparison, priority=priority)
            if key not in candidates or priority > candidates[key]["priority"]:
                candidates[key] = candidate
    return sorted(candidates.values(), key=lambda x: (-x["priority"], x["file_id"], str(x["body"]))), unranked_cases


def compare_volume(detail, baseline):
    estimate = detail.get("volume_midpoint_estimate_mm3") if detail["status"] == "complete" else None
    tetra = baseline.get("independent_tetra_volume_mm3")
    cad = baseline.get("exact_cad_volume_mm3")
    return dict(requested_samples=detail.get("requested_samples", detail.get("sample_count")),
        status=detail["status"], reason=detail.get("reason"), complete_samples=detail.get("complete_samples"),
        volume_midpoint_estimate_mm3=estimate, sampled_max_area_mm2=detail.get("sampled_max_area_mm2"),
        independent_tetra_volume_mm3=tetra, exact_cad_volume_mm3=cad,
        estimate_vs_tetra_relative_difference=abs(estimate-tetra)/abs(tetra) if estimate is not None and tetra else None,
        estimate_vs_cad_relative_difference=abs(estimate-cad)/abs(cad) if estimate is not None and cad else None)


def worker(args):
    import numpy as np
    import trimesh
    from amdfm.analysis import code_digest
    from amdfm.detail import run_detail, attach_detail
    from amdfm.models import Model
    from amdfm.presentation import html_report
    from amdfm.profiles import Profile
    target = json.loads((args.out / "target.json").read_text(encoding="utf-8"))
    folder = args.audit / target["file_id"]
    model_info = json.loads((folder / "model.json").read_text(encoding="utf-8"))
    with np.load(folder / "model.npz", allow_pickle=False) as arrays:
        mesh = trimesh.Trimesh(vertices=arrays["vertices"], faces=arrays["faces"], process=False)
        model = Model(mesh, model_info["metadata"], model_info["cad_features"],
            arrays["face_ids"].copy() if "face_ids" in arrays else None,
            arrays["body_ids"].copy() if "body_ids" in arrays else None)
    selected = model.select_body(target["body"])
    base_report = json.loads((folder / target["report_json"]).read_text(encoding="utf-8"))
    if selected.fingerprint != base_report["model_fingerprint"]:
        raise ValueError("Cached model fingerprint does not match the original audited target.")
    if code_digest() != base_report["provenance"]["code_sha256"]:
        raise ValueError("Refinement engine differs from the original audited engine.")
    profile = Profile(**base_report["profile"])
    record = dict(target=target, code_sha256=code_digest(), model_fingerprint=selected.fingerprint,
        status="running", results=[], scope="Process-neutral section geometry; representative process context preserved. Finite quadrature differences trigger refinement, not automatic printability judgments.")
    save(args.out / "record.json", record)
    for count in args.samples:
        started = time.perf_counter()
        detail = run_detail(selected, profile, base_report["current_orientation"]["direction"],
            mode="sections", sample_count=count, timeout_s=args.detail_timeout)
        save(args.out / f"sections_{count}.json", detail)
        comparison = compare_volume(detail, target["baseline_comparison"])
        comparison.update(elapsed_seconds=time.perf_counter()-started,
            requested_samples=count, detail_json=f"sections_{count}.json")
        record["results"].append(comparison)
        report = attach_detail(base_report, detail)
        report["audit_refinement"] = dict(timestamp_utc=datetime.now(timezone.utc).isoformat(),
            baseline_comparison=target["baseline_comparison"], new_comparison=comparison)
        save(args.out / f"report_{count}.json", report)
        (args.out / f"report_{count}.html").write_bytes(html_report(report))
        save(args.out / "record.json", record)
    record["status"] = "completed"
    save(args.out / "record.json", record)
    return 0


def run_one(target, index, args):
    out = args.out / f"rank_{index:02d}"
    out.mkdir()
    save(out / "target.json", target)
    command = [sys.executable, str(args.out / "refinement_script.py"), "--worker", "--audit", str(args.audit),
        "--out", str(out), "--samples", *(str(x) for x in args.samples), "--detail-timeout", str(args.detail_timeout)]
    with (out / "stdout.log").open("wb") as stdout, (out / "stderr.log").open("wb") as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr, cwd=args.engine_root)
        timed_out = False
        try:
            process.wait(timeout=len(args.samples)*args.detail_timeout + 120)
        except subprocess.TimeoutExpired:
            timed_out = True
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
            else:
                process.kill()
            process.wait(timeout=30)
    path = out / "record.json"
    result = json.loads(path.read_text(encoding="utf-8")) if path.exists() else dict(target=target, results=[])
    if timed_out or process.returncode:
        result.update(status="worker_timeout" if timed_out else "worker_failed",
            error="See stderr.log; completed detail files are retained.")
    result["rank"] = index
    result["directory"] = out.name
    save(path, result)
    print(json.dumps(dict(source=target["source"], body=target["body"], status=result["status"], rank=index), ensure_ascii=True), flush=True)
    return result


def main(args):
    from amdfm.analysis import code_digest
    if args.out.exists():
        raise SystemExit("Choose a fresh output directory; prior refinements are preserved.")
    summary = json.loads((args.audit / "summary.json").read_text(encoding="utf-8"))
    if summary["completed_files"] != summary["planned_files"]:
        raise SystemExit("The source audit is incomplete; do not rank a partial corpus as all inputs.")
    candidates, unranked = ranking(summary)
    args.out.mkdir(parents=True)
    shutil.copy2(Path(__file__), args.out / "refinement_script.py")
    save(args.out / "manifest.json", dict(source_audit=str(args.audit), engine_root=str(args.engine_root),
        code_sha256=code_digest(), sample_counts=args.samples, detail_timeout_s=args.detail_timeout,
        script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        eligible_unique_targets=len(candidates), unranked_cases=unranked,
        ranking=candidates, selected=candidates[:args.top],
        ranking_scope="Complete finite-section estimates with positive tetra/CAD reference volume only. One target per source/body, not repeated once per process. Unknown cases require separate diagnosis and have no numeric rank."))
    results = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(run_one, target, i, args) for i, target in enumerate(candidates[:args.top], 1)]
        for future in as_completed(futures):
            results.append(future.result())
            save(args.out / "summary.json", dict(results=sorted(results, key=lambda x:x["rank"])))
    rows = []
    for result in sorted(results, key=lambda x:x["rank"]):
        target = result["target"]
        baseline = target["baseline_comparison"]
        levels = [dict(requested_samples=baseline["sample_count"], **{k:baseline.get(k) for k in (
            "volume_midpoint_estimate_mm3", "estimate_vs_tetra_relative_difference", "estimate_vs_cad_relative_difference")})]
        levels += result["results"]
        for level in levels:
            sample = level["requested_samples"]
            link = (f"<a href='{result['directory']}/report_{sample}.html'>{sample}</a>" if level.get("detail_json") else str(sample))
            fields = [target["source"], str(target["body"]), link, str(level.get("status", "baseline complete")),
                str(level.get("volume_midpoint_estimate_mm3")), str(level.get("estimate_vs_tetra_relative_difference")),
                str(level.get("estimate_vs_cad_relative_difference"))]
            rows.append("<tr>" + "".join(f"<td>{value if i == 2 else html.escape(value)}</td>" for i, value in enumerate(fields)) + "</tr>")
    (args.out / "index.html").write_text("<!doctype html><meta charset='utf-8'><title>Section resampling</title>"
        "<style>body{font-family:system-ui;padding:30px}td,th{border:1px solid #ddd;padding:8px}table{border-collapse:collapse}</style>"
        "<h1>단면 표본 수 증가에 따른 변화</h1><p>차이는 유한 표본 적분의 재검토 지표입니다. 단조 수렴이나 표본 사이 최대값을 보장하지 않습니다. "
        "공정에 공통인 기하량이므로 입력·솔리드별 대표 공정 하나에서 재계산했습니다.</p>"
        "<table><tr><th>형상</th><th>솔리드</th><th>표본 수</th><th>상태</th><th>적분 체적 mm³</th>"
        "<th>테트라 기준 상대 차</th><th>CAD 기준 상대 차</th></tr>" + "".join(rows) + "</table>", encoding="utf-8")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--samples", type=int, nargs="+", default=[256, 1024])
    parser.add_argument("--detail-timeout", type=float, default=300)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    args.audit, args.out = args.audit.resolve(), args.out.resolve()
    if args.top < 1 or args.jobs < 1 or args.detail_timeout <= 0 or any(not 2 <= x <= 1024 for x in args.samples):
        parser.error("Positive budgets and sample counts between 2 and 1024 are required.")
    args.engine_root = Path(json.loads((args.audit / "manifest.json").read_text(encoding="utf-8"))["engine_root"])
    sys.path.insert(0, str(args.engine_root))
    raise SystemExit(worker(args) if args.worker else main(args))
