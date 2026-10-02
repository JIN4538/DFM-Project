"""Show actions and their evidence together, without a second analysis tab."""
from __future__ import annotations

import json
import pandas as pd
import streamlit as st

from .detail import attach_detail
from .detail_view import decision_card, render_wall_result, render_layer_result
from .presentation import model_figure
from .section_view import render_section_result
from .workflow import summarize_review, action_plan
from dfm.conclusion_view import render_conclusion
from dfm.location_navigation import location_heading, finish_location_navigation


def render_actions(model, report, profile, recommendation, *, on_apply, presets,
                   on_navigate, criterion_controls, detail_runner, hole_controls=None):
    overview, plan = summarize_review(report), action_plan(report)
    displayed = render_conclusion(
        report, on_select=lambda finding_id: on_navigate('설계 조치', None, finding_id),
        on_direction=lambda vector: on_apply(vector, presets),
        key_prefix='am')
    findings={f['id']:f for f in report['findings']}
    explanations={x['id']:x for x in overview['checklist']}
    identity=(report['model_fingerprint'],report['timestamp_utc'],
              json.dumps(report.get('review_context',{}),sort_keys=True,ensure_ascii=False))
    if st.session_state.get('finding_result')!=identity or st.session_state.get('highlight_finding') not in explanations:
        st.session_state['finding_result']=identity
        first_learned = next((row['id'] for row in report.get('conclusion',{}).get('items',[])
                              if row['id'] in explanations and row['state']=='confirmed'), None)
        primary = plan['primary']['id'] if plan['primary'] else None
        st.session_state['highlight_finding']='input' if primary=='input' else first_learned or primary or 'overhang'
        st.session_state['am_location_details']=False
    pending=st.session_state.pop('pending_finding',None)
    if pending in explanations:
        st.session_state['highlight_finding']=pending
        st.session_state['am_location_details']=True
    if not st.toggle('문제 위치·측정값 보기',key='am_location_details'):
        return
    location_heading('am')
    _render_location(model,report,profile,explanations,findings,overview,
                     on_navigate,criterion_controls,detail_runner,hole_controls)
    with st.expander('전체 검토 현황 · 측정 근거'):
        st.dataframe(pd.DataFrame([{'항목':x['label'],'현재 판단':x['state'],'다음 행동':x['next_action']}
                                  for x in overview['checklist']]),hide_index=True)
    finish_location_navigation('am')


def _render_location(model, report, profile, explanations, findings, overview,
                     on_navigate, criterion_controls, detail_runner, hole_controls=None):
    selected=st.selectbox('확인할 항목 · 위치와 조치를 바로 표시합니다',list(explanations),
                         format_func=lambda k:explanations[k]['label']+' · '+explanations[k]['state'],
                         key='highlight_finding')
    explanation=explanations[selected]
    if selected in ('wall','layers','sections'):
        detail=report.get('details',{}).get(selected)
        if not detail or detail.get('status') not in ('measured','complete','not_applicable'):
            st.caption('미완료 항목입니다. 시간을 늘려 추가 계산할 수 있습니다.')
            if st.button('이 항목 추가 계산',key='inline_retry_'+selected):
                with st.spinner('선택한 항목을 더 확인하는 중…'):
                    options={'sampling':'auto'} if selected=='sections' else {}
                    result=detail_runner(model,profile,report['current_orientation']['direction'],
                        mode=selected,timeout_s=60 if selected=='wall' else 90,**options)
                st.session_state['report']=attach_detail(report,result)
                st.rerun()
        if selected=='wall':
            render_wall_result(model,report,criterion_controls=criterion_controls)
        elif selected=='layers':
            render_layer_result(model,report)
        elif detail:
            render_section_result(detail,profile.process,report['geometry'].get('mesh_signed_volume_mm3'))
        else:
            decision_card({**explanation,'title':explanation['state']})
        return

    finding=findings[selected]
    left,right=st.columns([3,2])
    with right:
        decision_card({**explanation,'title':explanation['state']})
        if selected=='cad_holes' and hole_controls:
            if profile.minimum_hole_mm is None:
                hole_controls()
            else:
                with st.expander('비교할 구멍 지름 바꾸기'):
                    hole_controls()
        if explanation['target']=='방향 비교':
            st.button('추천 방향과 형상 비교하기',key='finding_action',on_click=on_navigate,args=('방향 비교',None))
        with st.expander('원본 측정값'):
            st.caption(f"CAD 면 번호: {', '.join(map(str,finding['cad_face_ids'][:20])) or '위치 번호 없음'}")
            st.json({k:v for k,v in finding['measurements'].items() if k not in ('samples','problem_face_indices','cylindrical_faces')},expanded=False)
    with left:
        transparent=st.toggle('부품을 투명하게 보기',value=False,key='transparent_model')
        st.plotly_chart(model_figure(model,report,selected,transparent=transparent),width='stretch',config={'scrollZoom':False})
        st.caption('주황색: 확인할 면 · 녹색 화살표: 재료가 쌓이는 방향')
        if not finding['face_indices']:
            st.caption('표시할 면 위치 없음')
        if len(model.mesh.faces)>250_000:st.caption('화면은 삼각형 일부를 표시합니다. 분석과 내보내기는 전체 원본 형상을 사용합니다.')
        if selected=='cad_holes' and finding['measurements'].get('cylindrical_faces'):
            st.dataframe(pd.DataFrame([{'CAD 면':c['face_id'],'역할':{'inner':'내측 원통','outer':'외측 원통'}.get(c['role'],'미확정'),
                '지름 (mm)':c['diameter_mm'],'축 (모델 좌표)':', '.join(f'{v:.3g}' for v in c['axis'])}
                for c in finding['measurements']['cylindrical_faces']]),hide_index=True)
            st.caption('CAD 원통면의 해석 값입니다. 원통면 수는 구멍 수와 다르고, 설계 공차·관통 여부를 포함하지 않습니다.')
