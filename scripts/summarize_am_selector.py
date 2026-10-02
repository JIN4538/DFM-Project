"""Keep train/validation/test counts, incremental costs and failures explicit."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import numpy as np
from benchmark_am_selector import comparison


def main(args):
    if args.output.exists():
        raise FileExistsError("Do not replace prior evaluation")
    summary = json.loads((args.input/"summary.json").read_text())
    prepared = json.loads((args.data/"prepared.json").read_text())
    groups = json.loads((args.data/"groups.json").read_text())
    training = json.loads((args.model/"training.json").read_text())
    cases = summary["cases"]
    timings = {}
    for method in cases[0]["timings"]:
        timings[method] = {}
        for field in ("total_seconds", "acquisition_seconds", "measurement_seconds", "full_queries", "additional_descriptor_queries"):
            values = np.array([c["timings"][method][field] for c in cases])
            timings[method][field] = dict(min=float(values.min()), median=float(np.median(values)), p95=float(np.quantile(values, .95)), max=float(values.max()))
    memberships = {split: {(r["dataset"], r["group"]) for r in groups["records"] if r["split"]==split} for split in ("train", "validation", "test")}
    overlap = {a+"/"+b: len(memberships[a]&memberships[b]) for a, b in (("train", "validation"), ("train", "test"), ("validation", "test"))}
    error = max([v for c in cases for v in c["errors"].values()])
    result = dict(split=summary["split"], groups=summary["groups"], cases=len(cases),
        groups_by_source=dict(Counter(c["dataset"] for c in cases[::5])),
        process_case_counts=dict(Counter(c["process"] for c in cases)),
        comparisons=summary["comparisons"], by_process=summary["by_process"], timings=timings,
        control_comparisons={control: comparison(cases, "height_neural", control) for control in ("legacy", "blind", "geometric")},
        control_by_process={process: {control: comparison([c for c in cases if c["process"]==process], "height_neural", control)
            for control in ("legacy", "blind", "geometric")} for process in {c["process"] for c in cases}},
        by_source={source: {method: {control: comparison([c for c in cases if c["dataset"]==source], method, control)
            for control in ("legacy", "blind", "geometric", "height_neural") if control!=method}
            for method in list(summary["policies"])+["height_neural"]} for source in {c["dataset"] for c in cases}},
        raw_proposal_mean={method: float(np.mean([c["raw_proposal_scores"][method] for c in cases])) for method in cases[0]["scores"]},
        final_exact_mean={method: float(np.mean([c["scores"][method] for c in cases])) for method in cases[0]["scores"]},
        independent_max_error=error, cross_split_group_overlap=overlap,
        training_groups=training["train_groups"], training_candidate_rows=training["train_candidate_rows"],
        validation_groups=len(memberships["validation"]), untouched_test_groups=len(memberships["test"]),
        training_seconds=training["seconds"], benchmark_seconds=summary["seconds"],
        model_sha256=summary["selector_sha256"], frozen_neural_sha256=summary["neural_sha256"],
        maximum_training_label_error=prepared["maximum_independent_error"],
        summary_sha256=hashlib.sha256((args.input/"summary.json").read_bytes()).hexdigest(),
        cost_note=summary["cost_note"], product_adopted=False,
        interpretation="Geometric recommendation utility for fixed 45 degree conditions; no generic accuracy claim, no manufacturing outcome labels. Ensemble spread is an acquisition heuristic, not calibrated probability.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k not in ("timings", "by_process", "by_source", "control_by_process")}))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--model", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    main(p.parse_args())
