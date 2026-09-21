"""Explain detailed checks before presenting diagnostic numbers."""
import math
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .detail_summary import summarize_wall, summarize_layers
from .presentation import model_figure
from .visuals import wall_samples


def decision_card(summary):
    with st.container(border=True):
        getattr(st, summary['level'])(summary['title'])
        st.write(summary['observation'])
        st.markdown(f"**다음에 할 일** · {summary['next_action']}")


def render_wall_result(model, report, *, criterion_controls=None):
    detail=report.get('details', {}).get('wall')
    summary=summarize_wall(detail, report['profile'].get('minimum_wall_mm'))
    decision_card(summary)
    if summary.get('minimum_mm') is None:
        return
    cols=st.columns(2)
    cols[0].metric('표본에서 가장 짧게 측정한 거리', f"{summary['minimum_mm']:.4g} mm")
    limit=summary.get('minimum_wall_mm')
    cols[1].metric('내가 입력한 최소 벽 기준', f'{limit:g} mm' if limit is not None else '미입력')
    st.caption(summary['scope'])
    if criterion_controls is not None:
        criterion_controls()
    st.markdown('**어디를 확인하나요?**')
    samples=wall_samples(report)
    selected=None
    if samples:
        identity=(report.get('model_fingerprint'),detail.get('elapsed_seconds'),report.get('timestamp_utc'))
        if st.session_state.get('wall_sample_result')!=identity or st.session_state.get('wall_sample') not in range(len(samples)):
            st.session_state['wall_sample_result']=identity
            st.session_state['wall_sample']=0
        selected=st.selectbox('확인할 측정 위치 · 짧은 거리순',list(range(len(samples))),
            format_func=lambda i:f"표본 {i+1} · {samples[i]['normal_chord_mm']:.5g} mm · 메시 면 {samples[i]['source_face']}",
            key='wall_sample')
        point=samples[selected]['point_mm']
        st.caption('선택 위치(원본 모델 좌표 mm): '+', '.join(f'{v:.5g}' for v in point))
    if limit is not None:
        st.write('붉은 ◆는 기준 미만, 회색 ●는 기준 이상으로 측정된 표본입니다. 주황 ◆와 숫자는 선택한 위치입니다. 표본 밖의 벽은 이 색으로 판단하지 않습니다.')
    else:
        st.write('점이 실제 측정 위치입니다. 짧은 거리는 진한 파랑, 긴 거리는 옅은 파랑으로 표시합니다. 주황 ◆와 숫자가 선택한 표본이며, 색 자체가 기준 미달을 뜻하지 않습니다.')
    if samples:
        see_through=st.toggle('반대쪽·내부 표본도 보기',value=True,key='wall_transparent')
        st.plotly_chart(model_figure(model,report,'wall',transparent=see_through,selected_sample=selected),width='stretch',config={'scrollZoom':False})
    else:
        st.info('이 기록에는 표본 좌표가 없습니다. 측정값만 표시하며 면 전체를 측정 위치로 대신 칠하지 않습니다.')
    with st.expander('측정 방법·표본과 기준 출처'):
        st.write('표면에서 안쪽 법선 방향으로 반대 면까지의 거리를 잽니다. 평행한 벽에서는 두께에 대응하지만, 곡면·모서리에서는 다른 의미의 짧은 거리일 수 있습니다.')
        st.write(f"기준 출처: {report['profile']['threshold_basis']}")
        if summary.get('p05_mm') is not None:
            st.write(f"유효 표본을 면적 대표 가중치로 정렬한 하위 5% 거리: {summary['p05_mm']:.4g} mm. 전체 부품 두께의 하위 5%라는 뜻은 아닙니다.")
        st.write(summary['counts'])
        raw_samples=(detail or {}).get('measurements',{}).get('samples',[])
        if raw_samples:
            st.dataframe(pd.DataFrame([{'원본 메시 면':s['source_face'], '측정 거리 (mm)':s['normal_chord_mm'],
                                       '위치 (모델 X, Y, Z mm)':', '.join(f'{v:.4g}' for v in s['point_mm'])}
                                      for s in sorted(raw_samples,key=lambda s:s['normal_chord_mm'])]),hide_index=True)


