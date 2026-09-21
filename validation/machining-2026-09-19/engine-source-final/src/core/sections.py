"""Bounded planar interpretation of triangle surfaces; never repairs the mesh.

Signed nonzero winding retains oppositely oriented cavities and unions material
overlaps. Noding is performed only in the plane. Unclosed linework is reported,
not bridged. These sections are a declared interpretation, not a repaired STL.
"""
from dataclasses import dataclass

import numpy as np

from src.core.section_index import WindingIndex, WindingLimit
from src.core.section_components import component_rings, fast_linework, isolated_material


@dataclass
class Section:
    material: object
    origin: np.ndarray
    axes: np.ndarray
    diagnostics: dict
    known_material: object = None


def plane_axes(normal):
    normal = np.asarray(normal, dtype=float)
    normal = normal / np.linalg.norm(normal)
    seed = np.eye(3)[np.argmin(np.abs(normal))]
    x = np.cross(seed, normal); x /= np.linalg.norm(x)
    return np.vstack([x, np.cross(normal, x)])


def intersect_triangles(mesh, origin, normal, local_faces=None, vertex_projection=None):
    """Canonical edge interpolation with an exact, consistent half-open sign.

    The same mesh edge produces bit-identical endpoints from either incident
    triangle. No global 'vertex is close to the plane' tolerance is used.
    """
    ids = np.arange(len(mesh.faces)) if local_faces is None else np.asarray(local_faces)
    faces = mesh.faces[ids]
    # Reuse the build-frame Z projection. Only active face/edge vertices are
    # gathered per plane; the full vertex array is not translated each time.
    projection = mesh.vertices @ normal if vertex_projection is None else vertex_projection
    offset = np.dot(origin, normal)
    side = projection[faces] >= offset
    active = np.any(side, axis=1) & ~np.all(side, axis=1)
    ids, faces, side = ids[active], faces[active], side[active]
    if not len(ids):
        return np.empty((0, 2, 3)), np.empty((0, 3))
    raw_normals = np.cross(mesh.vertices[faces[:, 1]]-mesh.vertices[faces[:, 0]],
                           mesh.vertices[faces[:, 2]]-mesh.vertices[faces[:, 0]])
    nonzero = np.any(raw_normals != 0, axis=1)
    faces, side, raw_normals = faces[nonzero], side[nonzero], raw_normals[nonzero]
    edge_pairs = np.array([[0, 1], [1, 2], [2, 0]])
    crosses = side[:, edge_pairs[:, 0]] != side[:, edge_pairs[:, 1]]
    edges = np.sort(faces[:, edge_pairs][crosses], axis=1)
    a, b = edges[:, 0], edges[:, 1]
    sa, sb = projection[a]-offset, projection[b]-offset
    fraction = sa / (sa-sb)
    points = mesh.vertices[a] + fraction[:, None]*(mesh.vertices[b]-mesh.vertices[a])
    points[sa == 0] = mesh.vertices[a[sa == 0]]
    points[sb == 0] = mesh.vertices[b[sb == 0]]
    return points.reshape((-1, 2, 3)), raw_normals


def winding_at(points, segments):
    a, b = segments[:, 0], segments[:, 1]
    values = []
    for x, y in points:
        left = (b[:, 0]-a[:, 0])*(y-a[:, 1]) - (x-a[:, 0])*(b[:, 1]-a[:, 1])
        w = np.count_nonzero((a[:, 1] <= y) & (b[:, 1] > y) & (left > 0))
        w -= np.count_nonzero((a[:, 1] > y) & (b[:, 1] <= y) & (left < 0))
        values.append(w)
    return np.asarray(values)


