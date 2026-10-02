"""Compare actual portable CAD feature paths; calibrate on validation only.

Certified MFInstSeg graphs retain original CAD face order. No weights are fit.
The source DB and prior evaluation records remain immutable.
"""
from __future__ import annotations
import argparse, gzip, hashlib, io, json, sqlite3, sys, time
from pathlib import Path
import numpy as np
from threadpoolctl import threadpool_limits

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dfm.feature_learning import load_model as load_semantic, predict_graph, CLASS_NAMES, CURVED_CLASS_NAMES
from dfm.feature_localization import load_model, predict_localization, components

VARIANTS = ('current_runtime', 'joint', 'joint_semantic_gate', 'joint_confident_gate', 'hybrid_semantic_gate', 'joint_agreement')
THRESHOLDS = (.5, .6, .7, .8, .9, .95, .98, .99, .995, .999, .9995, .9999, .99999)


def score(events, ground, thresholds):
    per_class = []
    for c in range(24):
        values = [v for confidence, v in events[c] if thresholds[c] is not None and confidence >= thresholds[c]]
        tp = sum(v > .5 for v in values); fp = len(values)-tp; fn = int(ground[c])-tp
        per_class.append(dict(class_name=CURVED_CLASS_NAMES[c], tp=tp, fp=fp, fn=fn,
            precision=tp/max(tp+fp, 1), recall=tp/max(int(ground[c]), 1),
            iou_sum=sum(v for v in values if v > .5), exact=sum(v == 1. for v in values)))
    tp = sum(r['tp'] for r in per_class); fp = sum(r['fp'] for r in per_class); fn = sum(r['fn'] for r in per_class)
    return dict(tp=tp, fp=fp, fn=fn, ground_truth=int(sum(ground)), precision=tp/max(tp+fp, 1),
        recall=tp/max(tp+fn, 1), pq=sum(r['iou_sum'] for r in per_class)/max(tp+.5*(fp+fn), 1),
        exact_recall=sum(r['exact'] for r in per_class)/max(tp+fn, 1), per_class=per_class)


def calibrate(events, ground, required_precision=.975):
    thresholds=[]; audit=[]
    for c in range(24):
        trials=[]
        for threshold in THRESHOLDS:
            values=[v for confidence,v in events[c] if confidence>=threshold]
            tp=sum(v>.5 for v in values); fp=len(values)-tp
            trials.append(dict(threshold=threshold,tp=tp,fp=fp,precision=tp/max(tp+fp,1)))
        valid=[r for r in trials if r['tp']>=100 and r['precision']>=required_precision]
        best=max(valid,key=lambda r:(r['tp'],-r['fp'])) if valid else None
        thresholds.append(best['threshold'] if best else None)
        audit.append(dict(class_name=CURVED_CLASS_NAMES[c], selected=best, trials=trials))
    return thresholds,audit


