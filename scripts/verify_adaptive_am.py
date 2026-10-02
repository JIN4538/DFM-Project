"""Independently recompute proposed directions and audit source-group splits."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

import numpy as np
from threadpoolctl import threadpool_limits

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from benchmark_adaptive_am import mesh_for
from prepare_full_am import chunk_labels


def main(args):
    if args.output.exists():
        raise FileExistsError('Previous validation must not be replaced')
    summary=json.loads((args.input/'summary.json').read_text())
    policy=next(iter(summary['policies']))
    index=sqlite3.connect(f'file:{(ROOT.parent/"study/ai-full-corpus-2026-09-30/am-full/index.sqlite").as_posix()}?mode=ro',uri=True)
    public=sqlite3.connect(f'file:{(ROOT.parent/"study/ai-expansion-2026-09-30/public-expansion.sqlite").as_posix()}?mode=ro',uri=True)
    things=sqlite3.connect(f'file:{(ROOT.parent/"study/external-training-2026-09-30/thingi.sqlite").as_posix()}?mode=ro',uri=True)
    rows=[];maximum=0.;queries=0;overlaps=[];current=None;mesh=None
    cases=[json.loads(path.read_text()) for path in args.input.glob('*.json') if path.name!='summary.json']
    for case in sorted(cases,key=lambda row:(row['dataset'],row['id'],row['process'],row['priority'])):
        identity=(case['dataset'],case['id'])
        if identity!=current:
            record=json.loads(index.execute('SELECT record FROM records WHERE dataset=? AND id=?',identity).fetchone()[0])
            mesh=mesh_for(record,public,things);current=identity
            splits={value for value, in index.execute('SELECT DISTINCT split FROM records WHERE dataset=? AND group_id=? AND accepted=1',(record['dataset'],record['group']))}
            if splits!={summary['split']}:
                overlaps.append(dict(dataset=record['dataset'],group=record['group'],splits=sorted(splits)))
        added=case['extras'][policy]
        angle=added[0]['overhang_angle_deg'] if added else 45.
        height,area=chunk_labels(mesh,[row['direction'] for row in added],angles=[angle])
        error=max((abs(row['height_mm']/np.linalg.norm(mesh.extents)-height[i]) for i,row in enumerate(added)),default=0.)
        if case['process']!='PBF_POLYMER':
            error=max(error,max((abs(row['overhang_projected_area_sum_mm2']/mesh.area-area[0,i]) for i,row in enumerate(added)),default=0.))
        maximum=max(maximum,error);queries+=len(added)
        rows.append(dict(id=case['id'],dataset=case['dataset'],process=case['process'],priority=case['priority'],maximum_normalized_error=error))
    result=dict(cases=len(rows),queries=queries,maximum_normalized_error=maximum,group_split_overlaps=overlaps,
        passed=maximum<=1e-7 and not overlaps,method='Independent chunked original-vertex extrema and triangle projection; no neural prediction used as a measurement',records=rows)
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({key:value for key,value in result.items() if key!='records'}))
    if not result['passed']:
        raise SystemExit(1)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--input',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    with threadpool_limits(limits=1):main(parser.parse_args())
