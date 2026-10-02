"""Exercise the real native recognizer/review on the frozen CNC holdout."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time
import numpy as np

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dfm.machining import MachiningProfile
from dfm.tool_recommendation import review_with_tool_recommendation
from dfm.enhanced_planning import recommend_plan


def main(folder,output):
    from threadpoolctl import threadpool_limits
    from dfm.cad_edit_preview import eligible_corner_edit,create_preview
    from dfm.edit_reinspection import compare_plan
    output.mkdir(parents=True,exist_ok=False)
    source=json.loads((folder/'manifest.json').read_text(encoding='utf8'));results=[];started=time.perf_counter()
    with threadpool_limits(limits=1):
        for row in source['records']:
            if row['split']!='test':continue
            path=folder/row['file']
            if hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('Frozen CAD changed')
            t=time.perf_counter()
            # Native converter appends .json/.npz; with_suffix would truncate
            # the decimal in a frozen CAD filename such as aspect2.6-0.
            from amdfm.cad_worker import convert
            from amdfm.io import exact_weld
            from amdfm.models import Model
            target=output/'native'/row['id'];target.parent.mkdir(exist_ok=True)
            convert(path,target,.05)
            info=json.loads(Path(str(target)+'.json').read_text(encoding='utf8'));arrays=np.load(str(target)+'.npz')
            mesh=exact_weld(arrays['vertices'],arrays['faces']);features=info.pop('features')
            info.update(filename=path.name,source_format='step',unit_status='declared_in_step',dimensions_confirmed=True)
            model=Model(mesh,info,features,arrays['face_ids'].copy(),arrays['body_ids'].copy())
            report=review_with_tool_recommendation(model,MachiningProfile(),row['direction'],visibility=False)
            report['plan_recommendation']=recommend_plan(report,feedback_path=output/'no-user-labels.json')
            p=report.get('external_feature_recognition',{}).get('verified_pockets',[])
            holes=report.get('verified_hole_inventory',{}).get('holes',[])
            good_holes=len(holes)==row['protected_hole_count'] and all(math.isclose(h['diameter_mm'],row['protected_hole_diameter_mm'],abs_tol=1e-6)
                and math.isclose(h['depth_mm'],row['protected_hole_depth_mm'],abs_tol=1e-6) for h in holes)
            good_pocket=len(p)==1 and math.isclose(p[0]['wall_height_mm'],row['depth_mm'],abs_tol=1e-6) and math.isclose(p[0]['area_mm2'],row['floor_area_mm2'],abs_tol=1e-5)
            request=eligible_corner_edit(report);edit=None
            if request is not None:
                try:
                    modified,audit=create_preview(path.read_bytes(),request,timeout=50)
                    edit=dict(status='verified',comparison=compare_plan(report,audit),remeasurement=audit['remeasurement'],
                        after_sha256=hashlib.sha256(modified).hexdigest())
                    (output/(row['id']+'-improved.step')).write_bytes(modified)
                except ValueError as error:edit=dict(status='rejected',reason=str(error))
            nn=[c for r in model.metadata.get('external_feature_recognition',[]) for c in r.get('candidates',[])]
            result=dict(id=row['id'],family=row['family'],hole_dimensions_correct=bool(good_holes),pocket_recognized_and_measured=bool(good_pocket),
                expected_holes=row['protected_hole_count'],verified_holes=len(holes),raw_neural_candidates=len(nn),
                plan=report['plan_recommendation'].get('selected'),edit=edit,seconds=time.perf_counter()-t)
            results.append(result)
            (output/'progress.json').write_text(json.dumps(results,indent=2),encoding='utf8')
            print(json.dumps(dict(processed=len(results),holes_correct=good_holes,pocket_recognized=good_pocket,edit=edit['status'] if edit else None)),flush=True)
    summary=dict(cases=len(results),hole_measurement_correct=sum(r['hole_dimensions_correct'] for r in results),
        pocket_recognized_and_measured=sum(r['pocket_recognized_and_measured'] for r in results),
        actual_edited_and_reinspected=sum(r['edit'] is not None and r['edit']['status']=='verified' for r in results),
        all_attempted_edits=sum(r['edit'] is not None for r in results),results=results,seconds=time.perf_counter()-started,
        scope='real product native learned feature candidates, certified holes, recommended tools and optional corner editing; synthetic new grouped CAD only')
    (output/'result.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in summary.items() if k!='results'}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('folder',type=Path);p.add_argument('output',type=Path);a=p.parse_args();main(a.folder,a.output)
