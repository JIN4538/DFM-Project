"""Research-only six-query selector; never supplies report measurements.

The frozen neural surrogate supplies downward-area estimates. Exact convex-hull
heights and plane contact are cheap acquisition features, not learned outputs.
An independently trained tree ensemble predicts candidate geometric-policy
regret. No product caller uses this experimental module.
"""
from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import numpy as np
from scipy.spatial import ConvexHull, QhullError, cKDTree
import trimesh

from .neural_orientation import predict_surrogates
from .orientation import CONTACT_NORMAL_COSINE, candidates

SCHEMA = "dfm-am-six-query-selector-1"
PROCESSES = ("MEX", "VPP", "PBF_POLYMER", "PBF_METAL")
PRIORITIES = ("balanced", "height", "support", "contact")
FEATURES = (tuple(f"height_{i}" for i in range(26))
    + tuple(f"overhang_{i}" for i in range(26))
    + ("dx", "dy", "dz", "dx2", "dy2", "dz2", "dxdy", "dydz", "dzdx",
       "exact_height", "exact_contact", "neural_height", "neural_overhang",
       "height_prediction_error", "nearest_similarity", "nearest_height",
       "nearest_overhang", "interpolated_overhang", "facet", "angle")
    + tuple(f"process_{p}" for p in PROCESSES)
    + tuple(f"priority_{p}" for p in PRIORITIES))


def directions_array(directions):
    d = np.asarray(directions, dtype=float)
    if d.ndim != 2 or d.shape[1] != 3 or not np.isfinite(d).all():
        raise ValueError("finite Nx3 directions required")
    norm = np.linalg.norm(d, axis=1)
    if np.any(norm <= 0):
        raise ValueError("zero direction")
    return d / norm[:, None]


def cheap_geometry(mesh, directions):
    """Exact original-mesh height/contact without scanning downward faces.

    The hull contains extrema of the original vertices. A normal-space tree
    limits plate tests to triangles within the runtime's contact angle. Feature
    cost (including hull construction) must be charged in every benchmark.
    """
    d = directions_array(directions)
    xyz = np.asarray(mesh.vertices)
    try:
        hull = xyz[ConvexHull(xyz).vertices]
    except QhullError:
        hull = xyz
    transforms = np.asarray([trimesh.geometry.align_vectors(v, [0., 0., 1.])[:3, :3] for v in d])
    projected = hull @ transforms.reshape(-1, 3).T
    low = projected.min(axis=0).reshape(-1, 3)
    dims = (projected.max(axis=0).reshape(-1, 3) - low)
    tolerance = np.maximum(1e-9, dims.max(axis=1)*1e-10)
    normals = np.asarray(mesh.face_normals)
    tree = cKDTree(normals)
    radius = np.sqrt(2*(1-CONTACT_NORMAL_COSINE))
    contacts = np.zeros(len(d))
    for i, nearby in enumerate(tree.query_ball_point(-d, radius)):
        indices = np.asarray(nearby, dtype=int)
        if not len(indices):
            continue
        nz = normals[indices] @ d[i]
        on_plate = (xyz[mesh.faces[indices]] @ d[i]).max(axis=1)-low[i, 2] <= tolerance[i]
        contacts[i] = mesh.area_faces[indices][on_plate & (nz < -CONTACT_NORMAL_COSINE)].sum()
    return dict(height=dims[:, 2]/np.linalg.norm(mesh.extents), contact=contacts/mesh.area,
                hull_vertices=len(hull), original_vertices=len(xyz))


def features(model, descriptor, directions, sources, geometry, process, priority, angle=45.):
    if process not in PROCESSES or priority not in PRIORITIES:
        raise ValueError("unsupported selector context")
    d = directions_array(directions)
    h, o = np.asarray(descriptor["height"]), np.asarray(descriptor["overhang"])
    predictions = predict_surrogates(model, descriptor, d, angle)
    base = np.asarray(list(candidates(None, dense=True).values()))
    dots = np.clip(d @ base.T, -1., 1.)
    near = np.argsort(-dots, axis=1, kind="stable")[:, :4]
    weights = 1/np.maximum(1e-4, 1-np.take_along_axis(dots, near, axis=1))
    weights /= weights.sum(axis=1, keepdims=True)
    query = np.column_stack((d, d*d, d[:, 0]*d[:, 1], d[:, 1]*d[:, 2], d[:, 2]*d[:, 0]))
    x = np.column_stack((np.broadcast_to(h, (len(d), 26)), np.broadcast_to(o, (len(d), 26)), query,
        geometry["height"], geometry["contact"], predictions["height"], predictions["overhang"],
        geometry["height"]-predictions["height"], dots[np.arange(len(d)), near[:, 0]], h[near[:, 0]],
        o[near[:, 0]], (o[near]*weights).sum(axis=1), np.array(sources)=="facet", np.full(len(d), angle/90),
        np.broadcast_to([float(process==p) for p in PROCESSES], (len(d), len(PROCESSES))),
        np.broadcast_to([float(priority==p) for p in PRIORITIES], (len(d), len(PRIORITIES)))))
    if x.shape[1] != len(FEATURES) or not np.isfinite(x).all():
        raise ValueError("invalid selector features")
    return x.astype("float32")


