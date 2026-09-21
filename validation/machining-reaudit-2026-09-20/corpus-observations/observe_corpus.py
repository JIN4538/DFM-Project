"""Sequential, read-only observation of the preserved 26-file user corpus.

No dimensional ground truth is supplied for these downloaded models. Completion
is processing evidence, never a correctness assertion or machining certificate.
Run once in a new output subdirectory to preserve earlier observations.
"""
from collections import Counter
from datetime import datetime, timezone
import gc
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from amdfm.analysis import code_digest
from amdfm.io import load_model
from amdfm.models import json_bytes
from dfm.machining import MachiningProfile, review_machining


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def timeout_caused(exc):
    while exc is not None:
        if isinstance(exc, subprocess.TimeoutExpired):
            return True
        exc = exc.__cause__
    return False


def main(destination):
    destination.mkdir()  # Refuse to overwrite a prior observation.
    corpus = ROOT / "examples/corpus"
    manifest_path = corpus / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    sources = [entry for entry in manifest["files"] if entry["kind"] == "geometry"]
    profile = MachiningProfile(tool_diameter_mm=4., flute_length_mm=10., reach_mm=15.,
        basis="감사 시연 조건: 지름4/날길이10/끝날-홀더 돌출길이15mm. 실제 공구·재료·장비의 검증된 가공 조건이 아님.")
    start_digest = code_digest()
    environment = dict(created_utc=datetime.now(timezone.utc).isoformat(),
        python=sys.version, executable=sys.executable, platform=platform.platform(),
        code_digest=start_digest, manifest_sha256=sha256(manifest_path),
        source_sha256={path.as_posix(): sha256(ROOT / path) for path in [
            Path("dfm/machining.py"), Path("amdfm/io.py"), Path("amdfm/cad_worker.py"), Path("amdfm/cad_features.py")]},
        packages={}, profile=profile.to_dict(), direction=[0, 0, 1],
        visibility=False, load_timeout_seconds=45,
        mesh_unit_policy="STL default mm is an unconfirmed assumption; STEP and 3MF use declared units.",
        execution_policy="One model at a time; preserve assembly inputs; no auto body choice; no shape repair; no ray visibility; source bytes never changed.",
        interpretation="Observed processing and scope only. No dimensional oracle and no physical machining trial.")
    for package in ("numpy", "trimesh", "cadquery-ocp-novtk", "streamlit", "shapely"):
        try:
            environment["packages"][package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            environment["packages"][package] = None
    (destination / "environment.json").write_bytes(json_bytes(environment))
    observations = []
    for index, entry in enumerate(sources, 1):
        source = corpus / entry["path"]
        started = time.perf_counter()
        row = dict(index=index, path=entry["path"], expected_sha256=entry["sha256"],
                   actual_sha256=sha256(source), bytes=source.stat().st_size,
                   source_format=source.suffix.lower(), started_utc=datetime.now(timezone.utc).isoformat())
        print(f"[{index}/{len(sources)}] {entry['path']}", flush=True)
        model = report = data = None
        stage = "integrity"
        try:
            if row["actual_sha256"] != row["expected_sha256"]:
                row.update(processing_status="source_integrity_mismatch", analytic_cnc_scope="not_evaluated")
            else:
                stage = "load"
                data = source.read_bytes()
                model = load_model(data, source.name, unit="mm", dimensions_confirmed=False,
                                   deflection_mm=.05, timeout_s=45)
                row["load_seconds"] = time.perf_counter() - started
                stage = "review"
                report = review_machining(model, profile, direction=(0, 0, 1), visibility=False)
                report_name = f"model_{index:02d}.json"
                (destination / report_name).write_bytes(json_bytes(report))
                by_id = {finding["id"]: finding for finding in report["findings"]}
                ready = by_id["cnc_input"]["measurements"]["cad_feature_dimensions_available"]
                row.update(processing_status="completed", report=report_name,
                    analytic_cnc_scope="available_limited_features" if ready else "unsupported_input_or_unresolved_cad",
                    metadata={key: model.metadata.get(key) for key in (
                        "source_format", "cad_geometry_kind", "cad_valid", "solid_count", "cad_face_count",
                        "cavity_shell_count", "unit_status", "dimensions_confirmed", "coordinate_unit")},
                    triangles=len(model.mesh.faces), cad_features=len(model.cad_features),
                    finding_statuses={key: finding["status"] for key, finding in by_id.items()},
                    finding_reasons={key: finding["reason"] for key, finding in by_id.items()},
                    feature_counts={
                        "360_degree_cylindrical_faces": by_id["cnc_holes"]["measurements"].get("face_count"),
                        "parallel_concave_cylindrical_faces": len(by_id["cnc_curved_corners"]["measurements"].get("cylindrical_faces", [])) if ready else None,
                        "recognized_rectangular_floors": by_id["cnc_rectangular_pockets"]["measurements"].get("count"),
                        "unresolved_inward_floor_candidates": len(by_id["cnc_rectangular_pockets"]["measurements"].get("unresolved_floor_face_ids", [])) if ready else None,
                        "incomplete_planar_boundaries": len(by_id["cnc_coverage"]["measurements"].get("incomplete_boundary_face_ids", [])) if ready else None,
                        "unresolved_cylinder_sides": len(by_id["cnc_coverage"]["measurements"].get("unresolved_cylinder_face_ids", [])) if ready else None,
                        "unsupported_surfaces": len(by_id["cnc_coverage"]["measurements"].get("unsupported_face_ids", [])) if ready else None,
                    },
                    visibility_status="not_run_by_audit_design")
        except Exception as exc:
            row.update(processing_status="load_timeout" if timeout_caused(exc) else f"{stage}_error",
                       analytic_cnc_scope="not_evaluated", error_type=type(exc).__name__,
                       error=str(exc), traceback=traceback.format_exc())
        finally:
            row["elapsed_seconds"] = time.perf_counter() - started
            row["source_unchanged"] = sha256(source) == row["actual_sha256"]
            observations.append(row)
            (destination / "observations-progress.json").write_bytes(json_bytes(observations))
            print(f"  {row['processing_status']} / {row['analytic_cnc_scope']} / {row['elapsed_seconds']:.2f}s", flush=True)
            del model, report, data
            gc.collect()
    end_digest = code_digest()
    summary = dict(completed_utc=datetime.now(timezone.utc).isoformat(), total_inputs=len(observations),
        processing_counts=dict(Counter(row["processing_status"] for row in observations)),
        analytic_scope_counts=dict(Counter(row["analytic_cnc_scope"] for row in observations)),
        code_digest_start=start_digest, code_digest_end=end_digest, code_unchanged=start_digest == end_digest,
        all_sources_unchanged=all(row["source_unchanged"] for row in observations),
        manifest_sha256_after=sha256(manifest_path),
        all_manifest_hashes_match=all(row["actual_sha256"] == row["expected_sha256"] for row in observations),
        interpretation=environment["interpretation"], observations=observations)
    (destination / "summary.json").write_bytes(json_bytes(summary))
    print(json.dumps({key: value for key, value in summary.items() if key != "observations"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]))
