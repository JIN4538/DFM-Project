"""One report-wide decision; measurements, unresolved checks and plans stay distinct."""
from __future__ import annotations

import html
import json

from .advisor import prioritize_actions
from .learned_review import analyze_report


_SHORT = {
    'input': '입력 형상', 'cnc_input': 'CAD 입력', 'build': '배치 공간',
    'wall': '벽', 'layers': '층간 형상', 'cad_holes': '구멍', 'cavities': '밀폐 공간',
    'contact': '바닥', 'overhang': '하향면', 'sections': '단면',
    'cnc_holes': '구멍과 공구', 'cnc_rectangular_pockets': '포켓',
    'cnc_curved_corners': '내부 반경', 'cnc_visibility': '공구 접근',
    'cnc_tool_recommendation': '공구 제안 조건',
    'cnc_learned_pockets': '추가 포켓 코너',
}
_COMMANDS = {
    'wall': '얇은 벽을 보강하세요', 'layers': '가는 단면과 층간 지지를 보완하세요',
    'build': '배치 공간에 맞게 방향이나 크기를 바꾸세요',
    'cad_holes': '구멍의 지름·방향을 수정하세요',
    'cavities': '밀폐 공간의 내부 형상을 수정하세요',
    'contact': '평평한 면을 바닥으로 배치하세요',
    'overhang': '배치 방향과 하향면을 개선하세요',
    'cnc_holes': '구멍에 맞게 공구와 접근 방향을 바꾸세요',
    'cnc_rectangular_pockets': '포켓과 공구 치수를 맞추세요',
    'cnc_curved_corners': '공구에 맞게 내부 반경을 넓히세요',
    'cnc_visibility': '가려진 면을 향하도록 가공 방향을 바꾸세요',
    'cnc_tool_recommendation': '측정한 형상에 맞게 공구 치수를 조정하세요',
    'cnc_learned_pockets': '포켓 내부 코너에 공구 반경 여유를 추가하세요',
}


def _items(report, analysis):
    rows = []
    covered = set()
    for item in analysis.get('items', []):
        key = item['finding_id']
        if item['state'] == 'unavailable':
            if item.get('reason') == '크기 제한 미적용':
                covered.add(key)
            continue  # Retain raw unknown/attention unless explicitly N/A.
        covered.add(key)
        row = dict(id=key, label=_SHORT.get(key, item.get('label', key)),
                   state=item['state'], title=item.get('title', ''),
                   action=item.get('action', ''), evidence=item.get('evidence', []),
                   complete=item.get('complete', item['state'] == 'clear'),
                   reason=item.get('reason', ''), recommendations=item.get('recommendations', []),
                   action_kind='candidate' if item['state'] == 'confirmed' else 'condition')
        rows.append(row)
    for finding in report.get('findings', []):
        key, state = finding.get('id'), finding.get('status')
        if key in covered or key == 'sections' or state == 'not_applicable':
            continue
        # Auxiliary section sampling is available on demand, not a missing
        # manufacturing criterion. Unknown mandatory geometry remains visible.
        rows.append(dict(id=key, label=_SHORT.get(key, finding.get('title', key)),
                         state='confirmed' if state == 'attention' else
                               'review' if state in ('unknown', 'partial') else 'clear',
                         title=finding.get('title', ''), action=finding.get('action', ''),
                         evidence=[finding.get('reason', '')], reason=finding.get('reason', ''),
                         complete=state not in ('unknown', 'partial'), recommendations=[],
                         action_kind='candidate' if state == 'attention' else 'condition'))
    return prioritize_actions(rows, report.get('review_context', {}))


def summarize_conclusion(report, *, plan_result=None):
    """No model score can clear a measured violation or unknown geometry."""
    analysis = analyze_report(report)
    rows = _items(report, analysis)
    issues = [x for x in rows if x['state'] == 'confirmed']
    pending = [x for x in rows if x['state'] == 'review']
    partial = [x for x in issues if not x['complete']]
    blockers = [x for x in rows if x['id'] in ('input', 'cnc_input', 'assembly', 'shells', 'surface_input')
                and x['state'] != 'clear']
    if plan_result is None:
        from .enhanced_planning import recommend_plan
        plan_result = recommend_plan(report, preferences=report.get('review_context', {}).get('plan_preferences'))
    selected = plan_result.get('selected') or {}
    orientation = None
    process = report.get('profile', {}).get('process', report.get('process'))
    if process in ('MEX', 'VPP', 'PBF_POLYMER', 'PBF_METAL'):
        from .enhanced_planning import orientation_recommendation
        orientation = orientation_recommendation(report, plan_result)
    first = (blockers or issues or pending or [None])[0]
    if blockers:
        level, title = 'error', '입력 형상을 먼저 수정하세요'
    elif issues:
        level, title = 'warning', _COMMANDS.get(first['id'], '표시된 문제를 먼저 수정하세요')
    elif pending or not rows:
        level, title = 'info', '결론을 완성하려면 추가 확인이 필요합니다'
    else:
        level, title = 'success', '검토한 항목에서 수정할 문제가 없습니다'
    if not blockers and orientation and orientation.get('action') == 'apply':
        direction = orientation.get('recommended', {}).get('name', '')
        if not issues:
            level, title = 'info', f'{direction} 방향으로 배치하세요'
        elif first['id'] in ('overhang', 'contact', 'build'):
            title = f'{direction} 방향으로 바꾸고 남은 문제를 수정하세요'
    if not blockers and selected and process == 'MILLING_3AXIS':
        # A selected numeric plan does not imply unknown geometry was resolved.
        if issues and first['id'] in selected.get('covered_finding_ids',[]):
            title = selected.get('title') or title
    if not blockers and plan_result.get('joint_planning'):
        title=selected['title']+'하세요'
    actions = []
    for item in blockers or issues:
        text = item['action'] or item['title']
        actions.append(dict(id=item['id'], label=item['label'], text=text,
                            evidence=item['evidence'], recommendations=item['recommendations']))
    covered = set(selected.get('covered_finding_ids', [])) - set(selected.get('remaining_finding_ids', []))
    if selected.get('remaining'):
        # The plan explicitly lists its residual issues. Do not repeat the old
        # generic action, which can suggest geometry edits forbidden by the
        # user's tool-only constraint or re-list already addressed conflicts.
        covered.update(selected.get('covered_finding_ids', []))
    visible_actions = actions if blockers else [x for x in actions if x['id'] not in covered]
    counts = f"수정 {len(issues)}건 · 추가 확인 {len(pending) + len(partial)}건"
    if not issues and not pending and not partial:
        counts = f"확인한 항목 {sum(x['state'] == 'clear' for x in rows)}개"
    return dict(schema='dfm-conclusion-1', level=level, title=title, counts=counts,
                issues=issues, pending=pending, partial=partial, items=rows,
                blockers=blockers, actions=actions, visible_actions=visible_actions, first=first,
                plan=plan_result, orientation=orientation, analysis=analysis)


