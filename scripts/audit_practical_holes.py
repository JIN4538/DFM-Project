"""Actual bounded STEP input path; old checks, NN records and CAD stay intact."""
from __future__ import annotations
from copy import deepcopy
import hashlib,json,sys,time
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from amdfm.io import load_model
from amdfm.models import json_bytes
from dfm.machining import MachiningProfile, review_machining
from dfm.tool_recommendation import review_with_tool_recommendation
from dfm.hole_view import entry_choice
from dfm.machining_view import machining_html


def main():
    output=Path(sys.argv[1]);output.mkdir(parents=True,exist_ok=False)
    paths=sorted((ROOT/'examples/machining').glob('*.step'))+sorted((ROOT/'examples/public_demo').glob('*.step'))
    paths+=sorted((ROOT/'examples/learning_validation/hole_review').glob('*.step'))
    rows=[]
    for path in paths:
        start=time.monotonic();row=dict(file=path.relative_to(ROOT).as_posix(),source_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        try:
            model=load_model(path.read_bytes(),path.name,timeout_s=120)
            features=json_bytes(model.cad_features)
            neural=json_bytes(model.metadata.get('external_feature_recognition',[]))
            fingerprint=model.fingerprint
            checks=[]
            for direction in ((0,0,1),(0,0,-1),(1,0,0)):
                profile=MachiningProfile(tool_diameter_mm=3,flute_length_mm=12,reach_mm=15)
                raw=review_machining(model,profile,direction)
                report=review_with_tool_recommendation(model,profile,direction)
                native=report.get('native_hole_face_review')
                preserved=not native or native==next(f for f in raw['findings'] if f['id']=='cnc_holes')
                coverage=next(f for f in raw['findings'] if f['id']=='cnc_coverage')==next(f for f in report['findings'] if f['id']=='cnc_coverage')
                passed=(preserved and coverage and all(report['profile'][f]==getattr(profile,f) for f in ('tool_diameter_mm','flute_length_mm','reach_mm')))
                checks.append(dict(direction=direction,passed=passed,holes=len(report['verified_hole_inventory']['holes']),
                                   inventory_status=report['verified_hole_inventory']['status'],raw_face_review_preserved=bool(preserved),coverage_preserved=coverage))
            holes=report['verified_hole_inventory']['holes']
            if holes:
                choice=entry_choice(holes,(0,0,1))
                automatic=review_with_tool_recommendation(model,MachiningProfile(),choice['direction'])
                compatible=[h for h in automatic['verified_hole_inventory']['holes'] if h['entry_matches_direction']]
                okay=len(compatible)==choice['covered_count'] and all(h['depth_mm']>0 for h in compatible)
                checks.append(dict(auto_entry_direction=choice,passed=okay))
                (output/(path.stem+'.json')).write_bytes(json_bytes(automatic))
                (output/(path.stem+'.html')).write_text(machining_html(automatic,model),encoding='utf8')
            unchanged=(features==json_bytes(model.cad_features) and neural==json_bytes(model.metadata.get('external_feature_recognition',[])) and fingerprint==model.fingerprint
                       and row['source_sha256']==hashlib.sha256(path.read_bytes()).hexdigest())
            row.update(checks=checks,passed=bool(unchanged and all(c['passed'] for c in checks)),input_and_neural_unchanged=unchanged,
                       inventory=report['verified_hole_inventory'],solids=model.metadata['solid_count'])
        except (ValueError,MemoryError) as exc:
            row.update(passed=False,error=str(exc))
        row['seconds']=time.monotonic()-start
        rows.append(row)
        (output/'progress.json').write_bytes(json_bytes(rows))
        print(json.dumps({k:row.get(k) for k in ('file','passed','error','seconds')},ensure_ascii=False),flush=True)
    result=dict(files=len(rows),passed=sum(r['passed'] for r in rows),direction_conditions=sum(len(r.get('checks',[])) for r in rows),records=rows,
                nn_weights_or_training_changed=False)
    (output/'result.json').write_bytes(json_bytes(result))
    if result['passed']!=result['files']:raise SystemExit(1)

if __name__=='__main__':main()
