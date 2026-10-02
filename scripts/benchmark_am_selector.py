"""Paired six-query controls, original-group holdout, and geometry remeasurement."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from amdfm.proposal_selector import (cheap_geometry, features, objective_values, predictions,
                                   load_selector, select_indices, feature_sha256)
from amdfm.full_search import MODEL_PATH, refined_directions
from amdfm.neural_orientation import load_model, proposal_pool, baseline_descriptor, predict_surrogates, proposal_scores
from amdfm.ensemble_search import enrich_ensemble
from amdfm.orientation import compare_orientations, measure_orientation
from amdfm.profiles import Profile
from benchmark_adaptive_am import mesh_for
from prepare_am_selector import open_db, CONDITIONS
from prepare_full_am import chunk_labels
from train_neural_orientation import objective

POLICIES = {"learned": 0., "uncertainty05": .5, "uncertainty1": 1., "retain2_learned": 0.}
CONTROLS = ("legacy", "blind", "geometric", "height_neural")


def comparison(cases, method, control):
    differences = np.asarray([c["scores"][method]-c["scores"][control] for c in cases])
    groups = {}
    for case, value in zip(cases, differences):
        groups.setdefault(case["dataset"]+":"+case["group"], []).append(value)
    group_values = np.array([np.mean(v) for v in groups.values()])
    rng = np.random.default_rng(930306)
    boot = group_values[rng.integers(0, len(group_values), (4000, len(group_values)))].mean(axis=1)
    return dict(cases=len(cases), better=int(np.sum(differences < -1e-8)), same=int(np.sum(np.abs(differences)<=1e-8)),
        worse=int(np.sum(differences > 1e-8)), mean_difference=float(differences.mean()),
        group_mean_difference=float(group_values.mean()), grouped_bootstrap95=np.quantile(boot, [.025, .975]).tolist())


def main(args):
    args.output.mkdir(parents=True, exist_ok=False)
    benchmark_source = Path(__file__).read_bytes()
    (args.output/"benchmark-source.py").write_bytes(benchmark_source)
    (args.output/"selector-source.py").write_bytes((ROOT/"amdfm/proposal_selector.py").read_bytes())
    groups_raw = args.groups.read_bytes()
    manifest = json.loads(groups_raw)
    records = [r for r in manifest["records"] if r["split"] == args.split]
    model = load_model(MODEL_PATH)
    selector = load_selector(args.model)
    if selector["groups_manifest_sha256"] != hashlib.sha256(groups_raw).hexdigest():
        raise ValueError("different group manifest")
    if selector["neural_model_sha256"] != model["sha256"]:
        raise ValueError("frozen neural model changed")
    policies = dict(POLICIES)
    if args.split == "test":
        if args.selection is None:
            raise ValueError("Test requires a frozen validation selection")
        frozen = json.loads(args.selection.read_text())
        if frozen["selector_sha256"] != hashlib.sha256(args.model.read_bytes()).hexdigest():
            raise ValueError("selector changed after validation")
        policies = {name: POLICIES[name] for name in frozen["selected_policies"]}
    public = open_db(ROOT.parent/"study/ai-expansion-2026-09-30/public-expansion.sqlite")
    things = open_db(ROOT.parent/"study/external-training-2026-09-30/thingi.sqlite")
    cases, total_started = [], time.perf_counter()
    for group in records:
        mesh = mesh_for(group, public, things)
        for process, priority in CONDITIONS:
            profile = Profile(process=process)
            height_only = process == "PBF_POLYMER"
            baseline = compare_orientations(mesh, profile, dense=True)
            before = enrich_ensemble(mesh, profile, baseline, priority=priority, timeout_s=8.)
            base = before["rows"]
            descriptor = baseline_descriptor(mesh, baseline, require_overhang=not height_only)
            common_begin = time.perf_counter()
            pool, sources = proposal_pool(mesh, base)
            legacy_begin = time.perf_counter()
            refined = refined_directions(model, descriptor, pool, 45., priority, height_only, time.monotonic()+.7)
            neural = predict_surrogates(model, descriptor, pool, 45., height_only=height_only)
            old_scores = proposal_scores(neural, descriptor, priority=priority, height_only=height_only)
            legacy = []
            old = [np.asarray(r["direction"]) for r in base]
            for direction in refined + [pool[i] for i in np.argsort(old_scores, kind="stable")[:40]]:
                if any(direction@d > 1-1e-8 for d in old+legacy):
                    continue
                if legacy and max(direction@d for d in legacy) > np.cos(np.deg2rad(8.)):
                    continue
                legacy.append(direction)
                if len(legacy) == 6:
                    break
            legacy_seconds = time.perf_counter()-legacy_begin
            common = list(pool); common_sources = list(sources)
            for direction in refined:
                if not any(direction@d > 1-1e-8 for d in old+common):
                    common.append(direction); common_sources.append("continuous_refinement")
            common = np.asarray(common)
            pool_seconds = time.perf_counter()-common_begin-legacy_seconds
            # Controls receive the same candidate pool (including continuous seeds),
            # so common-pool construction is also charged to every method.
            common_seconds = legacy_seconds+pool_seconds
            geometry_begin = time.perf_counter()
            geometry = cheap_geometry(mesh, common)
            geometry_seconds = time.perf_counter()-geometry_begin
            feature_begin = time.perf_counter()
            x = features(model, descriptor, common, common_sources, geometry, process, priority)
            feature_seconds = time.perf_counter()-feature_begin
            prediction_begin = time.perf_counter()
            mean, uncertainty = predictions(selector, x)
            prediction_seconds = time.perf_counter()-prediction_begin
            hybrid_begin = time.perf_counter()
            hybrid_prediction = predict_surrogates(model, descriptor, common, 45., height_only=height_only)
            hybrid_seconds = time.perf_counter()-hybrid_begin
            n = len(common)
            cheap_scores = objective_values(geometry["height"], np.zeros(n), geometry["contact"], process, priority)
            hybrid_scores = objective_values(geometry["height"], hybrid_prediction.get("overhang", np.zeros(n)), geometry["contact"], process, priority)
            chosen = dict(legacy=legacy, blind=[common[i] for i in np.linspace(0, n-1, 6, dtype=int)],
                geometric=common[select_indices(common, cheap_scores)], height_neural=common[select_indices(common, hybrid_scores)])
            for policy, exploration in policies.items():
                indices = select_indices(common, mean, uncertainty, budget=12 if policy=="retain2_learned" else 6, exploration=exploration)
                proposed = list(legacy[:2]) if policy=="retain2_learned" else []
                for index in indices:
                    if not any(common[index]@d > 1-1e-8 for d in proposed):
                        proposed.append(common[index])
                    if len(proposed)==6:
                        break
                chosen[policy] = proposed
            extras, timings, errors = {}, {}, {}
            for method, directions in chosen.items():
                begin = time.perf_counter()
                extra = [measure_orientation(mesh, direction, profile) for direction in directions]
                measurement_seconds = time.perf_counter()-begin
                extras[method] = extra
                acquisition = common_seconds
                if method in ("geometric", "height_neural") or method in policies:
                    acquisition += geometry_seconds
                if method == "height_neural":
                    acquisition += hybrid_seconds
                if method in policies:
                    acquisition += feature_seconds+prediction_seconds
                timings[method] = dict(acquisition_seconds=acquisition, measurement_seconds=measurement_seconds,
                    total_seconds=acquisition+measurement_seconds, full_queries=len(extra),
                    additional_descriptor_queries=0)
                if method in policies:
                    h, o = chunk_labels(mesh, directions, angles=[45.], block=512)
                    error = max(abs(r["height_mm"]/descriptor["diagonal_mm"]-h[i]) for i, r in enumerate(extra))
                    if not height_only:
                        error = max(error, max(abs(r["overhang_projected_area_sum_mm2"]/mesh.area-o[0, i]) for i, r in enumerate(extra)))
                    for measured in extra:
                        index = int(np.argmax(common@np.asarray(measured["direction"])))
                        if common[index]@np.asarray(measured["direction"]) < 1-1e-8:
                            raise ValueError("proposed direction absent from common pool")
                        error = max(error, abs(measured["contact_triangle_area_mm2"]/mesh.area-geometry["contact"][index]))
                    errors[method] = error
                    if error > 1e-7:
                        raise ValueError("independent selected geometry mismatch")
            union = base+[r for extra in extras.values() for r in extra]
            scores = {method: float(objective(base+extra, union, process=process, priority=priority).min()) for method, extra in extras.items()}
            raw_scores = {method: float(objective(extra, union, process=process, priority=priority).min()) for method, extra in extras.items()}
            case = dict(id=group["id"], dataset=group["dataset"], group=group["group"], split=args.split, process=process, priority=priority,
                scores=scores, raw_proposal_scores=raw_scores, timings=timings, errors=errors, pool_size=n,
                source_sha256=group["sha256"], existing_added_count=before["metadata"]["added_count"],
                hull_vertices=geometry["hull_vertices"], original_vertices=geometry["original_vertices"])
            cases.append(case)
            key = hashlib.sha256((group["dataset"]+group["id"]+process+priority).encode()).hexdigest()
            (args.output/(key+".json")).write_text(json.dumps(dict(**case, base=base, extras=extras), ensure_ascii=False), encoding="utf-8")
        print(json.dumps(dict(groups=len(cases)//len(CONDITIONS), seconds=time.perf_counter()-total_started)), flush=True)
    result = dict(cases=cases, groups=len(records), split=args.split, policies=policies,
        comparisons={method: {control: comparison(cases, method, control) for control in CONTROLS} for method in policies},
        by_process={process: {method: {control: comparison([c for c in cases if c["process"]==process], method, control) for control in CONTROLS} for method in policies} for process in set(c["process"] for c in cases)},
        selector_sha256=hashlib.sha256(args.model.read_bytes()).hexdigest(), neural_sha256=model["sha256"],
        benchmark_source_sha256=hashlib.sha256(benchmark_source).hexdigest(),
        feature_sha256=feature_sha256(), seconds=time.perf_counter()-total_started,
        cost_note="Same 6 full geometry queries; acquisition features, ensemble inference and shared continuous candidate construction cost charged separately. Polymer omits downward measurements consistently in train and evaluation.")
    (args.output/"summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    if args.split == "validation":
        chosen = min(policies, key=lambda method: (np.mean([c["scores"][method] for c in cases]), method))
        frozen = dict(selected_policies=[chosen], selector_sha256=result["selector_sha256"],
            validation_summary_sha256=hashlib.sha256((args.output/"summary.json").read_bytes()).hexdigest(),
            by_process_best_diagnostic={process: min(list(policies)+list(CONTROLS), key=lambda method: (
                np.mean([c["scores"][method] for c in cases if c["process"]==process]), method)) for process in {c["process"] for c in cases}},
            selection_rule="Lowest mean exact six-query candidate-union objective on validation; no test access")
        (args.output/"selection.json").write_text(json.dumps(frozen, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key not in ("cases", "by_process")}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--groups", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--split", choices=("validation", "test"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--selection", type=Path)
    with threadpool_limits(limits=1):
        main(parser.parse_args())
