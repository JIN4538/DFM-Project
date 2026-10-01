"""Check original 26-pool filtering against base44 pool construction."""
import argparse
import json
from pathlib import Path
import sys

import numpy as np
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from amdfm.neural_orientation import proposal_pool, baseline_descriptor
from amdfm.ensemble_search import enrich_ensemble
from amdfm.orientation import compare_orientations, measure_orientation
from amdfm.profiles import Profile
from prepare_am_selector import open_db, CONDITIONS
from benchmark_adaptive_am import mesh_for


def filtered(mesh, seeds, measured):
    pool, sources = proposal_pool(mesh, seeds)
    old = np.asarray([row["direction"] for row in measured])
    keep = [i for i, d in enumerate(pool) if np.max(old@d) < 1-1e-10]
    return pool[keep], [sources[i] for i in keep]


def main(args):
    if args.output.exists():
        raise FileExistsError("Audit output already exists")
    groups = json.loads(args.groups.read_text())["records"]
    selected = [next(r for r in groups if r["dataset"]==dataset and r["split"]=="validation")
                for dataset in ("PBF-orientation", "CadQuarry", "Thingi10K")]
    public = open_db(ROOT.parent/"study/ai-expansion-2026-09-30/public-expansion.sqlite")
    things = open_db(ROOT.parent/"study/external-training-2026-09-30/thingi.sqlite")
    records = []
    for group in selected:
        mesh = mesh_for(group, public, things)
        for process, priority in CONDITIONS:
            profile = Profile(process=process)
            base = compare_orientations(mesh, profile, dense=True)
            for with_current in (False, True):
                baseline = list(base)
                if with_current:
                    row = measure_orientation(mesh, [.2, .7, .3], profile)
                    row.update(name="현재 지정 방향", candidate_role="current_only")
                    baseline.append(row)
                measured = enrich_ensemble(mesh, profile, baseline, priority=priority)["rows"]
                old_pool, old_sources = filtered(mesh, baseline, measured)
                new_pool, new_sources = filtered(mesh, measured, measured)
                before = baseline_descriptor(mesh, baseline, require_overhang=process!="PBF_POLYMER")
                after = baseline_descriptor(mesh, measured, require_overhang=process!="PBF_POLYMER")
                passed = (old_pool.shape==new_pool.shape and np.allclose(old_pool, new_pool, rtol=0, atol=1e-12)
                          and old_sources==new_sources and before==after)
                records.append(dict(id=group["id"], dataset=group["dataset"], process=process, priority=priority,
                    current_only=with_current, old_count=len(old_pool), new_count=len(new_pool), passed=bool(passed)))
                if not passed:
                    raise ValueError("Product/benchmark candidate pool mismatch")
    result = dict(passed=all(r["passed"] for r in records), cases=len(records), groups=len(selected), records=records,
        constraint="Both variants explicitly exclude ALL measured directions after proposal_pool, including current_only")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k:v for k,v in result.items() if k!="records"}))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--groups", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    with threadpool_limits(limits=1):
        main(p.parse_args())
