"""Combine learned placement with measured, condition-bound local CAD edits.

The edits specify target dimensions; they never stand in for regenerated CAD.
Unknown/partial sampling and unedited feature axes remain in the conclusion.
"""
from copy import deepcopy
import math
from amdfm.detail_summary import summarize_wall

def _positive(x):
    return isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) and x>0

def combine_am_plan(report,result,preferences=None):
    if not result.get('selected'):return result
    prefs=(report.get('review_context',{}).get('plan_preferences') or {}) | (preferences or {})
    if prefs.get('preserve_geometry') is True:return result
    profile=report.get('profile',{});edits=[];covered=[];pending=[];evidence=[]
    detail=report.get('details',{}).get('wall',{});limit=profile.get('minimum_wall_mm')
    wall=summarize_wall(detail,limit)
    if wall['status']=='attention' and _positive(limit):
        measured=wall['minimum_mm']
        # A chord is a local measurement, not a certified global minimum.
        edits.append(dict(field='minimum_wall_mm',label='표시된 얇은 구간의 목표 두께',before=measured,after=limit,unit='mm',
                          finding_id='wall',measurement_scope='normal-chord samples',cad_regenerated=False,
                          source_faces=wall['below_limit_face_indices']))
        covered.append('wall');evidence.append(f'벽 표본 {measured:g} mm / 목표 {limit:g} mm')
        if not wall['complete']:pending.append('벽 미측정 구간')
    hole_limit=profile.get('minimum_hole_mm')
    hole=next((f for f in report.get('findings',[]) if f.get('id')=='cad_holes'),{})
    cylinders=hole.get('measurements',{}).get('cylindrical_faces',[])
    if _positive(hole_limit):
        seen=set()
        for c in cylinders:
            if c.get('role')!='inner' or not _positive(c.get('diameter_mm')) or c['diameter_mm']>=hole_limit:continue
            # A split cylindrical surface may have several faces. Keep explicit
            # IDs rather than silently calling each face a separate hole.
            identifier=c.get('face_id')
            if identifier is None or identifier in seen:continue
            seen.add(identifier)
            edits.append(dict(field='diameter_mm',label=f'구멍 면 {identifier} 목표 지름',before=c['diameter_mm'],after=hole_limit,
                              unit='mm',cad_face_id=identifier,finding_id='cad_holes',cad_regenerated=False))
        if seen:
            covered.append('cad_holes');evidence.append(f'기준 미만 원통 면 {len(seen)}개 / 목표 지름 {hole_limit:g} mm')
            # Direction and diameter are distinct; diameter edits do not clear
            # transverse-hole or incomplete analytic recognition findings.
            if hole.get('status') in ('unknown','partial') or hole.get('measurements',{}).get('transverse_inner_face_count') not in (0,):
                pending.append('구멍 축 방향·천장 형상')
    if not edits:return result
    output=deepcopy(result);ranking=[]
    for old in output.get('ranking',[]):
        p=deepcopy(old);p['direction_keep_current']=p['keep_current'];p['keep_current']=False
        p['changes'].extend(deepcopy(edits));p['covered_finding_ids']=list(dict.fromkeys(p.get('covered_finding_ids',[])+covered))
        p['remaining']=list(dict.fromkeys(p.get('remaining',[])+pending))
        # Always retain a hole-axis check unless the raw record explicitly
        # reports no transverse groups and complete measurement scope.
        if 'cad_holes' in covered and ('구멍 축 방향·천장 형상' in pending):
            p['remaining_finding_ids']=list(dict.fromkeys(p.get('remaining_finding_ids',[])+['cad_holes']))
        if 'wall' in covered and not wall['complete']:
            p['remaining_finding_ids']=list(dict.fromkeys(p.get('remaining_finding_ids',[])+['wall']))
        names=[]
        if 'wall' in covered:names.append('벽 보강')
        if 'cad_holes' in covered:names.append('구멍 확대')
        names.append('현재 배치 유지' if p['direction_keep_current'] else p['orientation']['name']+' 배치')
        p['title']=' + '.join(names);p['evidence'].extend(evidence)
        p['verification_scope']=p.get('verification_scope','측정된 방향 비교')+'; 국소 목표 치수와 입력 기준 대조';p['cad_regenerated']=False
        ranking.append(p)
    lookup={p['id']:p for p in ranking}
    output['ranking']=ranking;output['selected']=lookup[output['selected']['id']]
    output['alternatives']=[lookup[p['id']] for p in output.get('alternatives',[])]
    output['status']='recommended';output['joint_planning']=dict(local_target_count=len(edits),covered=covered,
        source='CAD cylinder dimensions and measured wall samples; targets from selected conditions',cad_regenerated=False)
    return output

def direction_result(report,result):
    from .plan_learning import orientation_recommendation
    if not result.get('joint_planning'):return orientation_recommendation(report,result)
    result=deepcopy(result)
    for p in result.get('ranking',[]):p['keep_current']=p.get('direction_keep_current',p['keep_current'])
    if result.get('selected'):result['selected']['keep_current']=result['selected'].get('direction_keep_current',False)
    return orientation_recommendation(report,result)
