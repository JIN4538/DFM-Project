"""Reproducible, read-only corpus audit with isolated per-file computation.

The input directory is never modified. Every invocation requires a fresh output
directory. Unsupported inputs, time limits, and incomplete bodies remain records.
Use --engine-root to test a frozen source tree instead of the current checkout.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import html
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import traceback

FORMATS = {".step", ".stp", ".stl", ".3mf"}
PROCESSES = ("MEX", "VPP", "PBF_POLYMER", "PBF_METAL")


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def engine_digest(root):
    digest = hashlib.sha256()
    files = sorted((root / "amdfm").glob("*.py")) + sorted((root / "src" / "core").glob("*.py"))
    for path in files:
        digest.update(path.relative_to(root).as_posix().encode())
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(65536), b""):
                digest.update(block)
    return digest.hexdigest()


def save(path, value):
    from amdfm.models import json_bytes
    path.write_bytes(json_bytes(value))


def file_report_html(record):
    """Readable index for every file, including rejected and timed-out files."""
    esc = lambda x: html.escape(str(x))
    rows = []
    for case in record.get("cases", []):
        link = (f"<a href='{esc(case['report_html'])}'>{esc(case['name'])}</a>"
                if case.get("report_html") else esc(case["name"]))
        rows.append("<tr>" + "".join(f"<td>{x}</td>" for x in (link,
            esc(case.get("status")), esc(case.get("review_status")), esc(case.get("wall_status")),
            esc(case.get("layer_status")), esc(case.get("section_status")),
            esc(case.get("section_complete_samples")), esc(case.get("error", "")))) + "</tr>")
    return ("<!doctype html><html lang='ko'><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
        "<style>body{font-family:system-ui,sans-serif;max-width:1200px;margin:30px auto;padding:20px}"
        "table{border-collapse:collapse;width:100%}td,th{border:1px solid #ddd;padding:8px;text-align:left}"
        "pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>"
        f"<title>{esc(record.get('relative_path', record.get('source')))}</title>"
        f"<h1>{esc(record.get('relative_path', record.get('source')))}</h1>"
        f"<p>파일 검토 상태: {esc(record.get('status'))}</p>"
        f"<p>{esc(record.get('error', record.get('reason', '')))}</p>"
        "<p>빌드 공간 제한 없음. STL 치수는 mm 가정이며 원본은 변경하지 않았습니다. "
        "측정 완료는 제조 성공 판정이 아닙니다. 미확정·부분·해당 없음은 계산된 수치와 구분합니다.</p>"
        f"<p>SHA-256: {esc(record.get('source_sha256'))}</p>"
        f"<p>분석 코드 SHA-256: {esc(record.get('code_sha256'))}</p>"
        "<p><a href='record.json'>전체 파일 기록 JSON</a></p>"
        "<table><tr><th>대상·공정 보고서</th><th>계산</th><th>입력 기하</th><th>법선 거리</th>"
        "<th>MEX 층</th><th>공통 단면</th><th>확정 단면 수</th><th>오류</th></tr>"
        + "".join(rows) + "</table></html>").encode("utf-8")


def sampling_volume_comparison(sections, independent, geometry):
    """Sampling discrepancy ranks refinement needs; it is not a kernel error."""
    estimate = sections.get("volume_midpoint_estimate_mm3") if sections["status"] == "complete" else None
    tetra = independent.get("independent_tetra_volume_mm3")
    cad = geometry.get("exact_cad_volume_mm3")
    comparison = dict(sample_count=sections.get("requested_samples"),
        volume_midpoint_estimate_mm3=estimate, independent_tetra_volume_mm3=tetra,
        exact_cad_volume_mm3=cad,
        estimate_vs_tetra_relative_difference=(abs(estimate-tetra)/abs(tetra) if estimate is not None and tetra else None),
        estimate_vs_cad_relative_difference=(abs(estimate-cad)/abs(cad) if estimate is not None and cad else None),
        scope="Finite uniform midpoint quadrature; discrepancy is a resampling priority, not proof of a geometry-kernel error. Partial sections have no whole-volume estimate.")
    differences = [comparison[key] for key in ("estimate_vs_tetra_relative_difference", "estimate_vs_cad_relative_difference")
        if comparison[key] is not None]
    comparison["resampling_priority_relative_difference"] = max(differences) if differences else None
    return comparison


def diagnostic_comparison(model, report):
    """Independent coordinate/cross-product arithmetic; no engine helpers."""
    import numpy as np
    vertices = np.asarray(model.mesh.vertices)
    tri = vertices[model.mesh.faces]
    cross = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    lengths = np.linalg.norm(cross, axis=1)
    normals = np.divide(cross, lengths[:, None], out=np.zeros_like(cross), where=lengths[:, None] > 0)
    area = lengths / 2
    failures, maximum_height_error, maximum_projection_error = [], 0., 0.
    reliable = report["summary"]["review_status"] == "geometry_review"
    for row in report["orientations"]:
        direction = np.asarray(row["direction"])
        axial = vertices @ direction
        expected_height = float(axial.max() - axial.min())
        error = abs(expected_height - row["height_mm"])
        maximum_height_error = max(maximum_height_error, error)
        tolerance = max(1e-9, expected_height * 1e-10)
        if error > tolerance:
            failures.append({"check": "axial_height", "direction": row["name"], "error_mm": error})
        rotation = np.asarray(row["transform"])[:3, :3]
        if not np.allclose(rotation @ rotation.T, np.eye(3), atol=1e-12, rtol=0):
            failures.append({"check": "rigid_rotation", "direction": row["name"]})
        if row["build_fit"] is not None:
            failures.append({"check": "unrestricted_build", "direction": row["name"]})
        if reliable and row["overhang_projected_area_sum_mm2"] is not None:
            translated = axial - axial.min()
            placed = vertices @ rotation.T
            tolerance = max(1e-9, float(np.ptp(placed, axis=0).max()) * 1e-10)
            on_plate = translated[model.mesh.faces].max(axis=1) <= tolerance
            dots = normals @ direction
            mask = (dots < -np.cos(np.deg2rad(report["profile"]["overhang_angle_deg"])) - 1e-12) & ~on_plate
            expected = float(np.sum(area[mask] * -dots[mask]))
            error = abs(expected - row["overhang_projected_area_sum_mm2"])
            maximum_projection_error = max(maximum_projection_error, error)
            if error > max(1e-8, expected * 1e-10):
                failures.append({"check": "projected_facet_sum", "direction": row["name"], "error_mm2": error})
    cad_volume = model.metadata.get("exact_volume_mm3")
    mesh_volume = report["geometry"]["mesh_signed_volume_mm3"]
    local_tri = tri - vertices.mean(axis=0)
    # Signed tetrahedra about a local reference point, independently of the
    # trimesh mass-properties integration used by the production report.
    tetra = float(np.sum(np.einsum("ij,ij->i", local_tri[:, 0],
        np.cross(local_tri[:, 1], local_tri[:, 2]))) / 6)
    cad_bodies = model.metadata.get("bodies", [])
    selected_body = model.metadata.get("selected_body")
    if selected_body is not None:
        cad_bodies = [b for b in cad_bodies if b["body_id"] == selected_body]
    cad_bounds = None
    if cad_bodies:
        bounds = np.asarray([b["bounds_mm"] for b in cad_bodies])
        cad_bounds = np.array([bounds[:, 0].min(axis=0), bounds[:, 1].max(axis=0)])
    return dict(scope="Independent arithmetic on the same tessellation; does not validate tessellation against every CAD surface or printing physics.",
        orientation_count=len(report["orientations"]), failures=failures,
        max_height_error_mm=maximum_height_error, max_projection_error_mm2=maximum_projection_error,
        independent_tetra_volume_mm3=tetra if mesh_volume is not None else None,
        tetra_vs_report_volume_absolute_difference_mm3=(abs(tetra-mesh_volume) if mesh_volume is not None else None),
        cad_mesh_volume_relative_error=(abs(mesh_volume-cad_volume)/cad_volume if cad_volume and mesh_volume is not None else None),
        cad_mesh_area_relative_error=(abs(float(area.sum())-model.metadata["exact_area_mm2"])/model.metadata["exact_area_mm2"] if model.metadata.get("exact_area_mm2") else None),
        cad_bounds_mm=cad_bounds,
        cad_mesh_bounds_max_abs_difference_mm=(float(np.max(np.abs(cad_bounds-model.mesh.bounds))) if cad_bounds is not None else None))


def worker(args):
    import numpy as np
    from amdfm.analysis import review, code_digest
    from amdfm.detail import run_detail, attach_detail
    from amdfm.io import load_model
    from amdfm.models import plain
    from amdfm.presentation import html_report
    from amdfm.profiles import Profile
    path, out = Path(args.file), Path(args.out)
    started = time.perf_counter()
    record = dict(source=str(path), source_sha256=sha(path), format=path.suffix.lower(),
        code_sha256=code_digest(), status="running", cases=[], original_unchanged=None,
        conditions=dict(build_volume_mm=None, direction=[0, 0, 1], dense_candidates=26,
            stl_scale="mm assumption; unconfirmed; no resizing", deflection_mm=args.deflection,
            cad_timeout_s=args.cad_timeout, detail_timeout_s=args.detail_timeout,
            file_timeout_s=args.file_timeout, detail_processes=args.detail_processes,
            section_samples=args.section_samples))
    save(out / "record.json", record)
    try:
        load_started = time.perf_counter()
        model = load_model(path.read_bytes(), path.name, dimensions_confirmed=False,
            deflection_mm=args.deflection, timeout_s=args.cad_timeout)
        record.update(import_seconds=time.perf_counter()-load_started,
            metadata=model.metadata, faces=len(model.mesh.faces), vertices=len(model.mesh.vertices),
            extents_mm=model.mesh.extents.tolist(), fingerprint=model.fingerprint)
        arrays = dict(vertices=model.mesh.vertices, faces=model.mesh.faces)
        if model.face_ids is not None:
            arrays.update(face_ids=model.face_ids, body_ids=model.body_ids)
        np.savez_compressed(out / "model.npz", **arrays)
        save(out / "model.json", dict(metadata=model.metadata, cad_features=model.cad_features))
        save(out / "record.json", record)
        print(json.dumps(dict(file=path.name, import_seconds=record["import_seconds"], faces=record["faces"],
            solids=model.metadata.get("solid_count"), status="imported"), ensure_ascii=True), flush=True)
        bodies = [None]
        if model.metadata.get("solid_count", 0) and model.metadata["solid_count"] > 1:
            bodies.extend(sorted(int(x) for x in np.unique(model.body_ids)))
        record["planned_cases"] = len(bodies) * len(PROCESSES)
        record["planned_bodies"] = bodies
        for body in bodies:
            selected = model.select_body(body)
            for process in PROCESSES:
                label = f"{'whole' if body is None else f'body_{body:03d}'}_{process}"
                case_started = time.perf_counter()
                case = dict(name=label, body=body, process=process, status="running", stage="quick")
                record["cases"].append(case)
                save(out / "record.json", record)
                try:
                    profile = Profile(process=process, build_volume_mm=None)
                    report = review(selected, profile, dense=True)
                    independent = diagnostic_comparison(selected, report)
                    save(out / f"{label}_quick.json", report)
                    case.update(quick_json=f"{label}_quick.json", independent=independent,
                        review_status=report["summary"]["review_status"], geometry=report["geometry"], stage="wall")
                    save(out / "record.json", record)
                    if process in args.detail_processes:
                        wall = run_detail(selected, profile, mode="wall", timeout_s=args.detail_timeout)
                        save(out / f"{label}_wall.json", wall)
                        report = attach_detail(report, wall)
                    else:
                        wall = {"status": "not_run", "reason": "Explicit audit detail-process scope"}
                    case.update(stage="layers", wall_status=wall["status"], wall_reason=wall.get("reason"))
                    save(out / "record.json", record)
                    layers = run_detail(selected, profile, mode="layers", timeout_s=args.detail_timeout)
                    save(out / f"{label}_layers.json", layers)
                    report = attach_detail(report, layers)
                    case.update(stage="sections", layer_status=layers["status"], layer_reason=layers.get("reason"))
                    save(out / "record.json", record)
                    sections = run_detail(selected, profile, mode="sections", timeout_s=args.detail_timeout,
                                          sample_count=args.section_samples)
                    save(out / f"{label}_sections.json", sections)
                    report = attach_detail(report, sections)
                    section_comparison = sampling_volume_comparison(sections, independent, report["geometry"])
                    report["audit_section_volume_comparison"] = section_comparison
                    save(out / f"{label}.json", report)
                    (out / f"{label}.html").write_bytes(html_report(report))
                    case.update(status="reviewed", stage="complete", elapsed_seconds=time.perf_counter()-case_started,
                        review_status=report["summary"]["review_status"], geometry=report["geometry"],
                        statuses={x["id"]: x["status"] for x in report["findings"]},
                        independent=independent, wall_status=wall["status"], wall_reason=wall.get("reason"),
                        wall_minimum_mm=wall.get("measurements", {}).get("minimum_mm"),
                        wall_valid_samples=wall.get("measurements", {}).get("valid_samples"),
                        layer_status=layers["status"], layer_reason=layers.get("reason"),
                        expected_layers=layers.get("expected_layers"), complete_layers=layers.get("complete_layers"),
                        section_status=sections["status"], section_reason=sections.get("reason"),
                        section_complete_samples=sections.get("complete_samples"),
                        section_requested_samples=sections.get("requested_samples", args.section_samples),
                        section_max_area_mm2=sections.get("sampled_max_area_mm2"),
                        section_volume_midpoint_estimate_mm3=sections.get("volume_midpoint_estimate_mm3"),
                        section_volume_comparison=section_comparison,
                        report_json=f"{label}.json", report_html=f"{label}.html")
                    if process != "MEX" and layers["status"] != "not_applicable":
                        independent["failures"].append({"check": "non_MEX_layer_scope"})
                    if process == "PBF_POLYMER" and case["statuses"]["overhang"] != "not_applicable":
                        independent["failures"].append({"check": "polymer_PBF_overhang_scope"})
                except Exception as exc:
                    case.update(status="error", error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
                save(out / "record.json", record)
        record["status"] = "reviewed" if all(x["status"] == "reviewed" for x in record["cases"]) else "partial"
    except Exception as exc:
        record.update(status="input_rejected", error=f"{type(exc).__name__}: {exc}", traceback=traceback.format_exc())
    record.update(elapsed_seconds=time.perf_counter()-started, original_unchanged=sha(path)==record["source_sha256"])
    save(out / "record.json", plain(record))
    return 0


def run_one(item, args, out):
    target = out / item["id"]
    target.mkdir()
    command = [sys.executable, str(out / "audit_script.py"), "--worker", "--file", item["absolute_path"],
        "--out", str(target), "--engine-root", str(args.engine_root),
        "--cad-timeout", str(args.cad_timeout), "--detail-timeout", str(args.detail_timeout),
        "--file-timeout", str(args.file_timeout), "--deflection", str(args.deflection),
        "--section-samples", str(args.section_samples),
        "--detail-processes", *args.detail_processes]
    started = time.perf_counter()
    with (target / "stdout.log").open("wb") as stdout, (target / "stderr.log").open("wb") as stderr:
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
    record_path = target / "record.json"
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        record = dict(source=item["absolute_path"], source_sha256=item["sha256"], cases=[])
    if timed_out:
        record.update(status="file_timeout", reason=f"Per-file {args.file_timeout:g} s limit; completed case files are retained.")
        for case in record["cases"]:
            if case.get("status") == "running":
                case["status"] = "interrupted"
    elif process.returncode:
        record.update(status="worker_failure", reason=f"Worker exit {process.returncode}")
    record.update(id=item["id"], relative_path=item["relative_path"], wall_seconds=time.perf_counter()-started,
        original_unchanged=sha(Path(item["absolute_path"])) == item["sha256"])
    save(record_path, record)
    (target / "record.html").write_bytes(file_report_html(record))
    print(json.dumps(dict(file=item["relative_path"], status=record["status"], cases=len(record["cases"]),
        elapsed_seconds=record["wall_seconds"], error=record.get("error")), ensure_ascii=True), flush=True)
    return record


def main(args):
    from amdfm.analysis import code_digest
    source, out = Path(args.input).resolve(), Path(args.out).resolve()
    if out.exists():
        raise SystemExit("Output path already exists; preserve previous audits and select a new directory.")
    if source == out or source in out.parents:
        raise SystemExit("Output must be outside the immutable input directory.")
    out.mkdir(parents=True)
    original_engine = Path(args.engine_root)
    original_digest = code_digest()
    shutil.copy2(Path(__file__), out / "audit_script.py")
    # Freeze both the orchestration script and geometry implementation so later
    # editor changes cannot silently produce mixed-code cases in one audit.
    frozen_engine = out / "engine-source"
    frozen_engine.mkdir()
    for package in ("amdfm", "src"):
        shutil.copytree(original_engine / package, frozen_engine / package,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    if engine_digest(frozen_engine) != original_digest or engine_digest(original_engine) != original_digest:
        raise SystemExit("Engine changed while taking the audit snapshot; preserve this attempt and retry in a fresh output directory.")
    args.engine_root = str(frozen_engine)
    entries = []
    for i, path in enumerate(sorted(p for p in source.rglob("*") if p.is_file()), 1):
        entry = dict(id=f"file_{i:03d}", relative_path=path.relative_to(source).as_posix(),
            absolute_path=str(path), bytes=path.stat().st_size, sha256=sha(path),
            suffix=path.suffix.lower(), is_shape=path.suffix.lower() in FORMATS)
        if path.suffix.lower() == ".txt":
            entry["metadata_text"] = path.read_text(encoding="utf-8", errors="replace")
        entries.append(entry)
    manifest = dict(created_utc=datetime.now(timezone.utc).isoformat(), input_root=str(source),
        output_root=str(out), original_engine_root=str(original_engine), engine_root=str(args.engine_root),
        code_sha256=original_digest,
        script_sha256=sha(Path(__file__)), python=platform.python_version(), platform=platform.platform(),
        settings=vars(args), inventory=entries)
    save(out / "manifest.json", manifest)
    shapes = [x for x in entries if x["is_shape"]]
    results = []
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(run_one, item, args, out) for item in shapes]
        for future in as_completed(futures):
            results.append(future.result())
            save(out / "summary.json", dict(manifest="manifest.json", completed_files=len(results),
                planned_files=len(shapes), results=sorted(results, key=lambda x: x["id"])))
    integrity = []
    for entry in entries:
        path = Path(entry["absolute_path"])
        actual = sha(path) if path.is_file() else None
        integrity.append(dict(id=entry["id"], relative_path=entry["relative_path"],
            expected_sha256=entry["sha256"], actual_sha256=actual, unchanged=actual == entry["sha256"]))
    cases = [case for result in results for case in result.get("cases", [])]
    save(out / "summary.json", dict(manifest="manifest.json", completed_files=len(results),
        planned_files=len(shapes), all_original_files_unchanged=all(x["unchanged"] for x in integrity),
        input_integrity=integrity, results=sorted(results, key=lambda x: x["id"]),
        statistics=dict(file_status=dict(Counter(x["status"] for x in results)),
            case_status=dict(Counter(x["status"] for x in cases)),
            section_status=dict(Counter(x.get("section_status", "not_run") for x in cases)),
            wall_status=dict(Counter(x.get("wall_status", "not_run") for x in cases)),
            layer_status=dict(Counter(x.get("layer_status", "not_run") for x in cases)),
            independent_arithmetic_failures=sum(len(x.get("independent", {}).get("failures", [])) for x in cases))))
    rows = []
    for result in sorted(results, key=lambda x: x["id"]):
        base = dict(file=result["relative_path"], file_status=result["status"],
            error=result.get("error"), faces=result.get("faces"),
            solids=result.get("metadata", {}).get("solid_count"),
            unit_status=result.get("metadata", {}).get("unit_status"), original_unchanged=result["original_unchanged"])
        for case in result.get("cases") or [{}]:
            rows.append(dict(**base, body=case.get("body"), process=case.get("process"),
                case_status=case.get("status"), case_stage=case.get("stage"), case_error=case.get("error"),
                review_status=case.get("review_status"),
                wall_status=case.get("wall_status"), wall_minimum_mm=case.get("wall_minimum_mm"),
                layer_status=case.get("layer_status"), complete_layers=case.get("complete_layers"),
                expected_layers=case.get("expected_layers"),
                section_status=case.get("section_status"),
                section_complete_samples=case.get("section_complete_samples"),
                section_requested_samples=case.get("section_requested_samples"),
                section_max_area_mm2=case.get("section_max_area_mm2"),
                section_volume_midpoint_estimate_mm3=case.get("section_volume_midpoint_estimate_mm3"),
                section_vs_tetra_relative_difference=case.get("section_volume_comparison", {}).get("estimate_vs_tetra_relative_difference"),
                section_vs_cad_relative_difference=case.get("section_volume_comparison", {}).get("estimate_vs_cad_relative_difference"),
                section_resampling_priority=case.get("section_volume_comparison", {}).get("resampling_priority_relative_difference"),
                independent_failures=len(case.get("independent", {}).get("failures", [])),
                volume_relative_error=case.get("independent", {}).get("cad_mesh_volume_relative_error")))
    with (out / "summary.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["file"])
        writer.writeheader()
        writer.writerows(rows)
    links = "".join(f"<tr><td>{html.escape(r['relative_path'])}</td><td>{html.escape(r['status'])}</td>"
        f"<td>{len(r.get('cases', []))}</td><td><a href='{r['id']}/record.html'>보고서</a> · "
        f"<a href='{r['id']}/record.json'>JSON</a></td></tr>" for r in sorted(results, key=lambda x:x["id"]))
    (out / "index.html").write_text("<!doctype html><meta charset='utf-8'><title>AM-DFM corpus audit</title>"
        "<h1>AM-DFM corpus audit</h1><p>Build space unrestricted. STL dimensions assumed in mm; originals unchanged. "
        "Geometric measurements and unavailable scopes are recorded separately. No print-success certification.</p>"
        "<table><tr><th>File</th><th>Status</th><th>Cases</th><th>Details</th></tr>"+links+"</table>", encoding="utf-8")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input")
    parser.add_argument("--out", required=True)
    parser.add_argument("--engine-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--file-timeout", type=float, default=7200)
    parser.add_argument("--cad-timeout", type=float, default=120)
    parser.add_argument("--detail-timeout", type=float, default=90)
    parser.add_argument("--section-samples", type=int, default=64)
    parser.add_argument("--deflection", type=float, default=.05)
    parser.add_argument("--detail-processes", nargs="+", choices=PROCESSES, default=list(PROCESSES))
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--file", help=argparse.SUPPRESS)
    arguments = parser.parse_args()
    arguments.engine_root = str(Path(arguments.engine_root).resolve())
    sys.path.insert(0, arguments.engine_root)
    if arguments.jobs < 1 or min(arguments.file_timeout, arguments.cad_timeout, arguments.detail_timeout) <= 0:
        parser.error("Positive process count and time budgets are required.")
    if not 2 <= arguments.section_samples <= 1024:
        parser.error("--section-samples must be between 2 and 1024")
    if not arguments.worker and not arguments.input:
        parser.error("--input is required")
    raise SystemExit(worker(arguments) if arguments.worker else main(arguments))
