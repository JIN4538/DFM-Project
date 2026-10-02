"""Deep surrogate proposals, always remeasured by the geometry engine.

Two offline-trained multilayer perceptrons interpolate direction-dependent
height and downward projected-area sum from 26 measured views. The networks
select extra queries; they never supply measurements to a review report.
"""
from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
import hashlib
import inspect
import json
import math
from pathlib import Path
import time

import numpy as np

from .orientation import candidates, measure_orientation, unit_direction

ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = ROOT / "data/models/neural_orientation_external_v2.json"
SCHEMA = "dfm-neural-orientation-1"
BASE_NAMES = tuple(candidates(None, dense=True))
DEFAULT_POOL = 384
MAX_FACES = 100_000
MAX_PROPOSALS = 12


def fibonacci_directions(count=DEFAULT_POOL):
    """Deterministic equal-area sphere points, no random runtime state."""
    if not isinstance(count, int) or not 1 <= count <= 4096:
        raise ValueError("sphere candidate count must be between 1 and 4096")
    i = np.arange(count, dtype=float)
    z = 1 - 2 * (i + .5) / count
    phi = i * (math.pi * (3 - math.sqrt(5)))
    radius = np.sqrt(1 - z * z)
    return np.column_stack((radius * np.cos(phi), radius * np.sin(phi), z))


def proposal_pool(mesh, baseline_rows, count=DEFAULT_POOL):
    """Same sphere/facet pool is used by neural and comparison policies."""
    known = [unit_direction(r["direction"]) for r in baseline_rows
             if r.get("candidate_role", "search") == "search"]
    output, source = [], []
    normals = np.asarray(mesh.face_normals, dtype=float)
    keys, inverse = np.unique(np.round(normals, 6), axis=0, return_inverse=True)
    areas = np.bincount(inverse, weights=mesh.area_faces)
    face_options = [-normals[np.flatnonzero(inverse == k)[0]]
                    for k in np.argsort(-areas, kind="stable")[:24]]
    for direction, kind in [(d, "facet") for d in face_options] + [
            (d, "sphere") for d in fibonacci_directions(count)]:
        direction = unit_direction(direction)
        if any(float(np.dot(direction, d)) > 1 - 1e-10 for d in known + output):
            continue
        output.append(direction)
        source.append(kind)
    return np.asarray(output), source


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError("orientation measurement missing or invalid")
    return float(value)


def baseline_descriptor(mesh, rows, *, require_overhang=True):
    """Named 26 views only: the current direction must not alter proposals."""
    named = {r.get("name"): r for r in rows if r.get("candidate_role", "search") == "search"}
    options = candidates(None, dense=True)
    diagonal = float(np.linalg.norm(np.ptp(mesh.vertices, axis=0)))
    area = float(mesh.area)
    if not math.isfinite(diagonal) or diagonal <= 0 or not math.isfinite(area) or area <= 0:
        raise ValueError("nondegenerate finite geometry is required")
    heights, overhangs = [], []
    for name in BASE_NAMES:
        row = named.get(name)
        if row is None or not np.allclose(unit_direction(row["direction"]), options[name], rtol=0, atol=1e-12):
            raise ValueError("complete named 26-direction measurements are required")
        heights.append(_number(row.get("height_mm")) / diagonal)
        overhangs.append(_number(row.get("overhang_projected_area_sum_mm2")) / area if require_overhang else 0.)
    return dict(height=heights, overhang=overhangs, diagonal_mm=diagonal, area_mm2=area)


