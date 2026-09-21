"""Bounded point visibility along a fixed tool approach axis.

This is a necessary geometric screen, not a finite cutter, holder, stock or
fixture collision test. A direction points FROM a surface TOWARD the incoming
tool. No manufacturing limits or empirical success probabilities are used.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time

import numpy as np
import trimesh

from src.core.mesh_diagnostics import inspect_mesh


_STATES = ("visible", "occluded", "back_facing", "tangent", "unknown")
_LIMITATIONS = [
    "표면에서 지정 방향으로 뻗은 점·직선의 차폐 검사입니다. 실제 공구의 지름·날·홀더 충돌은 계산하지 않습니다.",
    "선택한 삼각형 내부의 한 점만 검사합니다. 표본 밖 영역과 같은 면 내부의 다른 위치를 보장하지 않습니다.",
    "면적 가중 비율은 선택한 표본에 한정되며, 전체 가공 가능 면적률이나 제조 성공 확률이 아닙니다.",
    "축과 평행한 면은 접선 상태로 분리합니다. 이 결과만으로 측면 밀링 가능 여부를 결정하지 않습니다.",
    "소재·고정구·공정 순서·공구 강성·공차·표면 품질과 모든 자기교차를 검사하지 않습니다.",
]


def _integer(value, name, minimum, maximum):
    if isinstance(value, (bool, np.bool_)) or not np.isscalar(value):
        raise ValueError(f"{name} must be an integer in [{minimum}, {maximum}]")
    try:
        valid = np.isfinite(value) and int(value) == value and minimum <= value <= maximum
    except (TypeError, ValueError, OverflowError):
        valid = False
    if not valid:
        raise ValueError(f"{name} must be an integer in [{minimum}, {maximum}]")
    return int(value)


def _parameters(direction, max_samples, max_faces, max_ray_triangle_tests, timeout_s):
    try:
        d = np.asarray(direction, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError("direction must contain three finite numbers") from exc
    if d.shape != (3,) or not np.isfinite(d).all() or not np.any(d):
        raise ValueError("direction must be a nonzero finite 3-vector")
    d = d / np.max(np.abs(d))
    d /= np.linalg.norm(d)
    if isinstance(timeout_s, (bool, np.bool_)):
        raise ValueError("timeout_s must be finite and greater than zero")
    try:
        timeout = float(timeout_s)
    except (TypeError, ValueError) as exc:
        raise ValueError("timeout_s must be finite and greater than zero") from exc
    if not np.isfinite(timeout) or not 0 < timeout <= 300:
        raise ValueError("timeout_s must be in (0, 300]")
    return (d, _integer(max_samples, "max_samples", 1, 4096),
            _integer(max_faces, "max_faces", 4, 500000),
            _integer(max_ray_triangle_tests, "max_ray_triangle_tests", 1, 100000000), timeout)


def _result(direction, max_samples, max_faces, max_tests, timeout):
    return {
        "status": "unknown", "method": "point_visibility", "direction": direction.tolist(),
        "direction_convention": "surface_toward_incoming_tool", "coordinate_frame": "model_mm",
        "reason": "", "reasons": [], "diagnostics": {}, "samples": [],
        "scope": "deterministic_triangle_interior_samples_and_straight_rays_only",
        "limitations": list(_LIMITATIONS),
        "budget": {"max_samples": max_samples, "max_faces": max_faces,
                   "max_ray_triangle_tests": max_tests, "timeout_s": timeout},
        "measurements": {"requested_samples": 0, "selected_samples": 0,
            "evaluated_samples": 0, "ray_triangle_tests": 0,
            "sampled_face_area_fraction": None, "area_weighted_sample_fractions": None,
            "omitted_face_count": None, "omitted_face_area_mm2": None},
        **{f"{state}_face_indices": [] for state in _STATES},
    }


def _unknown(result, code, reason):
    result.update(reason=reason, reasons=[code])
    return result


def _coplanar_ahead(point, direction, triangles, tolerance):
    """Whether the ray touches a coplanar triangle in front of its origin.

    Clip affine barycentric coordinates against all three triangle edges. This
    prevents an ignored parallel triangle from turning a grazing ray into clear.
    """
    if not len(triangles):
        return False
    e1, e2 = triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0]
    relative = point - triangles[:, 0]
    aa, bb, cc = (np.einsum("ij,ij->i", a, b) for a, b in ((e1, e1), (e1, e2), (e2, e2)))
    determinant = aa * cc - bb * bb
    safe = determinant > np.finfo(float).tiny
    if not np.all(safe):
        # A numerically collapsed coplanar triangle may still touch the ray;
        # it must not disappear just because another triangle is resolvable.
        return True
    aa, bb, cc, determinant = aa[safe], bb[safe], cc[safe], determinant[safe]
    e1, e2, relative = e1[safe], e2[safe], relative[safe]
    rp, rq = np.einsum("ij,ij->i", relative, e1), np.einsum("ij,ij->i", relative, e2)
    dp, dq = e1 @ direction, e2 @ direction
    u, v = (cc * rp - bb * rq) / determinant, (aa * rq - bb * rp) / determinant
    du, dv = (cc * dp - bb * dq) / determinant, (aa * dq - bb * dp) / determinant
    lower, upper = np.full(len(u), tolerance), np.full(len(u), np.inf)
    valid = np.ones(len(u), dtype=bool)
    for value, slope in ((u, du), (v, dv), (1 - u - v, -du - dv)):
        flat = np.abs(slope) < 1e-14
        valid &= ~flat | (value >= -tolerance)
        crossing = np.divide(-tolerance - value, slope, out=np.zeros_like(value), where=~flat)
        lower = np.where(slope > 1e-14, np.maximum(lower, crossing), lower)
        upper = np.where(slope < -1e-14, np.minimum(upper, crossing), upper)
    return bool(np.any(valid & (upper >= lower)))


def _ray(point, source, direction, triangles, normals, *,
         remaining_tests, deadline, tolerance, angular_tolerance):
    """Read-only, chunked two-sided intersections; no potentially skipping offset."""
    tested, boundary = 0, False
    for start in range(0, len(triangles), 2048):
        stop = min(start + 2048, len(triangles))
        if time.perf_counter() >= deadline:
            return "unknown", None, None, tested, "time_budget_exceeded"
        if tested + stop - start > remaining_tests:
            return "unknown", None, None, tested, "ray_budget_exceeded"
        tri = triangles[start:stop]
        tested += len(tri)
        e1, e2 = tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
        p = np.cross(direction, e2)
        det = np.einsum("ij,ij->i", e1, p)
        relative = point - tri[:, 0]
        parallel = np.abs(normals[start:stop] @ direction) <= angular_tolerance
        usable = ~parallel
        inv = np.divide(1., det, out=np.zeros_like(det), where=usable)
        u = np.einsum("ij,ij->i", relative, p) * inv
        q = np.cross(relative, e1)
        v = (q @ direction) * inv
        distance = np.einsum("ij,ij->i", e2, q) * inv
        other = np.arange(start, stop) != source
        intersects = other & usable & (u >= -tolerance) & (v >= -tolerance) & (u + v <= 1 + tolerance)
        ahead = intersects & (distance > tolerance)
        interior = ahead & (u > tolerance) & (v > tolerance) & (u + v < 1 - tolerance)
        if np.any(interior):
            candidates = np.flatnonzero(interior)
            hit = candidates[np.argmin(distance[candidates])]
            # This witnessed obstruction proves blockage; it need not be the
            # nearest obstruction in not-yet-visited chunks.
            return "occluded", int(start + hit), float(distance[hit]), tested, None
        boundary |= bool(np.any(ahead) or np.any(intersects & (np.abs(distance) <= tolerance)))
        plane_distance = np.abs(np.einsum("ij,ij->i", relative, normals[start:stop]))
        coplanar = other & parallel & (plane_distance <= tolerance)
        if _coplanar_ahead(point, direction, tri[coplanar], tolerance):
            boundary = True
    if boundary:
        return "unknown", None, None, tested, "grazing_or_near_surface_intersection"
    return "visible", None, None, tested, None


def inspect_point_visibility(mesh, direction=(0, 0, 1), *, max_samples=512,
                             max_faces=200000, max_ray_triangle_tests=20000000,
                             timeout_s=5.0):
    """Inspect sampled point visibility; use ``run_point_visibility`` in the UI.

    ``complete`` means every selected point was classified, NOT that all surfaces
    are visible or machinable. ``tangent`` is a known angular classification but
    leaves side milling undecided. Unknown rows and omitted faces stay explicit.
    The deadline is cooperative; the wrapper supplies a hard process timeout.
    """
    started = time.perf_counter()
    d, max_samples, max_faces, max_tests, timeout = _parameters(
        direction, max_samples, max_faces, max_ray_triangle_tests, timeout_s)
    result = _result(d, max_samples, max_faces, max_tests, timeout)
    deadline = started + timeout
    if not isinstance(mesh, trimesh.Trimesh):
        return _unknown(result, "not_triangle_mesh", "단일 삼각형 메시가 필요합니다.")
    if len(mesh.faces) > max_faces:
        result["measurements"]["omitted_face_count"] = len(mesh.faces)
        return _unknown(result, "face_budget_exceeded", "면 개수가 계산 한도를 넘어 접근 차폐 검토를 보류했습니다.")
    if len(mesh.vertices) > max_faces * 3:
        return _unknown(result, "vertex_budget_exceeded", "정점 개수가 계산 한도를 넘어 접근 차폐 검토를 보류했습니다.")
    try:
        diagnostic = inspect_mesh(mesh)
        result["diagnostics"] = diagnostic
        if not diagnostic["topology_ready"]:
            return _unknown(result, "invalid_mesh", "닫힘·면 방향·중복·퇴화 조건을 충족하지 않아 재료 안팎을 확정하지 않습니다.")
        components = trimesh.graph.connected_component_labels(mesh.face_adjacency, node_count=len(mesh.faces))
        shell_count = len(np.unique(components))
        diagnostic["surface_component_count"] = shell_count
        if shell_count != 1:
            return _unknown(result, "multiple_surface_components",
                "여러 표면 껍질의 재료·공동·교차 관계를 이 검사에서 확정하지 않습니다. 단일 연결 솔리드로 검토하세요.")
        areas = np.asarray(mesh.area_faces, dtype=float)
        total_area = float(areas.sum())
        nf = len(areas)
        requested = min(nf, max_samples)
        if nf <= max_samples:
            selected = np.arange(nf)
        else:
            # Deterministic area-stratified selection. The reported fractions
            # use ONLY actual areas of selected faces, never imputed whole-part
            # area or a fabricated probability for unsampled triangles.
            selected = np.unique(np.searchsorted(np.cumsum(areas),
                (np.arange(requested) + .5) * total_area / requested))
        scale = float(np.max(mesh.extents))
        offset = np.asarray(mesh.bounds[0], dtype=float)
        vertices = (np.asarray(mesh.vertices) - offset) / scale
        triangles = vertices[np.asarray(mesh.faces)]
        cross = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
        double_areas = np.linalg.norm(cross, axis=1)
        if np.any(double_areas <= np.finfo(float).tiny) or not np.isfinite(double_areas).all():
            return _unknown(result, "unresolved_numeric_scale", "수치 해상도에서 안정적인 삼각형 법선을 계산하지 못했습니다.")
        normals = cross / double_areas[:, None]
        # Normalization avoids scale-dependent ray epsilon and translation
        # cancellation during intersection calculations. This is a numeric
        # tolerance, not a machining clearance or manufacturing threshold.
        tolerance, angular_tolerance = 1e-10, 1e-10
        result["numerical_policy"] = {"length_tolerance_mm": tolerance * scale,
            "angular_dot_tolerance": angular_tolerance, "source_offset_mm": 0.,
            "obstruction_distance": "witnessed_intersection_not_guaranteed_nearest"}
        rows, tests, reasons = [], 0, set()
        for face in selected:
            point = triangles[face].mean(axis=0)
            dot = float(normals[face] @ d)
            row = {"source_face": int(face), "point_mm": (point * scale + offset).tolist(),
                "normal_dot_direction": dot, "area_weight_mm2": float(areas[face]),
                "state": "unknown", "obstruction_face": None, "obstruction_distance_mm": None,
                "reason": None}
            if time.perf_counter() >= deadline:
                row["reason"] = "time_budget_exceeded"
            elif dot < -angular_tolerance:
                row["state"] = "back_facing"
            elif dot <= angular_tolerance:
                row["state"] = "tangent"
            else:
                state, hit, distance, used, why = _ray(point, int(face), d, triangles, normals,
                    remaining_tests=max_tests - tests, deadline=deadline,
                    tolerance=tolerance, angular_tolerance=angular_tolerance)
                tests += used
                row.update(state=state, obstruction_face=hit,
                    obstruction_distance_mm=distance * scale if distance is not None else None,
                    reason=why)
            if row["reason"]:
                reasons.add(row["reason"])
            rows.append(row)
        selected_area = float(areas[selected].sum())
        fractions = {state: float(sum(row["area_weight_mm2"] for row in rows if row["state"] == state) / selected_area)
                     for state in _STATES}
        result.update(samples=rows, reasons=sorted(reasons),
            status="partial" if reasons else "complete",
            reason=("일부 표본은 시간·연산 한도 또는 수치 경계 때문에 미확정입니다." if reasons else
                "선택한 표본의 방향·직선 차폐 검사를 완료했습니다. 실제 공구 접근·가공 가능 판정은 아닙니다."))
        for state in _STATES:
            result[f"{state}_face_indices"] = [r["source_face"] for r in rows if r["state"] == state]
        result["measurements"].update(requested_samples=requested, selected_samples=len(rows),
            evaluated_samples=sum(r["state"] != "unknown" for r in rows), ray_triangle_tests=tests,
            sampled_face_area_fraction=selected_area / total_area,
            selected_face_area_mm2=selected_area, total_surface_area_mm2=total_area,
            omitted_face_count=nf - len(selected), omitted_face_area_mm2=max(0., total_area - selected_area),
            area_weighted_sample_fractions=fractions,
            sample_state_counts={state: len(result[f"{state}_face_indices"]) for state in _STATES})
    except (ValueError, IndexError, FloatingPointError, MemoryError) as exc:
        return _unknown(result, "geometry_computation_failed", f"접근 차폐 계산을 완료하지 못했습니다: {type(exc).__name__}")
    result["elapsed_seconds"] = time.perf_counter() - started
    return result


def run_point_visibility(mesh, direction=(0, 0, 1), *, max_samples=512,
                         max_faces=200000, max_ray_triangle_tests=20000000,
                         timeout_s=10.0):
    """Hard-bound the complete geometry worker, including topology inspection."""
    from amdfm.models import json_bytes
    from amdfm.processes import run_bounded

    d, count, faces, tests, timeout = _parameters(
        direction, max_samples, max_faces, max_ray_triangle_tests, timeout_s)
    result = _result(d, count, faces, tests, timeout)
    if not isinstance(mesh, trimesh.Trimesh):
        return _unknown(result, "not_triangle_mesh", "단일 삼각형 메시가 필요합니다.")
    if len(mesh.faces) > faces:
        result["measurements"]["omitted_face_count"] = len(mesh.faces)
        return _unknown(result, "face_budget_exceeded", "면 개수가 계산 한도를 넘어 접근 차폐 검토를 보류했습니다.")
    if len(mesh.vertices) > faces * 3:
        return _unknown(result, "vertex_budget_exceeded", "정점 개수가 계산 한도를 넘어 접근 차폐 검토를 보류했습니다.")
    request = dict(direction=d.tolist(), max_samples=count, max_faces=faces,
        max_ray_triangle_tests=tests, timeout_s=timeout)
    try:
        with tempfile.TemporaryDirectory(prefix="dfm-point-visibility-") as tmp:
            base = Path(tmp)
            np.savez(base / "mesh.npz", vertices=mesh.vertices, faces=mesh.faces)
            (base / "request.json").write_bytes(json_bytes(request))
            proc = run_bounded([sys.executable, "-m", "dfm.accessibility", str(base)],
                cwd=Path(__file__).resolve().parents[1], timeout=timeout)
            if proc.returncode or not (base / "result.json").exists():
                return _unknown(result, "worker_failed", "접근 차폐 작업자가 완료되지 않아 결과를 보류했습니다.")
            return json.loads((base / "result.json").read_text(encoding="utf-8"))
    except subprocess.TimeoutExpired:
        return _unknown(result, "worker_timeout", "접근 차폐 계산의 시간 한도를 초과했습니다. 계산되지 않은 영역을 통과로 처리하지 않습니다.")
    except (OSError, ValueError, MemoryError):
        return _unknown(result, "worker_failed", "격리된 접근 차폐 계산을 시작하거나 결과를 읽지 못했습니다.")


def _worker(base):
    from amdfm.models import json_bytes

    request = json.loads((base / "request.json").read_text(encoding="utf-8"))
    with np.load(base / "mesh.npz", allow_pickle=False) as arrays:
        mesh = trimesh.Trimesh(vertices=arrays["vertices"], faces=arrays["faces"], process=False)
    (base / "result.json").write_bytes(json_bytes(inspect_point_visibility(mesh, **request)))


if __name__ == "__main__":
    _worker(Path(sys.argv[1]))
