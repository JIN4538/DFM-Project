"""Grouped public geometry learning. No downloaded source code is executed."""
import argparse, hashlib, io, json, sqlite3, sys, time
from pathlib import Path
from collections import Counter
import numpy as np
import trimesh
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from scripts.train_external_orientation import labels
from amdfm.orientation import candidates,measure_orientation
from amdfm.neural_orientation import BASE_NAMES,SCHEMA,feature_arrays,feature_contract_sha256,load_model,fibonacci_directions
from amdfm.profiles import Profile

def measure(root):
    out=root/'am-training';out.mkdir(exist_ok=False)
    packed={s:{k:[] for k in ('height_x','height_y','overhang_x','overhang_y','group','dataset')} for s in ('train','validation','test')}
    db=sqlite3.connect(f'file:{(root/"public-expansion.sqlite").resolve()}?mode=ro',uri=True)
    # Deterministic hash selection, independent of labels, bounded per family.
    selected=[]
    for family, in db.execute("SELECT DISTINCT family FROM parts WHERE dataset='PBF-orientation'"):
        ids=[(hashlib.sha256(i.encode()).hexdigest(),i) for i, in db.execute('SELECT id FROM parts WHERE family=?',(family,))]
        selected.extend(i for _,i in sorted(ids)[:500])
    selected.extend(i for i, in db.execute("SELECT id FROM parts WHERE dataset='CadQuarry' ORDER BY id"))
    def stream():
        for identifier in selected:
            dataset,family,group,split,raw,sha=db.execute('SELECT dataset,family,group_id,split,stl,stl_sha256 FROM parts WHERE id=?',(identifier,)).fetchone()
            yield identifier,dataset,family,group,split,raw,sha,'stl'
        old=sqlite3.connect(f'file:{(root.parent/"external-training-2026-09-30/thingi.sqlite").resolve()}?mode=ro',uri=True)
        for identifier,thing,split,raw,sha in old.execute('SELECT id,thing_id,split,npz,sha256 FROM parts WHERE training_ready=1 ORDER BY id'):
            yield str(identifier),'Thingi10K','public_thing','thing:'+str(thing),split,raw,sha,'npz'
        old.close()
    base=np.array(list(candidates(None,dense=True).values()));sphere=fibonacci_directions(48)
    groups=[];rejected=[];errors=[];start=time.monotonic()
    for number,(identifier,dataset,family,group,split,raw,sha,kind) in enumerate(stream()):
        try:
            if split not in packed:raise ValueError('Quarantined split')
            if kind=='stl':mesh=trimesh.load(io.BytesIO(raw),file_type='stl',force='mesh',process=True)
            else:
                with np.load(io.BytesIO(raw),allow_pickle=False) as z:mesh=trimesh.Trimesh(z['vertices'],z['facets'],process=False)
            if not 4<=len(mesh.faces)<=12000:raise ValueError('Mesh complexity outside bounded training domain')
            if not np.isfinite(mesh.vertices).all() or not mesh.is_volume or not mesh.is_watertight or not mesh.is_winding_consistent:raise ValueError('Not a finite, closed, consistently wound volume')
            mesh.vertices=(mesh.vertices-mesh.vertices.mean(0))/max(mesh.extents)*100
            seed=int(hashlib.sha256(identifier.encode()).hexdigest()[:8],16);rng=np.random.default_rng(seed)
            rotation=trimesh.transformations.euler_matrix(*rng.uniform(-np.pi,np.pi,3))[:3,:3]
            mesh.vertices=mesh.vertices@rotation.T;directions=sphere@rotation.T
            for angle in (25.,35.,45.,60.,75.):
                h,o=labels(mesh,base,angle);x=feature_arrays(dict(height=h,overhang=o),directions,angle);hy,oy=labels(mesh,directions,angle)
                if len(groups)<25:
                    measured=measure_orientation(mesh,directions[13],Profile(process='MEX',overhang_angle_deg=angle))
                    errors.extend([abs(measured['height_mm']/np.linalg.norm(mesh.extents)-hy[13]),abs(measured['overhang_projected_area_sum_mm2']/mesh.area-oy[13])])
                for target,y in (('height',hy),('overhang',oy)):
                    packed[split][target+'_x'].append(x[target].astype('float32'));packed[split][target+'_y'].extend(y)
                packed[split]['group'].extend([group]*len(directions));packed[split]['dataset'].extend([dataset]*len(directions))
            groups.append(dict(id=identifier,dataset=dataset,family=family,group=group,split=split,sha256=sha,faces=len(mesh.faces)))
        except (ValueError,TypeError,IndexError,KeyError) as e:rejected.append(dict(id=identifier,dataset=dataset,reason=str(e)))
        if number%100==0:print(json.dumps(dict(measured=len(groups),rejected=len(rejected),seconds=time.monotonic()-start)),flush=True)
    db.close()
    if max(errors,default=0)>1e-7:raise ValueError('Independent measurement mismatch')
    sets={s:{g['group'] for g in groups if g['split']==s} for s in packed}
    if any(sets[a]&sets[b] for a,b in [('train','validation'),('train','test'),('validation','test')]):raise ValueError('Geometry group leakage')
    data={s+'_'+k:np.concatenate(v) if k.endswith('_x') else np.asarray(v,dtype='float32' if k.endswith('_y') else str) for s,p in packed.items() for k,v in p.items()}
    np.savez_compressed(out/'training.npz',**data)
    (out/'audit.json').write_text(json.dumps(dict(groups=groups,rejected=rejected,accepted=len(groups),by_dataset=dict(Counter(g['dataset'] for g in groups)),independent_max_error=max(errors,default=0),seconds=time.monotonic()-start),indent=2),encoding='utf8')
    return data

