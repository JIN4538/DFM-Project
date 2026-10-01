"""Learned feature-instance boundaries and bottom faces, with CAD measurements.

Semantic labels alone merge adjacent instances of the same class. An external
instance-label head instead predicts whether two adjacent faces belong together.
The resulting face IDs remain original B-rep IDs; reported dimensions are never
neural predictions.
"""
from functools import lru_cache
import hashlib
import inspect
import json
from pathlib import Path
import numpy as np
from .feature_learning import load_model as load_semantic_model, predict_graph, CLASS_NAMES, CLASS_LABELS, CURVED_CLASS_NAMES, CURVED_CLASS_LABELS

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT/'data/models/external_feature_localization_v1.json'
SCHEMA = 'dfm-feature-localization-1'


def edge_geometry(graph):
    edges = np.asarray(graph['edges'], dtype=int).reshape(-1, 2)
    if not len(edges):
        return np.empty((0, 5), dtype=np.float32)
    if 'measurements' in graph:
        m = graph['measurements']
        centroids = np.array([r['centroid_mm'] for r in m])
        normals = np.array([r['normal'] for r in m])
        areas = np.array([r['area_mm2'] for r in m])
        scale = float(graph['scale_mm'])
    else:
        centroids, normals, areas, scale = (graph[k] for k in ('centroids', 'normals', 'areas', 'scale'))
    a, b = edges.T
    delta = (centroids[b]-centroids[a])/scale
    first = np.sum(delta*normals[a], axis=1)
    second = np.sum(-delta*normals[b], axis=1)
    return np.column_stack((np.linalg.norm(delta, axis=1),
        np.sum(normals[a]*normals[b], axis=1), np.minimum(areas[a], areas[b])/np.maximum(np.maximum(areas[a], areas[b]), 1e-20),
        np.minimum(first, second), np.maximum(first, second))).astype('float32')


def node_geometry(edges, geometry, count):
    output = np.zeros((count, 15), dtype='float32')
    for i in range(count):
        rows = geometry[np.asarray(edges)[:, 0] == i]
        if len(rows):
            output[i] = np.r_[rows.min(0), rows.mean(0), rows.max(0)]
    return output


def embedding(graph, semantic_model):
    h = (np.asarray(graph['x'], dtype=float)-semantic_model['mean'])/semantic_model['std']
    edges = np.asarray(graph['edges'], dtype=int).reshape(-1, 2)
    for layer in semantic_model['layers'][:3]:
        aggregate = np.zeros_like(h)
        count = np.zeros(len(h))
        if len(edges):
            np.add.at(aggregate, edges[:, 0], h[edges[:, 1]])
            np.add.at(count, edges[:, 0], 1)
        h = np.maximum(np.concatenate([h, aggregate/np.maximum(count[:, None], 1)], axis=1) @ np.asarray(layer['weight']).T + layer['bias'], 0)
    return h


def head_predict(values, layers):
    h = np.asarray(values)
    for i, layer in enumerate(layers):
        h = h @ np.asarray(layer['weight']).T + layer['bias']
        if i < len(layers)-1:
            h = np.maximum(h, 0)
    return 1/(1+np.exp(-np.clip(h[:, 0], -50, 50)))


def contract_hash():
    source = '\n'.join(inspect.getsource(f) for f in (edge_geometry, node_geometry, embedding, head_predict, predict_localization))
    return hashlib.sha256((SCHEMA+source).encode()).hexdigest()


@lru_cache(maxsize=4)
def _load(path, stamp, mstamp, semantic_stamp, semantic_manifest_stamp):
    path = Path(path)
    if path.stat().st_size > 2_000_000:
        raise ValueError('Localization artifact too large')
    raw = path.read_bytes()
    manifest = json.loads(path.with_suffix('.manifest.json').read_text(encoding='utf8'))
    if hashlib.sha256(raw).hexdigest() != manifest.get('sha256'):
        raise ValueError('Localization checksum mismatch')
    model = json.loads(raw)
    if model.get('schema') != SCHEMA or model.get('contract_sha256') != contract_hash():
        raise ValueError('Localization feature contract mismatch')
    semantic_path = path.with_name(model['semantic_filename'])
    semantic = load_semantic_model(semantic_path)
    if hashlib.sha256(semantic_path.read_bytes()).hexdigest() != model['semantic_sha256']:
        raise ValueError('Localization backbone mismatch')
    for name, width, end in (('bottom', 63, 1), ('edge', 101, 1), ('semantic', 63, 25)):
        if len(model[name]) != 2:
            raise ValueError('Invalid localization head depth')
        for layer in model[name]:
            weight = np.asarray(layer['weight'])
            bias = np.asarray(layer['bias'])
            if weight.ndim != 2 or weight.shape[1] != width or bias.shape != (weight.shape[0],) or not np.isfinite(weight).all() or not np.isfinite(bias).all():
                raise ValueError('Invalid localization head tensors')
            width = weight.shape[0]
        if width != end:
            raise ValueError('Invalid localization head output')
    if not .05 <= model['edge_threshold'] <= .95 or not .05 <= model['bottom_threshold'] <= .95:
        raise ValueError('Invalid localization thresholds')
    thresholds=model.get('class_thresholds')
    if thresholds is not None and (len(thresholds)!=24 or any(v is not None and (type(v) not in (int,float) or not np.isfinite(v) or not .5<=v<=1.) for v in thresholds)):
        raise ValueError('Invalid class-specific localization thresholds')
    return model, semantic


