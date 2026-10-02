"""Frozen grouped CAD -> real exported edit labels -> portable MLP -> equal-budget audit."""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import time
import numpy as np

ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT))
from dfm.cad_edit_pairs import read_shape, write_step, round_corners
from dfm.cad_graph import extract_graph
from dfm.external_features_review import pocket_dimensions
from dfm.edit_learning import features, descriptor, FEATURES, predict, candidate_order


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf8')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def generate(folder):
    from OCP.gp import gp_Pnt, gp_Vec, gp_Trsf, gp_Ax1, gp_Dir, gp_Ax2
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon, BRepBuilderAPI_MakeFace, BRepBuilderAPI_Transform
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakePrism, BRepPrimAPI_MakeCylinder
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.BRepCheck import BRepCheck_Analyzer
    folder.mkdir(parents=True, exist_ok=False); records=[]
    # Every parameter/rotation/radius variant of a family stays in one split.
    # Evaluation elongations (1.8/2.6) never occur in training (1/1.4).
    for sides in (3, 4, 6):
        for holes in (0, 1, 2, 3):
            for aspect_index, aspect in enumerate((1., 1.4, 1.8, 2.6)):
                split = ('train', 'train', 'validation', 'test')[aspect_index]
                group=f'polygon{sides}-holes{holes}-aspect{aspect}'
                for sample in range(5):
                    rng=np.random.default_rng(100200+int(hashlib.sha256((group+str(sample)).encode()).hexdigest()[:7],16))
                    scale=float(rng.uniform(.55,1.8)); depth=float(rng.uniform(3,14))*scale
                    rx, ry=8*aspect*scale,8*scale; length=2*rx+22*scale; width=42*scale; height=depth+6*scale
                    center=np.array([length/2,16*scale]); z=height-depth
                    xy=np.array([[center[0]+rx*math.cos(2*math.pi*i/sides),center[1]+ry*math.sin(2*math.pi*i/sides)] for i in range(sides)])
                    polygon=BRepBuilderAPI_MakePolygon()
                    for x,y in xy:polygon.Add(gp_Pnt(float(x),float(y),z))
                    polygon.Close()
                    cutter=BRepPrimAPI_MakePrism(BRepBuilderAPI_MakeFace(polygon.Wire()).Face(),gp_Vec(0,0,depth+2)).Shape()
                    shape=BRepAlgoAPI_Cut(BRepPrimAPI_MakeBox(length,width,height).Shape(),cutter).Shape()
                    hole_radius=.9*scale
                    hole_centers=[]
                    for x in np.linspace(length*.25,length*.75,holes) if holes else []:
                        hole_centers.append([float(x),35*scale])
                        cutter=BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(float(x),35*scale,-1),gp_Dir(0,0,1)),hole_radius,height+2).Shape()
                        shape=BRepAlgoAPI_Cut(shape,cutter).Shape()
                    angle=.43*sample; transform=gp_Trsf(); transform.SetRotation(gp_Ax1(gp_Pnt(0,0,0),gp_Dir(0,1,0)),angle)
                    shape=BRepBuilderAPI_Transform(shape,transform,True).Shape()
                    axis=[math.sin(angle),0.,math.cos(angle)]
                    area=abs(float(np.sum(xy[:,0]*np.roll(xy[:,1],-1)-xy[:,1]*np.roll(xy[:,0],-1))))/2
                    expected_volume=length*width*height-area*depth-holes*math.pi*hole_radius**2*height
                    if not BRepCheck_Analyzer(shape).IsValid():raise ValueError('Invalid independent CAD construction')
                    file=f'{group}-{sample}.step'; sha=write_step(shape,folder/file)
                    # Separate polygon-angle expression, independent of the edit implementation.
                    coefficient=0.
                    for i,p in enumerate(xy):
                        a,b=xy[i-1]-p,xy[(i+1)%sides]-p
                        theta=math.acos(float(a@b/(np.linalg.norm(a)*np.linalg.norm(b))))
                        coefficient+=1/math.tan(theta/2)-(math.pi-theta)/2
                    records.append(dict(id=f'{group}-{sample}',family=group,split=split,file=file,sha256=sha,
                        sides=sides,direction=axis,depth_mm=depth,floor_height_mm=z,floor_area_mm2=area,
                        expected_volume_mm3=expected_volume,rounded_area_coefficient=coefficient,
                        protected_hole_diameter_mm=2*hole_radius,protected_hole_count=holes,
                        protected_hole_depth_mm=height,protected_outer_size_mm=[length,width,height],
                        maximum_corner_fraction=.9 if holes%2 else .7,
                        parameters=dict(aspect=aspect,sample=sample,scale=scale,angle=angle)))
    manifest=dict(schema='independent-cad-edit-study/1',created_before_labels=True,
        generator_sha256=digest(Path(__file__)),records=records,
        splits={s:sum(r['split']==s for r in records) for s in ('train','validation','test')},
        split_policy='whole geometry family; validation/test elongation withheld; rotations and edit radii stay within family',
        supervision='synthetic CAD geometry only; no expert preference or physical manufacturing labels',
        candidates=[.35,.6,.8,.98,1.08],minimum_corner_fraction=.6,
        constraints='only pocket corner radius may change; external envelope, hole diameter/count/depth and pocket depth protected')
    save(folder/'manifest.json',manifest)
    print(json.dumps(dict(stage='frozen',cases=len(records),splits=manifest['splits'])),flush=True)