def section_mesh(mesh, origin, normal, *, axes=None, local_faces=None,
                 max_segments=60000, max_winding_tests=8000000,
                 vertex_projection=None, use_fast_path=True, mesh_scale_mm=None):
    """Return polygons without gap filling or part deletion.

    Repeated callers may reuse the same immutable mesh's largest extent.
    Recompute mesh_scale_mm and vertex_projection after any geometry change.
    """
    import shapely as sh
    origin = np.asarray(origin, dtype=float)
    normal = np.array(normal, dtype=float, copy=True); normal /= np.linalg.norm(normal)
    axes = plane_axes(normal) if axes is None else np.asarray(axes, dtype=float)
    scale = float(np.max(mesh.extents)) if mesh_scale_mm is None else float(mesh_scale_mm)
    if not np.isfinite(scale) or scale < 0:
        raise ValueError('단면 좌표 정밀도의 기준 크기는 유한한 비음수여야 합니다.')
    grid = max(1e-10, min(1e-6, scale * 1e-11))
    diag = dict(method='oriented_nonzero_section_v2', grid_mm=grid,
                complete=False, segment_count=0, polygon_count=0,
                unresolved_length_mm=0.0, collapsed_segments=0,
                zero_length_segments=0, orientation_imbalances=0,
                internal_seam_length_mm=0.0, boundary_precision_collapses=0,
                known_area_mm2=0.0, unknown_bounds_mm=[], winding_tests=0)
    empty = sh.GeometryCollection()
    index = None
    try:
        lines, raw_normals = intersect_triangles(mesh, origin, normal, local_faces, vertex_projection)
        diag['segment_count'] = len(lines)
        if len(lines) > max_segments:
            diag['reason'] = '단면 선분 수가 계산 한도를 초과했습니다.'
            return Section(empty, origin, axes, diag, empty)
        if len(lines) == 0:
            diag['complete'] = True
            return Section(empty, origin, axes, diag)
        xy = (lines-origin) @ axes.T
        # Orient each segment from the source face, independent of the ordering
        # emitted by the intersection routine.
        tangent = np.cross(raw_normals, normal)
        reverse = np.einsum('ij,ij->i', lines[:, 1]-lines[:, 0], tangent) < 0
        xy[reverse] = xy[reverse, ::-1]
        snapped = np.round(xy / grid) * grid
        keep = np.linalg.norm(snapped[:, 1]-snapped[:, 0], axis=1) > grid/2
        exact_zero = np.linalg.norm(xy[:, 1]-xy[:, 0], axis=1) == 0
        diag['zero_length_segments'] = int(np.count_nonzero(exact_zero))
        diag['collapsed_segments'] = int(np.count_nonzero(~keep & ~exact_zero))
        # A sub-grid edge on a retained boundary is covered by the declared
        # coordinate precision. Never accept a whole isolated contour vanishing
        # at that precision: its collapsed vertex has no retained incident edge.
        retained_points = set(map(tuple, snapped[keep].reshape((-1,2))))
        lost_points = snapped[~keep & ~exact_zero, 0]
        boundary_collapses = sum(tuple(p) in retained_points for p in lost_points)
        orphan_points = [p for p in lost_points if tuple(p) not in retained_points]
        diag['boundary_precision_collapses'] = int(boundary_collapses)
        diag['collapsed_segments'] -= boundary_collapses
        snapped = snapped[keep]
        if not len(snapped):
            diag['reason'] = '모든 단면 선분이 수치 해상도보다 작습니다.'
            return Section(empty, origin, axes, diag)
        # Exact duplicate directed segments contribute one surface boundary.
        # Opposite directions remain and cancel under the signed fill rule.
        snapped = np.unique(snapped.reshape((-1, 4)), axis=0).reshape((-1, 2, 2))
        _, endpoints = np.unique(snapped.reshape((-1, 2)), axis=0, return_inverse=True)
        ends = endpoints.reshape((-1, 2))
        balance = np.bincount(ends[:, 0], minlength=endpoints.max()+1) - np.bincount(ends[:, 1], minlength=endpoints.max()+1)
        diag['orientation_imbalances'] = int(np.count_nonzero(balance))
        groups, segment_groups = component_rings(snapped)
        rings = fast_linework(groups) if use_fast_path else None
        diag['contour_path'] = 'endpoint_loops' if rings is not None else 'noded'
        linework = rings if rings is not None else sh.get_parts(sh.union_all(sh.linestrings(snapped), grid_size=grid))
        polygons, cuts, dangles, invalid = sh.polygonize_full(linework)
        residual = float(cuts.length+dangles.length+invalid.length)
        cells = list(sh.get_parts(polygons))
        diag['polygon_count'] = len(cells)
        diag['exhaustive_winding_tests'] = len(cells) * len(snapped)
        index = WindingIndex(snapped, max_winding_tests)
        inside = []
        points = [(p.representative_point().x, p.representative_point().y) for p in cells]
        for cell, winding in zip(cells, index.values(points)):
            if winding:
                inside.append(cell)
        material = sh.union_all(inside) if inside else empty
        # Snapping can make collinear tessellation vertices alternate by one
        # grid cell. Those microscopic zigzags destabilize polygon offsets.
        # Simplify only within this declared numerical precision, preserving
        # polygon topology (including holes and disconnected components).
        original_area = float(material.area)
        material = material.simplify(grid*2, preserve_topology=True)
        diag['contour_simplification_tolerance_mm'] = grid*2
        diag['contour_area_change_mm2'] = float(material.area-original_area)
        # Balanced linework can include internal coincident seams. A seam is
        # irrelevant only when signed winding is nonzero on BOTH sides at
        # several points. This cannot turn an unbalanced open cavity into solid.
        if residual and not diag['orientation_imbalances']:
            for seam in list(sh.get_parts(cuts))+list(sh.get_parts(dangles)):
                coords = np.asarray(seam.coords)
                if len(coords) != 2:
                    continue
                delta = coords[1]-coords[0]; length = np.linalg.norm(delta)
                if length <= grid:
                    continue
                perpendicular = np.array([-delta[1], delta[0]]) / length * grid*8
                centers = coords[0]+np.array([.2, .5, .8])[:, None]*delta
                sides = np.concatenate([centers-perpendicular, centers+perpendicular])
                try:
                    side_winding = index.values(sides)
                except WindingLimit:
                    diag['winding_limit_reached'] = True
                    break
                if np.all(side_winding != 0):
                    diag['internal_seam_length_mm'] += float(length)
        residual = max(0.0, residual-diag['internal_seam_length_mm'])
        diag['winding_tests'] = index.tests
        diag['unresolved_length_mm'] = residual
        diag.update(complete=residual <= grid*2 and diag['collapsed_segments'] == 0 and diag['orientation_imbalances'] == 0,
                    material_area_mm2=float(material.area),
                    material_components=len(sh.get_parts(material)))
        if residual > grid*2:
            diag['reason'] = '닫히지 않은 단면 선분이 남아 해당 층 전체를 확정할 수 없습니다.'
        elif diag['collapsed_segments']:
            diag['reason'] = '수치 해상도보다 작은 단면 선분이 있습니다.'
        elif diag['orientation_imbalances']:
            diag['reason'] = '단면 경계의 방향 연결이 일관되지 않습니다.'
        if material.is_empty and diag['complete']:
            diag['complete'] = False
            diag['reason'] = '선분은 있지만 재료 면적이 0입니다. 반대 방향 중복 경계의 상쇄 가능성을 확인하세요.'
        known = material if diag['complete'] else empty
        if not diag['complete'] and (residual > grid*2 or diag['collapsed_segments'] or diag['orientation_imbalances']):
            try:
                known, bounds, accepted, work = isolated_material(
                    snapped, groups, segment_groups, orphan_points, grid,
                    max(0, max_winding_tests-index.tests))
                diag.update(unknown_bounds_mm=bounds, isolated_closed_groups=accepted,
                            winding_tests=index.tests+work)
            except WindingLimit:
                diag['partial_reason'] = '부분 단면 판별도 누적 계산 한도 내에서만 수행합니다.'
                known = empty
        # An incomplete section without localized uncertainty cannot provide a
        # safe support/comparison mask. Treat its whole observed extent as unknown.
        if not diag['complete'] and not diag['unknown_bounds_mm']:
            xy_all = snapped.reshape((-1,2))
            diag['unknown_bounds_mm'] = [[*xy_all.min(axis=0), *xy_all.max(axis=0)]]
        diag['known_area_mm2'] = float(known.area)
        return Section(material, origin, axes, diag, known)
    except WindingLimit as exc:
        diag['winding_tests'] = index.tests if index is not None else 0
        diag['reason'] = str(exc)
        diag['winding_limit_reached'] = True
        return Section(empty, origin, axes, diag)
    except Exception as exc:
        diag['reason'] = f'단면 구성 실패: {exc}'
        return Section(empty, origin, axes, diag)


def opening_residual(material, width):
    """Planar offset feature loss, not 3D wall thickness or printability.

    Mitred joins retain ordinary sharp corners; the bounded mitre limit leaves
    long, acute tips visible. No operation here modifies the source polygon.
    """
    eroded = material.buffer(-width/2, join_style='mitre', mitre_limit=5)
    restored = eroded.buffer(width/2, join_style='mitre', mitre_limit=5)
    return material.difference(restored)
