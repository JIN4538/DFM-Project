"""Geometric trade-offs for a finite, explicit candidate set. No success score."""
from __future__ import annotations

from itertools import product

import numpy as np
import trimesh

from .profiles import Profile

DIRECTIONS = {"+Z": (0, 0, 1), "-Z": (0, 0, -1), "+X": (1, 0, 0),
              "-X": (-1, 0, 0), "+Y": (0, 1, 0), "-Y": (0, -1, 0)}

# Numerical boundary policies, not manufacturing tolerances or printer limits.
ANGLE_COSINE_TOLERANCE = 1e-12
CONTACT_NORMAL_COSINE = .999999


def unit_direction(direction):
    d = np.asarray(direction, dtype=float)
    if d.shape != (3,) or not np.isfinite(d).all() or not np.any(d):
        raise ValueError("적층 방향은 0이 아닌 유한한 3차원 벡터여야 합니다.")
    # Scale first: a finite vector can overflow/underflow a direct L2 norm.
    d = d / np.max(np.abs(d))
    return d / np.linalg.norm(d)


def direction_from_angles(tilt_deg, azimuth_deg):
    """Model-space build axis: polar tilt from +Z, azimuth +X toward +Y."""
    if not np.isfinite([tilt_deg, azimuth_deg]).all() or not 0 <= tilt_deg <= 180 or not 0 <= azimuth_deg <= 360:
        raise ValueError("기울기는 0~180°, 방위각은 0~360°의 유한한 값이어야 합니다.")
    if tilt_deg in (0, 180):
        return np.array([0., 0., 1. if tilt_deg == 0 else -1.])
    t, a = np.deg2rad([tilt_deg, azimuth_deg])
    # Preserve exactly axial directions, without rounding away small real tilts.
    st, ct = (1., 0.) if tilt_deg == 90 else (np.sin(t), np.cos(t))
    ca, sa = {0: (1., 0.), 90: (0., 1.), 180: (-1., 0.), 270: (0., -1.)}.get(
        azimuth_deg % 360, (np.cos(a), np.sin(a)))
    return unit_direction([st*ca, st*sa, ct])


def direction_angles(direction):
    d = unit_direction(direction)
    tilt = np.rad2deg(np.arctan2(np.hypot(d[0], d[1]), d[2]))
    azimuth = np.rad2deg(np.arctan2(d[1], d[0])) % 360 if np.any(d[:2]) else 0.
    return float(tilt), float(azimuth)


def placement(mesh, direction):
    d = unit_direction(direction)
    matrix = trimesh.geometry.align_vectors(d, [0., 0., 1.])
    xyz = mesh.vertices @ matrix[:3, :3].T
    # Place the lowest geometry on z=0 and center x/y, without changing its scale.
    translation = np.array([-(xyz[:, 0].min()+xyz[:, 0].max())/2,
                            -(xyz[:, 1].min()+xyz[:, 1].max())/2, -xyz[:, 2].min()])
    matrix[:3, 3] = translation
    return xyz + translation, matrix