def load_model(path=MODEL_PATH):
    path = Path(path)
    if path.stat().st_size > 2_000_000:
        raise ValueError('Localization artifact too large')
    meta = json.loads(path.read_text(encoding='utf8'))
    if meta.get('semantic_filename') != 'external_feature_mfinstseg_v2.json':
        raise ValueError('Unexpected localization backbone filename')
    semantic = path.with_name(meta['semantic_filename'])
    return _load(str(path.resolve()), path.stat().st_mtime_ns, path.with_suffix('.manifest.json').stat().st_mtime_ns,
        semantic.stat().st_mtime_ns,semantic.with_suffix('.manifest.json').stat().st_mtime_ns)


def predict_localization(graph, model, semantic):
    h = embedding(graph, semantic)
    e = np.asarray(graph['edges'], dtype=int).reshape(-1, 2)
    geo = edge_geometry(graph)
    enriched = np.concatenate([h, node_geometry(e, geo, len(h))], axis=1)
    edge = np.concatenate([(h[e[:, 0]]+h[e[:, 1]])*.5, np.abs(h[e[:, 0]]-h[e[:, 1]]), geo], axis=1)
    correction = enriched
    for i, layer in enumerate(model['semantic']):
        correction = correction @ np.asarray(layer['weight']).T + layer['bias']
        if i < len(model['semantic'])-1:
            correction = np.maximum(correction, 0)
    logits = h @ np.asarray(semantic['layers'][-1]['weight']).T + semantic['layers'][-1]['bias'] + correction
    logits -= logits.max(1, keepdims=True)
    probability = np.exp(logits)
    probability /= probability.sum(1, keepdims=True)
    return dict(edge=head_predict(edge, model['edge']), bottom=head_predict(enriched, model['bottom']), semantic=probability)


def components(edges, connect, count):
    neighbors = [[] for _ in range(count)]
    for (i, j), selected in zip(edges, connect):
        if selected:
            neighbors[int(i)].append(int(j))
    seen = set()
    output = []
    for i in range(count):
        if i in seen:
            continue
        group = {i}
        stack = [i]
        seen.add(i)
        while stack:
            for j in neighbors[stack.pop()]:
                if j not in seen:
                    seen.add(j)
                    group.add(j)
                    stack.append(j)
        output.append(sorted(group))
    return output


def recognize_instances(graph, semantic_model=None, *, localization_path=MODEL_PATH):
    model, backbone = load_model(localization_path)
    semantic = backbone if semantic_model is None else semantic_model
    x = np.asarray(graph['x'])
    names = tuple(semantic['classes'])
    labels = CLASS_LABELS if names == CLASS_NAMES else CURVED_CLASS_LABELS
    if np.any(x[:, 5] > .5) or (names == CLASS_NAMES and np.any(x[:, 0] < .5)):
        return dict(status='outside_training_domain', candidates=[], model_id=semantic['model_id'])
    prediction = predict_localization(graph, model, backbone)
    probabilities = prediction['semantic'] if semantic_model is None else predict_graph(graph, semantic)
    edges = np.asarray(graph['edges'], dtype=int).reshape(-1, 2)
    candidates = []
    for group in components(edges, prediction['edge'] >= model['edge_threshold'], len(x)):
        # Whole-instance log-posterior voting tolerates one uncertain face;
        # reporting still requires the validated instance confidence cutoff.
        scores = np.log(np.maximum(probabilities[group], 1e-12)).mean(0)
        q = np.exp(scores-scores.max())
        q /= q.sum()
        label = int(q.argmax())
        confidence = float(q[label])
        threshold = model.get('instance_threshold',.9)
        if 'class_thresholds' in model and names[label]!='stock':
            threshold=model['class_thresholds'][CURVED_CLASS_NAMES.index(names[label])]
        if names[label] == 'stock' or threshold is None or confidence < float(threshold):
            continue
        measured = [graph['measurements'][j] for j in group]
        candidates.append(dict(feature=names[label], label=labels[label], face_ids=[int(m['face_id']) for m in measured],
            confidence=confidence, area_mm2=sum(m['area_mm2'] for m in measured), measured_faces=measured,
            bottom_face_ids=[int(graph['measurements'][j]['face_id']) for j in group if prediction['bottom'][j] >= model['bottom_threshold']],
            localization_model_id=model['model_id'], measurement_method='Learned instance boundary/bottom proposals; OCCT B-rep integration'))
    return dict(status='measured', model_id=semantic['model_id'], localization_model_id=model['model_id'],
        candidates=candidates, evaluated_faces=len(x), threshold=model.get('instance_threshold', .9),
        unconfirmed_classes=[CURVED_CLASS_NAMES[i] for i,t in enumerate(model.get('class_thresholds',[])) if t is None])
