"""Final app-path comparison on loaded public and authored STEP shapes."""
from __future__ import annotations
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from amdfm.io import load_model
from dfm import compound_planning as cp, enhanced_planning as enhanced, rl_planner as env
from dfm.machining import MachiningProfile
from dfm.tool_recommendation import review_with_tool_recommendation


def main(args):
    args.output.mkdir(parents=True,exist_ok=False)
    paths=list(sorted((ROOT/'examples/public_demo').glob('*.step')))
    paths+=list(sorted((ROOT/'examples/machining').glob('*.step')))
    paths+=args.extra_step
    paths=list(dict.fromkeys(p.resolve() for p in paths))
    sources={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
        [*cp.source_hashes(), 'amdfm/cad_worker.py','dfm/feature_routing.py','dfm/enhanced_planning.py','dfm/verified_selection.py']}
    records=[];start=time.monotonic()
    for path in paths:
        raw=path.read_bytes()
        entry=dict(file=str(path),sha256=hashlib.sha256(raw).hexdigest(),queries=[])
        try:
            model=load_model(raw,path.name,deflection_mm=.1,timeout_s=100)
            entry['cad']={key:model.metadata.get(key) for key in ('cad_valid','solid_count','exact_volume_mm3','cad_face_count')}
            for condition,(diameter,flute,reach) in enumerate(((None,None,None),(12.,4.,6.),(3.,15.,20.))):
                report=review_with_tool_recommendation(model,MachiningProfile(tool_diameter_mm=diameter,
                    flute_length_mm=flute,reach_mm=reach),visibility=False)
                report_before=deepcopy(report)
                for priority in ('balanced','accuracy','tool_access'):
                    for locked in (False,True):
                        prefs=dict(priority=priority,preserve_geometry=locked,allow_tool_change=True)
                        feedback=args.output/'absent-local-preferences.json'
                        with patch.object(cp,'MODEL_PATH',args.output/'absent-model.json'):
                            old=enhanced.recommend_plan(report,preferences=prefs,feedback_path=feedback)
                        with patch.object(cp,'MODEL_PATH',args.model.resolve()):
                            new=enhanced.recommend_plan(report,preferences=prefs,feedback_path=feedback)
                        before,after=old.get('selected'),new.get('selected')
                        row=dict(condition=condition,priority=priority,geometry_locked=locked,
                            old_status=old['status'],new_status=new['status'],
                            old_id=(before or {}).get('id'),new_id=(after or {}).get('id'),
                            compound=new.get('compound_planning'),before_changes=(before or {}).get('changes'),
                            after_changes=(after or {}).get('changes'))
                        if before and after:
                            a=env.evaluate_changes(report,before['changes'],preferences=prefs)
                            b=env.evaluate_changes(report,after['changes'],preferences=prefs)
                            qa,qb=[a['conflicts'],a['cost']],[b['conflicts'],b['cost']]
                            delta=next((x-y for x,y in zip(qb,qa) if abs(x-y)>1e-7),0.)
                            row.update(before=qa,after=qb,better=delta<0,worse=delta>0,same=delta==0)
                        entry['queries'].append(row)
                if report!=report_before:raise ValueError('Source report was changed')
        except Exception as error:entry['error']=repr(error)
        records.append(entry)
        print(json.dumps(dict(file=path.name,queries=len(entry['queries']),error=entry.get('error'))),flush=True)
        (args.output/'progress.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf8')
    rows=[r for e in records for r in e['queries']]
    summary=dict(files=len(records),completed_files=sum('error' not in e for e in records),queries=len(rows),
        compared=sum('before' in r for r in rows),better=sum(r.get('better',False) for r in rows),
        worse=sum(r.get('worse',False) for r in rows),same=sum(r.get('same',False) for r in rows),
        compound_selected=sum(str(r['new_id']).startswith('cnc-compound:') for r in rows),
        new_available=sum(r['old_status']=='unavailable' and r['new_status']!='unavailable' for r in rows),
        old_available_lost=sum(r['old_status']!='unavailable' and r['new_status']=='unavailable' for r in rows),
        seconds=time.monotonic()-start)
    after={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in sources}
    output=dict(scope='Actual STEP remeasurement; generated tool conditions; compound proposer disabled versus enabled in the final app path; empty user feedback',
        model_sha256=hashlib.sha256(args.model.read_bytes()).hexdigest(),source_before=sources,source_after=after,
        sources_unchanged=sources==after,summary=summary,records=records)
    (args.output/'evaluation.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(summary),flush=True)
    if sources!=after or summary['worse'] or summary['old_available_lost'] or summary['completed_files']!=len(records):
        raise ValueError('CAD audit detected a regression, changed source or incomplete file')


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--model',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--extra-step',type=Path,action='append',default=[])
    main(parser.parse_args())