def conclusion_html(report):
    """Same single conclusion as the screen, escaped and with folded evidence."""
    summary = summarize_conclusion(report)
    esc = lambda x: html.escape(str(x), quote=True)
    parts = [f"<h2>종합 결론</h2><div class='decision {summary['level']}'><h3>{esc(summary['title'])}</h3>",
             f"<p>{esc(summary['counts'])}</p>"]
    from .tool_recommendation_presentation import tool_summary_html
    parts.append(tool_summary_html(report))
    selected = summary['plan'].get('selected') or {}
    if selected and selected.get('changes') and not summary['blockers']:
        parts.append(f"<p><b>추천 개선안</b> · {esc(selected.get('title', ''))}</p>")
        parts.append('<ul>' + ''.join(f"<li>{esc(change_text(x))}</li>" for x in selected.get('changes', [])) + '</ul>')
    if summary['visible_actions']:
        parts.append('<ol>' + ''.join(f"<li>{esc(x['text'])}</li>" for x in summary['visible_actions'][:3]) + '</ol>')
    if selected.get('remaining') and not summary['blockers']:
        parts.append('<p>함께 확인: ' + esc(' · '.join(selected['remaining'])) + '</p>')
    if summary['pending'] or summary['partial']:
        parts.append('<p>추가 확인: ' + esc(' · '.join(x['label'] for x in summary['pending'] + summary['partial'])) + '</p>')
    parts.append('</div><details><summary>판단 근거·전체 항목</summary>')
    for row in summary['items']:
        state = {'confirmed':'수정','review':'추가 확인','clear':'확인됨'}[row['state']]
        parts.append(f"<p><b>{esc(row['label'])} · {state}</b> · {esc(' / '.join(row['evidence']))}<br>{esc(row['action'])}</p>")
    record = dict(selection_source=summary['plan'].get('selection_source'), model=summary['plan'].get('model'),
                  check_model={key:summary['analysis'].get('model',{}).get(key) for key in ('id','sha256')},
                  learning=summary['plan'].get('learning'), selected_plan_id=selected.get('id'),
                  checks=[{key:item.get(key) for key in ('finding_id','state','origin','complete')}
                          for item in summary['analysis'].get('items',[])])
    search = report.get('neural_search') or {}
    if search:
        record['neural_search'] = {k:search.get(k) for k in ('status','model_id','model_sha256','neural_query_count','facet_query_count','added_count')}
    rl = summary['plan'].get('reinforcement_planning') or {}
    if rl:
        record['reinforcement_planning'] = {k:rl.get(k) for k in ('status','model','adopted','reason','proposal_conflicts','baseline_conflicts')}
    if summary['plan'].get('verified_selection'):
        record['verified_selection'] = summary['plan']['verified_selection']
    parts.append('</details><details><summary>추천·학습 기록</summary><p>전체 후보·측정 기록은 JSON 결과에 있습니다.</p><pre>' +
                 esc(json.dumps(record, ensure_ascii=False, indent=2)) + '</pre></details>')
    return ''.join(parts)


def change_text(change):
    labels = {'tool_diameter_mm': '공구 지름', 'flute_length_mm': '날 길이', 'reach_mm': '돌출 길이',
              'width_mm': '포켓 폭', 'wall_height_mm': '포켓 벽 높이', 'diameter_mm': '구멍 지름',
              'radius_mm': '내부 반경', 'minimum_wall_mm': '벽 두께', 'direction': '방향'}
    def value(x):
        if isinstance(x, float):
            return f'{x:,.4g}'
        return '미입력' if x is None else str(x)
    field = change.get('field', '')
    if change.get('cad_regenerated') is False and change.get('label'):
        return f"{change['label']} · {value(change.get('before'))} → {value(change.get('after'))} {change.get('unit','')}"
    face = change.get('cad_face_id', change.get('face_id', change.get('floor_face_id')))
    location = f' (CAD 면 {face})' if face is not None else ''
    return f"{change.get('label') or labels.get(field, field or '변경')}{location} · {value(change.get('before'))} → {value(change.get('after'))} {change.get('unit', '')}".strip()
