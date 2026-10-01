"""25-class GNN with independently certified author face mapping."""
import argparse, copy, hashlib, io, json, sqlite3, sys, time
from pathlib import Path
import numpy as np
import torch
from torch import nn
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.train_external_features import GNN,batch
from dfm.cad_graph import FEATURES,SCHEMA,extract_graph
from dfm.feature_learning import CLASS_NAMES,predict_graph
NAMES=('chamfer','through_hole','triangular_passage','rectangular_passage','6sides_passage','triangular_through_slot',
 'rectangular_through_slot','circular_through_slot','rectangular_through_step','2sides_through_step','slanted_through_step',
 'Oring','blind_hole','triangular_pocket','rectangular_pocket','6sides_pocket','circular_end_pocket','rectangular_blind_slot',
 'v_circular_end_blind_slot','h_circular_end_blind_slot','triangular_blind_step','circular_blind_step','rectangular_blind_step','round','stock')

def evaluate(model,graphs):
    cm=np.zeros((25,25),int);confidence=[];correct=[];model.eval()
    with torch.no_grad():
        for i in range(0,len(graphs),128):
            x,e,y=batch(graphs[i:i+128]);p=torch.softmax(model(x,e),1).numpy();a=p.argmax(1);t=y.numpy()
            np.add.at(cm,(t,a),1);confidence.extend(p.max(1));correct.extend(t==a)
    tp=cm.diagonal(); precision=tp/np.maximum(cm.sum(0),1);recall=tp/np.maximum(cm.sum(1),1)
    f1=2*precision*recall/np.maximum(precision+recall,1e-10)
    return dict(accuracy=float(tp.sum()/max(cm.sum(),1)),macro_f1=float(f1.mean()),faces=int(cm.sum()),parts=len(graphs),
        per_class={name:dict(precision=float(precision[i]),recall=float(recall[i]),faces=int(cm[i].sum())) for i,name in enumerate(NAMES)},
        confusion=cm.tolist()),np.array(confidence),np.array(correct)

