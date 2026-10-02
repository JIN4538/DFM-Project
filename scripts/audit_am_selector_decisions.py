"""Replay saved measurements through the actual product recommendation path.

No proposals, labels, model weights or policy choices are changed. A fixed
control union defines the external score scale in both validation and test.
Candidate best-possible utility and actual method-local normalization choices
are recorded separately, as is product arbitration under the common reference.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time

from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from amdfm.profiles import Profile
from dfm import plan_learning
from dfm.enhanced_planning import recommend_plan
from dfm.verified_selection import arbitrate
from train_neural_orientation import objective
from benchmark_am_selector import comparison, CONTROLS

SOURCES = ("dfm/enhanced_planning.py", "dfm/verified_selection.py", "dfm/plan_learning.py",
           "dfm/am_joint_planning.py", "amdfm/recommendation.py")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def comparison_report(cases, kind):
    normalized = [{**case, "scores": case[kind]} for case in cases]
    return {method: {control: comparison(normalized, method, control) for control in CONTROLS if method!=control}
            for method in ("height_neural", "uncertainty05")}


def main(args):
    args.output.mkdir(parents=True, exist_ok=False)
    snapshot = {p: sha(ROOT/p) for p in SOURCES}
    (args.output/"audit-source.py").write_bytes(Path(__file__).read_bytes())
    # Nonexistent explicitly named path avoids any user preference residual.
    feedback = args.output/"no-user-feedback.json"
    cases, started = [], time.perf_counter()
    for path in sorted(args.input.glob("*.json")):
        if path.name in ("summary.json", "selection.json"):
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        candidates = {}
        for method, extra in raw["extras"].items():
            # The same names/tie order the existing full_search product uses.
            candidates[method] = deepcopy(raw["base"])+[
                dict(row, name=f"AI 정밀 방향 {i+1}", candidate_role="search") for i, row in enumerate(extra)]
        reference_rows = deepcopy(raw["base"])+[dict(row, name=f"control:{method}:{i}", candidate_role="search")
            for method in CONTROLS for i, row in enumerate(raw["extras"][method])]
        template = dict(profile=Profile(process=raw["process"]).to_dict(), process=raw["process"],
            summary={"review_status": "geometry_review"}, model={"unit_status": "declared"}, findings=[],
            current_orientation=deepcopy(raw["base"][0]), review_context={"priority": raw["priority"]})
        reference_report = dict(template, orientations=reference_rows)
        oracle, actual, common, selections = {}, {}, {}, {}
        for method, rows in candidates.items():
            report = dict(template, orientations=rows)
            result = recommend_plan(report, feedback_path=feedback)
            if result.get("selected") is None:
                raise ValueError(f"actual product did not select {raw['id']} {method}: {result.get('reason')}")
            fixed = arbitrate(report, plan_learning.recommend_plan(report, feedback_path=feedback),
                              normalization_report=reference_report, feedback_path=feedback)
            if fixed.get("selected") is None:
                raise ValueError("fixed-reference arbitration failed")
            selected = result["selected"]["orientation"]
            fixed_selected = fixed["selected"]["orientation"]
            score = lambda values: objective(values, reference_rows, process=raw["process"], priority=raw["priority"])
            oracle[method] = float(score(rows).min())
            actual[method] = float(score([selected])[0])
            common[method] = float(score([fixed_selected])[0])
            selections[method] = dict(selected_direction=selected["direction"], selected_name=selected["name"],
                actual_source=result["selection_source"], actual_status=result["status"],
                actual_exact_score=result.get("verified_selection", {}).get("exact_score"),
                fixed_selected_direction=fixed_selected["direction"], own_reference_score=actual[method],
                fixed_reference_score=common[method], oracle_score=oracle[method],
                actual_winner_gap=actual[method]-oracle[method])
        case = {key: raw[key] for key in ("id", "dataset", "group", "split", "process", "priority")}
        case.update(candidate_oracle=oracle, actual_product=actual, common_reference_product=common,
                    selections=selections, original_case_sha256=sha(path))
        cases.append(case)
        (args.output/path.name).write_text(json.dumps(case, indent=2), encoding="utf-8")
        if len(cases)%50==0:
            print(json.dumps(dict(cases=len(cases), seconds=time.perf_counter()-started)), flush=True)
    if {p: sha(ROOT/p) for p in SOURCES} != snapshot:
        raise ValueError("Product recommendation source changed during replay")
    result = dict(cases=cases, count=len(cases), sources=snapshot, input_summary_sha256=sha(args.input/"summary.json"),
        reference="base44 + fixed legacy/blind/geometric/height_neural controls in both splits; no clipping beyond reference extrema",
        comparisons={kind: comparison_report(cases, kind) for kind in ("candidate_oracle", "actual_product", "common_reference_product")},
        actual_product_by_process={process: comparison_report([c for c in cases if c["process"]==process], "actual_product") for process in {c["process"] for c in cases}},
        policy_retuned=False, extra_geometry_measurements=0, seconds=time.perf_counter()-started,
        scope="Actual enhanced_planning on saved measured direction reports, empty findings and no feedback; not full CAD-import/UI simulation or a wall/hole edit evaluation")
    (args.output/"summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("cases", "actual_product_by_process")}), flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    with threadpool_limits(limits=1):
        main(p.parse_args())