def fit(data,name,epochs):
    import torch
    from torch import nn
    torch.set_num_threads(3);torch.manual_seed(9302026)
    x=data['train_'+name+'_x'];y=data['train_'+name+'_y'];vx=data['validation_'+name+'_x'];vy=data['validation_'+name+'_y']
    mean=x.mean(0,dtype=np.float64);scale=np.maximum(x.std(0,dtype=np.float64),1e-8)
    x=torch.tensor((x-mean)/scale,dtype=torch.float32);y=torch.tensor(y[:,None]);vx=torch.tensor((vx-mean)/scale,dtype=torch.float32);vy=torch.tensor(vy[:,None])
    widths=[x.shape[1],64,48,24,1] if name=='height' else [x.shape[1],96,64,32,1]
    layers=[]
    for a,b in zip(widths,widths[1:]):layers.extend([nn.Linear(a,b),nn.ReLU()])
    net=nn.Sequential(*layers[:-1]);opt=torch.optim.AdamW(net.parameters(),lr=.001,weight_decay=.0001);best=float('inf');state=None;history=[];rng=np.random.default_rng(930)
    for epoch in range(epochs):
        net.train();order=rng.permutation(len(x));losses=[]
        for start in range(0,len(order),4096):
            idx=order[start:start+4096];opt.zero_grad();loss=nn.functional.mse_loss(net(x[idx]),y[idx]);loss.backward();opt.step();losses.append(float(loss.detach()))
        net.eval()
        with torch.no_grad():error=float(nn.functional.mse_loss(net(vx),vy))
        history.append(dict(epoch=epoch+1,validation_mse=error,loss=float(np.mean(losses))))
        if error<best:best=error;state={k:v.clone() for k,v in net.state_dict().items()};chosen=epoch+1
        if (epoch+1)%5==0:print(json.dumps(dict(network=name,**history[-1])),flush=True)
    net.load_state_dict(state);dense=[l for l in net if isinstance(l,nn.Linear)]
    return dict(mean=mean.tolist(),scale=scale.tolist(),weights=[l.weight.detach().numpy().T.tolist() for l in dense],biases=[l.bias.detach().numpy().tolist() for l in dense],hidden_layers=widths[1:-1],selected_epoch=chosen,validation_mse=best),history

def main(root,epochs):
    started=time.monotonic();out=root/'am-training'
    if (out/'training.npz').exists():
        with np.load(out/'training.npz',allow_pickle=False) as z:data={k:z[k].copy() for k in z.files}
    else:data=measure(root)
    networks={};history={}
    for name in ('height','overhang'):networks[name],history[name]=fit(data,name,epochs)
    model=dict(schema=SCHEMA,model_id='public-am-multi-family-2026-09-30',base_names=list(BASE_NAMES),networks=networks,measurement_source_sha256=hashlib.sha256((ROOT/'amdfm/orientation.py').read_bytes()).hexdigest(),feature_contract_sha256=feature_contract_sha256(),angle_range_deg=[25,75],sources=['PBF-LB/M part orientation (author Apache-2.0)','CadQuarry (CC0-1.0)','Thingi10K (accepted per-item rights)'],target_definition='Independently remeasured geometric height and projected downward area; published canonical rotations are preserved but not optimal-DFM targets')
    path=out/'neural_orientation_external_v3.json';raw=json.dumps(model,separators=(',',':')).encode();path.write_bytes(raw)
    path.with_suffix('.manifest.json').write_text(json.dumps(dict(schema=SCHEMA,sha256=hashlib.sha256(raw).hexdigest())))
    models={'previous':load_model(ROOT/'data/models/neural_orientation_external_v2.json'),'expanded':load_model(path)};metrics={}
    for name in ('height','overhang'):
        x=data['test_'+name+'_x'];y=data['test_'+name+'_y'];metrics[name]={}
        for label,m in models.items():
            net=m['networks'][name];pred=[]
            for start in range(0,len(x),4096):
                h=(x[start:start+4096]-net['mean'])/net['scale']
                for i,(w,b) in enumerate(zip(net['weights'],net['biases'])):
                    h=h@w+b
                    if i<len(net['weights'])-1:h=np.maximum(h,0)
                pred.extend(np.clip(h[:,0],0,1))
            error=np.abs(np.array(pred)-y);metrics[name][label]={'mae':float(error.mean()),'samples':len(y),'by_dataset':{ds:float(error[data['test_dataset']==ds].mean()) for ds in set(data['test_dataset'])}}
    result=dict(metrics=metrics,history=history,groups={s:len(set(data[s+'_group'])) for s in ('train','validation','test')},seconds=time.monotonic()-started)
    (out/'evaluation.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='history'}),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--epochs',type=int,default=50);a=p.parse_args();main(a.root,a.epochs)
