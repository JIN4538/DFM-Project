"""Recover simple circular holes from native CAD rims, not neural labels.

Constant-radius walls must span the same interval, cover one circumference and
have the native area of that cylinder. Closed planar rim wires must be incident
to exactly those walls. A blind floor must be a complete planar disk. Stepped,
intersecting, incomplete and non-solid inputs remain outside this certificate.
The frozen face recognizer and its learned weights are never changed here.
"""
from __future__ import annotations

from copy import deepcopy
import math
import numpy as np

from .machining import _axis_angle_and_alignment, _record_comparison
from amdfm.orientation import unit_direction

VERSION = 'native-circular-rims-1'
MAX_CYLINDERS = 512
MAX_RIMS = 2048
ANGLE_TOLERANCE = 1e-8


def _vector(value):
    a = np.asarray(value, dtype=float)
    if a.shape != (3,) or not np.isfinite(a).all():
        raise ValueError('Invalid native CAD vector')
    return a


def _parallel(a, b):
    return np.linalg.norm(np.cross(a, b)) <= ANGLE_TOLERANCE


def _circle_rims(features):
    rims = []
    for face in features:
        if (face.get('kind') != 'plane' or face.get('boundary_status') != 'complete'
                or face.get('material_normal_confirmed') is not True):
            continue
        for wire in face.get('boundary_wires', []):
            edges = wire.get('edges', [])
            if (not wire.get('closed') or not wire.get('ordered') or not edges
                    or len(edges) != wire.get('total_edge_count')
                    or any(e.get('kind') != 'circle' or e.get('geometry_status') != 'complete'
                           or e.get('degenerate') for e in edges)):
                continue
            center = _vector(edges[0]['center_mm'])
            radius = float(edges[0]['radius_mm'])
            axis = unit_direction(edges[0]['axis'])
            tol = max(1e-7, radius * 1e-8)
            if radius <= 0 or not math.isfinite(radius):
                continue
            if (len({e['edge_id'] for e in edges}) != len(edges)
                    or any(np.linalg.norm(_vector(e['center_mm']) - center) > tol
                           or abs(e['radius_mm'] - radius) > tol
                           or not _parallel(unit_direction(e['axis']), axis) for e in edges)
                    or abs(sum(e['sweep_rad'] for e in edges) - 2 * math.pi) > 1e-7
                    or not _parallel(unit_direction(face['normal']), axis)):
                continue
            adjacent = set()
            valid = True
            for i, edge in enumerate(edges):
                neighbors = edge.get('adjacent_faces', [])
                if len(neighbors) != 1 or neighbors[0].get('kind') != 'cylinder':
                    valid = False
                    break
                adjacent.add(neighbors[0]['face_id'])
                if np.linalg.norm(_vector(edge['end_mm']) - _vector(edges[(i+1) % len(edges)]['start_mm'])) > tol:
                    valid = False
                    break
            if valid:
                rims.append(dict(face_id=face['face_id'], body_id=face['body_id'],
                    center=center, radius=radius, axis=axis, normal=unit_direction(face['normal']),
                    outer=wire['outer'], adjacent=adjacent, edge_ids=[e['edge_id'] for e in edges],
                    disk=(len(face['boundary_wires']) == 1 and wire['outer']
                          and math.isclose(face.get('area_mm2', 0), math.pi*radius**2, rel_tol=1e-8, abs_tol=1e-7))))
            if len(rims) > MAX_RIMS:
                raise OverflowError('Circular rim budget exceeded')
    return rims


