"""Validation-only instance confidence gate for a frozen training checkpoint."""
import argparse,hashlib,io,json,sqlite3,sys
from pathlib import Path
import numpy as np
import torch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from scripts.train_full_features import MultiTask,evaluate,panoptic,export
from dfm.feature_learning import load_model
from dfm.feature_localization import edge_geometry,node_geometry,predict_localization,components


def graphs(root,split):
    out=[]
    with sqlite3.connect(f'file:{(root/"mfinstseg-verified.sqlite").as_posix()}?mode=ro',uri=True) as db:
        for identifier,blob in db.execute('SELECT id,graph FROM parts WHERE split=? AND graph IS NOT NULL ORDER BY id',(split,)):
            with np.load(io.BytesIO(blob),allow_pickle=False) as z:g={k:z[k].copy() for k in z.files}
            g['geo']=edge_geometry(g);g['node_geo']=node_geometry(g['edges'],g['geo'],len(g['x']))
            g.update(id=identifier,edge_y=g['inst'][g['edges'][:,0],g['edges'][:,1]].astype('float32'),
                instance_rows=g['inst'],face_mask=np.ones(len(g['x']),dtype=bool),edge_mask=np.ones(len(g['edges']),dtype=bool))
            out.append(g)
    return out


def instance_events(graphs,probabilities,predictions,edge_threshold=.5):
    events={i:[] for i in range(24)};ground=np.zeros(24,dtype=int)
    for g,p,pred in zip(graphs,probabilities,predictions):
        truth=[];seen=set()
        for i,c in enumerate(g['y']):
            if i in seen or c==24:continue
            group=set(np.flatnonzero(g['instance_rows'][i])) or {i}
            seen.update(group);truth.append((group,int(c)));ground[c]+=1
        for group in components(g['edges'],pred['edge']>=edge_threshold,len(g['x'])):
            s=np.log(np.maximum(p[group],1e-12)).mean(0);q=np.exp(s-s.max());q/=q.sum();c=int(q.argmax())
            if c==24:continue
            selected=set(group)
            iou=max((len(selected&t)/len(selected|t) for t,label in truth if label==c),default=0.)
            events[c].append((float(q[c]),iou))
    return events,ground


def event_metrics(events,ground,thresholds):
    tp=fp=exact=0;iou=0.
    for c,rows in events.items():
        threshold=thresholds[c]
        if threshold is None:continue
        for confidence,value in rows:
            if confidence<threshold:continue
            if value>.5:tp+=1;iou+=value;exact+=value==1.
            else:fp+=1
    fn=int(ground.sum())-tp
    return dict(pq=iou/max(tp+.5*(fp+fn),1),instance_precision=tp/max(tp+fp,1),instance_recall=tp/max(tp+fn,1),
        exact_instance_recall=exact/max(int(ground.sum()),1),tp=tp,fp=fp,fn=fn,ground_truth_instances=int(ground.sum()))


def class_calibration(events,ground):
    choices=[];audit=[]
    for c in range(24):
        rows=[]
        for threshold in (.5,.6,.7,.8,.9,.95,.98,.99,.995,.999,.9995,.9999,.99999):
            values=[value for confidence,value in events[c] if confidence>=threshold]
            tp=sum(v>.5 for v in values);fp=len(values)-tp;fn=int(ground[c])-tp
            rows.append(dict(threshold=threshold,precision=tp/max(tp+fp,1),pq=sum(v for v in values if v>.5)/max(tp+.5*(fp+fn),1),tp=tp,fp=fp,fn=fn))
        valid=[q for q in rows if q['precision']>=.97 and q['tp']>=100]
        choice=max(valid,key=lambda q:q['pq']) if valid else None
        choices.append(choice['threshold'] if choice else None)
        audit.append(dict(class_index=c,chosen=choice,threshold_trials=rows))
    return choices,audit


