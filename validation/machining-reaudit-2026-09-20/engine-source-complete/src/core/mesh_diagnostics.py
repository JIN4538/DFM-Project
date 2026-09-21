"""Read-only mesh diagnosis and an explicit, geometry-preserving cleanup preview.

Edge incidence is not an exhaustive self-intersection test. Cleanup never welds
nearby vertices, fills holes, reverses cavity shells, or deletes small components.
"""
import hashlib

import numpy as np


def mesh_digest(mesh):
    digest = hashlib.sha256()
    for values in (mesh.vertices, mesh.faces):
        a = np.ascontiguousarray(values)
        digest.update(str((a.shape, a.dtype.str)).encode())
        digest.update(a.tobytes())
    return digest.hexdigest()


def inspect_mesh(mesh, highlight_limit=8000):
    """Return counts plus bounded face indices in the SAME mesh's index space."""
    result = dict(geometry_available=False, topology_ready=False,
                  face_count=len(mesh.faces), vertex_count=len(mesh.vertices),
                  issues=[], problem_face_indices=[], highlight_truncated=False,
                  self_intersections='not_exhaustively_checked')
    v, f = np.asarray(mesh.vertices), np.asarray(mesh.faces)
    if len(f) == 0 or len(v) == 0:
        result['issues'].append('면 또는 정점이 없는 입력입니다.')
        return result
    if not np.isfinite(v).all():
        result['issues'].append('비유한 좌표(NaN/Infinity)를 포함합니다.')
        return result
    if f.ndim != 2 or f.shape[1] != 3 or f.min() < 0 or f.max() >= len(v):
        result['issues'].append('삼각형의 정점 인덱스가 유효하지 않습니다.')
        return result
    with np.errstate(over='ignore', invalid='ignore'):
        extents = mesh.extents
    if extents is None or not np.isfinite(extents).all():
        result['issues'].append('외곽 치수가 계산 가능한 수치 범위를 벗어납니다.')
        return result
    result['geometry_available'] = True
    incidence = np.bincount(mesh.edges_unique_inverse)
    edge_counts = incidence[mesh.edges_unique_inverse].reshape((-1, 3))
    degenerate = ((f[:, 0] == f[:, 1]) | (f[:, 1] == f[:, 2]) |
                  (f[:, 0] == f[:, 2]) | (mesh.area_faces == 0))
    duplicate = ~mesh.unique_faces()
    with np.errstate(divide='ignore', invalid='ignore', over='ignore'):
        volume, area = float(mesh.volume), float(mesh.area)
    result.update(
        boundary_edges=int(np.count_nonzero(incidence == 1)),
        nonmanifold_edges=int(np.count_nonzero(incidence > 2)),
        degenerate_faces=int(degenerate.sum()), duplicate_faces=int(duplicate.sum()),
        winding_consistent=bool(mesh.is_winding_consistent),
        raw_signed_volume_integral=volume, triangle_area_sum=area,
        extents=mesh.extents.tolist())
    issues = result['issues']
    if result['boundary_edges']:
        issues.append(f"열린 경계 모서리 {result['boundary_edges']:,}개")
    if result['nonmanifold_edges']:
        issues.append(f"3개 이상 면이 연결된 모서리 {result['nonmanifold_edges']:,}개")
    if result['duplicate_faces']:
        issues.append(f"중복 삼각형 {result['duplicate_faces']:,}개")
    if result['degenerate_faces']:
        issues.append(f"면적이 0인 퇴화 삼각형 {result['degenerate_faces']:,}개")
    if not result['winding_consistent']:
        issues.append('면 방향이 일관되지 않습니다')
    if len(f) < 4 or not np.isfinite(volume) or volume <= 0:
        issues.append('양의 부피를 둘러싸는 솔리드인지 확인이 필요합니다')
    if not np.isfinite(area) or area <= 0:
        issues.append('삼각형 면적 합이 유효하지 않습니다')
    affected = np.flatnonzero(np.any(edge_counts != 2, axis=1) | degenerate | duplicate)
    result['problem_face_count'] = int(len(affected))
    result['problem_face_indices'] = affected[:highlight_limit].tolist()
    result['highlight_truncated'] = len(affected) > highlight_limit
    result['topology_ready'] = not issues
    return result


def cleanup_preview(mesh):
    """Return a NEW mesh and audit record; success is never implied by cleanup.

    Remove exact zero-area faces and same-winding exact duplicates only.
    Opposite-winding coincident faces can encode ambiguous material boundaries;
    they are deliberately retained for review. No tolerance-based deletion.
    """
    before = inspect_mesh(mesh)
    candidate = mesh.copy()
    record = dict(method='exact_zero_area_and_oriented_duplicates_v1',
                  source_mesh_sha256=mesh_digest(mesh), before=before,
                  removed_zero_area_faces=0, removed_oriented_duplicates=0,
                  changes_applied=False)
    if before['geometry_available']:
        f = candidate.faces
        bad = ((f[:, 0] == f[:, 1]) | (f[:, 1] == f[:, 2]) |
               (f[:, 0] == f[:, 2]) | (candidate.area_faces == 0))
        record['removed_zero_area_faces'] = int(bad.sum())
        candidate.update_faces(~bad)
        if len(candidate.faces):
            f = candidate.faces
            starts = f.argmin(axis=1)
            oriented = np.take_along_axis(f, (starts[:, None] + np.arange(3)) % 3, axis=1)
            _, keep = np.unique(oriented, axis=0, return_index=True)
            record['removed_oriented_duplicates'] = len(f) - len(keep)
            candidate.update_faces(np.sort(keep))
        candidate.remove_unreferenced_vertices()
    after = inspect_mesh(candidate)
    record.update(after=after, analyzed_mesh_sha256=mesh_digest(candidate))
    record['changes_applied'] = record['source_mesh_sha256'] != record['analyzed_mesh_sha256']
    record['note'] = ('정리 후보입니다. 면 연결·겹침을 다시 검사하며 복구 완료를 보장하지 않습니다. '
                      '구멍 메우기, 근접 정점 병합, 작은 부품 삭제, 공동 반전은 수행하지 않았습니다.')
    if before['geometry_available'] and after['geometry_available']:
        record['bounds_max_change_mm'] = float(np.max(np.abs(mesh.bounds - candidate.bounds)))
    else:
        record['bounds_max_change_mm'] = None
    candidate.metadata['preprocessing'] = record
    return candidate, record
