"""Freeze source groups, then prepare regret targets without opening test labels."""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import time

import numpy as np
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from amdfm.proposal_selector import cheap_geometry, features, objective_values, feature_sha256
from amdfm.full_search import MODEL_PATH
from amdfm.neural_orientation import load_model, proposal_pool, BASE_NAMES
from amdfm.orientation import candidates, measure_orientation
from amdfm.profiles import Profile
from benchmark_adaptive_am import mesh_for
from prepare_full_am import chunk_labels

CONDITIONS = (("MEX", "balanced"), ("MEX", "support"), ("VPP", "balanced"),
              ("PBF_POLYMER", "height"), ("PBF_METAL", "balanced"))


def open_db(path):
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def freeze_groups(output, train_count=100, validation_count=15, test_count=25):
    study = ROOT.parent/"study"
    excluded, previous = set(), []
    paths = [p for directory in ("ai-expansion-2026-09-30", "ai-full-corpus-2026-09-30", "external-training-2026-09-30")
             for p in (study/directory).glob("*benchmark*.json")]
    paths.append(study/"ai-improvement-2026-09-30/am-adaptive-test/summary.json")
    for path in paths:
        doc = json.loads(path.read_text())
        cases = doc.get("cases", []) if isinstance(doc, dict) else []
        excluded.update((r.get("dataset"), r.get("group")) for r in cases)
        previous.append(dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    db = open_db(study/"ai-full-corpus-2026-09-30/am-full/index.sqlite")
    records, availability = [], {}
    for dataset in ("PBF-orientation", "CadQuarry", "Thingi10K"):
        for split, requested in (("train", train_count), ("validation", validation_count), ("test", test_count)):
            values = [json.loads(raw) for raw, in db.execute("SELECT record FROM records WHERE accepted=1 AND dataset=? AND split=?", (dataset, split))]
            unique = {}
            for row in sorted(values, key=lambda r: hashlib.sha256(("selector-v1:"+r["id"]).encode()).hexdigest()):
                if row["faces"] <= 100_000 and (dataset, row["group"]) not in excluded:
                    unique.setdefault(row["group"], row)
            availability[dataset+":"+split] = len(unique)
            records.extend(list(unique.values())[:requested])
    memberships = {split: {(r["dataset"], r["group"]) for r in records if r["split"]==split} for split in ("train", "validation", "test")}
    if any(memberships[a]&memberships[b] for a, b in (("train", "validation"), ("train", "test"), ("validation", "test"))):
        raise ValueError("source group leakage")
    document = dict(records=records, available_groups=availability, requested_per_source=dict(train=train_count, validation=validation_count, test=test_count),
        previous_benchmarks=previous, excluded_previous_groups=len(excluded), maximum_faces=100_000, angles=[45.],
        policy="One original group per split; deterministic selection before opening labels; previous proposal-test groups excluded; no new downloads")
    output.write_text(json.dumps(document, indent=2), encoding="utf-8")
    db.close()
    return document


def main(args):
    if args.output.exists():
        raise FileExistsError("Use a new experiment directory")
    args.output.mkdir(parents=True)
    pipeline_raw = Path(__file__).read_bytes()
    (args.output/"prepare-source.py").write_bytes(pipeline_raw)
    (args.output/"selector-source.py").write_bytes((ROOT/"amdfm/proposal_selector.py").read_bytes())
    manifest = freeze_groups(args.output/"groups.json", args.train, args.validation, args.test)
    model = load_model(MODEL_PATH)
    public = open_db(ROOT.parent/"study/ai-expansion-2026-09-30/public-expansion.sqlite")
    things = open_db(ROOT.parent/"study/external-training-2026-09-30/thingi.sqlite")
    started = time.perf_counter()
    records, maximum_error = [], 0.
    for row in manifest["records"]:
        if row["split"] == "test":
            continue
        begin = time.perf_counter()
        mesh = mesh_for(row, public, things)
        base_directions = np.asarray(list(candidates(None, dense=True).values()))
        base_stub = [dict(name=name, direction=d.tolist()) for name, d in zip(BASE_NAMES, base_directions)]
        pool, sources = proposal_pool(mesh, base_stub)
        all_directions = np.concatenate((base_directions, pool))
        acquisition_begin = time.perf_counter()
        geometry = cheap_geometry(mesh, all_directions)
        feature_seconds = time.perf_counter()-acquisition_begin
        h, o = chunk_labels(mesh, all_directions, angles=[45.], block=512)
        if np.max(np.abs(h-geometry["height"])) > 1e-8:
            raise ValueError("convex hull height mismatch")
        descriptor = dict(height=h[:26], overhang=o[0, :26])
        pool_geometry = {key: value[26:] for key, value in geometry.items() if isinstance(value, np.ndarray)}
        xs, ys, weights = [], [], []
        for process, priority in CONDITIONS:
            local_descriptor = dict(descriptor)
            if process == "PBF_POLYMER":
                local_descriptor["overhang"] = np.zeros(26)
            x = features(model, local_descriptor, pool, sources, pool_geometry, process, priority)
            loss = objective_values(h, o[0], geometry["contact"], process, priority)
            y = loss[26:]-loss.min()
            xs.append(x); ys.append(y)
            # More attention to candidates able to improve the measured 26-view incumbent.
            weights.append(np.where(loss[26:] <= loss[:26].min()+.02, 4., 1.))
        # Independent runtime includes a facet (plate contact discontinuity) and an arbitrary sphere direction.
        errors = []
        for index in (26, len(all_directions)-1):
            actual = measure_orientation(mesh, all_directions[index], Profile(process="MEX"))
            errors.extend((abs(actual["height_mm"]/np.linalg.norm(mesh.extents)-h[index]),
                abs(actual["overhang_projected_area_sum_mm2"]/mesh.area-o[0, index]),
                abs(actual["contact_triangle_area_mm2"]/mesh.area-geometry["contact"][index])))
        error = max(errors)
        if error > 1e-7:
            raise ValueError(f"runtime label mismatch {error:g}")
        maximum_error = max(maximum_error, error)
        key = hashlib.sha256((row["dataset"]+row["id"]).encode()).hexdigest()
        path = args.output/row["split"]/(key+".npz")
        path.parent.mkdir(exist_ok=True)
        np.savez_compressed(path, x=np.asarray(xs), y=np.asarray(ys, dtype="float32"), weight=np.asarray(weights, dtype="float32"),
            directions=pool, base_directions=base_directions, height=h, overhang=o[0], contact=geometry["contact"],
            sources=np.asarray(sources), descriptor_height=h[:26], descriptor_overhang=o[0, :26])
        records.append({**row, "shard": str(path.relative_to(args.output)), "candidates": len(pool),
                        "selector_independent_error": error, "acquisition_seconds": feature_seconds,
                        "seconds": time.perf_counter()-begin})
        if len(records)%10==0:
            print(json.dumps(dict(prepared=len(records), seconds=time.perf_counter()-started)), flush=True)
    result = dict(records=records, conditions=CONDITIONS, feature_sha256=feature_sha256(), neural_model_sha256=model["sha256"],
        maximum_independent_error=maximum_error, seconds=time.perf_counter()-started, test_labels_opened=False,
        preparation_sha256=hashlib.sha256(pipeline_raw).hexdigest(), polymer_downward_features="unmeasured zero with explicit process code",
        groups_manifest_sha256=hashlib.sha256((args.output/"groups.json").read_bytes()).hexdigest())
    (args.output/"prepared.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key!="records"}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--train", type=int, default=100)
    parser.add_argument("--validation", type=int, default=15)
    parser.add_argument("--test", type=int, default=25)
    with threadpool_limits(limits=1):
        main(parser.parse_args())
