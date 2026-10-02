"""Portable graph neural inference trained on external face labels (no torch)."""
from __future__ import annotations
import json, hashlib
from functools import lru_cache
from pathlib import Path
import numpy as np
from .cad_graph import FEATURES, SCHEMA

MODEL_PATH=Path(__file__).resolve().parents[1]/'data/models/external_feature_gnn_v2.json'
CURVED_MODEL_PATH=MODEL_PATH.with_name('external_feature_mfinstseg_v1.json')
CURVED_CLASS_NAMES=('chamfer','through_hole','triangular_passage','rectangular_passage','6sides_passage',
 'triangular_through_slot','rectangular_through_slot','circular_through_slot','rectangular_through_step',
 '2sides_through_step','slanted_through_step','Oring','blind_hole','triangular_pocket','rectangular_pocket',
 '6sides_pocket','circular_end_pocket','rectangular_blind_slot','v_circular_end_blind_slot',
 'h_circular_end_blind_slot','triangular_blind_step','circular_blind_step','rectangular_blind_step','round','stock')
CURVED_CLASS_LABELS=('모따기','관통 구멍','삼각 관통부','직사각 관통부','육각 관통부','삼각 관통 홈',
 '직사각 관통 홈','원형 관통 홈','관통 단차','양측 관통 단차','경사 단차','원형 링 홈','막힌 구멍',
 '삼각 포켓','직사각 포켓','육각 포켓','원형 끝 포켓','막힌 홈','수직 원형 끝 홈','수평 원형 끝 홈',
 '삼각 단차','원형 단차','직사각 단차','둥근 모서리','바깥면')
CLASS_NAMES=('chamfer','triangular_passage','rectangular_passage','6sides_passage',
             'triangular_through_slot','rectangular_through_slot','rectangular_through_step',
             '2sides_through_step','slanted_through_step','triangular_pocket','rectangular_pocket',
             '6sides_pocket','rectangular_blind_slot','triangular_blind_step','rectangular_blind_step','stock')
CLASS_LABELS=('모따기','삼각 관통부','직사각 관통부','육각 관통부','삼각 관통 홈','직사각 관통 홈',
              '관통 단차','양측 관통 단차','경사 단차','삼각 포켓','직사각 포켓','육각 포켓',
              '막힌 홈','삼각 단차','직사각 단차','바깥면')

@lru_cache(maxsize=4)
def _load_model(path,stamp,mstamp):
    path=Path(path)
    if path.stat().st_size>10_000_000:raise ValueError('Feature model exceeds size budget')
    raw=path.read_bytes();manifest=json.loads(path.with_suffix('.manifest.json').read_text(encoding='utf8'))
    if manifest.get('sha256')!=hashlib.sha256(raw).hexdigest():raise ValueError('Feature model checksum mismatch')
    data=json.loads(raw)
    if data.get('graph_schema')!=SCHEMA or tuple(data.get('features',()))!=FEATURES: raise ValueError('Graph model contract mismatch')
    if data.get('schema')!='dfm-feature-gnn-1' or tuple(data['classes']) not in (CLASS_NAMES,CURVED_CLASS_NAMES): raise ValueError('Feature model schema mismatch')
    if data.get('graph_source_sha256')!=hashlib.sha256(Path(__file__).with_name('cad_graph.py').read_bytes()).hexdigest():raise ValueError('Graph extraction version mismatch')
    if not .5<=data['candidate_threshold']<=1:raise ValueError('Invalid candidate threshold')
    mean,std=np.array(data['mean']),np.array(data['std'])
    if mean.shape!=(len(FEATURES),) or std.shape!=mean.shape or not np.isfinite(mean).all() or not np.isfinite(std).all() or np.any(std<=0):raise ValueError('Invalid graph normalization')
    width=len(FEATURES)
    if len(data['layers'])!=4:raise ValueError('Invalid graph network depth')
    for i,layer in enumerate(data['layers']):
        w=np.array(layer['weight']);b=np.array(layer['bias']);kind='graph' if i<3 else 'dense';activation='relu' if i<3 else 'linear'
        if layer['kind']!=kind or layer['activation']!=activation or w.ndim!=2 or w.shape[1]!=width*(2 if i<3 else 1) or b.shape!=(w.shape[0],) or not np.isfinite(w).all() or not np.isfinite(b).all():raise ValueError('Invalid graph network weights')
        width=w.shape[0]
    if width!=len(data['classes']):raise ValueError('Invalid graph network classes')
    return data

def load_model(path=MODEL_PATH):
    path=Path(path)
    return _load_model(str(path.resolve()),path.stat().st_mtime_ns,path.with_suffix('.manifest.json').stat().st_mtime_ns)

def predict_graph(graph, model=None):
    model=load_model() if model is None else model
    h=(np.asarray(graph['x'],dtype=np.float64)-model['mean'])/model['std']
    if h.ndim!=2 or h.shape[1]!=len(FEATURES) or not np.isfinite(h).all(): raise ValueError('Invalid graph input')
    edges=np.asarray(graph['edges'],dtype=int).reshape(-1,2); n=len(h)
    if edges.size and (edges.min()<0 or edges.max()>=n): raise ValueError('Invalid graph edges')
    for layer in model['layers']:
        if layer['kind']=='graph':
            aggregate=np.zeros_like(h); count=np.zeros(n)
            if len(edges):
                np.add.at(aggregate,edges[:,0],h[edges[:,1]]); np.add.at(count,edges[:,0],1)
            aggregate/=np.maximum(count[:,None],1)
            h=np.concatenate([h,aggregate],axis=1)
        h=h@np.asarray(layer['weight']).T+layer['bias']
        if layer['activation']=='relu': h=np.maximum(h,0)
    h-=h.max(axis=1,keepdims=True); exp=np.exp(h)
    return exp/exp.sum(axis=1,keepdims=True)

def recognize_graph(graph,model=None):
    model=load_model() if model is None else model
    # The external corpus contains planar machining features only. Curved
    # faces are handled by existing exact cylinder checks, never forced here.
    names=tuple(model['classes']); labels=CLASS_LABELS if names==CLASS_NAMES else CURVED_CLASS_LABELS
    x=np.asarray(graph['x'])
    if (names==CLASS_NAMES and np.any(x[:,0]<.5)) or (names==CURVED_CLASS_NAMES and np.any(x[:,5]>.5)):
        return dict(status='outside_training_domain',candidates=[],model_id=model['model_id'])
    p=predict_graph(graph,model); ids=p.argmax(1); confidence=p.max(1)
    threshold=float(model['candidate_threshold'])
    candidates=[]; visited=set(); edges=np.asarray(graph['edges']).reshape(-1,2)
    for i,label in enumerate(ids):
        if i in visited or names[label]=='stock' or confidence[i]<threshold: continue
        group={i}; stack=[i]; visited.add(i)
        while stack:
            k=stack.pop()
            for j in edges[edges[:,0]==k,1]:
                j=int(j)
                if j not in visited and ids[j]==label and confidence[j]>=threshold:
                    visited.add(j); group.add(j); stack.append(j)
        measurements=[graph['measurements'][j] for j in sorted(group)]
        candidates.append(dict(feature=names[label],label=labels[label],
            face_ids=[int(m['face_id']) for m in measurements],confidence=float(min(confidence[list(group)])),
            area_mm2=sum(m['area_mm2'] for m in measurements),
            measured_faces=measurements,measurement_method='OCCT B-rep integration; predictions only select faces'))
    return dict(status='measured',model_id=model['model_id'],candidates=candidates,
                evaluated_faces=len(ids),threshold=threshold)
