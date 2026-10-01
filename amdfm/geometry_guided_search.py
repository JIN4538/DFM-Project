"""Optional acquisition API for the frozen exact-height/neural-area experiment.

This does not replace final geometry measurements or product selection. The
caller retains already measured 26+18 rows, supplies its common sphere/facet/
continuous candidate pool, and remeasures each returned direction. Unsupported
scope returns None so the caller can retain its established proposal policy.
"""
from __future__ import annotations

import time
import numpy as np

from .neural_orientation import predict_surrogates, MAX_FACES
from .proposal_selector import cheap_geometry, directions_array, objective_values, select_indices

FROZEN_NEURAL_SHA256 = "68ec8e2b1fd7c4ce13cc3ee669f75c2d6e91e599fdb095e0e6c93ef4e52ccd64"
EVALUATED_CONDITIONS = {("MEX", "balanced"), ("MEX", "support"), ("VPP", "balanced"),
                        ("PBF_METAL", "balanced"), ("PBF_POLYMER", "height")}


def rank_geometry_guided_queries(mesh, model, descriptor, directions, profile, *, priority="balanced", budget=6, deadline=None, reliable_normals=True):
    """Return six exact-acquisition/learned-area choices, or None outside scope.

    The optional deadline uses time.monotonic. Whole-array hull and normal-tree
    calls cannot be interrupted midway; checks before/after prevent emitting
    late choices. Callers must also enforce their deadline during remeasurement.
    All candidate-construction time remains the caller's responsibility.
    """
    if ((profile.process, priority) not in EVALUATED_CONDITIONS or abs(float(profile.overhang_angle_deg)-45.) > 1e-12
            or profile.build_volume_mm is not None
            or model.get("sha256") != FROZEN_NEURAL_SHA256 or len(mesh.faces) > MAX_FACES):
        return None
    if not reliable_normals or not mesh.is_volume:
        return None
    if (not np.isclose(descriptor.get("diagonal_mm", np.nan), np.linalg.norm(mesh.extents), rtol=1e-9, atol=1e-12)
            or not np.isclose(descriptor.get("area_mm2", np.nan), mesh.area, rtol=1e-9, atol=1e-12)):
        return None
    if budget != 6:
        return None
    if deadline is not None and time.monotonic() >= deadline:
        return None
    started = time.perf_counter()
    d = directions_array(directions)
    if len(d) < budget:
        return None
    geometry = cheap_geometry(mesh, d)
    geometry_seconds = time.perf_counter()-started
    if deadline is not None and time.monotonic() >= deadline:
        return None
    inference_start = time.perf_counter()
    height_only = profile.process == "PBF_POLYMER"
    if height_only:
        # The height-only process has no learned choice once height is exact.
        overhang = None
    else:
        overhang = predict_surrogates(model, descriptor, d, 45.)["overhang"]
    scores = objective_values(geometry["height"], np.zeros(len(d)) if overhang is None else overhang,
                             geometry["contact"], profile.process, priority)
    indices = select_indices(d, scores, budget=budget)
    if deadline is not None and time.monotonic() >= deadline:
        return None
    return dict(indices=indices, directions=d[indices].tolist(),
        exact_height_mm=(geometry["height"][indices]*descriptor["diagonal_mm"]).tolist(),
        exact_contact_triangle_area_mm2=(geometry["contact"][indices]*descriptor["area_mm2"]).tolist(),
        neural_overhang_projected_area_sum_mm2=None if overhang is None else (overhang[indices]*descriptor["area_mm2"]).tolist(),
        scores=scores[indices].tolist(), candidate_count=len(d), requested_full_queries=budget,
        geometry_seconds=geometry_seconds, inference_seconds=time.perf_counter()-inference_start,
        geometry_neural_model_sha256=FROZEN_NEURAL_SHA256,
        policy="exact original-mesh height/contact + frozen neural downward-area; 8-degree query diversity",
        learned_component=None if height_only else "downward projected-area acquisition only")