def layer_table(rows):
    def area(row, prefix):
        value=row.get(prefix+'_candidate_area_mm2')
        if value is None:
            return '미확정'
        return f'{value:.4g}' + ('' if row.get(prefix+'_full_scope') else ' (일부 범위)')
    return pd.DataFrame([{'층':r['index']+1,'높이 (mm)':r['z_mm'],
                         '재료 윤곽': '확인됨' if r.get('complete') else '미확정',
                         '선폭보다 좁을 수 있는 영역 (mm²)':area(r,'thin'),
                         '아래층 지지가 부족할 수 있는 영역 (mm²)':area(r,'unsupported'),
                         '한 층에만 나타난 영역 (mm²)':area(r,'single_layer')}
                        for r in rows])


def render_layer_result(model, report):
    detail=report.get('details',{}).get('layers')
    summary=summarize_layers(detail)
    decision_card(summary)
    if not detail or not detail.get('layers'):
        return
    compact_clear=summary['complete'] and all(c['candidate_layers']==0 for c in summary['checks'])
    for check in ([] if compact_clear else summary['checks']):
        with st.container(border=True):
            count=check['candidate_layers']
            result=f'후보가 관측된 층 {count}개' if count is not None else '후보 유무 미확인'
            st.markdown(f"**{check['label']}** · {result}")
            st.write(check['description'])
            st.caption(f"전체 범위를 확인한 층: {check['fully_measured_layers']}개 · 일부라도 측정한 층: {check['known_layers']}개")
            if check['candidate_layers']:
                st.write(check['next_action'])
    affected=summary['affected_rows']
    if affected:
        st.markdown('**확인할 층만 모았습니다**')
        st.dataframe(layer_table(affected),hide_index=True)
        choices=list(range(len(affected)))
        identity=(report.get('model_fingerprint'),report.get('timestamp_utc'),detail.get('elapsed_seconds'))
        if st.session_state.get('layer_result')!=identity or st.session_state.get('layer_location') not in choices:
            st.session_state['layer_result']=identity
            st.session_state['layer_location']=0
        index=st.selectbox('위치를 확인할 층',choices,
                           format_func=lambda i:f"{affected[i]['index']+1}층 · 높이 {affected[i]['z_mm']:.4g} mm",
                           key='layer_location')
        row=affected[index]
        st.write(row['action'])
        figure=model_figure(model,report,'layers',transparent=True)
        markers=0
        labels={'thin':'선폭 후보 위치','unsupported':'미지지 후보 위치','single_layer':'한 층 후보 위치'}
        for prefix,label in labels.items():
            for i,region in enumerate(row.get(prefix+'_details',[])):
                bounds=region.get('bounds_mm')
                if not bounds or len(bounds)!=4:
                    continue
                if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in bounds):
                    continue
                x0,y0,x1,y1=bounds
                if x0>x1 or y0>y1:
                    continue
                figure.add_trace(go.Scatter3d(x=[x0,x1,x1,x0,x0],y=[y0,y0,y1,y1,y0],
                                             z=[row['z_mm']]*5,mode='lines',name=label,
                                             line=dict(width=6),showlegend=i==0))
                markers+=1
        figure.update_layout(showlegend=True)
        if markers:
            st.plotly_chart(figure,width='stretch',config={'scrollZoom':False})
            st.caption('사각형은 후보 영역이 있는 위치의 경계 상자입니다. 실제 결함 모양이나 서포트가 아닙니다. 작은 세부를 포함하며, 위치 기록은 종류별 최대 50개입니다.')
        else:
            st.info('이 결과에는 후보의 위치 경계가 없습니다. 표시된 높이를 슬라이서 미리보기에서 확인하세요.')
    else:
        st.write('확인할 후보가 없어서 빈 그래프를 표시하지 않습니다.' if summary['complete'] else
                 '미확정 범위가 남아 있어 전체 후보 유무를 판단하지 않습니다. 아래 측정값에서 확인 범위를 살펴보세요.')
    with st.expander('전체 층 측정값·계산 범위'):
        st.caption(summary['scope'])
        st.write('층 번호는 1부터 표시합니다. 높이는 층 중간의 검사 평면이며 슬라이서 노즐 Z와 다를 수 있습니다. 빈 값은 미확정입니다. 0은 해당 검사 범위에서 후보 면적이 없다는 뜻입니다.')
        st.dataframe(layer_table(detail['layers']),hide_index=True)
        for warning in detail.get('warnings',[]):
            st.caption(warning)
        st.json({'계산 상태':detail.get('status'),'요청 층':detail.get('expected_layers'),
                 '검사한 층':detail.get('examined_layers'),'윤곽 확인 층':detail.get('complete_layers')},expanded=False)