def collect(database, split, output, source='mfinstseg'):
    head, backbone=load_model(); planar_model=load_semantic(); began=time.monotonic()
    events={v:{'all':[[] for _ in range(24)],'planar':[[] for _ in range(24)],'curved':[[] for _ in range(24)]} for v in VARIANTS}
    ground={scope:np.zeros(24,dtype=int) for scope in ('all','planar','curved')}
    counts=dict(records=0,planar=0,curved=0,outside_face_budget=0,other_surface=0)
    mapping=[CURVED_CLASS_NAMES.index(n) for n in CLASS_NAMES]
    ids=[]; runtime_parity=[]
    with sqlite3.connect(f'file:{database.resolve().as_posix()}?mode=ro',uri=True) as db, threadpool_limits(limits=1):
        query=('SELECT id,graph,audit,NULL FROM parts' if source=='mfinstseg' else 'SELECT id,graph,measurement,sha256 FROM parts')
        rows=db.execute(query+' WHERE split=? AND graph IS NOT NULL ORDER BY id',(split,))
        for identifier, raw, audit, raw_sha in rows:
            with np.load(io.BytesIO(raw),allow_pickle=False) as z:g={k:z[k].copy() for k in z.files}
            if source=='mfcad':
                g.update(json.loads(audit)); g['y']=np.asarray(mapping)[g['y']]
                a,b=g['edges'].T
                # MFCAD has semantic labels only: these are connected labelled
                # regions, not author-labelled feature instances.
                g['inst']=np.zeros((len(g['x']),len(g['x'])),dtype=np.uint8)
                for group in components(g['edges'],g['y'][a]==g['y'][b],len(g['x'])):
                    g['inst'][np.ix_(group,group)]=1
            n=len(g['x']); truth=[]; seen=set()
            planar=bool(np.all(g['x'][:,0]>.5)); scope='planar' if planar else 'curved'
            for i,c in enumerate(g['y']):
                if i in seen or c==24:continue
                group=set(np.flatnonzero(g['inst'][i])) or {i}; seen.update(group); truth.append((group,int(c)))
                ground['all'][c]+=1; ground[scope][c]+=1
            counts['records']+=1;counts[scope]+=1
            ids.append(dict(id=identifier,step_sha256=raw_sha if source=='mfcad' else json.loads(audit)['step_sha256'],faces=n,scope=scope))
            if n>200:counts['outside_face_budget']+=1;continue
            if np.any(g['x'][:,5]>.5):counts['other_surface']+=1;continue
            prediction=predict_localization(g,head,backbone); joint=prediction['semantic']
            hybrid=joint
            if planar:
                p=predict_graph(g,planar_model);hybrid=np.zeros((n,25));hybrid[:,mapping]=p
            expected_runtime=[]
            for variant in VARIANTS:
                p=hybrid if variant in ('current_runtime','hybrid_semantic_gate') else joint
                connection=prediction['edge']>=head['edge_threshold']
                if 'gate' in variant:
                    a,b=g['edges'].T; labels=p.argmax(1); different=labels[a]!=labels[b]
                    if variant=='joint_confident_gate':different &= np.minimum(p[a].max(1),p[b].max(1))>=.8
                    connection=connection & ~different
                for group in components(g['edges'],connection,n):
                    logits=np.log(np.maximum(p[group],1e-12)).mean(0);q=np.exp(logits-logits.max());q/=q.sum();c=int(q.argmax())
                    if c==24:continue
                    confidence=float(q[c])
                    if variant=='joint_agreement' and planar:
                        other=np.log(np.maximum(hybrid[group],1e-12)).mean(0);other=np.exp(other-other.max());other/=other.sum()
                        if int(other.argmax())==c:confidence=max(confidence,float(other[c]))
                    if variant=='joint_agreement' and head['class_thresholds'][c] is not None and confidence>=head['class_thresholds'][c]:
                        expected_runtime.append((CURVED_CLASS_NAMES[c],tuple(group),confidence))
                    predicted=set(group);iou=max((len(predicted&t)/len(predicted|t) for t,label in truth if label==c),default=0.)
                    event=(confidence,iou)
                    events[variant]['all'][c].append(event);events[variant][scope][c].append(event)
            if split=='test' and (counts['records']<=24 or counts['records']%100==0):
                from dfm.feature_routing import recognize_cad_features
                runtime_graph=dict(g)
                if 'measurements' not in runtime_graph:
                    runtime_graph['measurements']=[dict(face_id=i+1001,centroid_mm=g['centroids'][i].tolist(),normal=g['normals'][i].tolist(),area_mm2=float(g['areas'][i])) for i in range(n)]
                    runtime_graph['scale_mm']=float(g['scale'])
                lookup={int(m['face_id']):i for i,m in enumerate(runtime_graph['measurements'])}
                actual=recognize_cad_features(runtime_graph)
                candidates=[(r['feature'],tuple(lookup[f] for f in r['face_ids']),r['confidence']) for r in actual['candidates']]
                same=len(candidates)==len(expected_runtime) and all(a[:2]==b[:2] and abs(a[2]-b[2])<1e-10 for a,b in zip(candidates,expected_runtime))
                runtime_parity.append(dict(id=identifier,scope=scope,passed=same,candidates=len(candidates)))
                if not same:raise AssertionError('Portable CAD adapter differs from benchmark: '+identifier)
            if counts['records']%500==0:print(json.dumps(dict(split=split,counts=counts,seconds=round(time.monotonic()-began,2))),flush=True)
    result=dict(source=source,split=split,counts=counts,ground={k:v.tolist() for k,v in ground.items()},events=events,records=ids,
        seconds=time.monotonic()-began,old_thresholds=head['class_thresholds'],runtime_parity=runtime_parity)
    with gzip.open(output/f'{split}-events.json.gz','wt',encoding='utf8') as stream:json.dump(result,stream,separators=(',',':'))
    return result


def run(args):
    args.output.mkdir(parents=True,exist_ok=False)
    data=collect(args.database,args.split,args.output,args.source)
    summary=dict(source=args.source,split=args.split,counts=data['counts'],seconds=data['seconds'],methods={},models={},runtime_parity=data['runtime_parity'],
        label_scope=('Author instance membership and semantic classes of certified original CAD' if args.source=='mfinstseg' else 'Connected same-semantic-label CAD face regions; MFCAD does not provide instance labels')+'; same class and face IoU > .5. Runtime 200-face/analytic-surface gates retained.')
    for path in (ROOT/'data/models').glob('external_feature*.json'):
        summary['models'][path.name]=hashlib.sha256(path.read_bytes()).hexdigest()
    for method in VARIANTS:
        per_scope={scope:score(data['events'][method][scope],data['ground'][scope],data['old_thresholds']) for scope in data['ground']}
        record=dict(existing_thresholds=per_scope)
        if args.split=='val':
            thresholds,audit=calibrate(data['events'][method]['all'],data['ground']['all'])
            record.update(calibrated_thresholds=thresholds,calibration=audit,
                calibrated={scope:score(data['events'][method][scope],data['ground'][scope],thresholds) for scope in data['ground']})
        summary['methods'][method]=record
    (args.output/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
    print(json.dumps({method:{kind:{scope:{k:v for k,v in metrics.items() if k!='per_class'} for scope,metrics in record[kind].items()} for kind in ('existing_thresholds','calibrated') if kind in record} for method,record in summary['methods'].items()}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--database',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--split',choices=('val','test'),default='val');p.add_argument('--source',choices=('mfcad','mfinstseg'),default='mfinstseg')
    run(p.parse_args())