def measure_orientation(mesh, direction, profile: Profile, *, reliable_normals=True):
    """Measure triangle geometry; neither contact nor projection is a toolpath.

    Contact sums nearly coplanar bottom facets within the reported numerical
    tolerances. A genuinely tilted plane has only point/line contact with z=0.
    The excluded bottom-touching facets and angle boundary band are reported
    separately without enlarging contact or silently changing the strict rule.
    """
    profile.validate()
    d = unit_direction(direction)
    xyz, matrix = placement(mesh, d)
    dims = np.ptp(xyz, axis=0)
    face_heights = xyz[:, 2][mesh.faces]
    zmax = face_heights.max(axis=1)
    tol = max(1e-9, np.max(dims)*1e-10)
    on_plate = zmax <= tol
    nz = mesh.face_normals @ d
    cosine_threshold = np.cos(np.deg2rad(profile.overhang_angle_deg))
    angle_mask = (nz < -cosine_threshold-ANGLE_COSINE_TOLERANCE) & ~on_plate
    threshold_equal = ((nz >= -cosine_threshold-ANGLE_COSINE_TOLERANCE)
                       & (nz <= -cosine_threshold+ANGLE_COSINE_TOLERANCE)
                       & (nz < 0) & ~on_plate)
    if not reliable_normals:
        angle_mask[:] = False
    use_overhang = reliable_normals and profile.process != "PBF_POLYMER"
    contact_mask = on_plate & (nz < -CONTACT_NORMAL_COSINE)
    contact = float(mesh.area_faces[contact_mask].sum()) if reliable_normals else None
    # A vertex on the plate does not establish a finite contact patch. This
    # diagnostic explains zero contact for slightly tilted or noisy bottoms.
    bottom_nonplanar = (face_heights.min(axis=1) <= tol) & (nz < 0) & ~contact_mask
    bottom_min_tilt = None
    bottom_max_height = None
    if reliable_normals and np.any(bottom_nonplanar):
        selected_normals = mesh.face_normals[bottom_nonplanar]
        # atan2 preserves very small tilts that arccos(dot) can round to zero.
        tilt_angles = np.rad2deg(np.arctan2(np.linalg.norm(np.cross(selected_normals, d), axis=1),
                                         -nz[bottom_nonplanar]))
        bottom_min_tilt = float(tilt_angles.min())
        bottom_max_height = float(zmax[bottom_nonplanar].max())
    # Fit the placed AABB, allowing only an extra 90 degree build-plane yaw.
    fit, utilization, yaw, required = None, None, 0, dims.copy()
    if profile.build_volume_mm:
        available = np.asarray(profile.build_volume_mm)-2*profile.clearance_mm
        alternatives = [(float(np.max(dims/available)), 0, dims),
                        (float(np.max(dims[[1,0,2]]/available)), 90, dims[[1,0,2]])]
        utilization, yaw, required = min(alternatives, key=lambda x:x[0])
        fit = bool(np.all(required <= available + tol))
    # Include yaw in the actual transform, so exported geometry and fit agree.
    if yaw:
        rz = trimesh.transformations.rotation_matrix(np.pi/2, [0,0,1])
        matrix = rz @ matrix
    tilt, azimuth = direction_angles(d)
    return dict(direction=d.tolist(), tilt_deg=tilt, azimuth_deg=azimuth, height_mm=float(dims[2]),
        extents_mm=dims.tolist(), placed_extents_mm=required.tolist(), xy_yaw_deg=yaw,
        transform=matrix.tolist(), build_fit=fit, max_axis_utilization=utilization,
        contact_triangle_area_mm2=contact,
        contact_plate_tolerance_mm=float(tol),
        contact_normal_max_tilt_deg=float(np.rad2deg(np.arccos(CONTACT_NORMAL_COSINE))),
        contact_nonplanar_bottom_face_count=int(bottom_nonplanar.sum()) if reliable_normals else None,
        contact_nonplanar_bottom_min_tilt_deg=bottom_min_tilt,
        contact_nonplanar_bottom_max_height_mm=bottom_max_height,
        contact_scope="bottom triangle surface-area sum within numerical plane/normal tolerances; not first-layer area or adhesion; tilted point/line contact has zero area",
        overhang_surface_area_mm2=float(mesh.area_faces[angle_mask].sum()) if use_overhang else None,
        overhang_projected_area_sum_mm2=float((mesh.area_faces[angle_mask]*(-nz[angle_mask])).sum()) if use_overhang else None,
        overhang_face_indices=np.flatnonzero(angle_mask).tolist() if use_overhang else [],
        overhang_angle_deg=profile.overhang_angle_deg,
        overhang_threshold_equal_face_count=int(threshold_equal.sum()) if use_overhang else None,
        overhang_threshold_equal_surface_area_mm2=float(mesh.area_faces[threshold_equal].sum()) if use_overhang else None,
        overhang_threshold_equal_projected_area_sum_mm2=float((mesh.area_faces[threshold_equal]*(-nz[threshold_equal])).sum()) if use_overhang else None,
        overhang_threshold_cosine_tolerance=ANGLE_COSINE_TOLERANCE,
        overhang_threshold_comparator="nz < -cos(angle_deg) - cosine_tolerance; equality band excluded",
        overhang_threshold_equal_angle_range_deg=np.rad2deg(np.arccos(np.clip(
            [cosine_threshold+ANGLE_COSINE_TOLERANCE, cosine_threshold-ANGLE_COSINE_TOLERANCE], -1, 1))).tolist(),
        overhang_scope="down-facing facets strictly below horizontal angle outside numerical boundary band; plate excluded; projected area is a sum including overlaps, not a union; no bridge exemption or support generation")


def candidates(mesh, include_face_normals=False, *, dense=False):
    result = dict(DIRECTIONS)
    if dense:
        for d in product((-1, 0, 1), repeat=3):
            if np.count_nonzero(d) < 2:
                continue
            name = "".join(("+" if v > 0 else "-")+axis for axis, v in zip("XYZ", d) if v)
            result[name] = tuple(unit_direction(d))
    if include_face_normals:
        # Area-aggregate coarsely equivalent normals, then use an actual normal.
        keys, inverse = np.unique(np.round(mesh.face_normals, 3), axis=0, return_inverse=True)
        areas = np.bincount(inverse, weights=mesh.area_faces)
        added = 0
        for k in np.argsort(-areas):
            d = -mesh.face_normals[np.flatnonzero(inverse == k)[0]]
            if np.linalg.norm(d) < .5 or any(np.dot(d, unit_direction(v)) > .9999 for v in result.values()):
                continue
            added += 1
            result[f"면 방향 {added}"] = tuple(float(x) for x in d)
            if added >= 6:
                break
    return result


def compare_orientations(mesh, profile, *, reliable_normals=True, extended=False, dense=False, current_direction=None):
    rows = []
    options = candidates(mesh, extended, dense=dense)
    if current_direction is not None:
        d = unit_direction(current_direction)
        if not any(np.array_equal(d, unit_direction(v)) for v in options.values()):
            options["현재 지정 방향"] = d
    for name, direction in options.items():
        row = measure_orientation(mesh, direction, profile, reliable_normals=reliable_normals)
        row.pop("overhang_face_indices")
        row["name"] = name
        rows.append(row)
    eligible = [i for i,r in enumerate(rows) if r["build_fit"] is not False]
    keys = ["height_mm"]
    if reliable_normals and profile.process != "PBF_POLYMER":
        keys.insert(0, "overhang_projected_area_sum_mm2")
    # MEX benefits from a geometric contact proxy, without inferring adhesion.
    if reliable_normals and profile.process == "MEX":
        keys.append("contact_triangle_area_mm2")
    objective = lambda r: np.array([-r[k] if k=="contact_triangle_area_mm2" else r[k] for k in keys])
    for i,row in enumerate(rows):
        a = objective(row)
        row["pareto"] = i in eligible and not any(
            np.all(objective(rows[j]) <= a+1e-8) and np.any(objective(rows[j]) < a-1e-8)
            for j in eligible if j != i)
        row["objectives"] = keys
    return rows