def measured_pocket(shape, record):
    graph=extract_graph(shape); axis=np.asarray(record['direction']); z=record['floor_height_mm']
    faces=[m for m in graph['measurements'] if m['surface_kind']==0 and
        (abs(np.asarray(m['centroid_mm'])@axis-z)<1e-6 or abs(np.asarray(m['centroid_mm'])@axis-(z+record['depth_mm']/2))<1e-6)]
    candidate=dict(feature={3:'triangular_pocket',4:'rectangular_pocket',6:'6sides_pocket'}[record['sides']],
        face_ids=[m['face_id'] for m in faces],measured_faces=faces)
    p=pocket_dimensions(candidate,record['direction'])
    if p is None or not math.isclose(p['wall_height_mm'],record['depth_mm'],abs_tol=1e-6) or not math.isclose(p['area_mm2'],record['floor_area_mm2'],abs_tol=1e-5):
        raise ValueError('Exact measurements disagree with frozen independent dimensions')
    if not math.isclose(graph['volume_mm3'],record['expected_volume_mm3'],rel_tol=1e-7,abs_tol=1e-5):
        raise ValueError('Independent source volume mismatch')
    p['direction']=record['direction']
    return descriptor(p,graph['measurements']),graph


def label_case(job):
    folder,record,fractions=job; path=Path(folder)/record['file']
    if digest(path)!=record['sha256']:raise ValueError('Frozen CAD drift')
    shape=read_shape(path); pocket,graph=measured_pocket(shape,record); rows=[]
    from dfm.cad_edit_worker import main as edit_worker
    for fraction in fractions:
        radius=pocket['entry_circle_diameter_mm']*fraction/2
        output=Path(folder)/'pairs'/record['id']/str(fraction); output.mkdir(parents=True,exist_ok=False)
        (output/'before.step').write_bytes(path.read_bytes())
        save(output/'request.json',dict(pocket=pocket,radius=radius))
        start=time.perf_counter(); code=edit_worker(output); seconds=time.perf_counter()-start
        audit=json.loads((output/'result.json').read_text(encoding='utf8')); valid=code==0
        row=dict(case_id=record['id'],family=record['family'],split=record['split'],fraction=fraction,radius_mm=radius,
            features=features(pocket,radius).tolist(),valid=valid,seconds=seconds,error=audit.get('error'),
            satisfies_tool_radius=fraction>=.6-1e-8,protected_radius_ok=fraction<=record['maximum_corner_fraction']+1e-8,
            source_sha256=record['sha256'],request_file=str((output/'request.json').relative_to(Path(folder))))
        if valid:
            delta=audit['remeasurement']['after_volume_mm3']-record['expected_volume_mm3']
            expected=record['rounded_area_coefficient']*radius**2*record['depth_mm']
            if not math.isclose(delta,expected,rel_tol=1e-6,abs_tol=1e-5) or audit['remeasurement']['protected_cylinder_faces']!=record['protected_hole_count']:
                raise ValueError('Edited STEP differs from independent analytic/protected-hole truth')
            row.update(material_log_fraction=math.log1p(delta/(record['floor_area_mm2']*record['depth_mm'])),
                material_delta_mm3=delta,material_change_percent=100*delta/record['expected_volume_mm3'],
                independent_delta_mm3=expected,after_sha256=audit['after_sha256'],
                radius_after_mm=audit['remeasurement']['pockets'][0]['radius_after_mm'],
                depth_after_mm=audit['remeasurement']['pockets'][0]['depth_after_mm'],
                protected_cylinder_faces=audit['remeasurement']['protected_cylinder_faces'],
                protected_violation=False,after_file=str((output/'after.step').relative_to(Path(folder))))
        rows.append(row)
    return dict(id=record['id'],pocket=pocket,rows=rows)


