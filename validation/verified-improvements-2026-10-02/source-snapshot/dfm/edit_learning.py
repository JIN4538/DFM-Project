"""Portable CAD-edit feasibility/material surrogate; every accepted edit is rebuilt."""
import hashlib
import json
import math
from pathlib import Path
from functools import lru_cache
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT/'data/models/cad_edit_surrogate_v1.json'
FEATURES = ('sides', 'depth_scale', 'radius_scale', 'area_scale', 'perimeter_scale',
            'angle_min', 'angle_max', 'angle_mean', 'edge_min_scale', 'edge_max_scale', 'radius_entry_ratio')


def descriptor(pocket, measurements):
    floor = next(m for m in measurements if m['face_id'] == pocket['floor_face_id'])
    points = np.asarray(floor['vertex_points_mm'], dtype=float)
    axis = np.asarray(pocket['direction'], dtype=float); axis /= np.linalg.norm(axis)
    center = points.mean(0); u = points[0]-center; u /= np.linalg.norm(u); v = np.cross(axis, u)
    points = points[np.argsort(np.arctan2((points-center)@v, (points-center)@u))]
    return dict(pocket, floor_polygon_mm=points.tolist(), floor_area_mm2=floor['area_mm2'])


def features(pocket, radius):
    points = np.asarray(pocket['floor_polygon_mm'], dtype=float)
    depth = float(pocket['wall_height_mm']); entry = float(pocket['entry_circle_diameter_mm'])
    if points.ndim != 2 or points.shape[1] != 3 or len(points) not in (3, 4, 6) or not np.isfinite(points).all() or not math.isfinite(radius) or radius <= 0 or depth <= 0 or entry <= 0:
        raise ValueError('Invalid verified pocket edit input')
    # Polygon is stored in cyclic order by the exact dimension checker.
    lengths, angles = [], []
    for i, point in enumerate(points):
        a, b = points[i-1]-point, points[(i+1)%len(points)]-point
        lengths.append(float(np.linalg.norm(b)))
        angles.append(math.acos(float(np.clip(a@b/(np.linalg.norm(a)*np.linalg.norm(b)), -1, 1))))
    values = [len(points)/6, depth/entry, radius/entry, pocket['floor_area_mm2']/entry**2,
        sum(lengths)/entry, min(angles)/math.pi, max(angles)/math.pi, np.mean(angles)/math.pi,
        min(lengths)/entry, max(lengths)/entry, 2*radius/entry]
    if not np.isfinite(values).all():
        raise ValueError('Nonfinite edit features')
    return np.asarray(values, dtype=float)


@lru_cache(maxsize=2)
def _load(path, stamp, manifest_stamp):
    if Path(path).stat().st_size > 2_000_000:
        raise ValueError('CAD edit model exceeds byte budget')
    raw = Path(path).read_bytes(); manifest = json.loads(Path(path).with_suffix('.manifest.json').read_text(encoding='utf8'))
    data = json.loads(raw)
    if data.get('schema') != 'cad-edit-surrogate/1' or data.get('features') != list(FEATURES) or hashlib.sha256(raw).hexdigest() != manifest['model_sha256']:
        raise ValueError('CAD edit model contract mismatch')
    if set(data['networks']) != {'validity', 'material'}:
        raise ValueError('CAD edit model output contract mismatch')
    for net in data['networks'].values():
        mean, scale = np.asarray(net['mean']), np.asarray(net['scale'])
        if mean.shape != (len(FEATURES),) or scale.shape != mean.shape or not np.isfinite(mean).all() or not np.isfinite(scale).all() or np.min(scale) <= 0:
            raise ValueError('Invalid CAD edit normalization')
        width = len(FEATURES)
        if not 1 <= len(net['layers']) <= 4:
            raise ValueError('Invalid CAD edit network depth')
        for layer in net['layers']:
            weights, bias = np.asarray(layer['weights']), np.asarray(layer['bias'])
            if weights.ndim != 2 or weights.shape[0] != width or not 1 <= weights.shape[1] <= 256 or bias.shape != (weights.shape[1],) or not np.isfinite(weights).all() or not np.isfinite(bias).all():
                raise ValueError('Invalid CAD edit network tensors')
            width = weights.shape[1]
        if width != 1:
            raise ValueError('Invalid CAD edit network output')
    data['sha256'] = manifest['model_sha256']
    return data


def load_model(path=MODEL_PATH):
    p = Path(path)
    return _load(str(p.resolve()), p.stat().st_mtime_ns, p.with_suffix('.manifest.json').stat().st_mtime_ns)


def predict(x, model=None):
    model = model or load_model()
    x = np.asarray(x, dtype=float).reshape(-1, len(FEATURES))
    if not np.isfinite(x).all():
        raise ValueError('Nonfinite edit model input')
    out = {}
    for name, net in model['networks'].items():
        h = (x-np.asarray(net['mean']))/np.asarray(net['scale'])
        for i, layer in enumerate(net['layers']):
            h = h@np.asarray(layer['weights'])+np.asarray(layer['bias'])
            if i != len(net['layers'])-1:
                h = np.maximum(h, 0)
        if name == 'validity':
            h = 1/(1+np.exp(-np.clip(h, -40, 40)))
        out[name] = h[:, 0]
    if not all(np.isfinite(v).all() for v in out.values()):
        raise ValueError('Nonfinite CAD edit prediction')
    return out


def candidate_order(pocket, radii, *, minimum_radius=0., max_radius=None, model=None):
    if any(type(r) not in (int, float) or not math.isfinite(r) or r <= 0 for r in radii):
        raise ValueError('Finite positive edit radii required')
    indices = [i for i, r in enumerate(radii) if r >= minimum_radius-1e-8 and (max_radius is None or r <= max_radius+1e-8)]
    if not indices:
        return [], dict(status='empty', considered=len(radii))
    model = model or load_model()
    y = predict([features(pocket, radii[i]) for i in indices], model)
    # Discrete geometric constraints are enforced before learning; predicted
    # feasibility only orders costly CAD operations and cannot certify them.
    order = sorted(range(len(indices)), key=lambda k: (y['validity'][k] < .5, y['material'][k], -y['validity'][k], radii[indices[k]]))
    return [indices[k] for k in order], dict(status='predicted', model_sha256=model['sha256'],
        validity=y['validity'].tolist(), material_log_fraction=y['material'].tolist(), indices=indices)