def measure_holes(model):
    """A bounded geometry inventory; no missing certificate implies no holes."""
    result = dict(version=VERSION, method='Native cylinder area + closed incident circular rim wires',
                  holes=[], excluded=[], status='unavailable')
    meta = model.metadata
    if (meta.get('source_format') not in ('step', 'stp') or meta.get('solid_count') != 1
            or meta.get('cad_valid') is not True or meta.get('cad_geometry_kind') != 'solid'):
        result['reason'] = 'Valid single STEP solid required'
        return result
    cylinders = [f for f in model.cad_features if f.get('kind') == 'cylinder' and f.get('role') == 'inner']
    if len(cylinders) > MAX_CYLINDERS:
        result.update(status='budget_exceeded', reason='Inner cylinder budget exceeded')
        return result
    try:
        rims = _circle_rims(model.cad_features)
        normalized = []
        for f in cylinders:
            axis = unit_direction(f['axis'])
            j = int(np.argmax(np.abs(axis)))
            if axis[j] < 0:
                axis = -axis
            ends = np.asarray(f.get('axis_endpoints_mm'), dtype=float)
            diameter = float(f['diameter_mm'])
            if ends.shape != (2, 3) or not np.isfinite(ends).all() or not math.isfinite(diameter) or diameter <= 0:
                result['excluded'].append(dict(face_ids=[f['face_id']], reason='missing_native_interval'))
                continue
            ends = ends[np.argsort(ends @ axis)]
            normalized.append(dict(face=f, axis=axis, ends=ends, radius=diameter/2))
        groups = []
        for c in normalized:
            group = next((g for g in groups if g[0]['face']['body_id'] == c['face']['body_id']
                and _parallel(g[0]['axis'], c['axis'])
                and abs(g[0]['radius'] - c['radius']) <= max(1e-7, c['radius']*1e-8)
                and np.linalg.norm(np.cross(c['ends'][0]-g[0]['ends'][0], c['axis'])) <= max(1e-7, c['radius']*1e-8)), None)
            if group is None:
                groups.append([c])
            else:
                group.append(c)
        for group in groups:
            first = group[0]
            axis, ends, radius = first['axis'], first['ends'], first['radius']
            body = first['face']['body_id']
            ids = sorted(c['face']['face_id'] for c in group)
            length = float((ends[1]-ends[0]) @ axis)
            tol = max(1e-7, radius*1e-8, abs(length)*1e-8)
            reason = None
            if length <= tol or any(np.max(np.linalg.norm(c['ends']-ends, axis=1)) > tol for c in group):
                reason = 'axially_split_or_zero_interval'
            elif any(c['face'].get('area_mm2') is None or c['face'].get('u_span_rad') is None for c in group):
                reason = 'missing_native_area'
            elif (not math.isclose(sum(c['face']['area_mm2'] for c in group), 2*math.pi*radius*length, rel_tol=1e-8, abs_tol=1e-7)
                  or abs(sum(c['face']['u_span_rad'] for c in group)-2*math.pi) > 1e-7):
                reason = 'intersecting_or_incomplete_wall'
            elif any(c['face']['body_id'] == body and _parallel(c['axis'], axis)
                     and np.linalg.norm(np.cross(c['ends'][0]-ends[0], axis)) <= tol
                     and abs(c['radius']-radius) > tol for c in normalized):
                reason = 'coaxial_radius_change'
            matches = []
            if reason is None:
                for end in ends:
                    matches.append([r for r in rims if r['body_id'] == body and r['adjacent'] == set(ids)
                        and abs(r['radius']-radius) <= tol and _parallel(r['axis'], axis)
                        and np.linalg.norm(r['center']-end) <= tol])
                if any(len(m) != 1 for m in matches):
                    reason = 'missing_or_ambiguous_rim'
            if reason is not None:
                result['excluded'].append(dict(face_ids=ids, reason=reason))
                continue
            low, high = matches[0][0], matches[1][0]
            entries = []
            kind = None
            if not low['outer'] and not high['outer'] and low['normal'] @ axis < 0 and high['normal'] @ axis > 0:
                kind = 'through'
                entries = [(low, -axis), (high, axis)]
            elif low['disk'] and low['normal'] @ axis > 0 and not high['outer'] and high['normal'] @ axis > 0:
                kind = 'blind'
                entries = [(high, axis)]
            elif high['disk'] and high['normal'] @ axis < 0 and not low['outer'] and low['normal'] @ axis < 0:
                kind = 'blind'
                entries = [(low, -axis)]
            if kind is None:
                result['excluded'].append(dict(face_ids=ids, reason='no_open_mouth_or_flat_floor'))
                continue
            result['holes'].append(dict(face_id=min(ids), face_ids=ids, body_id=body, hole_kind=kind,
                diameter_mm=2*radius, depth_mm=length, cylindrical_length_mm=length,
                axis=axis.tolist(), axis_endpoints_mm=ends.tolist(),
                entry_directions=[v.tolist() for _, v in entries],
                entry_centers_mm=[r['center'].tolist() for r, _ in entries],
                rim_face_ids=[low['face_id'], high['face_id']],
                rim_edge_ids=[low['edge_ids'], high['edge_ids']],
                area_mm2=sum(c['face']['area_mm2'] for c in group), measurement_source=VERSION))
        result['status'] = 'complete'
    except (ValueError, KeyError, TypeError, OverflowError) as exc:
        result.update(status='unavailable', reason=str(exc), holes=[])
    return result