def labels(folder,workers):
    import concurrent.futures
    manifest=json.loads((folder/'manifest.json').read_text(encoding='utf8')); output=[]; start=time.perf_counter()
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
        for result in pool.map(label_case,[(str(folder),r,manifest['candidates']) for r in manifest['records']]):
            output.append(result)
            if len(output)%10==0:
                save(folder/'labels-progress.json',output)
                print(json.dumps(dict(stage='CAD labels',completed=len(output),total=len(manifest['records']),seconds=time.perf_counter()-start)),flush=True)
    save(folder/'labels.json',dict(manifest_sha256=digest(folder/'manifest.json'),cases=output,seconds=time.perf_counter()-start))


def portable(net,mean,scale):
    return dict(mean=mean.tolist(),scale=scale.tolist(),layers=[dict(weights=w.tolist(),bias=b.tolist()) for w,b in zip(net.coefs_,net.intercepts_)])


def train(folder,output):
    from sklearn.neural_network import MLPClassifier,MLPRegressor
    from sklearn.metrics import balanced_accuracy_score,mean_absolute_error
    from threadpoolctl import threadpool_limits
    labels=json.loads((folder/'labels.json').read_text(encoding='utf8'))
    rows=[r for case in labels['cases'] for r in case['rows']]
    train_rows=[r for r in rows if r['split']=='train']; validation=[r for r in rows if r['split']=='validation']
    x=np.array([r['features'] for r in train_rows]); mean=x.mean(0); scale=np.maximum(x.std(0),1e-6); z=(x-mean)/scale
    valid=np.array([r['valid'] for r in train_rows]); successes=np.flatnonzero(valid)
    history=[]; models=[]
    # Validation alone selects the fixed seed/network. Test outcomes remain unread.
    with threadpool_limits(limits=1):
        for seed in (12,41,73):
            classifier=MLPClassifier(hidden_layer_sizes=(32,16),max_iter=1500,alpha=.01,random_state=seed)
            classifier.fit(z,valid)
            regression=MLPRegressor(hidden_layer_sizes=(32,16),max_iter=1800,alpha=.001,random_state=seed)
            regression.fit(z[successes],[train_rows[i]['material_log_fraction'] for i in successes])
            model=dict(schema='cad-edit-surrogate/1',features=list(FEATURES),networks=dict(validity=portable(classifier,mean,scale),material=portable(regression,mean,scale)))
            xv=np.array([r['features'] for r in validation]); pred=predict(xv,model)
            accuracy=float(balanced_accuracy_score([r['valid'] for r in validation],pred['validity']>=.5))
            good=[i for i,r in enumerate(validation) if r['valid']]
            error=float(mean_absolute_error([validation[i]['material_log_fraction'] for i in good],pred['material'][good]))
            history.append(dict(seed=seed,validation_balanced_accuracy=accuracy,validation_material_log_mae=error))
            models.append(model)
    chosen=min(range(len(models)),key=lambda i:(-history[i]['validation_balanced_accuracy'],history[i]['validation_material_log_mae']))
    output.parent.mkdir(parents=True,exist_ok=True); save(output,models[chosen])
    manifest=dict(model_sha256=digest(output),labels_sha256=digest(folder/'labels.json'),cad_manifest_sha256=digest(folder/'manifest.json'),
        training_records=len(train_rows),training_CAD=len({r['case_id'] for r in train_rows}),
        validation_records=len(validation),test_used_for_fitting=False,selected_seed=history[chosen]['seed'],history=history,
        input_source_sha256=digest(ROOT/'dfm/edit_learning.py'),
        supervision='actual OCCT operation success/rejection; exported and reimported material delta; independent prism volume and protected-hole checks',
        target='edit geometry feasibility and normalized material change, not expert optimality',
        runtime_adoption='research comparison pending; no prediction certifies a CAD edit')
    save(output.with_suffix('.manifest.json'),manifest); save(folder/'training.json',manifest)
    print(json.dumps(dict(stage='trained',training_records=len(train_rows),selected=history[chosen])),flush=True)


