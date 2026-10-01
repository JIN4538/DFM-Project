"""Train a new affinity head using author instance labels; frozen GNN sources."""
from __future__ import annotations
import argparse,gzip,hashlib,io,json,sqlite3,sys,time
from pathlib import Path
import numpy as np
from threadpoolctl import threadpool_limits
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from dfm.feature_localization import load_model as load_joint,predict_localization
from dfm.feature_instance_refinement import (SCHEMA,TARGET_CLASSES,group_records,pair_inputs,
    contract_hash,predict_affinity,refine_groups)
from dfm.feature_learning import CURVED_CLASS_NAMES


def collect(args):
    args.output.mkdir(parents=True,exist_ok=True)
    target=args.output/f'{args.split}-pairs.npz'
    if target.exists():raise FileExistsError(target)
    head,backbone=load_joint();values=[];labels=[];records=[];began=time.monotonic()
    query='SELECT id,graph,audit FROM parts WHERE split=? AND graph IS NOT NULL ORDER BY id'
    if args.limit:query+=f' LIMIT {int(args.limit)}'
    with sqlite3.connect(f'file:{args.database.resolve().as_posix()}?mode=ro',uri=True) as db,threadpool_limits(limits=1):
        for identifier,raw,audit in db.execute(query,(args.split,)):
            with np.load(io.BytesIO(raw),allow_pickle=False) as z:g={k:z[k].copy() for k in z.files}
            truth=[];seen=set()
            for i,c in enumerate(g['y']):
                if i in seen or c==24:continue
                faces=set(map(int,np.flatnonzero(g['inst'][i]))) or {i};seen.update(faces)
                truth.append(dict(faces=sorted(faces),label=int(c)))
            row=dict(id=identifier,sha256=json.loads(audit)['step_sha256'],truth=truth,
                scope='planar' if np.all(g['x'][:,0]>.5) else 'curved',groups=[],pairs=[],start=len(labels),count=0)
            if len(g['x'])<=200 and not np.any(g['x'][:,5]>.5):
                prediction=predict_localization(g,head,backbone);groups=group_records(g,prediction,head['edge_threshold'])
                features,pairs=pair_inputs(g,groups,backbone)
                targets=[]
                for a,b in pairs:
                    left,right=groups[a]['faces'],groups[b]['faces']
                    target=bool(np.mean(g['inst'][np.ix_(left,right)])>.5 and
                        np.mean(g['y'][left]==groups[a]['label'])>.5 and np.mean(g['y'][right]==groups[b]['label'])>.5)
                    targets.append(int(target))
                if len(features):values.append(features);labels.extend(targets)
                row.update(groups=groups,pairs=pairs,count=len(pairs))
            records.append(row)
            if len(records)%1000==0:print(json.dumps(dict(split=args.split,cad=len(records),pairs=len(labels),seconds=round(time.monotonic()-began,1))),flush=True)
    x=np.concatenate(values) if values else np.empty((0,162),np.float32);y=np.asarray(labels,np.float32)
    np.savez_compressed(args.output/f'{args.split}-pairs.npz',x=x,y=y)
    with gzip.open(args.output/f'{args.split}-records.json.gz','wt',encoding='utf8') as f:json.dump(records,f,separators=(',',':'))
    summary=dict(split=args.split,cad=len(records),pairs=len(y),positive=int(y.sum()),seconds=time.monotonic()-began,
        database=str(args.database.resolve()),target='Author CAD instance membership between predicted disconnected face groups',input_contract=contract_hash())
    (args.output/f'{args.split}-collection.json').write_text(json.dumps(summary,indent=2),encoding='utf8');print(json.dumps(summary),flush=True)


def train(args):
    import torch
    torch.set_num_threads(1);torch.manual_seed(20260930)
    with np.load(args.output/'train-pairs.npz') as z:x=z['x'];y=z['y']
    with np.load(args.output/'val-pairs.npz') as z:vx=z['x'];vy=z['y']
    mean=x.mean(0);std=np.maximum(x.std(0),1e-5)
    tx=torch.tensor((x-mean)/std);ty=torch.tensor(y[:,None]);tvx=torch.tensor((vx-mean)/std);tvy=torch.tensor(vy[:,None])
    model=torch.nn.Sequential(torch.nn.Linear(162,64),torch.nn.ReLU(),torch.nn.Linear(64,32),torch.nn.ReLU(),torch.nn.Linear(32,1))
    optimizer=torch.optim.AdamW(model.parameters(),lr=.001,weight_decay=.002)
    best=float('inf');best_state=None;history=[];began=time.monotonic()
    with threadpool_limits(limits=1):
        for epoch in range(1,61):
            model.train();order=torch.randperm(len(tx));total=0.
            for indices in order.split(512):
                optimizer.zero_grad();loss=torch.nn.functional.binary_cross_entropy_with_logits(model(tx[indices]),ty[indices]);loss.backward();optimizer.step();total+=float(loss.detach())*len(indices)
            model.eval()
            with torch.no_grad():val=float(torch.nn.functional.binary_cross_entropy_with_logits(model(tvx),tvy))
            history.append(dict(epoch=epoch,train_bce=total/len(tx),val_bce=val))
            if val<best:best=val;best_state={k:v.clone() for k,v in model.state_dict().items()};selected_epoch=epoch
            if epoch%5==0:print(json.dumps(history[-1]),flush=True)
        model.load_state_dict(best_state)
    deps={path:hashlib.sha256((ROOT/path).read_bytes()).hexdigest() for path in
        ('dfm/cad_graph.py','dfm/feature_learning.py','dfm/feature_localization.py','dfm/feature_routing.py',
         'data/models/external_feature_mfinstseg_v2.json','data/models/external_feature_localization_v1.json')}
    artifact=dict(schema=SCHEMA,model_id='mfinstseg-disconnected-affinity-v1',contract_sha256=contract_hash(),
        frozen_dependencies=deps,mean=mean.tolist(),std=std.tolist(),layers=[dict(weight=l.weight.detach().numpy().tolist(),bias=l.bias.detach().numpy().tolist()) for l in model if isinstance(l,torch.nn.Linear)],
        targets=list(TARGET_CLASSES),training=dict(train_pairs=len(x),val_pairs=len(vx),selected_epoch=selected_epoch,seed=20260930,
        validation_use='Previously used source validation split; BCE selects epoch. Test is forbidden for training and threshold selection.'),
        merge_threshold=None,class_thresholds={str(c):None for c in TARGET_CLASSES})
    path=args.output/'feature_instance_affinity_v1.json';path.write_text(json.dumps(artifact,separators=(',',':')),encoding='utf8')
    path.with_suffix('.manifest.json').write_text(json.dumps(dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest()),indent=2),encoding='utf8')
    (args.output/'training-history.json').write_text(json.dumps(dict(history=history,selected_epoch=selected_epoch,seconds=time.monotonic()-began),indent=2),encoding='utf8')