def feature_arrays(descriptor, directions, angle_deg=45.):
    directions = np.asarray(directions, dtype=float)
    if directions.ndim != 2 or directions.shape[1] != 3 or not np.isfinite(directions).all():
        raise ValueError("finite Nx3 directions are required")
    norms = np.linalg.norm(directions, axis=1)
    if np.any(norms <= 0):
        raise ValueError("zero direction is invalid")
    d = directions / norms[:, None]
    query = np.column_stack((d, d * d, d[:, 0] * d[:, 1], d[:, 1] * d[:, 2], d[:, 2] * d[:, 0]))
    h = np.broadcast_to(np.asarray(descriptor["height"], dtype=float), (len(d), 26))
    o = np.broadcast_to(np.asarray(descriptor["overhang"], dtype=float), (len(d), 26))
    return {"height": np.column_stack((h, query)),
            "overhang": np.column_stack((h, o, query, np.full(len(d), float(angle_deg) / 90.)))}


def feature_contract_sha256():
    """Bind normalization, input order, forward activation and output clipping."""
    source = "\n".join(inspect.getsource(fn) for fn in (baseline_descriptor, feature_arrays, predict_surrogates))
    return hashlib.sha256((SCHEMA + repr(BASE_NAMES) + source).encode("utf-8")).hexdigest()


@lru_cache(maxsize=4)
def _load_model(path, modified_ns, size, manifest_modified_ns, measurement_source_sha, feature_source_sha):
    path = Path(path)
    raw = path.read_bytes()
    manifest = json.loads(path.with_suffix(".manifest.json").read_text(encoding="utf-8"))
    digest = hashlib.sha256(raw).hexdigest()
    if digest != manifest.get("sha256"):
        raise ValueError("neural orientation model hash mismatch")
    data = json.loads(raw)
    if data.get("schema") != SCHEMA or tuple(data.get("base_names", ())) != BASE_NAMES:
        raise ValueError("neural orientation feature schema mismatch")
    if data.get("measurement_source_sha256") != measurement_source_sha:
        raise ValueError("neural orientation geometry engine version mismatch")
    if data.get("feature_contract_sha256") != feature_source_sha:
        raise ValueError("neural orientation feature contract mismatch")
    for name, input_size in (("height", 35), ("overhang", 62)):
        net = data["networks"][name]
        mean, scale = np.asarray(net["mean"]), np.asarray(net["scale"])
        if mean.shape != (input_size,) or scale.shape != (input_size,) or not np.isfinite(mean).all() or not np.isfinite(scale).all() or np.any(scale <= 0):
            raise ValueError("invalid neural scaler")
        weights = [np.asarray(w, dtype=float) for w in net["weights"]]
        biases = [np.asarray(b, dtype=float) for b in net["biases"]]
        if len(weights) < 3 or len(weights) != len(biases):
            raise ValueError("at least two hidden layers are required")
        width = input_size
        for w, b in zip(weights, biases):
            if w.ndim != 2 or w.shape[0] != width or b.shape != (w.shape[1],) or not np.isfinite(w).all() or not np.isfinite(b).all():
                raise ValueError("invalid neural tensor")
            width = w.shape[1]
        if width != 1:
            raise ValueError("invalid neural output")
        net.update(mean=mean, scale=scale, weights=weights, biases=biases)
    data["sha256"] = digest
    return data


def load_model(path=MODEL_PATH):
    path = Path(path)
    stat = path.stat()
    return _load_model(str(path.resolve()), stat.st_mtime_ns, stat.st_size,
                       path.with_suffix(".manifest.json").stat().st_mtime_ns,
                       hashlib.sha256((ROOT / "amdfm/orientation.py").read_bytes()).hexdigest(), feature_contract_sha256())


def predict_surrogates(model, descriptor, directions, angle_deg=45., *, height_only=False):
    arrays = feature_arrays(descriptor, directions, angle_deg)
    predictions = {}
    for name in (("height",) if height_only else ("height", "overhang")):
        net = model["networks"][name]
        x = (arrays[name] - net["mean"]) / net["scale"]
        for index, (weight, bias) in enumerate(zip(net["weights"], net["biases"])):
            x = x @ weight + bias
            if index < len(net["weights"]) - 1:
                x = np.maximum(x, 0.)
        if not np.isfinite(x).all():
            raise ValueError("nonfinite neural prediction")
        predictions[name] = np.clip(x[:, 0], 0., 1.)
    return predictions