def attach_verified_holes(report, model):
    """Complement face-level findings; retain their original record for audit."""
    if report.get('model_fingerprint') != model.fingerprint:
        raise ValueError('구멍을 측정할 형상과 검토 결과가 다릅니다.')
    if report.get('verified_hole_inventory', {}).get('version') == VERSION:
        return report
    inventory = measure_holes(model)
    report['verified_hole_inventory'] = inventory
    holes = inventory['holes']
    if not holes:
        return report
    direction = unit_direction(report['direction'])
    profile = report['profile']
    owned = {i for h in holes for i in h['face_ids']}
    findings = {f['id']: f for f in report['findings']}
    hole_finding = findings['cnc_holes']
    report['native_hole_face_review'] = deepcopy(hole_finding)
    raw_rows = hole_finding['measurements'].get('cylindrical_faces', [])
    rows = [r for r in raw_rows if r['face_id'] not in owned]
    for h in holes:
        angle, aligned = _axis_angle_and_alignment(h['axis'], direction)
        entry_matches = any(float(direction @ np.asarray(v)) > 0 and _parallel(direction, v) for v in h['entry_directions'])
        h.update(axis_aligned=aligned, axis_angle_deg=angle, entry_blocked=aligned and not entry_matches,
                 entry_matches_direction=entry_matches)
        row = dict(h, length_diameter_ratio=h['depth_mm']/h['diameter_mm'],
                   tool_too_large=None, segment_exceeds_reach=None, exceeds_ratio=None)
        if aligned and not h['entry_blocked']:
            if profile.get('tool_diameter_mm') is not None:
                _record_comparison(row, 'tool_too_large', profile['tool_diameter_mm'], h['diameter_mm'])
            _record_comparison(row, 'segment_exceeds_reach', h['depth_mm'], profile.get('reach_mm'))
        if profile.get('hole_depth_ratio_limit'):
            _record_comparison(row, 'exceeds_ratio', row['length_diameter_ratio'], profile['hole_depth_ratio_limit'])
        rows.append(row)
    measures = hole_finding['measurements']
    measures.update(cylindrical_faces=rows, verified_hole_count=len(holes),
                    face_count=sum(len(r.get('face_ids', [r['face_id']])) for r in rows), review_location_count=len(rows),
                    verified_cylinder_face_count=len(owned), unverified_cylindrical_face_count=len(rows)-len(holes))
    bad = [r for r in rows if not r.get('axis_aligned') or any(r.get(k) for k in ('tool_too_large', 'segment_exceeds_reach', 'exceeds_ratio'))]
    unknown = bool(measures.get('unresolved_cylinder_face_ids')) or any(r.get('entry_blocked') for r in rows) or any(r.get('axis_aligned') and not r.get('entry_blocked')
        and (r.get('tool_too_large') is None or r.get('segment_exceeds_reach') is None) for r in rows)
    hole_finding.update(title='구멍 치수와 공구', status='attention' if bad else 'unknown' if unknown else 'observed',
        reason=f"구멍 {len(holes)}개 · 방향·공구를 조정할 위치 {len(bad)}곳" +
               (f" · 별도 원통 구간 {len(rows)-len(holes)}개" if len(rows)>len(holes) else ''),
        action='구멍이 열린 쪽에서 검토하도록 방향을 바꾸세요.' if any(r.get('entry_blocked') for r in rows) else
               '구멍 축 방향으로 바꾸어 다시 검토하세요.' if any(not r.get('axis_aligned') for r in bad) else
               '표시한 구멍에 맞춰 공구 지름·길이를 조정하세요.' if bad else
               '공구 치수가 비어 있으면 자동 제안을 켜세요.' if unknown else
               '측정한 구멍 치수와 공구 조건을 유지하세요.',
        method=hole_finding['method']+'; '+inventory['method'],
        cad_face_ids=sorted({i for r in (bad or rows) for i in r.get('face_ids', [r['face_id']])}))
    hole_finding['face_indices'] = np.flatnonzero(np.isin(model.face_ids, hole_finding['cad_face_ids'])).tolist()
    hole_finding['limitations'] = [
        '원형 입구와 전체 원통 벽을 확인한 일정 지름의 관통 구멍·평평한 바닥 구멍만 개수와 깊이를 확정합니다.',
        '단차·교차·축 방향 분할·불완전 경계는 개별 원통 구간으로 보존합니다.',
        '입구 방향 일치는 구멍의 국소 기하입니다. 다른 형상·공구 몸통·홀더와의 경로 간섭은 별도 항목입니다.',
        'CAD 기하 검산이며 학습 모델의 검출률을 변경하지 않습니다.']
    # Meridional split walls belong to a hole, not a pocket corner. Unrelated
    # concave surfaces and all unknown material-side records stay intact.
    corner = findings.get('cnc_curved_corners')
    if corner and any(r['face_id'] in owned for r in corner['measurements'].get('cylindrical_faces', [])):
        report['native_corner_face_review'] = deepcopy(corner)
        corner['measurements']['cylindrical_faces'] = rest = [r for r in corner['measurements']['cylindrical_faces'] if r['face_id'] not in owned]
        bad_corners = [r for r in rest if r.get('tool_too_large')]
        corner.update(status='attention' if bad_corners else 'unknown' if corner['measurements'].get('unresolved_cylinder_face_ids') or
                      (rest and profile.get('tool_diameter_mm') is None) else 'observed' if rest else 'not_detected',
                      reason=f'구멍 벽을 제외한 오목 원통면 {len(rest)}개 · 공구보다 작은 반경 {len(bad_corners)}개',
                      cad_face_ids=[r['face_id'] for r in bad_corners])
        if not rest:
            corner['action'] = '분할된 원통 벽은 구멍 항목에서 확인하세요.'
        corner['face_indices'] = np.flatnonzero(np.isin(model.face_ids, corner['cad_face_ids'])).tolist()
    blocked = [h for h in holes if h['entry_blocked']]
    if blocked:
        ids = sorted({i for h in blocked for i in h['face_ids']})
        report['findings'].insert(1, dict(id='cnc_hole_entry', title='막힌 쪽으로 접근한 구멍', status='attention',
            reason=f'바닥 쪽을 향한 막힌 구멍 {len(blocked)}개', action='구멍 입구 쪽으로 방향을 바꾸어 다시 검토하세요.',
            method=inventory['method'], evidence=['CNC_GEOMETRY'], measurements={'cylindrical_faces':blocked},
            cad_face_ids=ids, face_indices=np.flatnonzero(np.isin(model.face_ids, ids)).tolist(), limitations=[], severity='review'))
    data = report.setdefault('external_feature_recognition', {})
    report.setdefault('sources', []).append(dict(id='CNC_HOLE_METHODS',
        title='Sandvik Coromant — Milling holes and cavities/pockets',
        url='https://www.sandvik.coromant.com/en-us/knowledge/milling/milling-holes-cavities-pockets',
        scope='드릴과 원호 밀링을 구분하고 구멍 치수·입구·바닥 형상을 제시하는 이유. 인식 알고리즘 정확도나 앱의 80%·1 mm 정책 근거가 아님.',
        locator='Creating an opening; circular ramping applications; updated hole geometry audit 2026-09-30',
        access='공식 공개 자료 해당 항목 확인'))
    data['verified_holes'] = holes
    data['candidates'] = [c for c in data.get('candidates', []) if not (c.get('feature') in ('through_hole', 'blind_hole') and set(c['face_ids']) & owned)]
    for h in holes:
        data['candidates'].append(dict(feature=h['hole_kind']+'_hole', label='관통 구멍' if h['hole_kind']=='through' else '막힌 구멍',
            face_ids=h['face_ids'], body_id=h['body_id'], area_mm2=h['area_mm2'], confidence=None,
            recognition_source='cad_verified_geometry', recognition_model_id=None, measurement_source=VERSION))
    return report