def metrics(records,affinity,merge_threshold,class_thresholds):
    counts={str(c):dict(tp=0,fp=0,ground=0,exact=0,merged=0,iou_sum=0.) for c in TARGET_CLASSES}
    for record in records:
        for truth in record['truth']:
            if truth['label'] in TARGET_CLASSES:counts[str(truth['label'])]['ground']+=1
        groups=refine_groups(record['groups'],record['pairs'],affinity[record['start']:record['start']+record['count']],merge_threshold)
        for group in groups:
            c=group['label'];threshold=class_thresholds.get(str(c))
            if c not in TARGET_CLASSES or threshold is None or group['confidence']<threshold:continue
            s=set(group['faces']);iou=max((len(s&set(t['faces']))/len(s|set(t['faces'])) for t in record['truth'] if t['label']==c),default=0.)
            row=counts[str(c)];row['tp']+=int(iou>.5);row['fp']+=int(iou<=.5);row['exact']+=int(iou==1.);row['merged']+=int(group['fragments']>1);row['iou_sum']+=iou if iou>.5 else 0.
    for row in counts.values():
        row.update(precision=row['tp']/max(row['tp']+row['fp'],1),recall=row['tp']/max(row['ground'],1),exact_recall=row['exact']/max(row['ground'],1))
    return counts


def evaluate(args):
    path=args.output/'feature_instance_affinity_v1.json';model=json.loads(path.read_text(encoding='utf8'))
    with np.load(args.output/f'{args.split}-pairs.npz') as z:x=z['x'];y=z['y']
    with gzip.open(args.output/f'{args.split}-records.json.gz','rt',encoding='utf8') as f:records=json.load(f)
    with threadpool_limits(limits=1):affinity=predict_affinity(x,model)
    if args.split=='val':
        trials=[];selected=None
        # Selection is frozen before the reused test regression is inspected.
        for mt in (.9,.95,.98,.99,.995,.999):
            candidates=[]
            for ct in (.5,.7,.9,.95,.99,.995,.999,.9999):
                m=metrics(records,affinity,mt,{str(c):ct for c in TARGET_CLASSES})
                candidates.append((ct,m))
            thresholds={};score=0
            for c in TARGET_CLASSES:
                valid=[(ct,m[str(c)]) for ct,m in candidates if m[str(c)]['tp']>=100 and m[str(c)]['precision']>=.985]
                chosen=max(valid,key=lambda t:(t[1]['tp'],-t[1]['fp'])) if valid else None
                thresholds[str(c)]=chosen[0] if chosen else None;score+=chosen[1]['tp'] if chosen else 0
            trial=dict(merge_threshold=mt,class_thresholds=thresholds,tp=score,candidates=candidates);trials.append(trial)
            if selected is None or score>selected['tp']:selected=trial
        model.update(merge_threshold=selected['merge_threshold'],class_thresholds=selected['class_thresholds'])
        path.write_text(json.dumps(model,separators=(',',':')),encoding='utf8')
        path.with_suffix('.manifest.json').write_text(json.dumps(dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest()),indent=2),encoding='utf8')
        (args.output/'validation-selection.json').write_text(json.dumps(dict(target_precision=.985,min_true_positives=100,selected=selected,trials=trials),indent=2),encoding='utf8')
    result=dict(split=args.split,records=len(records),pairs=len(x),pair_accuracy=float(np.mean((affinity>=model['merge_threshold'])==y)),
        merge_threshold=model['merge_threshold'],class_thresholds=model['class_thresholds'],
        proposed=metrics(records,affinity,model['merge_threshold'],model['class_thresholds']),
        no_merge=metrics(records,affinity,1.1,model['class_thresholds']),
        notes='Four classes are disabled in existing runtime; no-merge is a counterfactual with new display thresholds, not the old runtime.')
    result['by_scope']={scope:metrics([r for r in records if r['scope']==scope],affinity,model['merge_threshold'],model['class_thresholds']) for scope in ('planar','curved')}
    (args.output/f'{args.split}-evaluation.json').write_text(json.dumps(result,indent=2),encoding='utf8');print(json.dumps(result),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=('collect','train','evaluate'));p.add_argument('--database',type=Path);p.add_argument('--output',type=Path,required=True);p.add_argument('--split',choices=('train','val','test'),default='train');p.add_argument('--limit',type=int,default=0)
    a=p.parse_args();globals()[a.mode](a)
