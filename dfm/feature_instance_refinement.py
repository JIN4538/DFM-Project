"""Versioned, opt-in learned affinity between disconnected CAD face groups.

The existing joint GNN and cad-feature-agreement-v1 remain unchanged. Only the
four previously unconfirmed through-feature classes may be proposed here.
Original B-rep face IDs and measurements are retained; no dimensions are fit.
"""
from __future__ import annotations
import hashlib
import inspect
import json
from pathlib import Path
import numpy as np
from .feature_localization import embedding, components

SCHEMA = 'dfm-disconnected-feature-affinity-1'
TARGET_CLASSES = (1, 2, 4, 7)
MODEL_PATH = Path(__file__).resolve().parents[1]/'data/models/external_feature_affinity_v1.json'


def geometry(graph):
    if 'measurements' in graph:
        rows = graph['measurements']
        return (np.asarray([r['centroid_mm'] for r in rows]),
                np.asarray([r['normal'] for r in rows]),
                np.asarray([r['area_mm2'] for r in rows]), float(graph['scale_mm']))
    return tuple(graph[k] for k in ('centroids', 'normals', 'areas', 'scale'))


def group_records(graph, prediction, edge_threshold):
    groups = components(np.asarray(graph['edges'], int), prediction['edge'] >= edge_threshold, len(graph['x']))
    result = []
    for group in groups:
        logits = np.log(np.maximum(prediction['semantic'][group], 1e-12)).mean(0)
        probability = np.exp(logits-logits.max()); probability /= probability.sum()
        label = int(probability.argmax())
        result.append(dict(faces=list(map(int, group)), label=label, confidence=float(probability[label])))
    return result


def pair_inputs(graph, groups, backbone):
    """Symmetric, translation/rotation/scale invariant descriptors; no labels."""
    x = np.asarray(graph['x'], float); h = embedding(graph, backbone)
    centers, normals, areas, scale = geometry(graph)
    centers = np.asarray(centers)/float(scale); normals = np.asarray(normals)
    areas = np.asarray(areas)/float(scale)**2
    edges = np.asarray(graph['edges'], int).reshape(-1, 2)
    descriptions = []
    for record in groups:
        g = np.asarray(record['faces'], int)
        neighbors = sorted(set(map(int, edges[np.isin(edges[:, 0], g), 1]))-set(g))
        all_ids = np.r_[g, neighbors].astype(int)
        descriptions.append(dict(g=g, neighbors=set(neighbors),
            center=np.average(centers[g], axis=0, weights=np.maximum(areas[g], 1e-12)),
            vec=np.r_[x[g].mean(0), h[g].mean(0)],
            normals=normals[all_ids], area=float(areas[g].sum())))
    pairs=[]; features=[]
    for i, left in enumerate(groups):
        if left['label'] not in TARGET_CLASSES or left['confidence'] < .5: continue
        for j in range(i+1, len(groups)):
            right=groups[j]
            if right['label'] != left['label'] or right['confidence'] < .5: continue
            a,b=descriptions[i],descriptions[j]; delta=b['center']-a['center']
            distances=np.linalg.norm(centers[a['g']][:,None]-centers[b['g']][None,:],axis=2)
            projections=np.r_[np.abs(a['normals']@delta),np.abs(b['normals']@delta)]
            cross=np.abs(a['normals']@b['normals'].T).ravel()
            count=sorted((len(a['g']),len(b['g']))); area=sorted((a['area'],b['area']))
            confidence=sorted((left['confidence'],right['confidence']))
            onehot=np.zeros(4);onehot[TARGET_CLASSES.index(left['label'])]=1
            extras=np.r_[count,area,confidence,np.linalg.norm(delta),
                distances.min(),distances.mean(),distances.max(),
                projections.min(),projections.mean(),projections.max(),cross.min(),cross.mean(),cross.max(),
                len(a['neighbors']&b['neighbors'])/max(len(a['neighbors']|b['neighbors']),1),
                area[0]/max(area[1],1e-12)]
            features.append(np.r_[(a['vec']+b['vec'])*.5,np.abs(a['vec']-b['vec']),extras,onehot])
            pairs.append((i,j))
    return np.asarray(features,dtype=np.float32).reshape(-1,162),pairs


def contract_hash():
    source='\n'.join(inspect.getsource(f) for f in (geometry,group_records,pair_inputs,predict_affinity,refine_groups))
    return hashlib.sha256((SCHEMA+source).encode()).hexdigest()


def predict_affinity(features, model):
    h=(np.asarray(features,float)-model['mean'])/model['std']
    for i,layer in enumerate(model['layers']):
        h=h@np.asarray(layer['weight']).T+layer['bias']
        if i<len(model['layers'])-1:h=np.maximum(h,0)
    return 1/(1+np.exp(-np.clip(h[:,0],-50,50)))


