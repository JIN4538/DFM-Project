"""End-to-end selection audit, distinct from best-available candidate quality.

App plan ranker receives exact augmented rows. The same finite-pool objective
measures what its final choice actually selects; no tuning occurs here.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
from amdfm.neural_orientation import (enrich_orientations, hybrid_proposal_indices, load_model,
                                     predict_surrogates, proposal_pool, proposal_scores)
from amdfm.orientation import measure_orientation
from amdfm.profiles import Profile
from dfm.plan_learning import recommend_plan, MODEL_PATH as PLAN_MODEL_PATH
from train_neural_orientation import make_group, objective, write_json, source_snapshot


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--evaluation-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("preserve previous recommendation audits")
    groups = json.loads((args.evaluation_run / "groups.json").read_text(encoding="utf-8"))
    model = load_model()
    sources_before = source_snapshot()
    records = []
    from threadpoolctl import threadpool_limits
    with threadpool_limits(limits=1):
        for group in groups:
            if group["split"] != "test":
                continue
            index = int(group["group"].split("-")[1])
            mesh, info, profile, baseline, descriptor = make_group(index, args.seed)
            if info["mesh_sha256"] != group["mesh_sha256"]:
                raise ValueError("evaluation geometry does not match saved group manifest")
            directions, sources = proposal_pool(mesh, baseline)
            predicted = predict_surrogates(model, descriptor, directions, profile.overhang_angle_deg)
            exact = [measure_orientation(mesh, d, profile) for d in directions]
            pool = baseline + exact
            current = measure_orientation(mesh, [0, 0, 1], profile)
            for process in ("MEX", "VPP", "PBF_POLYMER"):
                for priority in (("balanced", "support", "height", "contact") if process == "MEX" else
                                 ("balanced", "support", "height") if process == "VPP" else ("height",)):
                    scores = proposal_scores(predicted, descriptor, priority=priority, height_only=process == "PBF_POLYMER")
                    seeds, learned = hybrid_proposal_indices(directions, sources, scores, 12)
                    additions = []
                    for count, candidate in enumerate(seeds + learned):
                        row = deepcopy(exact[candidate])
                        row.pop("overhang_face_indices", None)
                        name = f"면 탐색 {count + 1}" if candidate in seeds else f"AI 탐색 {count - len(seeds) + 1}"
                        row.update(name=name, candidate_role="search")
                        additions.append(row)
                    report = dict(profile={**profile.to_dict(), "process": process}, process=process,
                                  summary={"review_status": "geometry_review"}, model={"unit_status": "declared"},
                                  findings=[], orientations=baseline, current_orientation=current,
                                  review_context={"priority": priority})
                    before = recommend_plan(report, feedback_path=args.output.parent / "disabled-user-preferences.json")
                    report["orientations"] = baseline + additions
                    after = recommend_plan(report, feedback_path=args.output.parent / "disabled-user-preferences.json")
                    if not before.get("selected") or not after.get("selected"):
                        raise ValueError("end-to-end ranker did not provide a selection")
                    before_row, after_row = before["selected"]["orientation"], after["selected"]["orientation"]
                    before_score = float(objective([before_row], pool, process=process, priority=priority)[0])
                    after_score = float(objective([after_row], pool, process=process, priority=priority)[0])
                    oracle = float(objective(pool, pool, process=process, priority=priority).min())
                    records.append(dict(group=info["group"], family=info["family"], process=process, priority=priority,
                                        before=dict(score=before_score, regret=before_score-oracle, direction=before_row["direction"],
                                                    selection_source=before["selection_source"], model=before["model"]),
                                        after=dict(score=after_score, regret=after_score-oracle, direction=after_row["direction"],
                                                   selection_source=after["selection_source"], model=after["model"]),
                                        score_delta=after_score-before_score))
            if len(records) % 80 == 0:
                print(f"final recommendation audited for {len(records) // 8} meshes", flush=True)
    delta = np.array([r["score_delta"] for r in records])
    summary = dict(audit="actual recommend_plan final choice; same held-out geometry as specified evaluation-run; no model tuning",
                   geometry_run=str(args.evaluation_run), seed=args.seed, shape_count=len({r["group"] for r in records}), scenarios=len(records),
                   better=int(np.sum(delta < -1e-10)), equal=int(np.sum(np.abs(delta) <= 1e-10)), worse=int(np.sum(delta > 1e-10)),
                   mean_before_regret=float(np.mean([r["before"]["regret"] for r in records])),
                   mean_after_regret=float(np.mean([r["after"]["regret"] for r in records])), mean_score_delta=float(delta.mean()),
                   neural_model_sha256=model["sha256"], plan_model_sha256=hashlib.sha256(PLAN_MODEL_PATH.read_bytes()).hexdigest(),
                   source_frozen_during_run=source_snapshot() == sources_before,
                   source_sha256=sources_before, recommendation_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    if not summary["source_frozen_during_run"]:
        raise RuntimeError("runtime source changed during audit")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json(args.output, dict(summary=summary, cases=records))
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
