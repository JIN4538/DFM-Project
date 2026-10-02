"""Retry only the two 45-second timeouts using the app's 180-second load limit."""
from datetime import datetime, timezone
import gc
import json
from pathlib import Path
import sys
import time
import traceback

from observe_corpus import ROOT, sha256, timeout_caused
from amdfm.analysis import code_digest
from amdfm.io import load_model
from amdfm.models import json_bytes
from dfm.machining import MachiningProfile, review_machining


def main(previous, destination):
    prior = json.loads((previous / "summary.json").read_text(encoding="utf-8"))
    prior_environment = json.loads((previous / "environment.json").read_text(encoding="utf-8"))
    cases = [row for row in prior["observations"] if row["processing_status"] == "load_timeout"]
    if len(cases) != 2:
        raise RuntimeError("This retry is authorized only for the two recorded 45-second timeouts.")
    destination.mkdir()
    profile = MachiningProfile(**prior_environment["profile"])
    environment = {**prior_environment, "created_utc": datetime.now(timezone.utc).isoformat(),
        "code_digest": code_digest(), "load_timeout_seconds": 180,
        "prior_summary_sha256": sha256(previous / "summary.json"),
        "retry_scope": "Only original indices 14 and 21 which exceeded the first 45-second audit limit; same geometry and demo profile; no body selection.",
        "concurrency_context": "Parent full regression finished before this retry. Ordinary browser/app processes may still exist."}
    (destination / "environment.json").write_bytes(json_bytes(environment))
    rows = []
    for case in cases:
        started = time.perf_counter()
        source = ROOT / "examples/corpus" / case["path"]
        row = dict(index=case["index"], path=case["path"], expected_sha256=case["expected_sha256"],
                   actual_sha256=sha256(source), prior_processing_status=case["processing_status"],
                   prior_elapsed_seconds=case["elapsed_seconds"], started_utc=datetime.now(timezone.utc).isoformat())
        print(f"[{row['index']}] {row['path']}", flush=True)
        model = report = data = None
        stage = "integrity"
        try:
            if row["actual_sha256"] != row["expected_sha256"]:
                raise RuntimeError("Source SHA no longer matches preserved input.")
            stage = "load"
            data = source.read_bytes()
            model = load_model(data, source.name, unit="mm", dimensions_confirmed=False,
                               deflection_mm=.05, timeout_s=180)
            row["load_seconds"] = time.perf_counter() - started
            stage = "review"
            report = review_machining(model, profile, direction=(0, 0, 1), visibility=False)
            by_id = {finding["id"]: finding for finding in report["findings"]}
            ready = by_id["cnc_input"]["measurements"]["cad_feature_dimensions_available"]
            name = f"model_{row['index']:02d}.json"
            (destination / name).write_bytes(json_bytes(report))
            row.update(processing_status="completed", report=name,
                analytic_cnc_scope="available_limited_features" if ready else "unsupported_input_or_unresolved_cad",
                metadata={key: model.metadata.get(key) for key in (
                    "source_format", "cad_geometry_kind", "cad_valid", "solid_count", "cad_face_count",
                    "cavity_shell_count", "unit_status", "dimensions_confirmed", "coordinate_unit")},
                triangles=len(model.mesh.faces), cad_features=len(model.cad_features),
                finding_statuses={key: finding["status"] for key, finding in by_id.items()},
                finding_reasons={key: finding["reason"] for key, finding in by_id.items()},
                visibility_status="not_run_by_audit_design")
        except Exception as exc:
            row.update(processing_status="load_timeout" if timeout_caused(exc) else f"{stage}_error",
                analytic_cnc_scope="not_evaluated", error_type=type(exc).__name__, error=str(exc),
                traceback=traceback.format_exc())
        finally:
            row["elapsed_seconds"] = time.perf_counter() - started
            row["source_unchanged"] = sha256(source) == row["actual_sha256"]
            rows.append(row)
            (destination / "observations-progress.json").write_bytes(json_bytes(rows))
            print(f"  {row['processing_status']} / {row['analytic_cnc_scope']} / {row['elapsed_seconds']:.2f}s", flush=True)
            del model, report, data
            gc.collect()
    summary = dict(created_utc=datetime.now(timezone.utc).isoformat(), load_timeout_seconds=180,
        total_inputs=len(rows), code_digest_start=environment["code_digest"], code_digest_end=code_digest(),
        code_unchanged=code_digest() == environment["code_digest"],
        all_sources_unchanged=all(row["source_unchanged"] for row in rows), observations=rows,
        interpretation="Second observation under app input budget. Not a dimensional correctness or physical machining validation.")
    (destination / "summary.json").write_bytes(json_bytes(summary))
    print(json.dumps({key: value for key, value in summary.items() if key != "observations"}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