def proposal_scores(predictions, descriptor, *, priority="balanced", height_only=False):
    fields = ("height",) if height_only else ("height", "overhang")
    regrets, weights = [], []
    for field in fields:
        values = np.asarray(descriptor[field], dtype=float)
        lo, hi = values.min(), values.max()
        # A nearly constant measured field does not supply a reliable scale.
        span = max(float(hi - lo), .05)
        regrets.append((predictions[field] - lo) / span)
        weights.append(3. if priority == ("support" if field == "overhang" else field) else 1.)
    values = np.asarray(regrets).T
    w = np.asarray(weights)
    return .7 * np.max(values * w / w.max(), axis=1) + .3 * (values @ w) / w.sum()


def choose_proposals(directions, scores, budget=MAX_PROPOSALS):
    """Rank the predicted objective, with 10-degree query diversity."""
    order = np.argsort(scores, kind="stable")
    selected = []
    cosine = math.cos(math.radians(10))
    for index in order:
        if all(float(np.dot(directions[index], directions[j])) < cosine for j in selected):
            selected.append(int(index))
        if len(selected) == budget:
            break
    if len(selected) < budget:
        selected.extend(int(i) for i in order if int(i) not in selected)
    return selected[:budget]


def hybrid_proposal_indices(directions, sources, scores, budget=MAX_PROPOSALS):
    """Reserve half the budget for real large facets, then learned search.

    Contact and bottom-face exclusion are discontinuous at true face normals;
    a smooth surrogate must not displace these cheap structural candidates.
    The deterministic seed is disclosed separately from learned proposals.
    """
    seeds = [i for i, source in enumerate(sources) if source == "facet"][:min(6, budget // 2)]
    remaining = [i for i in range(len(directions)) if i not in seeds]
    learned = choose_proposals(directions[remaining], np.asarray(scores)[remaining], budget - len(seeds))
    return seeds, [remaining[i] for i in learned]


def _update_pareto(rows, profile, reliable_normals):
    fields = ["height_mm"]
    if reliable_normals and profile.process != "PBF_POLYMER":
        fields.insert(0, "overhang_projected_area_sum_mm2")
    if reliable_normals and profile.process == "MEX":
        fields.append("contact_triangle_area_mm2")
    values = []
    for row in rows:
        try:
            value = np.array([-_number(row[k]) if k == "contact_triangle_area_mm2" else _number(row[k]) for k in fields])
        except (ValueError, KeyError):
            value = None
        values.append(value)
    for index, row in enumerate(rows):
        value = values[index]
        row["objectives"] = fields.copy()
        row["pareto"] = value is not None and row.get("build_fit") is not False and not any(
            other is not None and rows[j].get("build_fit") is not False
            and np.all(other <= value + 1e-8) and np.any(other < value - 1e-8)
            for j, other in enumerate(values))


def enrich_orientations(mesh, profile, baseline_rows, *, priority="balanced", max_proposals=MAX_PROPOSALS,
                        reliable_normals=True, model_path=MODEL_PATH, timeout_s=8., pool_size=DEFAULT_POOL):
    """Return original rows plus exact measured neural proposals and provenance.

    Errors/missing models leave original rows intact. The bounded per-direction
    measurement is not preempted mid-calculation; timeout is checked between
    measurements. Build-fit remains the geometry engine's True/False/None.
    """
    started = time.monotonic()
    rows = deepcopy(baseline_rows)
    metadata = dict(status="unavailable", method="deep-surrogate-proposal/exact-geometry-verification",
                    added_count=0, predicted_values_used_as_measurements=False, proposals=[],
                    targets=["height_mm", "overhang_projected_area_sum_mm2"],
                    contact_modelled=False, selection_priority=priority)
    result = dict(rows=rows, metadata=metadata)
    try:
        profile.validate()
        if type(max_proposals) is not int or not 0 <= max_proposals <= MAX_PROPOSALS:
            raise ValueError("proposal budget must be between 0 and 12")
        if not math.isfinite(timeout_s) or timeout_s < 0:
            raise ValueError("timeout must be finite and nonnegative")
        if max_proposals == 0 or timeout_s == 0:
            metadata.update(status="skipped", reason="탐색 예산이 0입니다")
            return result
        if len(mesh.faces) > MAX_FACES:
            raise ValueError("신경망 추가 탐색의 면 수 예산을 초과했습니다")
        height_only = profile.process == "PBF_POLYMER"
        if not height_only and not reliable_normals:
            raise ValueError("하향면 비교에 필요한 면 방향이 확정되지 않았습니다")
        if not height_only and not 25 <= profile.overhang_angle_deg <= 75:
            raise ValueError("신경망 탐색의 학습 각도 범위는 25°–75°입니다")
        descriptor = baseline_descriptor(mesh, rows, require_overhang=not height_only)
        model = load_model(model_path)
        directions, sources = proposal_pool(mesh, rows, count=pool_size)
        predictions = predict_surrogates(model, descriptor, directions, profile.overhang_angle_deg, height_only=height_only)
        scores = proposal_scores(predictions, descriptor, priority=priority, height_only=height_only)
        seeds, learned = hybrid_proposal_indices(directions, sources, scores, max_proposals)
        selected = seeds + learned
        metadata.update(model_id=model["model_id"], model_sha256=model["sha256"], candidate_pool_count=len(directions),
                        requested_count=max_proposals, facet_query_count=0, neural_query_count=0,
                        hidden_layers={name: [w.shape[1] for w in net["weights"][:-1]]
                                                                   for name, net in model["networks"].items()},
                        targets=["height_mm"] if height_only else metadata["targets"])
        names = {r.get("name") for r in rows}
        for index in selected:
            if time.monotonic() - started >= timeout_s:
                break
            measured = measure_orientation(mesh, directions[index], profile, reliable_normals=reliable_normals)
            measured.pop("overhang_face_indices", None)
            source = "geometric_facet_seed" if index in seeds else "deep_neural_surrogate"
            prefix = "면 탐색" if index in seeds else "AI 탐색"
            suffix = metadata["facet_query_count" if index in seeds else "neural_query_count"] + 1
            name = f"{prefix} {suffix}"
            while name in names:
                suffix += 1
                name = f"{prefix} {suffix}"
            names.add(name)
            measured.update(name=name, candidate_role="search", proposal_source=source,
                            neural_model_sha256=model["sha256"])
            predicted = {"height_mm": float(predictions["height"][index] * descriptor["diagonal_mm"])}
            if not height_only:
                predicted["overhang_projected_area_sum_mm2"] = float(predictions["overhang"][index] * descriptor["area_mm2"])
            metadata["proposals"].append(dict(name=name, direction=measured["direction"], pool_source=sources[index],
                                               selection_source=source,
                                               predicted=predicted, measured={key: measured[key] for key in predicted},
                                               build_fit=measured["build_fit"]))
            metadata["facet_query_count" if index in seeds else "neural_query_count"] += 1
            rows.append(measured)
        metadata.update(status="complete" if len(metadata["proposals"]) == len(selected) else "partial",
                        added_count=len(metadata["proposals"]), elapsed_s=time.monotonic() - started)
        if metadata["status"] == "partial":
            metadata["reason"] = "탐색 시간 예산 안에서 측정한 후보를 보존했습니다"
    except (OSError, ValueError, KeyError, TypeError, IndexError, OverflowError) as exc:
        metadata.update(status="partial" if metadata["proposals"] else "unavailable", added_count=len(metadata["proposals"]),
                        reason=str(exc), elapsed_s=time.monotonic() - started)
    if metadata["proposals"]:
        _update_pareto(rows, profile, reliable_normals)
    return result
