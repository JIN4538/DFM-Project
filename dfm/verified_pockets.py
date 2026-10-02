"""Native closed-prism certificates complement, never relabel, learned candidates."""
from copy import deepcopy
import math
import numpy as np
from amdfm.orientation import unit_direction
from .external_features_review import pocket_dimensions


def plane_measurement(face):
    wires=face.get('boundary_wires',[])
    if face.get('kind')!='plane' or face.get('boundary_status')!='complete' or not face.get('material_normal_confirmed') or len(wires)!=1:
        return None
    wire=wires[0];edges=wire.get('edges',[])
    if not wire.get('outer') or not wire.get('closed') or not wire.get('ordered') or any(e.get('kind')!='line' or e.get('geometry_status')!='complete' or e.get('degenerate') for e in edges):
        return None
    points=[]
    for edge in edges:
        for key in ('start_mm','end_mm'):
            point=np.asarray(edge[key],dtype=float)
            if not any(np.linalg.norm(point-old)<1e-7 for old in points):points.append(point)
    return dict(face_id=face['face_id'],surface_kind=0,normal=face['normal'],area_mm2=face['area_mm2'],
        centroid_mm=face['centroid_mm'],vertex_points_mm=[p.tolist() for p in points],radius_mm=None,
        perimeter_mm=sum(e['length_mm'] for e in edges))


def measure_pockets(model,direction):
    meta=model.metadata
    if meta.get('cad_valid') is not True or meta.get('cad_geometry_kind')!='solid' or meta.get('solid_count')!=1 or meta.get('source_format') not in ('step','stp'):
        return []
    if len(model.cad_features)>2048:return []
    axis=unit_direction(direction);faces={f['face_id']:f for f in model.cad_features};output=[]
    for floor in faces.values():
        measured=plane_measurement(floor)
        if measured is None or np.dot(measured['normal'],axis)<1-1e-7:continue
        edges=floor['boundary_wires'][0]['edges'];sides=len(edges)
        if sides not in (3,4,6) or len(measured['vertex_points_mm'])!=sides:continue
        center=np.mean(measured['vertex_points_mm'],axis=0);z=float(center@axis)
        walls=[];tops=[];valid=True
        for edge in edges:
            adjacent=edge.get('adjacent_faces',[])
            if len(adjacent)!=1 or adjacent[0]['kind']!='plane':valid=False;break
            wall=faces.get(adjacent[0]['face_id']);m=plane_measurement(wall) if wall else None
            if m is None or len(m['vertex_points_mm'])!=4 or abs(np.dot(m['normal'],axis))>1e-7 or np.dot(m['normal'],center-np.asarray(edge['midpoint_mm']))<=1e-7:
                valid=False;break
            # A closed cavity has an inward ceiling, rather than an outward
            # rim. Boss/channel/floor islands fail other explicit gates.
            top_edges=[e for e in wall['boundary_wires'][0]['edges'] if min(np.asarray(e['start_mm'])@axis,np.asarray(e['end_mm'])@axis)>z+1e-6]
            if len(top_edges)!=1:valid=False;break
            near=top_edges[0].get('adjacent_faces',[])
            if len(near)!=1 or near[0].get('kind')!='plane' or np.dot(near[0].get('normal',[0,0,0]),axis)<1-1e-7:
                valid=False;break
            rim=faces.get(near[0]['face_id'])
            if not rim or rim.get('body_id')!=floor.get('body_id') or rim.get('boundary_status')!='complete':valid=False;break
            tops.append(near[0]['face_id']);walls.append(m)
        if not valid or len(set(tops))!=1 or len({m['face_id'] for m in walls})!=sides:continue
        candidate=dict(feature={3:'triangular_pocket',4:'rectangular_pocket',6:'6sides_pocket'}[sides],
            face_ids=[measured['face_id']]+[m['face_id'] for m in walls],measured_faces=[measured]+walls,
            confidence=None,recognition_model_id=None,source='native_closed_prism',
            label={3:'삼각 홈',4:'사각 홈',6:'육각 홈'}[sides])
        pocket=pocket_dimensions(candidate,direction)
        if pocket is not None:
            pocket.update(measurement_source='native_closed_prism',shape_label=candidate['label'],direction=axis.tolist())
            output.append((pocket,candidate))
    return output


