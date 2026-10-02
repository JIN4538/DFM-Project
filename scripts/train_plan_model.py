"""Fit plan ranking from grouped counterfactual scenarios and explicit policy.

The target is a disclosed project selection objective, not expert preference or
literary truth. Actual user choices are learned separately at runtime.
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
from dfm.plan_learning import FEATURES, MODEL_PATH, SCHEMA, _stable, candidate_plans, predict_score, source_hashes, selection_index

AM_FAMILIES = ("box", "cylinder", "cone", "bracket", "thin_plate", "annulus", "rib_prism", "ellipsoid", "wedge", "torus")
AM_PER_FAMILY = 36
CNC_GROUPS = 720


def group_split(family_index, local_index, am=True):
    # Last two AM families / last CNC family are never fitted or selected on.
    if family_index >= (8 if am else 5): return "test"
    if local_index < (24 if am else 80): return "train"
    if local_index < (30 if am else 100): return "validation"
    return "test"


def selection_objective(x):
    """Disclosed robust trade-off prior; never evaluated by live recommender.

    AM: reduce worst weighted relative deterioration, with average as secondary.
    CNC: trade geometry edit, tool edit and geometric reach/diameter ratio;
    this is a change-selection policy, not a cost or stiffness calculation.
    """
    if x[0] == 0:
        active = x[14:17]
        weights = [(3. if x[8 + i] else 1.) * active[i] for i in range(3)]
        values = [x[1 + i] * weights[i] for i in range(3)]
        total = sum(weights)
        if total == 0: return 0.
        return -(.7 * max(values) / max(weights) + .3 * sum(values) / total)
    g, t, slender, changes = x[4:8]
    weights = (4., 1., 1.5) if x[11] else (1., 1., 3.) if x[13] else (2., 1., 2.)
    a, b, c = [value * weight for value, weight in zip((g, t, slender), weights)]
    return -(.5 * max(a, b, c) / max(weights) + .35 * (a + b + c) / sum(weights)
             + .1 * g * slender + .05 * changes)


def make_mesh(index, seed):
    import numpy as np
    import trimesh
    rng = random.Random(seed + index * 113)
    family_index, local_index = divmod(index, AM_PER_FAMILY)
    family = AM_FAMILIES[family_index]
    split = group_split(family_index, local_index)
    scale = 10 ** rng.uniform(.3, 2.3)
    if split == "test" and local_index % 3 == 0:
        scale = 10 ** rng.uniform(-1.5, -.2) if local_index % 2 else 10 ** rng.uniform(2.7, 3.)
    dims = [scale * rng.uniform(.35, 2) for _ in range(3)]
    parameters = {}
    if family in ("box", "thin_plate"):
        if family == "thin_plate": dims[2] = min(dims[:2]) * rng.uniform(.005, .06)
        mesh = trimesh.creation.box(extents=dims)
    elif family == "cylinder": mesh = trimesh.creation.cylinder(radius=dims[0] / 2, height=dims[2], sections=24)
    elif family == "cone": mesh = trimesh.creation.cone(radius=dims[0] / 2, height=dims[2], sections=24)
    elif family in ("bracket", "rib_prism"):
        w, h, depth = dims
        t = min(w, h) * rng.uniform(.08, .4)
        parameters["wall_mm"] = t
        if family == "bracket":
            vertices = np.array([[0, 0], [w, 0], [w, t], [t, t], [t, h], [0, h]])
            triangles = np.array([[0, 1, 2], [0, 2, 3], [0, 3, 4], [0, 4, 5]])
        else:
            vertices = np.array([[0, 0], [w, 0], [w, t], [w/2+t/2, t], [w/2+t/2, h], [w/2-t/2, h], [w/2-t/2, t], [0, t]])
            triangles = np.array([[0, 1, 2], [0, 2, 3], [0, 3, 6], [0, 6, 7], [3, 4, 5], [3, 5, 6]])
        mesh = trimesh.creation.extrude_triangulation(vertices, triangles, depth)
    elif family == "wedge":
        parameters["tip_x_mm"] = dims[0] * rng.uniform(.1, .9)
        vertices = np.array([[0, 0], [dims[0], 0], [parameters["tip_x_mm"], dims[1]]])
        mesh = trimesh.creation.extrude_triangulation(vertices, np.array([[0, 1, 2]]), dims[2])
    elif family == "annulus":
        parameters["inner_radius_mm"] = dims[0] / 2 * rng.uniform(.25, .9)
        mesh = trimesh.creation.annulus(r_min=parameters["inner_radius_mm"], r_max=dims[0]/2, height=dims[2], sections=32)
    elif family == "ellipsoid":
        mesh = trimesh.creation.icosphere(subdivisions=2)
        mesh.apply_scale([d/2 for d in dims])
    else:
        parameters["minor_radius_mm"] = dims[0] / 2 * rng.uniform(.1, .7)
        mesh = trimesh.creation.torus(major_radius=dims[0]/2, minor_radius=parameters["minor_radius_mm"], major_sections=24, minor_sections=16)
    rotation_kind = local_index % 4
    angles = ([0., 0., 0.] if rotation_kind == 0 else
              [rng.choice([0., math.pi/2, math.pi, -math.pi/2]) for _ in range(3)] if rotation_kind == 1 else
              [rng.uniform(.1, 1.4), 0., 0.] if rotation_kind == 2 else
              [rng.uniform(-math.pi, math.pi) for _ in range(3)])
    mesh.apply_transform(trimesh.transformations.euler_matrix(*angles))
    assert mesh.is_watertight and mesh.is_volume and mesh.volume > 0
    mesh_sha = hashlib.sha256(mesh.vertices.tobytes() + mesh.faces.tobytes()).hexdigest()
    return mesh, dict(family=family, split=split, dimensions_mm=dims, rotation_radians=angles, rotation_kind=rotation_kind, parameters=parameters,
                     family_held_out=family_index >= 8, boundary_scale=scale < 1 or scale > 500,
                     mesh_sha256=mesh_sha, vertices=len(mesh.vertices), faces=len(mesh.faces), volume_mm3=float(mesh.volume))


def am_reports(seed):
    from amdfm.orientation import compare_orientations, measure_orientation
    from amdfm.profiles import Profile
    for i in range(len(AM_FAMILIES) * AM_PER_FAMILY):
        mesh, construction = make_mesh(i, seed)
        split = construction["split"]
        for process in ("MEX", "VPP", "PBF_METAL", "PBF_POLYMER"):
            profile = Profile(process=process)
            rows = compare_orientations(mesh, profile, dense=True)
            report = dict(profile=profile.to_dict(), process=process, summary={"review_status": "geometry_review"},
                          model={"unit_status": "declared"}, findings=[], orientations=rows,
                          current_orientation=measure_orientation(mesh, [0, 0, 1], profile))
            for priority in ("balanced", "support", "height", "contact"):
                report["review_context"] = {"priority": priority}
                yield f"am-{i}", split, deepcopy(report), {"type": "measured procedural mesh", **construction}


def deepcopy(value):
    from copy import deepcopy as copy
    return copy(value)


def cnc_reports(seed):
    for i in range(CNC_GROUPS):
        rng = random.Random(seed + 200000 + i * 117)
        family, local_index = divmod(i, 120)
        split = group_split(family, local_index, am=False)
        scale = 10 ** rng.uniform(.3, 1.4)
        if split == "test" and local_index % 3 == 0:
            scale = 10 ** rng.uniform(-2, -.3) if local_index % 2 else 10 ** rng.uniform(2, 2.7)
        counts = ((3, 0, 0), (2, 2, 0), (0, 0, 3), (2, 1, 2), (4, 3, 4), (6, 4, 5))[family]
        holes = [dict(face_id=j+10, diameter_mm=scale * rng.uniform(.2, 2.5), cylindrical_length_mm=scale * rng.uniform(.3, 15), axis_aligned=True) for j in range(counts[0])]
        corners = [dict(face_id=j+30, radius_mm=scale * rng.uniform(.08, 1.5)) for j in range(counts[1])]
        pockets = [dict(floor_face_id=j+50, width_mm=scale * rng.uniform(.3, 3), wall_height_mm=scale * rng.uniform(.3, 10)) for j in range(counts[2])]
        for tool_index in range(2):
            diameter = scale * rng.uniform(.6, 2.5)
            flute = scale * rng.uniform(1, 4)
            reach = flute * rng.uniform(1, 2.5)
            if tool_index == 1 and holes and local_index % 4 == 0:
                diameter = holes[0]["diameter_mm"] * (1 + rng.choice([-1e-8, 0, 1e-8]))
            limit = (None, 2., 4., 8., 16.)[local_index % 5]
            report = dict(process="MILLING_3AXIS", profile=dict(machine="planning-scenario", material="unspecified",
                tool_diameter_mm=diameter, flute_length_mm=flute, reach_mm=reach, hole_depth_ratio_limit=limit), findings=[
                dict(id="cnc_input", status="observed", measurements={"cad_feature_dimensions_available": True}),
                dict(id="cnc_holes", status="attention", measurements={"cylindrical_faces": holes}),
                dict(id="cnc_curved_corners", status="attention" if corners else "not_detected", measurements={"cylindrical_faces": corners}),
                dict(id="cnc_rectangular_pockets", status="attention" if pockets else "not_detected", measurements={"pockets": pockets})])
            for priority in ("balanced", "accuracy", "tool_access"):
                for constraints in ({}, {"preserve_geometry": True}, {"allow_tool_change": False}):
                    report["review_context"] = {"priority": priority}
                    report["_training_preferences"] = constraints
                    yield f"cnc-{i}", split, deepcopy(report), {"type": "analytic feature-dimension counterfactual, not imported CAD",
                        "family": family, "family_held_out": family == 5, "boundary_scale": scale < 1 or scale > 100,
                        "tool_scenario": tool_index, "hole_depth_ratio_limit": limit}


def export_tree(estimator):
    t = estimator.tree_
    return [[int(t.feature[i]), float(t.threshold[i]), int(t.children_left[i]), int(t.children_right[i]), float(t.value[i][0][0])]
            for i in range(t.node_count)]


def existing_cad_evaluation(model):
    """Separate integration corpus: never included in fitting/model selection."""
    from amdfm.analysis import review
    from amdfm.io import load_model
    from amdfm.profiles import Profile
    from dfm.machining import MachiningProfile, review_machining
    records, queries = [], []
    for directory in ("examples/cad", "examples/machining"):
        for path in sorted((ROOT / directory).glob("*.step")):
            raw = path.read_bytes()
            cad = load_model(raw, path.name)
            if directory.endswith("/cad"):
                reports = [(review(cad, Profile(process=process), dense=True), {}) for process in ("MEX", "VPP", "PBF_METAL", "PBF_POLYMER")]
            else:
                reports = [(review_machining(cad, MachiningProfile(tool_diameter_mm=d, flute_length_mm=f, reach_mm=r, hole_depth_ratio_limit=4.)), preferences)
                           for d, f, r in ((12., 4., 6.), (3., 15., 20.))
                           for preferences in ({}, {"preserve_geometry": True}, {"allow_tool_change": False})]
            for report, preferences in reports:
                try:
                    plans, reason, baseline = candidate_plans(report, preferences)
                except ValueError as error:
                    plans, reason, baseline = [], str(error), None
                entry = dict(file=str(path.relative_to(ROOT)).replace("\\", "/"), sha256=hashlib.sha256(raw).hexdigest(),
                             process=report.get("process", report.get("profile", {}).get("process")), preferences=preferences,
                             candidate_count=len(plans), reason=reason)
                if plans:
                    scores = [predict_score(model, p["_features"]) for p in plans]
                    selected = plans[selection_index(scores, [_stable(p) for p in plans])]
                    entry.update(selected_id=selected["id"], outcomes=selected["outcomes"], remaining=selected["remaining"],
                                 changes=selected["changes"], verification_scope=selected["verification_scope"])
                    targets = [selection_objective(p["_features"]) for p in plans]
                    selected_index = plans.index(selected)
                    baseline_index = next((i for i, p in enumerate(plans) if p["id"] == baseline), 0)
                    entry.update(objective_regret=max(targets)-targets[selected_index], fixed_baseline_regret=max(targets)-targets[baseline_index])
                    if len(plans) > 1:
                        features = [p["_features"] for p in plans]
                        queries.append(dict(features=features, targets=[selection_objective(x) for x in features], stable_keys=[_stable(p) for p in plans],
                                            baseline_index=next((i for i, p in enumerate(plans) if p["id"] == baseline), 0)))
                records.append(entry)
    return dict(files=len({r["file"] for r in records}), reviews=len(records), unavailable=sum(r["candidate_count"] == 0 for r in records),
                ranking_objective=evaluate(queries, lambda xs: [predict_score(model, x) for x in xs]),
                interpretation="Imported CAD integration and disclosed-objective ranking, not independent expert/manufacturing labels"), records


def evaluate(queries, prediction):
    regrets, baseline_regrets, changed, improved, worsened, top1 = [], [], 0, 0, 0, 0
    for q in queries:
        scores = prediction(q["features"])
        best = selection_index(scores, q["stable_keys"])
        oracle = max(q["targets"])
        regret = oracle - q["targets"][best]
        baseline = q["baseline_index"]
        bregret = oracle - q["targets"][baseline]
        regrets.append(regret); baseline_regrets.append(bregret)
        changed += best != baseline
        improved += regret < bregret - 1e-7
        worsened += regret > bregret + 1e-7
        top1 += regret <= 1e-7
    return dict(queries=len(queries), exact_objective_best=top1, mean_objective_regret=sum(regrets) / max(1, len(regrets)),
                maximum_objective_regret=max(regrets, default=0), baseline_mean_objective_regret=sum(baseline_regrets) / max(1, len(regrets)),
                different_from_fixed_baseline=changed, better_than_fixed_objective=improved, worse_than_fixed_objective=worsened)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=MODEL_PATH)
    parser.add_argument("--validation-dir", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=2909202611)
    parser.add_argument("--replace-model", action="store_true")
    args = parser.parse_args()
    if args.output.exists() and not args.replace_model: parser.error("모델을 덮어쓰려면 --replace-model을 지정하세요")
    args.validation_dir.mkdir(parents=True, exist_ok=False)
    import numpy as np
    import sklearn
    from sklearn.ensemble import GradientBoostingRegressor
    started = time.perf_counter()
    start_sources = source_hashes()
    pipeline_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    queries, geometry, measurements = [], {}, []
    for group, split, report, construction in itertools_chain(am_reports(args.seed), cnc_reports(args.seed)):
        geometry[group] = dict(split=split, construction=construction)
        preferences = report.pop("_training_preferences", {})
        plans, _, baseline = candidate_plans(report, preferences)
        if report["review_context"]["priority"] == "balanced" and not preferences:
            measurements.append(dict(group=group, split=split, report=report))
        if len(plans) < 2: continue
        features = [p["_features"] for p in plans]
        queries.append(dict(group=group, split=split, process=report.get("process"), priority=report["review_context"]["priority"],
                            candidate_ids=[p["id"] for p in plans], stable_keys=[_stable(p) for p in plans], preferences=preferences, features=features,
                            targets=[selection_objective(x) for x in features],
                            baseline_index=next((i for i, p in enumerate(plans) if p["id"] == baseline), 0)))
    print(f"{len(geometry)} grouped geometries/scenarios, {len(queries)} candidate sets", flush=True)
    groups = {split: {q["group"] for q in queries if q["split"] == split} for split in ("train", "validation", "test")}
    assert not any(groups[a] & groups[b] for a, b in (("train", "validation"), ("train", "test"), ("validation", "test")))
    train = [q for q in queries if q["split"] == "train"]
    validation = [q for q in queries if q["split"] == "validation"]
    test = [q for q in queries if q["split"] == "test"]
    X = np.asarray([x for q in train for x in q["features"]]); y = np.asarray([t for q in train for t in q["targets"]])
    models, comparison = {}, {}
    for name, count, depth in (("gradient_boosting_96_depth3", 96, 3), ("gradient_boosting_180_depth4", 180, 4)):
        model = GradientBoostingRegressor(n_estimators=count, max_depth=depth, learning_rate=.05, min_samples_leaf=5, random_state=args.seed)
        model.fit(X, y)
        comparison[name] = evaluate(validation, model.predict)
        models[name] = model
        print(name, comparison[name], flush=True)
    selected = min(comparison, key=lambda key: comparison[key]["mean_objective_regret"])
    fit = models[selected]
    model = dict(schema=SCHEMA, id="local-counterfactual-plan-ranker-v1", features=list(FEATURES), sources=start_sources,
                 training_pipeline_sha256=pipeline_sha,
                 created_utc=datetime.now(timezone.utc).isoformat(), algorithm=selected,
                 training_scope="Grouped candidate plans; target is disclosed project trade-off policy, not expert labels. Explicit user choices learn a separate residual.",
                 training_rows=len(X), training_groups=len(groups["train"]), seed=args.seed,
                 intercept=float(fit.init_.constant_[0][0]), learning_rate=float(fit.learning_rate),
                 trees=[export_tree(t[0]) for t in fit.estimators_])
    validation_final = evaluate(test, fit.predict)
    exported = evaluate(test, lambda xs: [predict_score(model, x) for x in xs])
    assert validation_final == exported
    baseline = evaluate(test, lambda xs: [0.] * len(xs))
    oracle = evaluate(test, lambda xs: [selection_objective(x) for x in xs])
    subgroup = {}
    for name, subset in (("am_family_held_out", [q for q in test if q["group"].startswith("am-") and geometry[q["group"]]["construction"]["family_held_out"]]),
                         ("cnc_family_held_out", [q for q in test if q["group"].startswith("cnc-") and geometry[q["group"]]["construction"]["family_held_out"]]),
                         ("boundary_scale", [q for q in test if geometry[q["group"]]["construction"]["boundary_scale"]])):
        subgroup[name] = evaluate(subset, fit.predict)
    cad_evaluation, cad_records = existing_cad_evaluation(model)
    report = dict(model_selection=comparison, selected=selected, heldout=validation_final, zero_model_ablation=baseline,
                  deterministic_objective_oracle=oracle, heldout_subgroups=subgroup,
                  existing_cad_integration=cad_evaluation,
                  interpretation="Objective regret refers only to the disclosed selection objective. Separate model approximation from the value/validity of that objective.",
                  split_groups={k: sorted(v) for k, v in groups.items()}, query_counts={k: sum(q["split"] == k for q in queries) for k in groups},
                  training_rows=len(X), feature_columns=list(FEATURES), sklearn_version=sklearn.__version__, elapsed_seconds=time.perf_counter() - started,
                  training_pipeline_sha256=pipeline_sha, dataset_seed=args.seed,
                  measured_mesh_groups=len(AM_FAMILIES)*AM_PER_FAMILY, analytic_cnc_groups=CNC_GROUPS,
                  ranking_ties="Exact deployed policy: round(score,9), then fixed axis/id order",
                  sources=["https://scikit-learn.org/stable/modules/ensemble.html#gradient-tree-boosting",
                           "https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.GroupShuffleSplit.html",
                           "https://www.jmlr.org/papers/v4/freund03a.html"],
                  method_note="The shipped prior is pointwise gradient boosting. Online explicit choices use regularized pairwise logistic preference fitting; this is not an implementation of RankBoost.")
    raw = json.dumps(model, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    sha = hashlib.sha256(raw).hexdigest()
    assert source_hashes() == start_sources, "Runtime source changed during training; no model will be written"
    assert hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == pipeline_sha, "Training pipeline changed during execution"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(raw)
    args.output.with_suffix(".manifest.json").write_text(json.dumps({"sha256": sha, "bytes": len(raw), "schema": SCHEMA}, indent=2) + "\n", encoding="utf-8")
    (args.validation_dir / "fitted-model.json").write_bytes(raw)
    report["model_sha256"] = sha
    (args.validation_dir / "evaluation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.validation_dir / "group-construction.json").write_text(json.dumps(geometry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (args.validation_dir / "existing-cad-evaluation.json").write_text(json.dumps(cad_records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with gzip.open(args.validation_dir / "candidate-queries.json.gz", "wt", encoding="utf-8") as f:
        json.dump(queries, f, ensure_ascii=False, allow_nan=False)
    with gzip.open(args.validation_dir / "measured-and-scenario-reports.json.gz", "wt", encoding="utf-8") as f:
        json.dump(measurements, f, ensure_ascii=False, allow_nan=False)
    print(json.dumps({"sha256": sha, "heldout": validation_final, "zero_ablation": baseline}), flush=True)


def itertools_chain(*parts):
    for part in parts:
        yield from part


if __name__ == "__main__": main()
