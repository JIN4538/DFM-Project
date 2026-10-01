"""Learn change ranking on remeasured external CAD, with explicit policy labels."""
import argparse,gzip,hashlib,json,sys,time
from pathlib import Path
import numpy as np
from sklearn.ensemble import GradientBoostingRegressor
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dfm.plan_learning import FEATURES,SCHEMA,source_hashes,candidate_plans,_stable,load_plan_model,predict_score
from scripts.train_plan_model import selection_objective,export_tree,evaluate,am_reports,cnc_reports

def external_reports(cases):
    for c in cases:
        pockets=c['pockets']
        if not pockets:continue
        width=min(d.get('entry_circle_diameter_mm', d['width_mm']) for d in pockets);depth=max(d['wall_height_mm'] for d in pockets)
        for tool in (.6,1.25):
            profile=dict(machine='external CAD counterfactual',material='unspecified',tool_diameter_mm=width*tool,
                flute_length_mm=depth*.75,reach_mm=depth*1.1,hole_depth_ratio_limit=None)
            for priority in ('balanced','accuracy','tool_access'):
                report=dict(process='MILLING_3AXIS',profile=profile,review_context={'priority':priority},findings=[
                    dict(id='cnc_input',status='observed',measurements={'cad_feature_dimensions_available':True}),
                    dict(id='cnc_holes',status='not_detected',measurements={'cylindrical_faces':[]}),
                    dict(id='cnc_curved_corners',status='not_detected',measurements={'cylindrical_faces':[]}),
                    dict(id='cnc_rectangular_pockets',status='attention',measurements={'pockets':[d for d in pockets if d['feature']=='rectangular_pocket']}),
                    dict(id='cnc_learned_pockets',status='attention',measurements={'pockets':[d for d in pockets if d['feature']!='rectangular_pocket']})])
                yield 'external-'+c.get('group_id',c['id']),('validation' if c['split']=='val' else c['split']),report

def train(cases_path,output,baseline_path=None,filename='plan_ranker_external_v2.json'):
    output.mkdir(parents=True,exist_ok=False);started=time.monotonic();queries=[]
    for group,split,report in external_reports(json.loads(cases_path.read_text(encoding='utf8'))):
        plans,_,baseline=candidate_plans(report)
        if len(plans)<2:continue
        features=[p['_features'] for p in plans]
        queries.append(dict(group=group,split=split,features=features,targets=[selection_objective(x) for x in features],
            stable_keys=[_stable(p) for p in plans],baseline_index=next((i for i,p in enumerate(plans) if p['id']==baseline),0)))
    external_test=[q for q in queries if q['split']=='test'];external_val=[q for q in queries if q['split']=='validation']
    # Retain generated training examples; family holdouts remain test-only.
    for iterator in (am_reports(300930),cnc_reports(300930)):
        for group,split,report,_ in iterator:
            plans,_,baseline=candidate_plans(report,report.get('_training_preferences'))
            if len(plans)<2:continue
            features=[p['_features'] for p in plans];queries.append(dict(group=group,split=split,features=features,
                targets=[selection_objective(x) for x in features],stable_keys=[_stable(p) for p in plans],
                baseline_index=next((i for i,p in enumerate(plans) if p['id']==baseline),0)))
    trainrows=[q for q in queries if q['split']=='train']; val=[q for q in queries if q['split']=='validation'];test=[q for q in queries if q['split']=='test']
    x=np.asarray([f for q in trainrows for f in q['features']]);y=np.asarray([f for q in trainrows for f in q['targets']]);print('Training',len(x),'candidate rows',flush=True)
    candidates={};scores={}
    for trees,depth in ((180,4),(240,5)):
        fit=GradientBoostingRegressor(n_estimators=trees,max_depth=depth,learning_rate=.05,min_samples_leaf=5,random_state=300930).fit(x,y)
        key=f'{trees}-depth-{depth}';candidates[key]=fit;scores[key]=evaluate(val,fit.predict);print(key,scores[key],flush=True)
    selected=min(scores,key=lambda key:scores[key]['mean_objective_regret']);fit=candidates[selected]
    model=dict(schema=SCHEMA,id='external-cad-plan-ranker-v2',features=list(FEATURES),sources=source_hashes(),
        training_scope='External MFCAD exact rectangular pocket dimensions plus generated candidate scenarios; targets are disclosed project trade-off policy, not external expert improvements.',
        training_rows=len(x),training_groups=len({q['group'] for q in trainrows}),seed=300930,
        intercept=float(fit.init_.constant_[0][0]),learning_rate=float(fit.learning_rate),trees=[export_tree(t[0]) for t in fit.estimators_],
        external_source=dict(pocket_cases_sha256=hashlib.sha256(cases_path.read_bytes()).hexdigest(),source='hducg/MFCAD MIT',measurement='CAD planes/vertices',
            external_training_groups=len({q['group'] for q in trainrows if q['group'].startswith('external-')})))
    if baseline_path:
        raw=baseline_path.read_bytes();manifest=json.loads(baseline_path.with_suffix('.manifest.json').read_text(encoding='utf8'))
        if hashlib.sha256(raw).hexdigest()!=manifest['sha256']:raise ValueError('Frozen baseline checksum mismatch')
        baseline=json.loads(raw)
        if tuple(baseline['features'])!=FEATURES:raise ValueError('Frozen baseline feature schema mismatch')
    else:baseline=load_plan_model()
    new=evaluate(external_test,fit.predict);old=evaluate(external_test,lambda xs:[predict_score(baseline,x) for x in xs])
    summary=dict(external_new=new,external_old=old,all_heldout=evaluate(test,fit.predict),selection=scores,
        eligible_for_deployment=new['mean_objective_regret']<=old['mean_objective_regret']+1e-9,
        external_test_groups=len({q['group'] for q in external_test}),external_validation_groups=len({q['group'] for q in external_val}),
        target_definition='Disclosed objective in train_plan_model.selection_objective; no expert-designed improvement pairs in source datasets',seconds=time.monotonic()-started)
    model['id']='external-cad-full-plan-ranker-v3' if filename.endswith('_v3.json') else model['id']
    model['training_scope']='Exact externally annotated CAD triangle/rectangle/hexagon prism remeasurements and generated scenarios. Counterfactual before/after targets use disclosed project trade-off policy; no external expert improvement labels.'
    raw=json.dumps(model,separators=(',',':')).encode();path=output/filename;path.write_bytes(raw);path.with_suffix('.manifest.json').write_text(json.dumps(dict(schema=SCHEMA,sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))),encoding='utf8')
    (output/'evaluation.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
    with gzip.open(output/'queries.json.gz','wt',encoding='utf8') as f:json.dump(queries,f)
    print(json.dumps(summary),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--cases',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--baseline',type=Path);p.add_argument('--filename',default='plan_ranker_external_v2.json')
    a=p.parse_args();train(a.cases,a.output,a.baseline,a.filename)
