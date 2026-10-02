"""External geometry orientation learning; targets are disclosed geometric measurements."""
import argparse,hashlib,io,json,sqlite3,sys,time
from pathlib import Path
import numpy as np
import trimesh
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from amdfm.orientation import candidates,measure_orientation,ANGLE_COSINE_TOLERANCE
from amdfm.profiles import Profile
from amdfm.neural_orientation import SCHEMA,BASE_NAMES,feature_arrays,feature_contract_sha256,load_model,predict_surrogates,fibonacci_directions
from scripts.train_neural_orientation import fit_network

def labels(mesh,directions,angle):
    """Vectorized independent projections checked against the runtime engine."""
    projected=mesh.vertices@directions.T;minima=projected.min(0);height=np.ptp(projected,axis=0)
    face_top=projected[mesh.faces].max(1)-minima
    # Upper bound on in-plane extents for the plate tolerance; equality band
    # only affects roundoff at the exact bottom, checked below against engine.
    tol=max(1e-9,np.linalg.norm(np.ptp(mesh.vertices,axis=0))*1e-10)
    nz=mesh.face_normals@directions.T;mask=(nz < -np.cos(np.deg2rad(angle))-ANGLE_COSINE_TOLERANCE)&(face_top>tol)
    overhang=(mesh.area_faces[:,None]*np.maximum(-nz,0)*mask).sum(0)
    return height/np.linalg.norm(np.ptp(mesh.vertices,axis=0)),overhang/mesh.area

def train(root,output,epochs):
    intake=json.loads((root/'thingi-intake.json').read_text(encoding='utf8'))
    if intake.get('imported',0)<1:raise ValueError('No finalized external intake')
    output.mkdir(parents=True,exist_ok=False);db=sqlite3.connect(f'file:{(root/"thingi.sqlite").resolve()}?mode=ro',uri=True)
    packed={s:{k:[] for k in ('height_x','height_y','overhang_x','overhang_y','group')} for s in ('train','validation','test')}
    groups=[];errors=[];started=time.monotonic();base=np.array(list(candidates(None,dense=True).values()))
    sphere=fibonacci_directions(96)
    for number,(identifier,thing,split,raw,sha) in enumerate(db.execute('SELECT id,thing_id,split,npz,sha256 FROM parts WHERE training_ready=1 ORDER BY id')):
        with np.load(io.BytesIO(raw),allow_pickle=False) as z:mesh=trimesh.Trimesh(z['vertices'],z['facets'],process=False)
        if not mesh.is_watertight or not mesh.is_winding_consistent or not mesh.is_volume:continue
        mesh.vertices=(mesh.vertices-mesh.vertices.mean(0))/max(mesh.extents)*100
        rng=np.random.default_rng(identifier);rotation=trimesh.transformations.euler_matrix(*rng.uniform(-np.pi,np.pi,3))[:3,:3]
        # Independently rotate shape once; all views stay with the same Thing.
        mesh.apply_transform(np.block([[rotation,np.zeros((3,1))],[np.zeros((1,3)),np.ones((1,1))]]))
        for angle in (35.,45.,60.):
            h,o=labels(mesh,base,angle);descriptor=dict(height=h.tolist(),overhang=o.tolist())
            directions=sphere@rotation.T;x=feature_arrays(descriptor,directions,angle);hy,oy=labels(mesh,directions,angle)
            if number<30:
                profile=Profile(process='MEX',overhang_angle_deg=angle)
                for index in (0,13,51):
                    measured=measure_orientation(mesh,directions[index],profile)
                    errors.extend([abs(measured['height_mm']/np.linalg.norm(mesh.extents)-hy[index]),abs(measured['overhang_projected_area_sum_mm2']/mesh.area-oy[index])])
            for target,y in (('height',hy),('overhang',oy)):
                packed[split][target+'_x'].append(x[target]);packed[split][target+'_y'].extend(y)
            packed[split]['group'].extend([thing]*len(directions))
        groups.append(dict(file_id=identifier,thing_id=thing,split=split,sha256=sha,normalized_max_extent_mm=100,angles=[35,45,60]))
        if number%100==0:print(f'Measured {number} meshes; {time.monotonic()-started:.0f}s',flush=True)
    if max(errors,default=0)>1e-7:raise ValueError('Independent direction measurements disagree')
    db.close();data={s+'_'+k:np.concatenate(v) if k.endswith('_x') else np.asarray(v) for s,values in packed.items() for k,v in values.items()}
    np.savez_compressed(output/'external-orientation-training.npz',**data)
    (output/'groups.json').write_text(json.dumps(groups,indent=2),encoding='utf8')
    networks={};history={}
    for name in ('height','overhang'):networks[name],history[name],_,_=fit_network(data,name,300930,epochs)
    model=dict(schema=SCHEMA,model_id='thingi-external-orientation-2026-09-30',base_names=list(BASE_NAMES),networks=networks,
        measurement_source_sha256=hashlib.sha256(Path('amdfm/orientation.py').read_bytes()).hexdigest(),feature_contract_sha256=feature_contract_sha256(),
        source=dict(dataset='Thingi10K',revision='v1.5.0',url='https://github.com/Thingi10K/Thingi10K',license='per-item accepted rights; attribution in groups/DB'),
        angle_range_deg=[35,60],training_group_count=len(set(data['train_group'].tolist())),validation_group_count=len(set(data['validation_group'].tolist())),
        target_definition='geometric height/diagonal and downward projected area/surface area; computed labels, not externally annotated optimal direction')
    path=output/'neural_orientation_external_v2.json';path.write_text(json.dumps(model,separators=(',',':')),encoding='utf8')
    manifest=dict(schema=SCHEMA,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),model_id=model['model_id']);path.with_suffix('.manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf8')
    external=load_model(path);baseline=load_model(Path('data/models/neural_orientation_v1.json'));result={}
    for name in ('height','overhang'):
        x=data['test_'+name+'_x'];y=data['test_'+name+'_y']
        def predict(m):
            net=m['networks'][name];h=(x-net['mean'])/net['scale']
            for i,(w,b) in enumerate(zip(net['weights'],net['biases'])):
                h=h@w+b
                if i<len(net['weights'])-1:h=np.maximum(h,0)
            return np.clip(h[:,0],0,1)
        old,new=predict(baseline),predict(external)
        result[name]=dict(baseline_mae=float(np.mean(np.abs(old-y))),external_mae=float(np.mean(np.abs(new-y))),
            baseline_mse=float(np.mean((old-y)**2)),external_mse=float(np.mean((new-y)**2)),samples=len(y))
    summary=dict(metrics=result,meshes=len(groups),things={s:len(set(data[s+'_group'].tolist())) for s in ('train','validation','test')},
        independent_measurement_max_error=max(errors,default=0),history=history,seconds=time.monotonic()-started)
    (output/'evaluation.json').write_text(json.dumps(summary,indent=2),encoding='utf8'); print(json.dumps({k:v for k,v in summary.items() if k!='history'}),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--epochs',type=int,default=80);a=p.parse_args();train(a.root,a.output,a.epochs)
