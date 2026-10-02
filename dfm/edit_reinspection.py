"""Remeasure exported CAD, including protected faces and edited recess floors."""
import math
import numpy as np


def inspect_export(before, exported, requests, audit):
    from .cad_graph import extract_graph
    from .cad_edit_pairs import bounds
    original = extract_graph(before)
    result = extract_graph(exported)
    before_faces, after_faces = original['measurements'], result['measurements']
    edits = audit.get('edits', [audit])
    if len(edits) != len(requests):
        raise ValueError('Edit and remeasurement request counts differ')
    rows = []
    for request, edit in zip(requests, edits):
        p = request['pocket']; axis = np.asarray(p['direction'], dtype=float)
        axis /= np.linalg.norm(axis)
        floor = next(m for m in before_faces if m['face_id'] == p['floor_face_id'])
        z = float(np.asarray(floor['centroid_mm'])@axis)
        low, high = np.asarray(edit['edit_bounds_mm'], dtype=float)
        candidate_floors = [m for m in after_faces if m['surface_kind'] == 0
            and np.dot(m['normal'], axis) > 1-1e-7
            and abs(np.asarray(m['centroid_mm'])@axis-z) < 1e-6
            and np.all(np.asarray(m['centroid_mm']) >= low-1e-6)
            and np.all(np.asarray(m['centroid_mm']) <= high+1e-6)]
        if len(candidate_floors) != 1:
            raise ValueError('Exported pocket floor cannot be uniquely remeasured')
        floor_after = candidate_floors[0]
        expected_area = floor['area_mm2']-edit['analytic_material_addition_mm3']/p['wall_height_mm']
        if not math.isclose(floor_after['area_mm2'], expected_area, rel_tol=1e-7, abs_tol=1e-6):
            raise ValueError('Exported floor area does not match independent corner formula')
        curved = [m for m in after_faces if m['face_id'] in edit['rounded_face_ids']]
        radii = [m['radius_mm'] for m in curved]
        if len(radii) != edit['modified_corner_edges'] or any(not math.isclose(r, request['radius'], rel_tol=1e-7, abs_tol=1e-7) for r in radii):
            raise ValueError('Exported corner radii do not match the requested radius')
        heights = []
        for m in curved:
            points = np.asarray(m['vertex_points_mm'])
            if len(points) < 2:
                raise ValueError('Rounded wall endpoints missing')
            heights.append(float(np.ptp(points@axis)))
        if any(not math.isclose(h, p['wall_height_mm'], rel_tol=1e-7, abs_tol=1e-6) for h in heights):
            raise ValueError('Exported pocket depth changed')
        rows.append(dict(floor_face_id_before=p['floor_face_id'], floor_face_id_after=floor_after['face_id'],
            radius_before_mm=0., radius_after_mm=min(radii), depth_before_mm=p['wall_height_mm'],
            depth_after_mm=min(heights), floor_area_before_mm2=floor['area_mm2'], floor_area_after_mm2=floor_after['area_mm2']))
    # Cylinders that existed before a sharp-corner-only edit are protected.
    # Compare actual re-imported geometry, never source face ordinals alone.
    preserved = 0
    for face in before_faces:
        if face['surface_kind'] != 1:
            continue
        matches = [m for m in after_faces if m['surface_kind'] == 1
            and math.isclose(m['radius_mm'], face['radius_mm'], rel_tol=1e-7, abs_tol=1e-7)
            and math.isclose(m['area_mm2'], face['area_mm2'], rel_tol=1e-7, abs_tol=1e-6)
            and np.allclose(m['centroid_mm'], face['centroid_mm'], rtol=0, atol=1e-6)]
        if len(matches) != 1:
            raise ValueError('A protected original cylindrical face changed')
        preserved += 1
    unchanged = bool(np.allclose(bounds(before), bounds(exported), rtol=0, atol=1e-6))
    if not unchanged:
        raise ValueError('Protected outer dimensions changed after export')
    return dict(status='verified', method='exported STEP reimport; floor area, corner radius, wall height and original cylinders',
        pockets=rows, protected_cylinder_faces=preserved, protected_outer_bounds_unchanged=unchanged,
        before_volume_mm3=original['volume_mm3'], after_volume_mm3=result['volume_mm3'],
        material_change_percent=100*(result['volume_mm3']-original['volume_mm3'])/original['volume_mm3'])


def compare_plan(report, audit):
    """Scope-labelled numeric review uses exported radii/depths, not target values."""
    from .rl_planner import evaluate_changes, make_problem, conflicts
    problem = make_problem(report, report.get('review_context', {}).get('plan_preferences'))
    before = conflicts(problem, problem['initial'])
    selected = report['plan_recommendation']['selected']
    changes = [dict(change) for change in selected['changes']]
    rows = audit['remeasurement']['pockets']
    for row in rows:
        change = next(c for c in changes if c.get('cad_face_id') == row['floor_face_id_before'] and c['field'].endswith('.corner_radius'))
        change['after'] = row['radius_after_mm']
    checked = evaluate_changes(report, changes, preferences=report.get('review_context', {}).get('plan_preferences'))
    after = checked['plan']['conflict_details']
    signatures = lambda rows: {(r['finding_id'], r['code'], r.get('cad_face_id')) for r in rows}
    new = signatures(after)-signatures(before)
    if new:
        raise ValueError('Remeasured edit introduced a new supported dimensional conflict')
    return dict(before_conflicts=len(before), after_conflicts=len(after), new_conflicts=len(new),
        scope='entered tool and supported hole/pocket/corner dimensional comparisons',
        remaining=checked['plan']['remaining'], changes=changes)
