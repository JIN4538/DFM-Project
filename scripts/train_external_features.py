"""Part-family held-out supervised GNN; external labels, CAD-only inputs."""
from __future__ import annotations
import argparse, copy, hashlib, io, json, sqlite3, sys, time
from pathlib import Path
import numpy as np
import torch
from torch import nn
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dfm.cad_graph import FEATURES,SCHEMA
from dfm.feature_learning import CLASS_NAMES,predict_graph

class GNN(nn.Module):
    def __init__(self,mean,std,graph=True):
        super().__init__(); self.register_buffer('mean',torch.tensor(mean)); self.register_buffer('std',torch.tensor(std)); self.graph=graph
        widths=[len(FEATURES),64,64,48,16]
        self.layers=nn.ModuleList([nn.Linear(widths[i]*(2 if graph and i<3 else 1),widths[i+1]) for i in range(4)])
    def forward(self,x,e):
        h=(x-self.mean)/self.std
        for i,layer in enumerate(self.layers):
            if self.graph and i<3:
                a=torch.zeros_like(h); count=torch.zeros((len(h),1))
                a.index_add_(0,e[:,0],h[e[:,1]]); count.index_add_(0,e[:,0],torch.ones((len(e),1)))
                h=torch.cat([h,a/count.clamp(min=1)],dim=1)
            h=layer(h)
            if i<3: h=torch.relu(h)
        return h

def batch(graphs):
    xs=[]; es=[]; ys=[]; offset=0
    for g in graphs:
        xs.append(g['x']); es.append(g['edges']+offset); ys.append(g['y']); offset+=len(g['x'])
    return torch.from_numpy(np.concatenate(xs)),torch.from_numpy(np.concatenate(es)),torch.from_numpy(np.concatenate(ys))

def metrics(model,graphs):
    cm=np.zeros((16,16),dtype=np.int64); confidences=[];correct=[]
    model.eval()
    with torch.no_grad():
        for start in range(0,len(graphs),128):
            x,e,y=batch(graphs[start:start+128]); p=torch.softmax(model(x,e),1).numpy(); pred=p.argmax(1); truth=y.numpy()
            np.add.at(cm,(truth,pred),1); confidences.extend(p.max(1)); correct.extend(pred==truth)
    tp=cm.diagonal(); recall=tp/np.maximum(cm.sum(1),1); precision=tp/np.maximum(cm.sum(0),1)
    f1=2*precision*recall/np.maximum(precision+recall,1e-9); iou=tp/np.maximum(cm.sum(0)+cm.sum(1)-tp,1)
    return dict(accuracy=float(tp.sum()/cm.sum()),macro_f1=float(f1.mean()),mean_iou=float(iou.mean()),
        faces=int(cm.sum()),parts=len(graphs),confusion=cm.tolist(),
        per_class={name:dict(precision=float(precision[i]),recall=float(recall[i]),iou=float(iou[i]),faces=int(cm[i].sum())) for i,name in enumerate(CLASS_NAMES)}),np.asarray(confidences),np.asarray(correct)

