"""Fit and export local numeric rule/action classifiers (no runtime sklearn).

Synthetic measurement scenarios are NOT a CAD geometry recognition dataset.
Grouped parameter scenarios, unseen scales and numeric boundary probes are
reported separately; no training label/status is an input feature.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
from pathlib import Path
import random
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dfm.learned_review import (ACTION_IDS, FEATURE_VERSION, MODEL_PATH, SCHEMA, TASKS,
                                features_for, predict_mask, source_hashes, teacher_mask)


def scenario(task, rng, *, boundary=False, held_scale=False):
    # Distinct parameter groups/splits; geometric CAD families are audited in a
    # separate actual-engine corpus, not claimed by this tabular generator.
    scale = 10 ** rng.uniform(-2 if not held_scale else 2.7, 2.5 if not held_scale else 4)
    ratio = (lambda: 1. if rng.random() < .2 else 1 + rng.choice([-1, 1]) * 10 ** rng.uniform(-14, -3)) if boundary else (
        lambda: rng.choice([0.2, 0.5, 0.9, 1., 1.1, 2., 5.]) if rng.random() < .25 else 10 ** rng.uniform(-1.5, 1.5))
    maybe = lambda value: None if rng.random() < .15 else value
    if task == "wall":
        return dict(minimum_mm=scale * ratio(), limit_mm=scale)
    if task in ("overhang", "contact"):
        area = 1e-8 * ratio() if boundary or rng.random() < .35 else (0. if rng.random() < .4 else scale ** 2)
        return dict(area_mm2=area)
    if task == "cavities":
        return dict(shell_count=rng.choice([0, 0, 1, 2, 3, 5, 10, 25]))
    if task == "build":
        available = [scale * rng.uniform(.3, 3) for _ in range(3)]
        dimensions = [v * ratio() for v in available]
        values = dict(zip(("x_mm", "y_mm", "z_mm"), dimensions))
        values.update(zip(("ax_mm", "ay_mm", "az_mm"), available))
        values["tolerance_mm"] = max(1e-9, max(dimensions) * 1e-10)
        return values
    if task == "cad_holes":
        return dict(diameter_mm=scale * ratio(), limit_mm=maybe(scale),
                    axis_dot=(.70710678 * ratio() if boundary else rng.choice([0., .5, .70710678, .9, 1.]) if rng.random() < .4 else rng.random()),
                    process=rng.choice(["MEX", "VPP", "PBF_METAL", "PBF_POLYMER"]))
    if task == "layers":
        return {k: (0. if rng.random() < .5 else (10 ** rng.uniform(-24, -3) if boundary else scale ** 2 * ratio()))
                for k in ("thin_area", "unsupported_area", "single_layer_area")}
    if task == "cnc_holes":
        length = scale * rng.uniform(.3, 20)
        angle = (math.degrees(math.asin(1e-8 * ratio())) if boundary else
                 rng.choice([0., 0., 0., 90., 45., 1.]) if rng.random() < .7 else rng.uniform(0., 90.))
        return dict(diameter_mm=scale, length_mm=length, tool_mm=maybe(scale * ratio()), reach_mm=maybe(length / ratio()),
                    ratio_limit=maybe(length / scale / ratio()), angle_deg=angle)
    if task == "cnc_curved_corners":
        return dict(radius_mm=scale, tool_mm=maybe(2 * scale * ratio()))
    if task == "cnc_rectangular_pockets":
        height = scale * rng.uniform(.3, 10)
        flute = maybe(height / ratio())
        reach = maybe(height / ratio())
        # Real profiles require flute <= reach; retain this profile constraint.
        if flute and reach and flute > reach:
            flute, reach = reach, flute
        return dict(width_mm=scale, height_mm=height, tool_mm=maybe(scale * ratio()), flute_mm=flute, reach_mm=reach)
    if task == "cnc_visibility":
        dot = rng.choice([-1., -.5, 0., 1., .5]) if not boundary else rng.choice([-1e-10, 0., 1e-10 * ratio()])
        return dict(normal_dot=dot, obstruction_mm=None if rng.random() < .5 or dot <= 1e-10 else scale)
    raise ValueError(task)


def dataset(task, seed, count, split, *, boundary=False, held_scale=False):
    rng = random.Random(seed)
    rows = []
    for i in range(count):
        values = scenario(task, rng, boundary=boundary or (split == "train" and i % 4 == 0), held_scale=held_scale)
        rows.append(dict(scenario_id=f"{split}/{task}/{i}", split=split, task=task, values=values,
                         features=features_for(task, values), target_mask=teacher_mask(task, values)))
    return rows


def metrics(targets, predictions):
    n = len(targets)
    positives = sum(bool(v) for v in targets)
    clear = n - positives
    missed = sum(bool(y) and not bool(p) for y, p in zip(targets, predictions))
    false_positive = sum(not y and bool(p) for y, p in zip(targets, predictions))
    action_missed = sum(bool(y & ~p) for y, p in zip(targets, predictions))
    return dict(rows=n, exact_action_matches=sum(y == p for y, p in zip(targets, predictions)),
                exact_action_accuracy=sum(y == p for y, p in zip(targets, predictions)) / n,
                issue_positive_rows=positives, issue_clear_rows=clear, missed_issue_rows=missed,
                missed_issue_fraction=missed / positives if positives else None,
                false_positive_rows=false_positive, false_positive_fraction=false_positive / clear if clear else None,
                missing_any_action_rows=action_missed)


def export_tree(tree):
    t = tree.tree_
    nodes = []
    for i, feature in enumerate(t.feature):
        probabilities = t.value[i][0]
        total = float(probabilities.sum())
        nodes.append([int(feature), float(t.threshold[i]), int(t.children_left[i]), int(t.children_right[i]),
                      (probabilities / total).tolist() if feature == -2 else None])
    return nodes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=MODEL_PATH)
    parser.add_argument("--validation-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=29092026)
    parser.add_argument("--train-rows-per-task", type=int, default=5000)
    parser.add_argument("--replace-model", action="store_true", help="Explicitly replace only model+manifest, preserving evaluation directory")
    args = parser.parse_args()
    if args.output.exists() and not args.replace_model:
        parser.error("Model exists; choose new output or explicitly --replace-model")
    args.validation_dir.mkdir(parents=True, exist_ok=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    import numpy as np
    import sklearn
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.tree import DecisionTreeClassifier
    start = time.perf_counter()
    all_rows, records, evaluations = [], {}, {}
    total_train = 0
    for i, task in enumerate(TASKS):
        base = args.seed + i * 100
        train = dataset(task, base, args.train_rows_per_task, "train")
        validation = dataset(task, base + 1, 1000, "validation")
        test = dataset(task, base + 2, 1500, "test")
        boundary = dataset(task, base + 3, 500, "boundary", boundary=True)
        scale = dataset(task, base + 4, 500, "scale_holdout", held_scale=True)
        all_rows.extend(train + validation + test + boundary + scale)
        X, y = np.asarray([r["features"] for r in train]), np.asarray([r["target_mask"] for r in train])
        xv, yv = np.asarray([r["features"] for r in validation]), np.asarray([r["target_mask"] for r in validation])
        candidates = {"decision_tree": DecisionTreeClassifier(max_depth=12, min_samples_leaf=1, random_state=base),
                      "random_forest": RandomForestClassifier(n_estimators=24, max_depth=12, min_samples_leaf=1,
                                                               max_features=None, n_jobs=1, random_state=base)}
        comparison = {}
        for name, classifier in candidates.items():
            classifier.fit(X, y)
            comparison[name] = metrics(yv.tolist(), classifier.predict(xv).tolist())
        # Only validation is used to select; tie goes to the smaller model.
        selected = max(candidates, key=lambda name: (comparison[name]["exact_action_accuracy"], name == "decision_tree"))
        estimator = candidates[selected]
        domain = [[float(X[:, j].min()), float(X[:, j].max())] for j in range(X.shape[1])]
        record = dict(features=list(TASKS[task]), classes=estimator.classes_.tolist(), algorithm=selected,
                      trees=[export_tree(t) for t in estimator.estimators_] if selected == "random_forest" else [export_tree(estimator)],
                      domain=domain, training_rows=len(train))
        records[task] = record
        tests = {}
        for name, rows in (("test", test), ("boundary", boundary), ("scale_holdout", scale)):
            raw = estimator.predict(np.asarray([r["features"] for r in rows])).tolist()
            tests[name] = metrics([r["target_mask"] for r in rows], raw)
            exported = [predict_mask({"tasks": {task: record}}, task, r["features"]) for r in rows]
            tests[name]["in_domain_rows"] = sum(p is not None for p in exported)
            tests[name]["out_of_domain_rows"] = sum(p is None for p in exported)
            tests[name]["json_export_mismatch_rows"] = sum(p is not None and p != expected for p, expected in zip(exported, raw))
            if tests[name]["json_export_mismatch_rows"]:
                raise RuntimeError("JSON inference differs from sklearn")
        evaluations[task] = dict(selected=selected, validation_comparison=comparison, evaluation=tests,
                                 training_scenarios=len(train), evaluation_scenarios=len(validation) + len(test) + len(boundary) + len(scale))
        total_train += len(train)
        print(f"{task}: {selected}; test={tests['test']['exact_action_accuracy']:.4f}; boundary={tests['boundary']['exact_action_accuracy']:.4f}", flush=True)
    summary = {}
    for name in ("test", "boundary", "scale_holdout"):
        keys = ("rows", "exact_action_matches", "issue_positive_rows", "issue_clear_rows", "missed_issue_rows",
                "false_positive_rows", "missing_any_action_rows", "in_domain_rows", "out_of_domain_rows", "json_export_mismatch_rows")
        summary[name] = {key: sum(evaluations[task]["evaluation"][name][key] for task in TASKS) for key in keys}
        summary[name]["exact_action_accuracy"] = summary[name]["exact_action_matches"] / summary[name]["rows"]
    data = "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n" for row in all_rows).encode()
    with gzip.open(args.validation_dir / "measurement-scenarios.jsonl.gz", "wb") as f:
        f.write(data)
    model = dict(schema=SCHEMA, feature_version=FEATURE_VERSION, id="local-rule-actions-2026-09-29-v1",
                 algorithm="validation-selected decision trees / random forests", created_utc=datetime.now(timezone.utc).isoformat(),
                 teacher_sources=source_hashes(), training_rows=total_train, tasks=records,
                 validation={"scope": "teacher rule/action fidelity on synthetic primitive measurements; not CAD recognition accuracy",
                             "splits": summary}, seed=args.seed, training_library=f"scikit-learn {sklearn.__version__}")
    raw = json.dumps(model, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    checksum = hashlib.sha256(raw).hexdigest()
    manifest = dict(schema=SCHEMA, sha256=checksum, bytes=len(raw), model_id=model["id"])
    args.output.write_bytes(raw)
    (args.validation_dir / "fitted-model.json").write_bytes(raw)
    args.output.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    report = dict(model=manifest, seed=args.seed, training_rows=total_train, all_scenario_rows=len(all_rows),
                  uncompressed_dataset_sha256=hashlib.sha256(data).hexdigest(), library_versions={"sklearn": sklearn.__version__, "numpy": np.__version__},
                  elapsed_seconds=time.perf_counter() - start, teacher_sources=model["teacher_sources"], tasks=evaluations, summary=summary,
                  split_method="Independent seeded parameter draws. Distinct IDs do not imply geometry-family separation; repeated primitive values are possible. CAD family holdout is separate, not claimed by these numeric scenarios.",
                  selection="Validation exact action-match rate; decision tree wins ties. Locked test/boundary/scale sets were not used for model selection.",
                  development="Earlier runs informed continuous numeric conditioning and boundary sampling. Only a fresh final seed after implementation freeze is a final evaluation; earlier runs are development records.",
                  verification="Runtime compares raw predictions to the current numeric teacher. Fallback agreement is not counted as model accuracy.")
    (args.validation_dir / "training-evaluation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(dict(model_sha256=checksum, training_rows=total_train, summary=summary), ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