def refine_groups(groups, pairs, affinity, threshold):
    """Complete-link merging prevents a lone bridge joining several features."""
    lookup={tuple(pair):float(p) for pair,p in zip(pairs,affinity)}
    clusters=[{i} for i in range(len(groups))]
    for (i,j),p in sorted(lookup.items(),key=lambda v:-v[1]):
        if p<threshold:continue
        a=next(g for g in clusters if i in g);b=next(g for g in clusters if j in g)
        if a is b:continue
        if min(lookup.get(tuple(sorted((u,v))),0.) for u in a for v in b)<threshold:continue
        a.update(b);clusters.remove(b)
    result=[]
    for cluster in clusters:
        rows=[groups[i] for i in sorted(cluster)]
        result.append(dict(faces=sorted({v for r in rows for v in r['faces']}),label=rows[0]['label'],
            confidence=min(r['confidence'] for r in rows),fragments=len(rows)))
    return result


def load_model(path=MODEL_PATH):
    path=Path(path)
    if path.stat().st_size>2_000_000:raise ValueError('Affinity artifact too large')
    raw=path.read_bytes()
    manifest=json.loads(path.with_suffix('.manifest.json').read_text(encoding='utf8'))
    model=json.loads(raw)
    if hashlib.sha256(raw).hexdigest()!=manifest['sha256']:raise ValueError('Affinity checksum mismatch')
    if model['schema']!=SCHEMA or model['contract_sha256']!=contract_hash():raise ValueError('Affinity source contract mismatch')
    root=Path(__file__).resolve().parents[1]
    for relative,digest in model['frozen_dependencies'].items():
        if hashlib.sha256((root/relative).read_bytes()).hexdigest()!=digest:raise ValueError('Affinity frozen dependency mismatch')
    mean=np.asarray(model['mean']);std=np.asarray(model['std'])
    if mean.shape!=(162,) or std.shape!=(162,) or not np.isfinite(mean).all() or not np.isfinite(std).all() or np.any(std<=0):raise ValueError('Invalid affinity normalization')
    threshold=model.get('merge_threshold')
    if not isinstance(threshold,(int,float)) or not np.isfinite(threshold) or not .5<=threshold<=1:raise ValueError('Uncalibrated affinity model')
    if set(model.get('class_thresholds',{}))!=set(map(str,TARGET_CLASSES)):raise ValueError('Invalid affinity target classes')
    if any(t is not None and (not isinstance(t,(int,float)) or not np.isfinite(t) or not .5<=t<=1) for t in model['class_thresholds'].values()):raise ValueError('Invalid affinity class thresholds')
    width=162
    for layer in model['layers']:
        w=np.asarray(layer['weight']);b=np.asarray(layer['bias'])
        if w.ndim!=2 or w.shape[1]!=width or b.shape!=(w.shape[0],) or not np.isfinite(w).all() or not np.isfinite(b).all():raise ValueError('Invalid affinity tensors')
        width=len(b)
    if width!=1:raise ValueError('Invalid affinity output')
    return model


def recognize_refined_features(graph,model_path=None):
    """Opt-in companion to the immutable v1 adapter; old candidates stay intact."""
    from .feature_routing import recognize_cad_features
    from .feature_localization import load_model as load_joint,predict_localization
    from .feature_learning import CURVED_CLASS_NAMES,CURVED_CLASS_LABELS
    result=recognize_cad_features(graph)
    if result.get('status')!='measured' or result.get('routing_policy')!='cad-feature-agreement-v1':return result
    try:model=load_model(MODEL_PATH if model_path is None else model_path)
    except (OSError,ValueError,KeyError,TypeError) as error:
        return dict(result,refinement_unavailable=str(error))
    head,backbone=load_joint()
    p=predict_localization(graph,head,backbone);groups=group_records(graph,p,head['edge_threshold'])
    features,pairs=pair_inputs(graph,groups,backbone);affinity=predict_affinity(features,model)
    refined=refine_groups(groups,pairs,affinity,model['merge_threshold'])
    added=[]
    for group in refined:
        label=group['label'];threshold=model['class_thresholds'].get(str(label))
        if label not in TARGET_CLASSES or threshold is None or group['confidence']<threshold:continue
        measured=[graph['measurements'][i] for i in group['faces']]
        added.append(dict(feature=CURVED_CLASS_NAMES[label],label=CURVED_CLASS_LABELS[label],
            face_ids=[int(m['face_id']) for m in measured],confidence=group['confidence'],confidence_source='joint_with_learned_fragment_affinity',
            area_mm2=sum(m['area_mm2'] for m in measured),measured_faces=measured,
            bottom_face_ids=[int(graph['measurements'][i]['face_id']) for i in group['faces'] if p['bottom'][i]>=head['bottom_threshold']],
            localization_model_id=head['model_id'],refinement_model_id=model['model_id'],fragments=group['fragments'],
            measurement_method='Learned disconnected-instance affinity; original OCCT B-rep face integration'))
    result=dict(result,candidates=list(result['candidates'])+added,refinement_model_id=model['model_id'],
        refinement_candidates=len(added),routing_policy='cad-feature-agreement-v1+disconnected-affinity-v1',
        unconfirmed_classes=[CURVED_CLASS_NAMES[c] for c in TARGET_CLASSES if model['class_thresholds'].get(str(c)) is None])
    return result