def train(database,output,epochs):
    audit_path=database.parent/'label-audit/label-audit.json'
    audit=json.loads(audit_path.read_text(encoding='utf8'))
    if tuple(audit['classes'])!=CLASS_NAMES or audit['descriptor_cross_split_conflicts']:
        raise ValueError('External label audit/split identity must be resolved before training')
    torch.set_num_threads(4); torch.manual_seed(290930); rng=np.random.default_rng(290930)
    db=sqlite3.connect(f'file:{database.resolve()}?mode=ro',uri=True); groups={s:[] for s in ('train','val','test')}
    for identifier,split,blob in db.execute('SELECT id,split,graph FROM parts WHERE graph IS NOT NULL ORDER BY id'):
        with np.load(io.BytesIO(blob),allow_pickle=False) as z: g={k:z[k].copy() for k in ('x','edges','y')}
        groups[split].append(g)
    source=json.loads(db.execute('SELECT metadata FROM sources WHERE id="mfcad"').fetchone()[0]); db.close()
    external_counts={s:len(v) for s,v in groups.items()}
    # Empty, high-aspect-ratio stock was absent from the upstream corpus.
    # Construction-derived negative examples are explicitly separated from
    # external annotations and never counted as external CADs.
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from dfm.cad_graph import extract_graph
    negatives={s:[] for s in groups}
    negative_rng=np.random.default_rng(87341)
    for split,count in [('train',2000),('val',300),('test',300)]:
        for _ in range(count):
            dims=10**negative_rng.uniform(-1,2,3)
            g=extract_graph(BRepPrimAPI_MakeBox(*map(float,dims)).Shape())
            negatives[split].append(dict(x=g['x'],edges=g['edges'],y=np.full(len(g['x']),15,dtype=np.int64)))
    for split in ('train','val'):groups[split].extend(negatives[split])
    trainx=np.concatenate([g['x'] for g in groups['train']]); mean=trainx.mean(0);std=np.maximum(trainx.std(0),.02)
    counts=np.bincount(np.concatenate([g['y'] for g in groups['train']]),minlength=16)
    weights=torch.tensor(np.sqrt(counts.max()/np.maximum(counts,1)),dtype=torch.float32)
    criterion=nn.CrossEntropyLoss(weight=weights); started=time.monotonic(); history=[]; models={}
    for name,graph,passes in [('face_mlp',False,min(epochs,12)),('face_gnn',True,epochs)]:
        model=GNN(mean,std,graph); optimizer=torch.optim.AdamW(model.parameters(),lr=.002,weight_decay=.0001); best=-1; checkpoint=None
        for epoch in range(passes):
            model.train(); order=rng.permutation(len(groups['train'])); losses=[]
            for start in range(0,len(order),128):
                x,e,y=batch([groups['train'][i] for i in order[start:start+128]])
                optimizer.zero_grad(); loss=criterion(model(x,e),y); loss.backward(); optimizer.step(); losses.append(float(loss.detach()))
            result,_,_=metrics(model,groups['val']); score=result['macro_f1']
            row=dict(model=name,epoch=epoch+1,loss=float(np.mean(losses)),validation_macro_f1=score,validation_accuracy=result['accuracy'],seconds=time.monotonic()-started)
            history.append(row); print(json.dumps(row),flush=True)
            if score>best: best=score; checkpoint=copy.deepcopy(model.state_dict())
        model.load_state_dict(checkpoint); models[name]=model
    model=models['face_gnn']; validation,conf,correct=metrics(model,groups['val'])
    threshold=.95
    for t in (.7,.75,.8,.85,.9,.95,.98,.99):
        kept=conf>=t
        if kept.sum()>=100 and correct[kept].mean()>=.95: threshold=t; break
    evaluation={name:metrics(m,groups['test'])[0] for name,m in models.items()}
    layers=[]
    for i,layer in enumerate(model.layers):
        layers.append(dict(kind='graph' if i<3 else 'dense',weight=layer.weight.detach().numpy().tolist(),
                           bias=layer.bias.detach().numpy().tolist(),activation='relu' if i<3 else 'linear'))
    artifact=dict(schema='dfm-feature-gnn-1',model_id='mfcad-external-gnn-stock-2026-09-30',graph_schema=SCHEMA,
        features=FEATURES,classes=CLASS_NAMES,mean=mean.tolist(),std=std.tolist(),layers=layers,
        candidate_threshold=threshold,source=source,seed=290930,
        counts={s:len(v) for s,v in groups.items()},evaluation=evaluation,validation=validation,
        external_counts=external_counts,construction_negative_counts={s:len(v) for s,v in negatives.items()},
        construction_negative_evaluation={name:metrics(m,negatives['test'])[0] for name,m in models.items()},
        target='MFCAD external numeric face labels; semantic map independently audited',
        domain='planar machining feature segmentation; curved CAD falls back to analytic review')
    # Export independently verified against the actual trained torch network.
    parity=[]
    for g in groups['test'][:25]:
        with torch.no_grad(): expected=torch.softmax(model(torch.from_numpy(g['x']),torch.from_numpy(g['edges'])),1).numpy()
        parity.append(float(np.max(np.abs(predict_graph(g,artifact)-expected))))
    artifact['export_max_abs_error']=max(parity)
    artifact['graph_source_sha256']=hashlib.sha256(Path(__file__).resolve().parents[1].joinpath('dfm/cad_graph.py').read_bytes()).hexdigest()
    artifact['semantic_audit']=audit
    artifact['semantic_audit_sha256']=hashlib.sha256(audit_path.read_bytes()).hexdigest()
    if max(parity)>1e-4: raise ValueError('Portable inference disagrees with training')
    output.parent.mkdir(parents=True,exist_ok=True); output.write_text(json.dumps(artifact,separators=(',',':')),encoding='utf8')
    output.with_suffix('.manifest.json').write_text(json.dumps(dict(schema=artifact['schema'],sha256=hashlib.sha256(output.read_bytes()).hexdigest()),indent=2),encoding='utf8')
    report=dict(evaluation=evaluation,counts=artifact['counts'],history=history,export_max_abs_error=max(parity),
                threshold=threshold,validation=validation,seconds=time.monotonic()-started,
                model_sha256=hashlib.sha256(output.read_bytes()).hexdigest())
    output.with_suffix('.evaluation.json').write_text(json.dumps(report,indent=2),encoding='utf8'); print(json.dumps({k:v for k,v in report.items() if k!='history'}),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--database',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--epochs',type=int,default=35);a=p.parse_args();train(a.database,a.output,a.epochs)