def attach_verified_pockets(report,model):
    measured=measure_pockets(model,report['direction'])
    recognition=report.setdefault('external_feature_recognition',{})
    known=recognition.setdefault('verified_pockets',[]);existing={p['floor_face_id'] for p in known}
    geometry=[]
    for pocket,candidate in measured:
        if pocket['floor_face_id'] not in existing:
            known.append(pocket);existing.add(pocket['floor_face_id']);geometry.append(candidate)
    recognition['geometry_candidates']=recognition.get('geometry_candidates', [])+geometry
    native=next((f for f in report['findings'] if f['id']=='cnc_rectangular_pockets'),{})
    native_ids={p['floor_face_id'] for p in native.get('measurements',{}).get('pockets',[])}
    resolved = {p['floor_face_id'] for p,c in measured} & set(native.get('measurements',{}).get('unresolved_floor_face_ids',[]))
    if resolved:
        report.setdefault('native_rectangular_review', deepcopy(native))
        values = native['measurements']
        values['resolved_floor_face_ids'] = sorted(resolved)
        values['unresolved_floor_face_ids'] = remaining = [i for i in values['unresolved_floor_face_ids'] if i not in resolved]
        native['status'] = 'attention' if native_ids else 'unknown' if remaining or values.get('incomplete_boundary_face_ids') else 'not_applicable'
        native['reason'] = f"직사각 홈 {len(native_ids)}곳 · 추가 검산한 홈 {len(resolved)}곳은 ‘검산한 홈과 공구’에서 확인하세요."
        if remaining:
            native['reason'] += f' 내부 바닥 후보 {len(remaining)}곳의 치수는 미확정입니다.'
        if not native_ids:
            native['action'] = '검산한 홈과 공구 항목에서 치수와 수정할 코너를 확인하세요.'
        native['cad_face_ids'] = sorted(native_ids | set(remaining))
        native['face_indices'] = np.flatnonzero(np.isin(model.face_ids,native['cad_face_ids'])).tolist()
    added=[p for p,c in measured if p['floor_face_id'] not in native_ids and p.get('measurement_source')=='native_closed_prism']
    old=next((f for f in report['findings'] if f['id']=='cnc_learned_pockets'),None)
    old_rows=old.get('measurements',{}).get('pockets',[]) if old else []
    old_ids={p['floor_face_id'] for p in old_rows}
    added=[deepcopy(p) for p in added if p['floor_face_id'] not in old_ids]
    if not added:return report
    profile=report['profile']
    for p in added:
        p.update(internal_corner_radius_mm=0.,problems=['내부 코너 반경 0 mm'])
        for field,key,larger in (('width_too_small','tool_diameter_mm',True),('exceeds_flute_length','flute_length_mm',False),('exceeds_reach','reach_mm',False)):
            reference=p['entry_circle_diameter_mm'] if larger else p['wall_height_mm'];value=profile.get(key)
            p[field]=None if value is None else value>reference+1e-7 if larger else value<reference-1e-7
    rows=old_rows+added;ids=sorted({i for p in rows for i in p['face_ids']})
    finding=dict(id='cnc_learned_pockets',title='검산한 홈과 공구',status='attention',severity='review',
        reason=f'닫힌 홈 {len(rows)}곳 · 안쪽 코너 여유 필요',action='추천 공구에 맞는 안쪽 코너 반경을 적용하세요.',
        method='Learned face groups where available; exact native closed-floor, inward-wall and outward-rim certificates',
        evidence=['CNC_GEOMETRY'],measurements=dict(pockets=rows),cad_face_ids=ids,
        face_indices=np.flatnonzero(np.isin(model.face_ids,ids)).tolist(),limitations=[])
    if old:old.update(finding)
    else:report['findings'].append(finding)
    return report
