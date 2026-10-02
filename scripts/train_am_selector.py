"""Group-bootstrap regret ensemble; validation selects acquisition policy later."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from amdfm.proposal_selector import SCHEMA, FEATURES, feature_sha256, portable_predict


def export(fit):
    trees = []
    for stage in fit._predictors:
        rows = []
        for node in stage[0].nodes:
            if node["is_categorical"]:
                raise ValueError("categorical nodes unsupported")
            rows.append([-2, 0., -1, -1, float(node["value"])] if node["is_leaf"] else
                [int(node["feature_idx"]), float(node["num_threshold"]), int(node["left"]),
                 int(node["right"]), float(node["value"])])
        trees.append(rows)
    return dict(intercept=float(fit._baseline_prediction[0, 0]), trees=trees)


def main(args):
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output/"training-source.py").write_bytes(Path(__file__).read_bytes())
    (args.output/"selector-source.py").write_bytes((ROOT/"amdfm/proposal_selector.py").read_bytes())
    prepared = json.loads((args.input/"prepared.json").read_text())
    if feature_sha256() != prepared["feature_sha256"]:
        raise ValueError("features changed since preparation")
    records = [r for r in prepared["records"] if r["split"]=="train"]
    count = sum(r["candidates"]*len(prepared["conditions"]) for r in records)
    x = np.lib.format.open_memmap(args.output/"train-x.npy", mode="w+", dtype="float32", shape=(count, len(FEATURES)))
    y = np.empty(count, dtype="float32")
    weight = np.empty(count, dtype="float32")
    group_index = np.empty(count, dtype="int32")
    offset = 0
    for group, record in enumerate(records):
        with np.load(args.input/record["shard"], allow_pickle=False) as shard:
            n = shard["y"].size
            x[offset:offset+n] = shard["x"].reshape(-1, len(FEATURES))
            y[offset:offset+n] = shard["y"].reshape(-1)
            w = shard["weight"].reshape(-1)
            weight[offset:offset+n] = w/(w.mean()*n)*2000
            group_index[offset:offset+n] = group
            offset += n
    x.flush()
    members, fits = [], []
    started = time.perf_counter()
    error = 0.
    for member in range(3):
        # Bootstrap at original-group level; sibling candidates never resampled separately.
        rng = np.random.default_rng(309300+member)
        counts = np.bincount(rng.integers(0, len(records), len(records)), minlength=len(records))
        fit = HistGradientBoostingRegressor(max_iter=180, max_leaf_nodes=31, learning_rate=.06,
            min_samples_leaf=40, l2_regularization=1., early_stopping=False, random_state=309300+member)
        fit.fit(x, y, sample_weight=weight*counts[group_index])
        model = export(fit)
        parity = float(np.max(np.abs(fit.predict(x[:2048])-portable_predict(model, x[:2048]))))
        error = max(error, parity)
        if parity > 1e-7:
            raise ValueError("portable model prediction mismatch")
        members.append(model)
        fits.append(dict(member=member, sampled_groups=int(np.sum(counts>0)), trees=180, leaves=31, parity_error=parity))
        print(json.dumps(dict(member=member, seconds=time.perf_counter()-started, parity_error=parity)), flush=True)
    model = dict(schema=SCHEMA, id="am-regret-selector-v1", features=FEATURES, feature_sha256=feature_sha256(),
        members=members, train_groups=len(records), train_candidate_rows=count, neural_model_sha256=prepared["neural_model_sha256"],
        groups_manifest_sha256=prepared["groups_manifest_sha256"], conditions=prepared["conditions"],
        angle_degrees=[45.], training_source="Original public mesh projections under the declared project objective; not expert outcome labels",
        group_bootstrap=True, seed=309300, test_labels_opened=False, product_adopted=False)
    path = args.output/"am_regret_selector_v1.json"
    raw = json.dumps(model, separators=(",", ":"), allow_nan=False).encode()
    path.write_bytes(raw)
    path.with_suffix(".manifest.json").write_text(json.dumps(dict(schema=SCHEMA, sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw))))
    report = dict(train_groups=len(records), train_candidate_rows=count, members=fits, maximum_portable_error=error,
        seconds=time.perf_counter()-started, weights_sha256=hashlib.sha256(raw).hexdigest(),
        pipeline_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), feature_sha256=feature_sha256(),
        predefined_validation_policies=["learned", "uncertainty05", "uncertainty1", "retain2_learned"],
        selection="Choose mean exact six-query utility on validation. Freeze policy before any new test measurements.")
    (args.output/"training.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    with threadpool_limits(limits=2):
        main(parser.parse_args())
