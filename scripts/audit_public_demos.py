"""Public STEP input, independent authored dimensions, and AM/CNC reports."""
import argparse,hashlib,json,sys,time
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from amdfm.io import load_model
from amdfm.analysis import review
from amdfm.profiles import Profile
from amdfm.detail import run_detail,attach_detail
from amdfm.ai_search import extend_review_orientations
from dfm.tool_recommendation import review_with_tool_recommendation
from dfm.machining import MachiningProfile
from dfm.conclusion import summarize_conclusion

def main(root):
    manifest=json.loads((ROOT/'examples/public_demo/manifest.json').read_text(encoding='utf8'));results=[];started=time.monotonic()
    for item in manifest:
        raw=(ROOT/'examples/public_demo'/item['file']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('Demo SHA mismatch')
        model=load_model(raw,item['file'],deflection_mm=.1,timeout_s=100)
        record=dict(file=item['file'],cad_valid=model.metadata.get('cad_valid'),solid_count=model.metadata.get('solid_count'),
                    exact_volume_mm3=model.metadata.get('exact_volume_mm3'),mesh_volume_mm3=float(model.mesh.volume),
                    triangles=len(model.mesh.faces),face_count=model.metadata.get('cad_face_count'),checks={},parameter_checks=[])
        # External construction hole_d is not a learned measurement. Compare
        # it to analytic cylinder diameters, preserving nonmatching cases.
        params=json.loads(item.get('params','{}'));p=params.get('hole_d')
        if p:
            target=p['default'];actual=[f['diameter_mm'] for f in model.cad_features if f['kind']=='cylinder' and f.get('role')=='inner']
            record['parameter_checks'].append(dict(parameter='hole_d',source_value_mm=target,analytic_diameters_mm=actual,
                agrees=bool(actual) and min(abs(d-target) for d in actual)<1e-6))
        for process in ('MEX','VPP','PBF_POLYMER','PBF_METAL'):
            profile=Profile(process=process,minimum_wall_mm=1.2,minimum_hole_mm=2.)
            report=review(model,profile,dense=True)
            if item.get('family') in ('bracket','plate','enclosure'):
                detail=run_detail(model,profile,mode='wall',timeout_s=15);report=attach_detail(report,detail)
            report=extend_review_orientations(model,profile,report,timeout_s=5)
            conclusion=summarize_conclusion(report)
            record['checks'][process]=dict(title=conclusion['title'],issues=[i['id'] for i in conclusion['issues']],
                pending=[i['id'] for i in conclusion['pending']],plan_title=(conclusion['plan'].get('selected') or {}).get('title'),
                neural_added=report.get('neural_search',{}).get('added_count'),wall_status=report.get('details',{}).get('wall',{}).get('status'))
        cnc=review_with_tool_recommendation(model,MachiningProfile(),visibility=False);conclusion=summarize_conclusion(cnc)
        record['checks']['CNC']=dict(title=conclusion['title'],issues=[i['id'] for i in conclusion['issues']],
            pending=[i['id'] for i in conclusion['pending']],tool=cnc['tool_recommendation']['values'],
            graph_status=[r['status'] for r in cnc.get('external_feature_recognition',{}).get('records',[])])
        results.append(record);print(json.dumps(record,ensure_ascii=False),flush=True)
    model_shas={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'data/models').glob('*.json'))}
    result=dict(model_sha256=model_shas,files=len(results),process_reviews=sum(len(r['checks']) for r in results),results=results,
        dimension_matches=sum(c['agrees'] for r in results for c in r['parameter_checks']),
        dimension_checks=sum(len(r['parameter_checks']) for r in results),seconds=time.monotonic()-started)
    (root/'public-demo-review-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);args=p.parse_args();args.root.mkdir(parents=True,exist_ok=True);main(args.root)
