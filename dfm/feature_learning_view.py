"""Recognized CAD features stay one optional view below the final conclusion."""
import streamlit as st

def render_feature_candidates(model,report,direction):
    data=report.get('external_feature_recognition',{})
    candidates=data.get('candidates',[])
    if not candidates:return
    context=(model.fingerprint,tuple(direction))
    if st.session_state.get('external_feature_context') != context:
        st.session_state['external_feature_context']=context
        st.session_state['external_feature_panel']=False
        st.session_state['external_feature_selected']=0
    panel=st.expander(f'자동으로 찾은 세부 형상 · {len(candidates)}곳',
        key='external_feature_panel',on_change='rerun')
    if not panel.open:return
    with panel:
        if st.session_state.get('external_feature_selected',0) not in range(len(candidates)):
            st.session_state['external_feature_selected']=0
        selected=st.selectbox('살펴볼 부분',range(len(candidates)),key='external_feature_selected',
            format_func=lambda i:f"{candidates[i]['label']} · CAD 면 {', '.join(map(str,candidates[i]['face_ids']))}")
        c=candidates[selected]
        from .machining_view import machining_figure
        st.plotly_chart(machining_figure(model,report,direction=direction,cad_face_ids=c['face_ids']),key='external_feature_chart',width='stretch',config={'scrollZoom':False})
        st.caption('파랑 · 선택한 부분')
        exact=next((r for r in data.get('verified_pockets',[]) if set(r['face_ids'])==set(c['face_ids'])),None)
        if exact:
            a,b=st.columns(2)
            a.metric('포켓 안에 들어가는 원의 지름',f"Ø {exact['entry_circle_diameter_mm']:,.4g} mm",
                help='포켓 바닥 윤곽 안에 들어가는 가장 큰 원입니다. 공구 지름을 고를 때 비교하는 치수입니다.')
            b.metric('포켓 깊이',f"{exact['wall_height_mm']:,.4g} mm")
        else:
            hole=next((h for h in data.get('verified_holes', []) if set(h['face_ids']) == set(c['face_ids'])), None)
            if hole:
                a,b=st.columns(2)
                a.metric('구멍 지름',f"Ø {hole['diameter_mm']:,.4g} mm")
                b.metric('구멍 깊이',f"{hole['depth_mm']:,.4g} mm")
            else:st.metric('선택한 면의 넓이',f"{c['area_mm2']:,.4g} mm²")
