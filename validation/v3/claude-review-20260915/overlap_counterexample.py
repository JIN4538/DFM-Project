"""Reproduce a limitation of reviewed commit ae2a868; prints JSON, edits no input.

The volume oracle clips two XZ rectangles by half-planes using elementary
arithmetic, then multiplies overlap area by their common 10 mm Y depth.
It does not reuse section_mesh, Shapely, or a 3D Boolean operation.
Run from the repository root with the supported Python environment.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import subprocess
import sys
import types

import numpy as np
import trimesh


BASELINE = "ae2a86895b4a3885606e782aaf71741c82816efe"
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


def clip(polygon, axis, boundary, keep_greater):
    result = []
    for start, end in zip(polygon, polygon[1:] + polygon[:1]):
        inside_start = start[axis] >= boundary if keep_greater else start[axis] <= boundary
        inside_end = end[axis] >= boundary if keep_greater else end[axis] <= boundary
        if inside_start != inside_end:
            fraction = (boundary - start[axis]) / (end[axis] - start[axis])
            result.append(tuple(a + fraction * (b - a) for a, b in zip(start, end)))
        if inside_end:
            result.append(end)
    return result


def main():
    baseline_source = subprocess.check_output(
        ["git", "show", f"{BASELINE}:amdfm/event_sections.py"], cwd=ROOT
    )
    module = types.ModuleType("reviewed_event_sections")
    exec(compile(baseline_source.decode("utf-8"), "reviewed_event_sections.py", "exec"), module.__dict__)
    angle = .5
    first = trimesh.creation.box([10., 10., 10.])
    second = trimesh.creation.box([10., 10., 10.])
    second.apply_transform(trimesh.transformations.rotation_matrix(angle, [0., 1., 0.]))
    second.apply_translation([1., 0., 1.])
    combined = trimesh.util.concatenate([first, second])
    measurement = module.inspect_event_sections(combined)

    c, s = math.cos(angle), math.sin(angle)
    overlap = [(c*x+s*z+1., -s*x+c*z+1.) for x, z in
               [(-5., -5.), (5., -5.), (5., 5.), (-5., 5.)]]
    for axis, boundary, greater in [(0, -5., True), (0, 5., False),
                                     (1, -5., True), (1, 5., False)]:
        overlap = clip(overlap, axis, boundary, greater)
    area = abs(math.fsum(a[0]*b[1]-b[0]*a[1]
                        for a, b in zip(overlap, overlap[1:]+overlap[:1])))/2
    expected = 2*1000. - area*10.
    estimated = measurement["volume_quadrature_estimate_mm3"]
    from amdfm.io import load_model
    from amdfm.detail import run_detail
    from amdfm.profiles import Profile
    imported = load_model(combined.export(file_type="stl"), "overlapping_cubes.stl",
                          unit="mm", dimensions_confirmed=True)
    guarded = run_detail(imported, Profile(), mode="sections", sampling="events")
    result = {
        "purpose": "Counterexample to generalizing one overlapping-body success into a union-volume guarantee.",
        "reviewed_commit": BASELINE,
        "baseline_event_sections_sha256": hashlib.sha256(baseline_source).hexdigest(),
        "environment": {"python": sys.version, **{key: importlib.metadata.version(key)
                          for key in ["numpy", "trimesh", "shapely"]}},
        "input": {"cube_extents_mm": [10., 10., 10.], "second_rotation_y_radians": angle,
                  "second_translation_mm": [1., 0., 1.], "assembly": "concatenated boundary shells; not Boolean union"},
        "oracle": "Sutherland-Hodgman clipping in XZ, shoelace overlap area, common Y depth 10 mm",
        "overlap_polygon_xz_mm": overlap,
        "overlap_area_xz_mm2": area,
        "expected_union_volume_mm3": expected,
        "baseline_status": measurement["status"],
        "baseline_topology_ready": measurement["input_diagnostics"]["topology_ready"],
        "baseline_event_heights_mm": sorted(set(combined.vertices[:, 2].tolist())),
        "baseline_quadrature_volume_mm3": estimated,
        "baseline_omitted_height_envelope_mm3": measurement["omitted_interval_volume_envelope_mm3"],
        "relative_difference_percent": (estimated-expected)/expected*100,
        "user_entry_check": {
            "scope": "Current load_model and run_detail; the assembly guard also exists in the reviewed commit.",
            "surface_component_count": imported.metadata["surface_component_count"],
            "status": guarded["status"], "reason": guarded.get("reason"),
            "volume_quadrature_estimate_mm3": guarded.get("volume_quadrature_estimate_mm3"),
            "source_sha256": {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
                              for name in ["amdfm/io.py", "amdfm/detail.py", "amdfm/detail_worker.py"]},
        },
        "limitation": "The oracle is floating-point analytic polygon arithmetic, not an exact-real certificate. The observed difference is orders of magnitude larger than coordinate rounding. Only the reviewed event module is loaded from Git; section dependencies are the repository version.",
    }
    assert result["baseline_status"] == "complete"
    assert abs(result["relative_difference_percent"]) > .1
    assert guarded["status"] == "unknown"
    assert "겹침" in guarded.get("reason", "")
    assert guarded.get("volume_quadrature_estimate_mm3") is None
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
