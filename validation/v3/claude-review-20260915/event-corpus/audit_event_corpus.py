"""Read cached CAD without re-conversion; write only to a new audit directory."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess
import sys
import time


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def worker(args):
    import numpy as np
    import trimesh
    from amdfm.models import Model, plain
    from amdfm.orientation import placement
    from amdfm.detail_worker import inspect_section_strategy
    from src.core.mesh_diagnostics import mesh_digest

    cache = args.cache / args.case
    payload = json.loads((cache / "model.json").read_text(encoding="utf-8"))
    with np.load(cache / "model.npz", allow_pickle=False) as arrays:
        source = Model(trimesh.Trimesh(arrays["vertices"], arrays["faces"], process=False),
            payload["metadata"], payload.get("cad_features", []), arrays["face_ids"], arrays["body_ids"])
    body = max(source.metadata["bodies"], key=lambda item: item["volume_mm3"])["body_id"]
    model = source.select_body(body)
    xyz, matrix = placement(model.mesh, (0, 0, 1))
    placed = trimesh.Trimesh(xyz, model.mesh.faces.copy(), process=False)
    started = time.perf_counter()
    result = inspect_section_strategy(placed, "auto", 64, 8192)
    elapsed = time.perf_counter() - started
    event = result.get("event_attempt", result)
    triangles = placed.triangles - placed.bounds.mean(axis=0)
    tetra = math.fsum(np.einsum("ij,ij->i", triangles[:, 0], np.cross(triangles[:, 1], triangles[:, 2])) / 6)
    known = event.get("known_interval_volume_mm3")
    interval_rows = event.pop("intervals", [])
    event["incomplete_intervals"] = [item for item in interval_rows if not item["complete"]]
    event["recorded_interval_count"] = len(interval_rows)
    event.pop("rows", None)
    result.pop("rows", None)
    if known is not None and event.get("event_interval_count"):
        assert (event["complete_event_intervals"] + sum(event["unresolved_interval_counts"].values())
                + event["unexamined_event_intervals"] == event["event_interval_count"])
    record = dict(file_id=args.case, filename=source.metadata["filename"], selected_body=body,
        source_sha256=source.metadata["source_sha256"], selected_model_fingerprint=model.fingerprint,
        source_npz_sha256=digest(cache / "model.npz"), source_metadata_sha256=digest(cache / "model.json"),
        placed_mesh_sha256=mesh_digest(placed), placement_transform=matrix.tolist(),
        triangles=len(placed.faces), elapsed_seconds=elapsed, reference_tetra_mm3=tetra,
        cad_quadrature_mm3=model.metadata["exact_volume_mm3"],
        known_relative_difference_from_tetra=None if known is None else known / tetra - 1,
        result=result)
    write(args.out / (args.case + ".json"), plain(record))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--case")
    args = parser.parse_args()
    args.repo, args.cache, args.out = args.repo.resolve(), args.cache.resolve(), args.out.resolve()
    sys.path.insert(0, str(args.repo))
    if args.case:
        worker(args)
        return
    args.out.mkdir(parents=True, exist_ok=False)
    from amdfm.processes import run_bounded
    files = sorted(args.cache.glob("file_*/model.json"))
    inputs, excluded = [], []
    for path in files:
        metadata = json.loads(path.read_text(encoding="utf-8"))["metadata"]
        if metadata["source_format"] not in ("step", "stp"):
            continue
        if not metadata.get("solid_count"):
            excluded.append(dict(filename=metadata["filename"], reason="surface_only_no_solid"))
        else:
            inputs.append(path.parent.name)
    sources = {str(path.relative_to(args.repo)): digest(path) for package in ("amdfm", "src/core")
               for path in (args.repo / package).rglob("*.py")}
    records = []
    for case in inputs:
        command = [sys.executable, str(Path(__file__).resolve()), "--repo", str(args.repo),
            "--cache", str(args.cache), "--out", str(args.out), "--case", case]
        try:
            proc = run_bounded(command, cwd=args.repo, timeout=90)
            if proc.returncode:
                records.append(dict(file_id=case, error="worker_failed", output=proc.stdout + proc.stderr))
            else:
                record = json.loads((args.out / (case + ".json")).read_text(encoding="utf-8"))
                records.append(record)
                result = record["result"]
                print(case, record["filename"], result["sampling"], result["status"],
                    result.get("representation_limit_only"), round(record["elapsed_seconds"], 3), flush=True)
        except subprocess.TimeoutExpired:
            records.append(dict(file_id=case, error="timeout_90s"))
    changed = [name for name, sha in sources.items() if digest(args.repo / name) != sha]
    event_status = Counter()
    result_status = Counter()
    for record in records:
        if "result" in record:
            result = record["result"]
            event_status[result.get("event_attempt", result)["status"]] += 1
            result_status[result["sampling"] + ":" + result["status"]] += 1
    write(args.out / "summary.json", dict(python=sys.version, platform=platform.platform(),
        input_cache=str(args.cache), direction=[0, 0, 1], policy="maximum OCCT-volume solid per STEP; unchanged cached tessellation; automatic sections; uniform64 only after event preflight refusal",
        selected_solids=len(inputs), excluded=excluded, source_sha256=sources,
        source_changed_during_run=changed, script_sha256=digest(Path(__file__)),
        event_status=dict(event_status), result_status=dict(result_status), records=records,
        limitations="This reuses previously converted cached CAD; it is not a new STEP conversion test, slicer or physical-print validation. Tetra volume is an independent boundary formula on the same mesh. Omission envelope covers missing height contribution only; computed partial sums and their sums with the envelope are not certified total-volume bounds."))


if __name__ == "__main__":
    main()