def main(root,epochs):
    audit=json.loads((root/'mfinstseg-verified-audit.json').read_text())
    if audit['accepted']<1000:raise ValueError('Insufficient certified external graphs')
    groups={s:[] for s in ('train','val','test')};mf={s:[] for s in groups};torch.set_num_threads(4);torch.manual_seed(93026);rng=np.random.default_rng(93026)
    for path,mapping in ((root/'mfinstseg-verified.sqlite',None),(root.parent/'external-training-2026-09-30/training.sqlite',[NAMES.index(n) for n in CLASS_NAMES])):
        db=sqlite3.connect(f'file:{path.resolve()}?mode=ro',uri=True)
        for split,raw in db.execute('SELECT split,graph FROM parts WHERE graph IS NOT NULL ORDER BY id'):
            with np.load(io.BytesIO(raw),allow_pickle=False) as z:g={k:z[k].copy() for k in ('x','edges','y')}
            if mapping is not None:g['y']=np.asarray(mapping,dtype=np.int64)[g['y']]
            else:mf[split].append(g)
            groups[split].append(g)
        db.close()
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox,BRepPrimAPI_MakeCylinder,BRepPrimAPI_MakeSphere
    negative={s:[] for s in groups}
    for split,count in [('train',1200),('val',150),('test',150)]:
        for i in range(count):
            dims=10**rng.uniform(-1,2,3)
            shape=(BRepPrimAPI_MakeBox(*map(float,dims)).Shape() if i%3==0 else BRepPrimAPI_MakeCylinder(float(dims[0]),float(dims[1])).Shape() if i%3==1 else BRepPrimAPI_MakeSphere(float(dims[0])).Shape())
            g=extract_graph(shape);negative[split].append(dict(x=g['x'],edges=g['edges'],y=np.full(len(g['x']),24,dtype=np.int64)))
        if split!='test':groups[split].extend(negative[split])
    x=np.concatenate([g['x'] for g in groups['train']]);mean=x.mean(0);std=np.maximum(x.std(0),.02)
    model=GNN(mean,std);model.layers[-1]=nn.Linear(48,25)
    counts=np.bincount(np.concatenate([g['y'] for g in groups['train']]),minlength=25)
    criterion=nn.CrossEntropyLoss(weight=torch.tensor(np.sqrt(counts.max()/np.maximum(counts,1)),dtype=torch.float32))
    optimizer=torch.optim.AdamW(model.parameters(),lr=.002,weight_decay=.0002);best=-1;checkpoint=None;history=[];started=time.monotonic()
    for epoch in range(epochs):
        model.train();order=rng.permutation(len(groups['train']));losses=[]
        for i in range(0,len(order),128):
            x,e,y=batch([groups['train'][j] for j in order[i:i+128]]);optimizer.zero_grad();loss=criterion(model(x,e),y);loss.backward();optimizer.step();losses.append(float(loss.detach()))
        metric,_,_=evaluate(model,mf['val']);row=dict(epoch=epoch+1,loss=float(np.mean(losses)),validation=metric['macro_f1'],seconds=time.monotonic()-started);history.append(row);print(json.dumps(row),flush=True)
        if metric['macro_f1']>best:best=metric['macro_f1'];checkpoint=copy.deepcopy(model.state_dict())
    model.load_state_dict(checkpoint);validation,conf,correct=evaluate(model,mf['val']);threshold=.99
    for t in (.75,.8,.85,.9,.95,.98,.99):
        mask=conf>=t
        if mask.sum()>100 and correct[mask].mean()>=.97:threshold=t;break
    final,_,_=evaluate(model,mf['test']);artifact=dict(schema='dfm-feature-gnn-1',model_id='certified-mfinstseg-25class-2026-09-30',graph_schema=SCHEMA,
        features=FEATURES,classes=NAMES,mean=mean.tolist(),std=std.tolist(),candidate_threshold=threshold,
        layers=[dict(kind='graph' if i<3 else 'dense',weight=l.weight.detach().numpy().tolist(),bias=l.bias.detach().numpy().tolist(),activation='relu' if i<3 else 'linear') for i,l in enumerate(model.layers)],
        source=dict(dataset='MFInstSeg and MFCAD',url='https://github.com/whjdark/AAGNet',label_mapping='Per-record geometry and full adjacency certification',
          declarations='MFInstSeg author CC0 declaration; MFCAD MIT'),counts={s:len(mf[s]) for s in mf},
        graph_source_sha256=hashlib.sha256(Path('dfm/cad_graph.py').read_bytes()).hexdigest(),
        domain='planar and analytic curved machining faces; finite synthetic feature families; proposals require independent measurement',
        target='Author external 25-class face labels; no instance head or optimal-edit annotations',evaluation=final,validation=validation)
    errors=[]
    for g in mf['test'][:25]:
        with torch.no_grad():expected=torch.softmax(model(torch.from_numpy(g['x']),torch.from_numpy(g['edges'])),1).numpy()
        errors.append(float(np.max(np.abs(predict_graph(g,artifact)-expected))))
    if max(errors)>1e-4:raise ValueError('Inference export mismatch')
    artifact['export_max_abs_error']=max(errors);out=root/'models';out.mkdir(exist_ok=True);path=out/'external_feature_mfinstseg_v1.json';raw=json.dumps(artifact,separators=(',',':')).encode();path.write_bytes(raw)
    path.with_suffix('.manifest.json').write_text(json.dumps(dict(schema=artifact['schema'],sha256=hashlib.sha256(raw).hexdigest())))
    summary=dict(test=final,validation=validation,negative_test=evaluate(model,negative['test'])[0],history=history,export_max_abs_error=max(errors),seconds=time.monotonic()-started,
        threshold=threshold,accepted_external_graphs=audit['accepted'],mixed_mfcad_graphs=15488)
    (out/'mfinstseg-evaluation.json').write_text(json.dumps(summary,indent=2));print(json.dumps({k:v for k,v in summary.items() if k!='history'}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--epochs',type=int,default=50);a=p.parse_args();main(a.root,a.epochs)
