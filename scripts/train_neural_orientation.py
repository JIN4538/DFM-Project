"""Train/evaluate deep orientation query surrogates on grouped generated meshes.

All dimensions in labels are produced by measure_orientation. Training uses
fresh geometry seeds; all views of a mesh belong to one split. Wedge and torus
families are reserved for evaluation, never for checkpoint selection.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
import platform

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from amdfm.neural_orientation import (BASE_NAMES, MODEL_PATH, SCHEMA, baseline_descriptor, choose_proposals,
                                     feature_arrays, fibonacci_directions, load_model, predict_surrogates,
                                     proposal_pool, proposal_scores, hybrid_proposal_indices, feature_contract_sha256)
from amdfm.orientation import compare_orientations, measure_orientation
from amdfm.profiles import Profile
from train_plan_model import make_mesh


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def source_snapshot():
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in
            ("amdfm/neural_orientation.py", "amdfm/orientation.py", "scripts/train_neural_orientation.py", "scripts/train_plan_model.py")}


def make_group(index, seed):
    mesh, construction = make_mesh(index, seed)
    local = index % 36
    angle = (25., 35., 45., 60., 75.)[(local + index // 36) % 5]
    profile = Profile(process="MEX", overhang_angle_deg=angle)
    rows = compare_orientations(mesh, profile, dense=True)
    descriptor = baseline_descriptor(mesh, rows)
    construction.update(group=f"mesh-{index}", angle_deg=angle, seed=seed)
    return mesh, construction, profile, rows, descriptor


def training_data(run, seed, count):
    groups = []
    samples = {split: {key: [] for key in ("height_x", "height_y", "overhang_x", "overhang_y", "group")}
               for split in ("train", "validation")}
    for index in range(360):
        mesh, info, profile, rows, descriptor = make_group(index, seed)
        groups.append(info)
        if info["split"] == "test":
            continue
        directions, _ = proposal_pool(mesh, rows, count=count)
        # Per-shape rotations of the sample sphere avoid memorizing fixed query points.
        import trimesh
        rng = np.random.default_rng(seed + index)
        rotation = trimesh.transformations.euler_matrix(*rng.uniform(-np.pi, np.pi, 3))[:3, :3]
        directions[:min(count, len(directions))] = directions[:min(count, len(directions))] @ rotation.T
        features = feature_arrays(descriptor, directions, profile.overhang_angle_deg)
        labels = [measure_orientation(mesh, direction, profile) for direction in directions]
        dest = samples[info["split"]]
        for target, field, scale in (("height", "height_mm", descriptor["diagonal_mm"]),
                                      ("overhang", "overhang_projected_area_sum_mm2", descriptor["area_mm2"])):
            dest[target + "_x"].append(features[target])
            dest[target + "_y"].extend(row[field] / scale for row in labels)
        dest["group"].extend([index] * len(directions))
        if index % 36 == 29:
            print(f"generated family {index // 36 + 1}/8", flush=True)
    packed = {}
    for split, data in samples.items():
        for key, values in data.items():
            packed[split + "_" + key] = np.concatenate(values) if key.endswith("_x") else np.asarray(values)
    np.savez_compressed(run / "training_data.npz", **packed)
    write_json(run / "groups.json", groups)
    return packed, groups


def fit_network(data, name, seed, max_epochs):
    from sklearn.neural_network import MLPRegressor
    from sklearn.preprocessing import StandardScaler
    x, y = data[f"train_{name}_x"], data[f"train_{name}_y"]
    vx, vy = data[f"validation_{name}_x"], data[f"validation_{name}_y"]
    scaler = StandardScaler().fit(x)
    x, vx = scaler.transform(x), scaler.transform(vx)
    hidden = (64, 48, 24) if name == "height" else (96, 64, 32)
    model = MLPRegressor(hidden_layer_sizes=hidden, activation="relu", solver="adam", alpha=.001,
                         batch_size=256, learning_rate_init=.001, max_iter=1, random_state=seed,
                         early_stopping=False, shuffle=True)
    history, best, bad = [], None, 0
    for epoch in range(1, max_epochs + 1):
        model.partial_fit(x, y)
        if epoch % 5 == 0 or epoch == max_epochs:
            error = float(np.mean((model.predict(vx) - vy) ** 2))
            history.append(dict(epoch=epoch, validation_mse=error, training_loss=float(model.loss_)))
            if best is None or error < best[0]:
                best = (error, epoch, deepcopy(model.coefs_), deepcopy(model.intercepts_))
                bad = 0
            else:
                bad += 1
            if epoch % 20 == 0:
                print(f"{name}: epoch {epoch}, validation MSE {error:.6g}", flush=True)
            if bad >= 8:
                break
    model.coefs_, model.intercepts_ = best[2], best[3]
    exported = dict(mean=scaler.mean_.tolist(), scale=scaler.scale_.tolist(),
                    weights=[w.tolist() for w in best[2]], biases=[b.tolist() for b in best[3]],
                    hidden_layers=list(hidden), selected_epoch=best[1], validation_mse=best[0])
    return exported, history, model, scaler


def objective(rows, all_rows, *, process, priority):
    fields = ["height_mm"]
    if process != "PBF_POLYMER":
        fields.insert(0, "overhang_projected_area_sum_mm2")
    if process == "MEX":
        fields.append("contact_triangle_area_mm2")
    weights, components = [], []
    for field in fields:
        pool = np.asarray([r[field] for r in all_rows])
        lo, hi = pool.min(), pool.max()
        part = np.zeros(len(rows)) if hi - lo <= max(1e-12, abs(hi) * 1e-12) else (np.array([r[field] for r in rows]) - lo) / (hi - lo)
        if field == "contact_triangle_area_mm2" and hi > lo:
            part = 1 - part
        components.append(part)
        target = {"height_mm": "height", "overhang_projected_area_sum_mm2": "support", "contact_triangle_area_mm2": "contact"}[field]
        weights.append(3. if target == priority else 1.)
    components, weights = np.array(components).T, np.array(weights)
    return .7 * (components * weights / weights.max()).max(axis=1) + .3 * (components @ weights) / weights.sum()


def interpolated_predictions(descriptor, directions):
    from amdfm.orientation import candidates
    base = np.asarray(list(candidates(None, dense=True).values()))
    dots = np.clip(directions @ base.T, -1, 1)
    indices = np.argsort(-dots, axis=1)[:, :4]
    dist = np.maximum(1e-4, 1 - np.take_along_axis(dots, indices, axis=1))
    weights = 1 / dist
    weights /= weights.sum(axis=1, keepdims=True)
    return {name: (np.asarray(descriptor[name])[indices] * weights).sum(axis=1) for name in ("height", "overhang")}


def evaluate(run, model_path, groups, seed, budget, pool_count):
    model = load_model(model_path)
    results, error_sum, errors_n = [], {"height": 0., "overhang": 0.}, 0
    for group in groups:
        if group["split"] != "test":
            continue
        index = int(group["group"].split("-")[1])
        mesh, info, profile, baseline, descriptor = make_group(index, seed)
        directions, sources = proposal_pool(mesh, baseline, count=pool_count)
        predicted = predict_surrogates(model, descriptor, directions, profile.overhang_angle_deg)
        interpolated = interpolated_predictions(descriptor, directions)
        exact = [measure_orientation(mesh, d, profile) for d in directions]
        truth = {"height": np.asarray([r["height_mm"] / descriptor["diagonal_mm"] for r in exact]),
                 "overhang": np.asarray([r["overhang_projected_area_sum_mm2"] / descriptor["area_mm2"] for r in exact])}
        for target in error_sum:
            error_sum[target] += float(np.sum(np.abs(predicted[target] - truth[target])))
        errors_n += len(exact)
        # Baselines use exactly the same pool and added-measurement budget.
        rng = np.random.default_rng(seed + 700000 + index)
        seeds = [i for i, source in enumerate(sources) if source == "facet"][:min(6, budget // 2)]
        remaining = [i for i in range(len(directions)) if i not in seeds]
        extra_budget = min(budget - len(seeds), len(remaining))
        random = seeds + rng.choice(remaining, extra_budget, replace=False).tolist()
        uniform = seeds + [remaining[i] for i in np.linspace(0, len(remaining) - 1, extra_budget, dtype=int)]
        for process in ("MEX", "VPP", "PBF_POLYMER"):
            for priority in (("balanced", "support", "height", "contact") if process == "MEX" else
                             ("balanced", "support", "height") if process == "VPP" else ("height",)):
                scores = proposal_scores(predicted, descriptor, priority=priority, height_only=process == "PBF_POLYMER")
                seed_indices, learned_indices = hybrid_proposal_indices(directions, sources, scores, budget)
                neural = seed_indices + learned_indices
                interpolated_score = proposal_scores(interpolated, descriptor, priority=priority, height_only=process == "PBF_POLYMER")
                _, interp = hybrid_proposal_indices(directions, sources, interpolated_score, budget)
                interp = seeds + interp
                sphere_indices = [i for i, source in enumerate(sources) if source == "sphere"]
                sphere_local = choose_proposals(directions[sphere_indices], scores[sphere_indices], budget)
                neural_sphere = [sphere_indices[i] for i in sphere_local]
                pool = baseline + exact
                all_scores = objective(pool, pool, process=process, priority=priority)
                base_score = float(min(all_scores[:len(baseline)]))
                oracle_score = float(min(all_scores))
                methods = {"baseline_26": [], "facet_seed_only": seeds, "neural": neural, "random": random, "uniform": uniform,
                           "interpolation": interp, "neural_sphere_only": neural_sphere}
                record = dict(group=info["group"], family=info["family"], family_held_out=info["family_held_out"],
                              process=process, priority=priority, angle_deg=profile.overhang_angle_deg,
                              pool_count=len(directions), budget=budget, finite_pool_oracle=oracle_score,
                              shared_facet_seed_indices=seeds,
                              baseline_score=base_score, methods={})
                for method, indices in methods.items():
                    value = min([base_score] + [float(all_scores[len(baseline) + i]) for i in indices])
                    record["methods"][method] = dict(score=value, regret=value-oracle_score, improvement=base_score-value,
                                                     selected_indices=indices, facet_count=sum(sources[i] == "facet" for i in indices))
                results.append(record)
        if len(results) % 80 == 0:
            print(f"evaluated {len(results) // 8} held-out meshes", flush=True)
    methods = list(results[0]["methods"])
    summary = dict(evaluation="held-out grouped generated geometry; objectives disclosed, not human expert labels",
                   shapes=len({r["group"] for r in results}), scenarios=len(results), added_measurement_budget=budget,
                   normalized_surrogate_mae={k: v / errors_n for k, v in error_sum.items()}, methods={})
    for method in methods:
        summary["methods"][method] = dict(mean_regret=float(np.mean([r["methods"][method]["regret"] for r in results])),
                                           mean_improvement=float(np.mean([r["methods"][method]["improvement"] for r in results])),
                                           improving_scenarios=sum(r["methods"][method]["improvement"] > 1e-10 for r in results))
    summary["neural_vs"] = {}
    for baseline_method in ("random", "uniform", "interpolation"):
        delta = np.array([r["methods"]["neural"]["score"] - r["methods"][baseline_method]["score"] for r in results])
        summary["neural_vs"][baseline_method] = dict(better=int(np.sum(delta < -1e-10)), equal=int(np.sum(np.abs(delta) <= 1e-10)),
                                                    worse=int(np.sum(delta > 1e-10)), mean_score_delta=float(delta.mean()))
    write_json(run / "evaluation-cases.json", results)
    write_json(run / "evaluation.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=202609293)
    parser.add_argument("--samples", type=int, default=96)
    parser.add_argument("--epochs", type=int, default=140)
    parser.add_argument("--pool", type=int, default=384)
    parser.add_argument("--budget", type=int, default=12)
    parser.add_argument("--reuse-data", type=Path)
    parser.add_argument("--publish", action="store_true")
    parser.add_argument("--evaluate-only-model", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    sources_before = source_snapshot()
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=1):
        if args.evaluate_only_model:
            groups = [make_group(index, args.seed)[1] for index in range(360)]
            write_json(args.output / "groups.json", groups)
            result = evaluate(args.output, args.evaluate_only_model, groups, args.seed, args.budget, args.pool)
            result.update(elapsed_s=time.monotonic() - started, model_sha256=load_model(args.evaluate_only_model)["sha256"],
                          fresh_evaluation_geometry_seed=args.seed, evaluation_source_sha256=sources_before,
                          source_frozen_during_run=source_snapshot() == sources_before)
            if source_snapshot() != sources_before:
                raise RuntimeError("source changed while evaluating; preserve this run as incomplete")
            write_json(args.output / "evaluation.json", result)
            print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
            return
        if args.reuse_data:
            loaded = np.load(args.reuse_data / "training_data.npz")
            data = {key: loaded[key] for key in loaded.files}
            groups = json.loads((args.reuse_data / "groups.json").read_text(encoding="utf-8"))
            write_json(args.output / "groups.json", groups)
        else:
            data, groups = training_data(args.output, args.seed, args.samples)
        networks, history, parity = {}, {}, {}
        model = dict(schema=SCHEMA, model_id="neural-orientation-v1", base_names=list(BASE_NAMES), networks=networks,
                     measurement_source_sha256=hashlib.sha256((ROOT / "amdfm/orientation.py").read_bytes()).hexdigest(),
                     feature_contract_sha256=feature_contract_sha256(), source_sha256=sources_before,
                     group_manifest_sha256=hashlib.sha256((args.output / "groups.json").read_bytes()).hexdigest(),
                     seed=args.seed, angle_range_deg=[25, 75], training_group_count=len(set(data["train_group"].tolist())),
                     validation_group_count=len(set(data["validation_group"].tolist())),
                     target_definition="height/bounding-box-diagonal and downward projected-area sum/mesh-surface-area",
                     process_scope="MEX/VPP/PBF_METAL height+overhang; PBF_POLYMER height only; contact not learned",
                     created_utc=datetime.now(timezone.utc).isoformat())
        fitted = {}
        for name in ("height", "overhang"):
            networks[name], history[name], fit, scaler = fit_network(data, name, args.seed, args.epochs)
            fitted[name] = (fit, scaler)
        model_path = args.output / "neural_orientation_v1.json"
        write_json(model_path, model)
        manifest = dict(schema=SCHEMA, sha256=hashlib.sha256(model_path.read_bytes()).hexdigest(),
                        model_id=model["model_id"], run=str(args.output.relative_to(ROOT)) if args.output.is_relative_to(ROOT) else str(args.output))
        write_json(model_path.with_suffix(".manifest.json"), manifest)
        loaded = load_model(model_path)
        for name, (fit, scaler) in fitted.items():
            raw = data[f"validation_{name}_x"][:1024]
            net = loaded["networks"][name]
            x = (raw - net["mean"]) / net["scale"]
            for i, (w, b) in enumerate(zip(net["weights"], net["biases"])):
                x = x @ w + b
                if i < len(net["weights"]) - 1: x = np.maximum(x, 0)
            parity[name] = float(np.max(np.abs(x[:, 0] - fit.predict(scaler.transform(raw)))))
        write_json(args.output / "training-history.json", history)
        write_json(args.output / "export-parity.json", parity)
        result = evaluate(args.output, model_path, groups, args.seed, args.budget, args.pool)
        result.update(elapsed_s=time.monotonic() - started, model_sha256=manifest["sha256"],
                      training_samples=len(data["train_group"]), validation_samples=len(data["validation_group"]),
                      training_groups=model["training_group_count"], validation_groups=model["validation_group_count"],
                      export_max_abs_error=parity, source_frozen_during_run=source_snapshot() == sources_before,
                      python_version=platform.python_version(), numpy_version=np.__version__)
        write_json(args.output / "evaluation.json", result)
        if source_snapshot() != sources_before:
            raise RuntimeError("source changed while training; artifacts must not be published")
        if args.publish:
            MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
            MODEL_PATH.write_bytes(model_path.read_bytes())
            MODEL_PATH.with_suffix(".manifest.json").write_bytes(model_path.with_suffix(".manifest.json").read_bytes())
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
