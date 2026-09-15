"""User decisions derived from recorded evidence, without changing measurements."""
import math
from .detail_summary import summarize_wall, summarize_layers
from .section_summary import summarize_sections


def summarize_review(report):
    profile = report['profile']
    details = report.get('details', {})
    items = []
    for f in report['findings']:
        key, status = f['id'], f['status']
        item = dict(id=key, label=f['title'], observation=f['reason'], next_action=f['action'],
                    target='설계 조치', focus=None,
                    state={'attention':'확인할 후보 있음', 'observed':'측정됨',
                           'not_detected':'후보 미검출', 'unknown':'추가 정보 필요',
                           'not_applicable':'이 공정에 미적용'}[status],
                    level='warning' if status=='attention' else 'info', needs_action=status in ('attention','unknown'))
        if key == 'build':
            if profile.get('build_volume_mm') is None:
                item.update(state='크기 제한 미적용', needs_action=False,
                            observation='부품 크기를 제한하지 않고 필요한 배치 공간을 계산했습니다.',
                            next_action='장비를 정하면 왼쪽 「빌드 공간과 층 설정」에서 실제 공간과 여유를 입력하세요.')
            elif status == 'observed':
                item.update(state='입력 공간에 들어감', level='success')
            item['target']='방향 비교'
        elif key == 'input' and status == 'observed':
            item.update(state='기본 형상 검사 통과', level='success')
        elif key == 'overhang':
            item['target']='방향 비교'
            if status == 'not_detected':
                if f.get('measurements',{}).get('threshold_equal_face_count'):
                    item.update(state='기준 각도 부근의 면을 추가 확인',level='info',needs_action=True)
                else:
                    item.update(level='success', next_action='현재 각도 조건에서는 하향면 수정 후보가 없습니다. 벽·내부 형상 검토를 이어가세요.')
        elif key == 'contact' and status == 'observed':
            area=f['measurements'].get('area_mm2')
            item.update(state='평평한 접촉면 있음', observation=f'바닥의 평평한 면을 {area:.4g} mm² 관측했습니다. 접착력은 별도로 확인합니다.')
        elif key == 'cad_holes' and status == 'observed':
            count=f['measurements'].get('inner_face_count')
            if count == 0:
                item.update(state='내측 원통면 미검출', next_action='원통형이 아닌 구멍과 열린 통로는 3D 형상에서 별도로 확인하세요.')
            elif profile.get('minimum_hole_mm') is None:
                item.update(state='홀 기준 미입력', needs_action=True,
                            next_action='왼쪽 「장비·재료와 검토 기준」에 최소 홀 기준을 입력하고 다시 설계 검토하세요.')
        elif key == 'cavities' and status == 'not_detected':
            item.update(level='success', observation='CAD 솔리드에서 완전히 밀폐된 내부 경계가 검출되지 않았습니다.',
                        next_action='열린 채널의 좁은 목과 배출·청소 경로는 형상에서 따로 확인하세요.')
        elif key == 'wall':
            s=summarize_wall(details.get('wall'), profile.get('minimum_wall_mm'))
            item.update(state=s['title'], observation=s['observation'], next_action=s['next_action'],
                        level=s['level'], needs_action=s['level']!='success', target='정밀 검토', focus='벽')
        elif key == 'sections':
            item.update(target='정밀 검토', focus='단면', needs_action=False)
            if details.get('sections'):
                s=summarize_sections(details['sections'], profile['process'], report['geometry'].get('mesh_signed_volume_mm3'))
                item.update(state=s['completion_title'], observation=s['change_text'], next_action=s['next_step'],
                            level=s['completion_level'], needs_action=s['completion_level']=='warning')
            else:
                item.update(state='아직 실행하지 않음 · 필요할 때 단면 확인', observation='높이에 따라 단면 모양과 넓이가 어떻게 변하는지 살펴보는 보조 검사입니다.')
        if status=='not_detected' and key not in ('overhang','cavities'):
            item['level']='success'
        items.append(item)
    if profile['process']=='MEX':
        s=summarize_layers(details.get('layers'))
        items.append(dict(id='layers', label='MEX 층간 관계', state=s['title'], observation=s['observation'],
                          next_action=s['next_action'], level=s['level'], needs_action=s['level']!='success',
                          target='정밀 검토', focus='층간'))
    attention=[x for x in items if x['level']=='warning']
    pending=[x for x in items if x['needs_action'] and x['level']!='warning']
    first=(attention or pending or [None])[0]
    if attention:
        title=f"확인할 항목이 {len(attention)}개 있습니다"
        observation='아래에서 위치와 이유를 확인하세요. 후보가 있다는 사실만으로 제작 불가를 뜻하지는 않습니다.'
    elif pending:
        title='지금까지 검출된 수정 후보는 없고, 추가 확인이 남아 있습니다'
        observation='측정 전인 항목이나 비교 기준이 없는 항목은 아직 괜찮다고 판단하지 않았습니다.'
    else:
        title='실행한 검사에서 우선 수정할 후보가 없습니다'
        observation='표시된 검사 범위의 결과입니다. 실제 제작 전 장비·재료 조건과 슬라이서 설정을 확인하세요.'
    return dict(level='warning' if attention else 'info', title=title, observation=observation,
                next_action=first['next_action'] if first else '보고서를 저장하고 실제 제작 조건을 확인하세요.',
                next_item=first, checklist=items, attention_count=len(attention), pending_count=len(pending))


def ranked_orientations(report, goal):
    """Rank by one explicit measured objective; never call this a process optimum."""
    field={'높이를 낮추기':'height_mm', '하향면 후보 줄이기':'overhang_projected_area_sum_mm2',
           '평평한 바닥 넓히기':'contact_triangle_area_mm2'}[goal]
    reverse=goal=='평평한 바닥 넓히기'
    rows=[r for r in report['orientations'] if isinstance(r.get(field),(int,float))
          and not isinstance(r[field],bool) and math.isfinite(r[field]) and r[field]>=0]
    # Respect explicitly enabled space constraints; an unfitting candidate is not recommended.
    return sorted(rows, key=lambda r:(r.get('build_fit') is False, -r[field] if reverse else r[field], r['name']))