def compare(folder,model_path):
    from dfm.edit_learning import load_model
    manifest=json.loads((folder/'manifest.json').read_text(encoding='utf8')); labels=json.loads((folder/'labels.json').read_text(encoding='utf8'))
    model=load_model(model_path); records={r['id']:r for r in manifest['records']}; results=[]
    if digest(folder/'manifest.json')!=labels['manifest_sha256']:raise ValueError('Frozen holdout manifest drift')
    for case in labels['cases']:
        rows=case['rows']; record=records[case['id']]
        if record['split']!='test':continue
        allowed=[i for i,r in enumerate(rows) if r['satisfies_tool_radius'] and r['protected_radius_ok']]
        truth=[i for i in allowed if rows[i]['valid']]
        optimum=min(truth,key=lambda i:rows[i]['material_delta_mm3']) if truth else None
        start=time.perf_counter()
        learned,audit=candidate_order(case['pocket'],[r['radius_mm'] for r in rows],minimum_radius=case['pocket']['entry_circle_diameter_mm']*.3,
            max_radius=case['pocket']['entry_circle_diameter_mm']*record['maximum_corner_fraction']/2,model=model)
        acquisition=time.perf_counter()-start
        greedy=sorted(allowed,key=lambda i:rows[i]['radius_mm'])
        # Predict-only has no CAD queries. Its chosen output is independently
        # scored, including invalid STEP suggestions; budget isn't borrowed.
        chosen_only=learned[0] if learned else None
        outputs={}
        for budget in (1,2,3):
            for method,order in (('rules',greedy),('learned_verified',learned)):
                queried=order[:budget]; feasible=[i for i in queried if rows[i]['valid']]
                chosen=min(feasible,key=lambda i:rows[i]['material_delta_mm3']) if feasible else None
                outputs[f'{method}_{budget}']=dict(chosen=chosen,valid=chosen is not None,queries=len(queried),
                    regret_mm3=None if chosen is None or optimum is None else rows[chosen]['material_delta_mm3']-rows[optimum]['material_delta_mm3'],
                    new_supported_conflicts=0 if chosen is not None else None,protected_violations=0 if chosen is not None else None,
                    seconds=sum(rows[i]['seconds'] for i in queried)+(acquisition if method.startswith('learned') else 0))
        outputs['learned_only']=dict(chosen=chosen_only,valid=chosen_only in truth if chosen_only is not None else False,queries=0,
            regret_mm3=None if chosen_only not in truth or optimum is None else rows[chosen_only]['material_delta_mm3']-rows[optimum]['material_delta_mm3'],
            seconds=acquisition)
        results.append(dict(case_id=case['id'],family=record['family'],feasible_candidates=len(truth),oracle=optimum,methods=outputs))
    methods={}
    for method in results[0]['methods']:
        rows=[r['methods'][method] for r in results]
        methods[method]=dict(cases=len(rows),valid=sum(r['valid'] for r in rows),optimal=sum(r['regret_mm3'] is not None and abs(r['regret_mm3'])<1e-6 for r in rows),
            queries=sum(r['queries'] for r in rows),mean_seconds=float(np.mean([r['seconds'] for r in rows])),
            failure_or_abstention=sum(not r['valid'] for r in rows))
    test_rows=[r for c in labels['cases'] for r in c['rows'] if r['split']=='test']
    pred=predict([r['features'] for r in test_rows],model);actual=np.asarray([r['valid'] for r in test_rows])
    predicted=pred['validity']>=.5
    successes=np.flatnonzero(actual)
    metrics=dict(validity_accuracy=float(np.mean(actual==predicted)),
        false_valid=int(np.sum(predicted & ~actual)),false_rejected=int(np.sum(~predicted & actual)),
        material_log_fraction_mae=float(np.mean(np.abs(pred['material'][successes]-[test_rows[i]['material_log_fraction'] for i in successes]))))
    summary=dict(model_sha256=model['sha256'],test_CAD=len(results),test_records=len(test_rows),surrogate_metrics=metrics,
        methods=methods,results=results,oracle_scope='fixed reconstructed radius candidates; not continuous global optimum',
        timing='actual recorded single-operation wall times plus measured inference; query-cache replay, not whole app timings',
        equal_budget='same frozen candidates, constraints and 1/2/3 expensive CAD operations; invalid operations count',
        label_scope='geometric outcomes only; no expert preferred-action labels')
    save(folder/'cnc-comparison.json',summary)
    print(json.dumps(dict(stage='evaluated',test_CAD=len(results),methods=methods)),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['generate','labels','train','compare']);p.add_argument('folder',type=Path)
    p.add_argument('--workers',type=int,default=2);p.add_argument('--model',type=Path,default=ROOT/'data/models/cad_edit_surrogate_v1.json')
    a=p.parse_args()
    if a.action=='generate':generate(a.folder)
    elif a.action=='labels':labels(a.folder,a.workers)
    elif a.action=='train':train(a.folder,a.model)
    else:compare(a.folder,a.model)