def objective_values(height, overhang, contact, process, priority):
    """Same declared worst/mean objective, normalized over a fixed union."""
    fields = [(np.asarray(height), "height", False)]
    if process != "PBF_POLYMER":
        fields.append((np.asarray(overhang), "support", False))
    if process == "MEX":
        fields.append((np.asarray(contact), "contact", True))
    components, weights = [], []
    for values, name, reverse in fields:
        lo, hi = float(values.min()), float(values.max())
        part = np.zeros(len(values)) if hi-lo <= max(1e-12, abs(hi)*1e-12) else (values-lo)/(hi-lo)
        if reverse and hi > lo:
            part = 1-part
        components.append(part)
        weights.append(3. if priority == name else 1.)
    c, w = np.asarray(components).T, np.asarray(weights)
    return .7*(c*w/w.max()).max(axis=1) + .3*(c@w)/w.sum()


def feature_sha256():
    source = "\n".join(inspect.getsource(fn) for fn in (directions_array, cheap_geometry, features, objective_values))
    return hashlib.sha256((repr(FEATURES)+source).encode()).hexdigest()


def portable_predict(tree_model, x):
    x = np.asarray(x, dtype="float32")
    values = np.full(len(x), tree_model["intercept"], dtype=float)
    for tree in tree_model["trees"]:
        nodes = np.asarray(tree, dtype=float)
        current = np.zeros(len(x), dtype=int)
        for _ in range(len(nodes)):
            rows = nodes[current]
            active = rows[:, 0] != -2
            if not active.any():
                break
            r = rows[active]
            current[active] = np.where(x[active, r[:, 0].astype(int)] <= r[:, 1], r[:, 2], r[:, 3]).astype(int)
        values += nodes[current, 4]
    return values


def load_selector(path):
    path = Path(path)
    raw = path.read_bytes()
    manifest = json.loads(path.with_suffix(".manifest.json").read_text())
    if hashlib.sha256(raw).hexdigest() != manifest["sha256"]:
        raise ValueError("selector checksum mismatch")
    model = json.loads(raw)
    if model["schema"] != SCHEMA or tuple(model["features"]) != FEATURES or model["feature_sha256"] != feature_sha256():
        raise ValueError("selector feature contract mismatch")
    return model


def predictions(model, x):
    values = np.asarray([portable_predict(member, x) for member in model["members"]])
    return values.mean(axis=0), values.std(axis=0)


def select_indices(directions, mean, uncertainty=None, *, budget=6, exploration=0., diversity_deg=8.):
    """Lower confidence bound exploration; all selected views need remeasurement."""
    d = directions_array(directions)
    if isinstance(budget, bool) or not isinstance(budget, int) or not 1 <= budget <= 12:
        raise ValueError("query budget must be 1 to 12")
    if not np.isfinite(exploration) or exploration < 0:
        raise ValueError("nonnegative finite exploration required")
    scores = np.asarray(mean, dtype=float)
    if uncertainty is not None:
        spread = np.asarray(uncertainty, dtype=float)
        if spread.shape != (len(d),) or not np.isfinite(spread).all() or np.any(spread < 0):
            raise ValueError("nonnegative per-candidate uncertainty required")
        scores = scores-exploration*spread
    if scores.shape != (len(d),) or not np.isfinite(scores).all():
        raise ValueError("finite per-candidate scores required")
    order = np.argsort(scores, kind="stable")
    chosen = []
    for i in order:
        if all(d[i]@d[j] < np.cos(np.deg2rad(diversity_deg)) for j in chosen):
            chosen.append(int(i))
        if len(chosen) == budget:
            break
    if len(chosen) < budget:
        chosen += [int(i) for i in order if int(i) not in chosen][:budget-len(chosen)]
    return chosen
