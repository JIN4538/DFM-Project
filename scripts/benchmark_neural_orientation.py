"""Bounded search benchmark; counts common baseline separately from additions."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import trimesh
from amdfm.neural_orientation import enrich_orientations, proposal_pool
from amdfm.orientation import compare_orientations, measure_orientation
from amdfm.profiles import Profile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("preserve previous benchmark records")
    meshes = [("rotated_thin_plate", trimesh.creation.box(extents=[40, 30, .3])),
              ("torus_3072_faces", trimesh.creation.torus(major_radius=20, minor_radius=4, major_sections=48, minor_sections=32)),
              ("ellipsoid_81920_faces", trimesh.creation.icosphere(subdivisions=6))]
    meshes[-1][1].apply_scale([35, 15, 6])
    profile = Profile()
    records = []
    for name, mesh in meshes:
        mesh.apply_transform(trimesh.transformations.euler_matrix(.37, .58, .21))
        started = time.perf_counter()
        rows = compare_orientations(mesh, profile, dense=True)
        baseline_s = time.perf_counter() - started
        started = time.perf_counter()
        enhanced = enrich_orientations(mesh, profile, rows, timeout_s=30)
        enhanced_s = time.perf_counter() - started
        directions, _ = proposal_pool(mesh, rows)
        started = time.perf_counter()
        for direction in directions:
            measure_orientation(mesh, direction, profile)
        dense_s = time.perf_counter() - started
        record = dict(case=name, face_count=len(mesh.faces), vertex_count=len(mesh.vertices),
                      geometry_sha256=hashlib.sha256(mesh.vertices.tobytes() + mesh.faces.tobytes()).hexdigest(),
                      common_26_measurement_s=baseline_s, hybrid_addition_s=enhanced_s,
                      all_pool_measurement_s=dense_s, all_pool_directions=len(directions),
                      measured_additions=enhanced["metadata"]["added_count"], status=enhanced["metadata"]["status"],
                      metadata=enhanced["metadata"])
        records.append(record)
        print(f"{name}: common26 {baseline_s:.3f}s, hybrid {enhanced_s:.3f}s, dense {dense_s:.3f}s", flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dict(note="single-run wall time in current environment; not a general performance guarantee",
                                          records=records), ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


if __name__ == "__main__":
    main()