def main(root,width):
    torch.set_num_threads(1)
    base=load_model(ROOT/'data/models/external_feature_mfinstseg_v1.json')
    model=MultiTask(base,width)
    checkpoint=root/'feature-models/best-training-state.pt'
    model.load_state_dict(torch.load(checkpoint,weights_only=True));model.eval()
    val=graphs(root,'val');vm,vp,vl,_,_=evaluate(model,val,raw=True)
    calibration=[]
    for threshold in (.7,.9,.95,.98,.99,.995,.999,.9995,.9999,.99999):
        q=panoptic(val,vp,vl,confidence=threshold)
        calibration.append(dict(threshold=threshold,**q))
        print(json.dumps(calibration[-1]),flush=True)
    valid=[q for q in calibration if q['instance_precision']>=.97 and q['tp']>=100]
    boundary_trials=[]
    for edge_threshold in (.5,.7,.85,.95):
        events,ground=instance_events(val,vp,vl,edge_threshold)
        thresholds,class_audit=class_calibration(events,ground)
        chosen=event_metrics(events,ground,thresholds)
        boundary_trials.append(dict(edge_threshold=edge_threshold,class_thresholds=thresholds,class_calibration=class_audit,metrics=chosen))
        print(json.dumps(dict(edge_threshold=edge_threshold,metrics=chosen)),flush=True)
    best=max(boundary_trials,key=lambda q:q['metrics']['pq'])
    thresholds,class_audit,chosen=best['class_thresholds'],best['class_calibration'],best['metrics']
    if chosen['instance_precision']<.97 or chosen['tp']<100:
        raise ValueError('Per-class calibration does not meet validation precision gate')
    semantic,heads=export(model,root,base,.7)
    heads['class_thresholds']=thresholds
    heads['edge_threshold']=best['edge_threshold']
    heads['calibration_scope']='Validation class-specific instance precision >=.97 with >=100 true positives; unsupported classes remain unconfirmed'
    # Bottom confidence is separately calibrated; CAD floor checks remain exact.
    _,_,_,bottoms,_=evaluate(model,val,raw=True)
    by=np.asarray(bottoms[0]);bp=np.asarray(bottoms[1]);bottom_trials=[]
    from scripts.train_full_features import binary_metrics
    for t in (.5,.6,.7,.8,.9,.95,.98,.99):
        m=binary_metrics(by,bp>=t);bottom_trials.append(dict(threshold=t,**m))
    reliable=[q for q in bottom_trials if q['precision']>=.97]
    if reliable:heads['bottom_threshold']=max(reliable,key=lambda q:q['f1'])['threshold']
    hp=root/'feature-models/external_feature_localization_v1.json';raw=json.dumps(heads,separators=(',',':')).encode();hp.write_bytes(raw)
    hp.with_suffix('.manifest.json').write_text(json.dumps(dict(schema=heads['schema'],sha256=hashlib.sha256(raw).hexdigest())))
    test=graphs(root,'test');tm,tp,tl,_,_=evaluate(model,test,raw=True)
    parity=[]
    for g in test[:30]:
        portable=predict_localization(g,heads,semantic)
        single=evaluate(model,[g],raw=True)
        parity.append(float(np.max(np.abs(portable['semantic']-single[1][0]))))
        parity.append(float(np.max(np.abs(portable['edge']-single[2][0]['edge']))))
        parity.append(float(np.max(np.abs(portable['bottom']-single[2][0]['bottom']))))
    if max(parity)>1e-4:raise ValueError('Portable multi-head mismatch')
    summary=dict(validation=vm,calibration=calibration,class_calibration=class_audit,class_thresholds=thresholds,chosen_validation=chosen,
        test=tm,test_panoptic=event_metrics(*instance_events(test,tp,tl,best['edge_threshold']),thresholds),portable_max_error=max(parity),bottom_calibration=bottom_trials,
        boundary_trials=boundary_trials,chosen_edge_threshold=best['edge_threshold'],
        checkpoint_sha256=hashlib.sha256(checkpoint.read_bytes()).hexdigest(),width=width,
        selection='Frozen checkpoint; validation-only confidence calibration. Held-out testing after calibration.')
    (root/'feature-models/calibrated-evaluation.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps({k:v for k,v in summary.items() if k not in ('validation','test','calibration')}),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--width',type=int,default=64);a=p.parse_args();main(a.root,a.width)
