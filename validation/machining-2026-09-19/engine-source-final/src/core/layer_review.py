"""FDM section review with explicit incomplete scopes and no solid score inference."""
import math
import numpy as np

from src.core.geometry_analyzer import to_build_frame
from src.core.mesh_diagnostics import inspect_mesh
from src.core.sections import section_mesh, opening_residual
from src.core.section_index import FaceZIndex
from src.core.layer_regions import (meaningful_regions, classify_thin_regions,
                                    classify_difference_regions, comparison_scope)


def inspect_layers(mesh, build_direction=(0,0,1), layer_height=.2,
                   line_width=.4, critical_angle=45., max_layers=2000,
                   max_total_segments=2000000):
    """Review every midpoint or record limits; partial known area is never total area."""
    report=dict(method='fdm_layer_review_v3',status='unavailable',layers=[],
                layer_height_mm=float(layer_height),line_width_mm=float(line_width),
                critical_angle_deg=float(critical_angle),fill_rule='oriented_nonzero',
                checks=[],warnings=[],expected_layers=0,examined_layers=0,complete_layers=0,
                contour_coverage=0.,volume_estimate_mm3=None,total_score=None,
                thin_display_floor_mm2=float(.01*line_width**2),
                display_floor_mm2=float(.01*line_width**2),
                scope='Midpoint FDM sections; not a repaired solid, 3D thickness, support material prediction or print-success test.')
    if not (np.isfinite([layer_height,line_width,critical_angle]).all()
            and layer_height>0 and line_width>0 and 0<critical_angle<=90):
        raise ValueError('층 높이·선폭은 유한한 양수, FDM 임계각은 0도 초과 90도 이하여야 합니다.')
    diagnostic=inspect_mesh(mesh)
    if not diagnostic['geometry_available'] or len(mesh.faces)<4:
        report['reason']='유효한 좌표와 충분한 삼각형이 필요합니다.';return report
    if not mesh.is_winding_consistent:
        report['warnings'].append('입력 면 방향의 연결이 일관되지 않습니다. 이 함수는 면을 자동 반전하지 않으며 미확정 단면과 입력 진단을 확인해야 합니다.')
    try:
        import shapely as sh
    except ImportError:
        report['reason']='단면 검토 의존성 shapely가 없습니다. requirements-tested.txt로 설치하세요.';return report
    mbf=to_build_frame(mesh,build_direction)
    bottom,top=mbf.bounds[:,2];height=float(top-bottom)
    if height<=0 or not np.isfinite(height/layer_height):
        report['reason']='검토 가능한 빌드 높이가 없습니다.';return report
    count=int(math.ceil(height/layer_height-1e-10));report['expected_layers']=count
    if count<1 or count>max_layers:
        report['reason']=f'요청된 {count:,}개 층이 한도 {max_layers:,}개를 벗어납니다. 층 간격을 몰래 늘리지 않았습니다.';return report
    face_index=FaceZIndex(mbf)
    vertex_heights=np.unique(mbf.vertices[:,2])
    arithmetic_tol=np.finfo(float).eps*max(float(np.max(np.abs(mbf.vertices))),1.)*64
    materials=[];segments=0
    report['lateral_allowance_mm']=0. if critical_angle>=90 else layer_height/math.tan(math.radians(critical_angle))
    for i in range(count):
        span=min(layer_height,height-i*layer_height)
        z=float(bottom+i*layer_height+span/2);nominal_z=z
        section=section_mesh(mbf,[0,0,z],[0,0,1],axes=np.eye(3)[:2],
                             local_faces=face_index.sweep(z),vertex_projection=face_index.projection,
                             mesh_scale_mm=face_index.scale_mm)
        if not section.diagnostics['complete']:
            # Preserve the bounded lower-sided retry and its actual height.
            anchor=z
            near=vertex_heights[np.abs(vertex_heights-z)<=arithmetic_tol]
            if len(near):anchor=min(float(near.min()),z)
            below=vertex_heights[vertex_heights<anchor-arithmetic_tol]
            if len(below):
                gap=anchor-float(below[-1]);shifted=anchor-min(span*1e-6,gap/4)
                if bottom+i*layer_height<shifted<nominal_z:
                    retry=section_mesh(mbf,[0,0,shifted],[0,0,1],axes=np.eye(3)[:2],
                                       local_faces=face_index.query(shifted),vertex_projection=face_index.projection,
                                       mesh_scale_mm=face_index.scale_mm)
                    if retry.diagnostics['complete']:
                        retry.diagnostics['nominal_plane_diagnostics']=section.diagnostics
                        section,z=retry,float(shifted)
        d=section.diagnostics;segments+=d['segment_count']
        if segments>max_total_segments:
            report['warnings'].append('단면 선분 총량 한도에 도달했습니다. 나머지 층은 미검토입니다.');break
        material=section.material if d['complete'] else section.known_material
        if material is None:material=sh.GeometryCollection()
        row=dict(index=i,z_mm=z,nominal_z_mm=nominal_z,sampling_shift_mm=float(z-nominal_z),
                 thickness_mm=float(span),complete=d['complete'],
                 area_mm2=float(material.area) if d['complete'] else None,
                 perimeter_mm=float(material.length) if d['complete'] else None,
                 known_area_mm2=float(material.area),known_perimeter_mm=float(material.length),
                 thin_area_mm2=None,thin_regions=None,thin_detail_area_mm2=None,
                 thin_detail_regions=None,thin_candidate_area_mm2=None,thin_details=[],
                 unsupported_area_mm2=None,unsupported_islands=None,single_layer_area_mm2=None,
                 thin_full_scope=bool(d['complete']),unsupported_full_scope=False,
                 single_layer_full_scope=False,diagnostics=d)
        for prefix in ('unsupported', 'single_layer'):
            row.update({prefix+'_detail_area_mm2':None, prefix+'_detail_regions':None,
                        prefix+'_candidate_area_mm2':None, prefix+'_candidate_regions':None,
                        prefix+'_details':[], prefix+'_details_truncated':False})
        materials.append(material)
        if d['complete'] or material.area>0:
            try:
                _,_,metrics=classify_thin_regions(material,opening_residual(material,line_width),line_width,d['grid_mm'])
                row.update(metrics)
            except Exception as exc:
                row['metric_error']=f'단면 지표 계산 실패: {exc}'
            try:
                if i==0:
                    # The first layer uses the build plate as its reference.
                    _,_,metrics=classify_difference_regions(material,material,line_width,d['grid_mm'],'unsupported')
                    row.update(metrics)
                    row.update(unsupported_area_mm2=0.,unsupported_islands=0,
                               unsupported_scope_area_mm2=float(material.area),unsupported_full_scope=bool(d['complete']))
                else:
                    prior=report['layers'][-1];step=z-prior['z_mm']
                    reach=0. if critical_angle>=90 else step/math.tan(math.radians(critical_angle))
                    eligible=comparison_scope(material,[prior],reach)
                    row['unsupported_scope_area_mm2']=float(eligible.area)
                    if eligible.area>0 or (d['complete'] and material.is_empty):
                        previous=materials[-2];under=previous.buffer(reach) if reach else previous
                        _,_,metrics=classify_difference_regions(eligible,under,line_width,d['grid_mm'],'unsupported')
                        islands=[p for p in sh.get_parts(eligible) if not p.intersects(under)]
                        row.update(metrics)
                        row.update(unsupported_islands=len(islands),unsupported_full_scope=bool(d['complete'] and prior['complete']))
            except Exception as exc:
                row['support_error']=f'층간 지지 계산 실패: {exc}'
        report['layers'].append(row)
    rows=report['layers']
    report.update(examined_layers=len(rows),complete_layers=sum(r['complete'] for r in rows))
    if not rows:
        report['reason']='계산 한도 내에서 검토한 층이 없습니다.';return report
    report['contour_coverage']=report['complete_layers']/count
    report['shifted_layers']=sum(r['sampling_shift_mm']!=0 for r in rows)
    report['maximum_sampling_shift_mm']=max(abs(r['sampling_shift_mm']) for r in rows)
    report['known_component_layers']=sum(r['known_area_mm2']>0 for r in rows)
    report['partial_component_layers']=sum(not r['complete'] and r['known_area_mm2']>0 for r in rows)
    all_contours=len(rows)==count and all(r['complete'] for r in rows)
    for i,row in enumerate(rows):
        adjacent=[j for j in (i-1,i+1) if 0<=j<count]
        neighbors=[rows[j] if j<len(rows) else None for j in adjacent]
        if row['complete'] or row['known_area_mm2']>0:
            try:
                eligible=comparison_scope(materials[i],neighbors)
                row['single_layer_scope_area_mm2']=float(eligible.area)
                if eligible.area>0 or (row['complete'] and materials[i].is_empty):
                    combined=sh.union_all([materials[j] for j in adjacent if j<len(rows)])
                    _,_,metrics=classify_difference_regions(eligible,combined,line_width,row['diagnostics']['grid_mm'],'single_layer')
                    row.update(metrics)
                    row['single_layer_full_scope']=row['complete'] and all(n is not None and n['complete'] for n in neighbors)
            except Exception as exc:
                row['comparison_error']=f'층간 비교 실패: {exc}'
    positive=any(r['known_area_mm2']>0 for r in rows)
    metric_fields=('thin_area_mm2','unsupported_area_mm2','single_layer_area_mm2')
    if not positive:
        report['reason']='확인된 재료 단면이 없습니다. 열린 경계·면 방향 상쇄·계산 한도를 단면 진단에서 확인하세요.'
        for r in rows:
            for key in metric_fields:r[key]=None
            for prefix in ('thin','unsupported','single_layer'):
                r[prefix+'_candidate_area_mm2']=None
                r[prefix+'_detail_area_mm2']=None
    all_metrics=all_contours and all(all(r[k] is not None for k in metric_fields) for r in rows)
    if all_contours and positive:
        report['volume_estimate_mm3']=float(sum(r['area_mm2']*r['thickness_mm'] for r in rows))
    report['status']='complete' if all_metrics and positive else ('partial' if positive else 'unavailable')
    report['first_layer_area_mm2']=rows[0]['area_mm2'] if rows[0]['complete'] and positive else None
    report['first_layer_known_area_mm2']=rows[0]['known_area_mm2'] if positive else None
    def check(key,scope,label,explanation):
        prefix=key.removesuffix('_area_mm2')
        values=[r[key] for r in rows if r[key] is not None]
        found=[r['index'] for r in rows if r[key] is not None and r[key]>0]
        full=sum(r[key] is not None and r[scope] for r in rows)
        complete=positive and len(rows)==count and full==count
        detail_values=[r[prefix+'_detail_area_mm2'] for r in rows if r[prefix+'_detail_area_mm2'] is not None]
        candidate_values=[r[prefix+'_candidate_area_mm2'] for r in rows if r[prefix+'_candidate_area_mm2'] is not None]
        detail=any(x>0 for x in detail_values)
        state='risk' if found else ('details_only' if complete and detail else ('clear_in_layers' if complete else 'unresolved'))
        return dict(name=label,key=prefix,status=state,measured_layers=len(values),fully_measured_layers=full,
                    risk_layers=len(found),sum_mm2=float(sum(values)) if values else None,
                    detail_sum_mm2=float(sum(detail_values)) if detail_values else None,
                    detail_layers=sum((r[prefix+'_detail_area_mm2'] or 0)>0 for r in rows),
                    candidate_sum_mm2=float(sum(candidate_values)) if candidate_values else None,
                    layer_indices=found,description=explanation)
    report['checks']=[
        dict(name='단면 구성',status='clear_in_layers' if all_contours and positive else 'unresolved',
             measured_layers=len(rows),fully_measured_layers=report['complete_layers'],complete_layers=report['complete_layers'],
             description='층 전체의 확정과 손상 영역에서 분리된 닫힌 성분의 부분 검토를 구분합니다. 전체 면적을 추측하지 않습니다.'),
        check('thin_area_mm2','thin_full_scope','선폭 기준 얇은 단면 특징',
              '선폭 오프셋 소실 중 표시 하한 이상이거나 성분 전체가 소실된 영역입니다. 하한 미만 세부도 별도 기록합니다. 3D 최소 벽두께가 아닙니다.'),
        check('unsupported_area_mm2','unsupported_full_scope','지지·브리지 검토 영역',
              '이전 층과 경사 허용 범위로 지지되지 않는 영역을 우선 검토·작은 세부로 나눕니다. 성분 전체가 지지되지 않으면 크기와 무관하게 우선 검토합니다. 미확정 영향 성분은 제외하며 실제 브리지 가능성·재료량을 확정하지 않습니다.'),
        check('single_layer_area_mm2','single_layer_full_scope','한 층에만 나타나는 영역',
              '인접 층에 없는 영역을 우선 검토·작은 세부로 나눕니다. 성분 전체가 한 층에만 있으면 크기와 무관하게 우선 검토합니다. 비교 가능한 성분만 계산하며 전수 두께 검사가 아닙니다.')]
    report['thin_detail_sum_mm2']=float(sum(r['thin_detail_area_mm2'] or 0 for r in rows))
    report['thin_detail_layers']=sum((r['thin_detail_area_mm2'] or 0)>0 for r in rows)
    report['warnings'].extend([
        '단면 검토 완료는 해당 층들의 계산 완료입니다. 제조 가능 판정이나 원본 솔리드 복구를 뜻하지 않습니다.',
        '층 중간 평면을 사용하므로 층 높이보다 작은 수직 특징은 놓칠 수 있습니다. 선폭·층 높이를 실제 설정과 맞추세요.',
        f'작은 세부의 표시 하한은 선폭 제곱의 1%인 {report["thin_display_floor_mm2"]:g}mm²입니다. 검증된 제조 한계가 아니며, 세부 기록과 성분 전체 소실은 보존합니다.'])
    if report['shifted_layers']:
        report['warnings'].append(f"꼭짓점 근처의 수치 불안정을 피한 {report['shifted_layers']}개 층은 아래쪽 극한으로 재계산했습니다. 최대 높이 이동 {report['maximum_sampling_shift_mm']:.3g}mm이며 실제 계산 높이를 기록했습니다.")
    if not all_contours:
        report['warnings'].append('일부 단면이 미확정이므로 전체 부피 추정과 위험 미검출을 확정하지 않습니다. 부분 합산값은 확인 가능한 성분에만 해당합니다.')
    return report
