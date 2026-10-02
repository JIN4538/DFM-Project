"""Compact paired utility, source breakdown and geometry-group uncertainty."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def compare(cases,policy,control):
    differences=np.array([row['scores'][policy]-row['scores'][control] for row in cases])
    groups={}
    for row,delta in zip(cases,differences):
        groups.setdefault((row['dataset'],row['group']),[]).append(float(delta))
    grouped=np.array([np.mean(values) for values in groups.values()])
    rng=np.random.default_rng(302609)
    means=grouped[rng.integers(0,len(grouped),size=(10000,len(grouped)))].mean(1)
    return dict(cases=len(cases),distinct_groups=len(grouped),better=int(np.sum(differences< -1e-8)),
        same=int(np.sum(np.abs(differences)<=1e-8)),worse=int(np.sum(differences>1e-8)),
        mean_difference=float(differences.mean()),group_bootstrap_95_percentile_interval=np.quantile(means,[.025,.975]).tolist())


def main(args):
    if args.output.exists():
        raise FileExistsError('Use a new report path; previous evaluation is preserved')
    raw=args.input.read_bytes();report=json.loads(raw);cases=report['cases']
    policy=args.policy
    result=dict(input_sha256=hashlib.sha256(raw).hexdigest(),policy=policy,split=report['split'],groups=report['groups'],
        paired={control:compare(cases,policy,control) for control in ('legacy','blind')},
        by_dataset={dataset:{control:compare([case for case in cases if case['dataset']==dataset],policy,control)
                            for control in ('legacy','blind')} for dataset in sorted({case['dataset'] for case in cases})},
        counts={method:sorted({case['counts'][method] for case in cases}) for method in (policy,'legacy','blind')},
        incremental_wall_time_seconds={method:dict(zip(('median','p95','maximum'),np.quantile([case['seconds'][method] for case in cases],[.5,.95,1.])))
                                       for method in (policy,'legacy','blind')},
        time_scope='Incremental selection/refinement and six exact queries after the identical shared 18-query ensemble; loading/26-view baseline excluded equally',
        inference_note='Shape-local kernel residual fit on measured queries; pretrained network weights unchanged',
        normalization='One exact-measured common candidate union per case; each method retains the same shared baseline; raw candidate utility separately from UI plan arbitration',
        neural_model_sha256=report['neural_model_sha256'],algorithm_sha256=report['algorithm_sha256'])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--input',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--policy',default='retained4_residual20')
    main(parser.parse_args())
