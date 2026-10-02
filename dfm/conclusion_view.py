"""Conclusion first, supporting detail only on request."""
from __future__ import annotations

import json
import streamlit as st

from .conclusion import summarize_conclusion, change_text


_LOCATION_LABELS = {'wall':'벽 두께', 'layers':'층별 얇은 부분·받침', 'overhang':'아래로 향한 면',
                    'contact':'바닥 접촉', 'cad_holes':'구멍 크기', 'cavities':'막힌 내부 공간',
                    'cnc_holes':'구멍과 공구', 'cnc_curved_corners':'안쪽 코너',
                    'cnc_learned_pockets':'홈 안쪽 코너', 'cnc_rectangular_pockets':'홈과 공구',
                    'cnc_visibility':'공구가 닿는 면', 'cnc_tool_recommendation':'제안 공구 조건'}
_LOCATION_LABELS['cnc_hole_entry'] = '구멍 입구 방향'


def render_conclusion(report, on_select=None, on_direction=None, key_prefix='am'):
    summary = summarize_conclusion(report)
    report['conclusion'] = {k: v for k, v in summary.items() if k != 'analysis'}
    report['learned_review'] = summary['analysis']
    report['plan_recommendation'] = summary['plan']
    st.subheader('종합 결론', anchor='dfm-final-conclusion')
    identity = json.dumps([report.get('model_fingerprint'), report.get('timestamp_utc'), report.get('profile'),
                           report.get('review_context'), report.get('direction'), report.get('current_orientation',{}).get('direction')],
                          sort_keys=True, ensure_ascii=False)
    if st.session_state.get(key_prefix + '_conclusion_anchor') != identity:
        st.session_state[key_prefix + '_conclusion_anchor'] = identity
        # Fixed app-owned anchor only: no report text or other untrusted content
        # enters JavaScript. A completed review should land on its conclusion,
        # not retain the scroll position of the previous model preview.
        if not st.session_state.get(key_prefix + '_location_jump_pending'):
            st.html('''<script>requestAnimationFrame(() => requestAnimationFrame(() => {
          const heading = document.getElementById('dfm-final-conclusion');
          if (heading) { heading.style.scrollMarginTop = '6rem'; heading.scrollIntoView({block:'start', behavior:'instant'}); }
        }));</script>''', unsafe_allow_javascript=True)
    with st.container(border=True):
        getattr(st, summary['level'])(summary['title'])
        st.caption(summary['counts'])
        from .tool_recommendation_presentation import render_tool_summary
        render_tool_summary(report)
        selected = summary['plan'].get('selected') or {}
        if selected and selected.get('changes') and not summary['blockers']:
            st.markdown('**추천 개선안 · ' + selected.get('title', '') + '**')
            changes = [change for change in selected.get('changes', []) if change.get('field') != 'direction']
            for change in changes[:4]:
                st.write(change_text(change))
            if len(changes) > 4:
                with st.expander(f'전체 변경 {len(changes)}개'):
                    for change in changes:
                        st.write(change_text(change))
        actions = summary['visible_actions']
        if actions:
            # A compact ordered list, not independent and competing verdict cards.
            for i, item in enumerate(actions[:3], 1):
                st.markdown(f"**{i}. {item['label']}** · {item['text']}")
        elif summary['pending'] and not selected:
            first = summary['pending'][0]
            st.write(first['action'] or first['reason'])
        elif not selected:
            st.write('현재 설계를 유지하고 결과를 저장하세요.')
        orientation = summary.get('orientation')
        if orientation and not summary['blockers']:
            best = orientation.get('recommended')
            if best and orientation.get('action') == 'apply' and on_direction is not None:
                st.button(f"{best['name']} 방향 적용", key=key_prefix + '_apply_plan', type='primary',
                          on_click=on_direction, args=(best['direction'],))
            elif orientation.get('keep_current'):
                st.caption('배치 방향 · 현재 방향 유지')
        first = summary.get('first')
        if first and on_select:
            st.button('문제 위치 보기' if summary['issues'] or summary['blockers'] else '확인할 항목 보기',
                      key=key_prefix + '_conclusion_location', on_click=on_select, args=(first['id'],))
        # Every unresolved item is reachable from the conclusion, without first
        # opening evidence and then hunting for a second location control.
        others = [item for item in summary['items'] if item['state'] != 'clear'
                  and (not first or item['id'] != first['id'])]
        if others and on_select:
            with st.container(horizontal=True):
                for item in others:
                    st.button(_LOCATION_LABELS.get(item['id'], item['label'])+' 확인',
                              key=f"{key_prefix}_quick_{item['id']}", on_click=on_select, args=(item['id'],))
        if (summary['pending'] or summary['partial']) and not on_select:
            st.caption('추가 확인 · ' + ' · '.join(x['label'] for x in summary['pending'] + summary['partial']))
        if selected.get('remaining') and not summary['blockers']:
            st.caption('개선안 적용 후 남는 항목 · ' + ' · '.join(selected['remaining'][:2]))
            if len(selected['remaining']) > 2:
                with st.expander(f"남는 항목 전체 {len(selected['remaining'])}개"):
                    for item in selected['remaining']:
                        st.write(item)

    with st.expander('판단 근거·전체 조치', expanded=False):
        from .tool_recommendation_presentation import render_tool_evidence
        render_tool_evidence(report)
        for item in summary['items']:
            state = {'confirmed': '수정', 'review': '추가 확인', 'clear': '확인됨'}[item['state']]
            st.markdown(f"**{item['label']} · {state}**")
            if item['evidence']:
                st.write(' / '.join(item['evidence']))
            if item['state'] != 'clear':
                st.write(item['action'] or item['reason'])
                if on_select:
                    st.button('위치·측정값', key=f"{key_prefix}_learned_{item['id']}",
                              on_click=on_select, args=(item['id'],))
            if item.get('recommendations') and len(item['recommendations']) > 1:
                for suggestion in item['recommendations']:
                    st.caption(suggestion['action'])

    alternatives = summary['plan'].get('alternatives') or []
    if alternatives:
        with st.expander('다른 개선안 비교', expanded=False):
            from .enhanced_planning import record_plan_preference
            st.caption('선호를 저장하면 다음 추천에 반영합니다.')
            def prefer(identifier):
                try:
                    record_plan_preference(report, identifier, preferences=report.get('review_context', {}).get('plan_preferences'))
                    st.session_state[key_prefix + '_preference_saved'] = True
                except (OSError, ValueError) as exc:
                    st.session_state[key_prefix + '_preference_error'] = str(exc)
            if selected:
                st.button('현재 추천안을 선호함', key=key_prefix + '_prefer_selected',
                          on_click=prefer, args=(selected['id'],))
            for plan in alternatives[:4]:
                st.markdown('**' + plan.get('title', '') + '**')
                for change in plan.get('changes', []):
                    st.caption(change_text(change))
                if plan.get('remaining'):
                    st.caption('남는 항목 · ' + ' · '.join(map(str, plan['remaining'])))
                st.button('이 개선안을 선호함', key=key_prefix + '_prefer_' + plan['id'],
                          on_click=prefer, args=(plan['id'],))
            if st.session_state.pop(key_prefix + '_preference_saved', False):
                st.success('선호를 반영했습니다.')
            error = st.session_state.pop(key_prefix + '_preference_error', None)
            if error:
                st.error(error)
    with st.expander('추천·학습 기록', expanded=False):
        search = report.get('neural_search', {})
        if search.get('measured_count', search.get('added_count')):
            st.markdown('**딥러닝 방향 탐색**')
            counts = [f"신경망 제안 {search.get('neural_query_count', 0)}개", f"큰 평면 후보 {search.get('facet_query_count', 0)}개"]
            if search.get('geometry_query_count'):
                counts.append(f"높이 계산 후보 {search['geometry_query_count']}개")
            st.write(' · '.join(counts) + '를 추가 계산했습니다.')
            orientation = selected.get('orientation') or {}
            origin = orientation.get('proposal_source')
            st.caption('최종 배치: ' + ('추가 기하 계산으로 비교한 방향' if orientation.get('acquisition_method')
                       else '신경망이 찾은 방향' if origin == 'deep_neural_surrogate'
                       else '큰 평면을 활용한 방향' if origin == 'geometric_facet_seed' else '기존 비교 방향 또는 현재 방향'))
        elif search.get('reason'):
            st.caption('추가 방향 탐색: ' + search['reason'])
        if search.get('height_resolution_filter'):
            filtered = search['height_resolution_filter']
            st.caption(f"높이 감소가 {filtered['threshold_mm']:g} mm 이하인 추가 후보 {len(filtered['omitted_names'])}개는 추천에서 제외했습니다. 비교 기준은 CAD 메시 설정과 기존 높이의 0.1% 중 작은 값입니다.")
        reinforcement = summary['plan'].get('reinforcement_planning') or {}
        if reinforcement.get('model'):
            st.markdown('**강화학습 순차 개선**')
            st.write(reinforcement.get('reason', '수정 순서를 생성하고 치수 조건을 다시 검사했습니다.'))
            for step in reinforcement.get('steps', []):
                changes = ' · '.join(change_text(change) for change in step.get('changes', []))
                st.caption(f"{step['number']}. {changes}")
        if summary['plan'].get('learning', {}).get('choices'):
            from .plan_learning import reset_plan_preferences
            def reset_preference():
                try:
                    reset_plan_preferences(report, preferences=report.get('review_context', {}).get('plan_preferences'))
                except (OSError, ValueError) as exc:
                    st.session_state[key_prefix + '_reset_error'] = str(exc)
            st.button('저장한 선호 초기화', key=key_prefix + '_reset_preference', on_click=reset_preference)
        reset_error = st.session_state.pop(key_prefix + '_reset_error', None)
        if reset_error:
            st.error(reset_error)
        model = summary['plan'].get('model') or {}
        st.write('개선안 선택: ' + str(summary['plan'].get('selection_source', '조건 비교')))
        if model:
            st.json(model, expanded=False)
        st.json(summary['plan'], expanded=False)
        if search:
            st.json(search, expanded=False)
    return {x['id'] for x in summary['items']}
