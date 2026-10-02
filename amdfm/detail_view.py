"""Explain detailed checks before presenting diagnostic numbers."""
import math
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from .detail_summary import summarize_wall, summarize_layers
from .presentation import model_figure
from .visuals import wall_samples
from .wall_visual import wall_context_figure, wall_measurement_figure, wall_sample_geometry


def decision_card(summary):
    with st.container(border=True):
        getattr(st, summary['level'])(summary['title'])
        st.write(summary['observation'])
        st.markdown(f"**할 일** · {summary['next_action']}")


def render_wall_result(model, report, *, criterion_controls=None):
    detail=report.get('details', {}).get('wall')
    summary=summarize_wall(detail, report['profile'].get('minimum_wall_mm'))
    if summary.get('minimum_mm') is None:
        decision_card(summary)
        return
    getattr(st, summary['level'])(summary['title'])
    limit=summary.get('minimum_wall_mm')
    with st.container(horizontal=True):
        st.metric('가장 얇게 측정된 위치', f"{summary['minimum_mm']:.4g} mm", width='content',
                  help='표면에서 반대 면까지 측정한 거리입니다. 곡면·모서리에서는 CAD 두께와 다를 수 있습니다.')
        st.metric('이보다 얇으면 확인', f'{limit:g} mm' if limit is not None else '미입력', width='content',
                  help='얇은 벽을 찾기 위해 비교할 두께입니다. 사용 조건에 맞게 변경할 수 있습니다.')
    action = {
        'attention':'표시된 위치의 벽을 보강하거나 CAD 두께를 수정하세요.',
        'criterion_needed':'비교할 벽 두께를 입력하면 그보다 얇게 측정된 위치를 표시합니다.',
        'partial':'미확인 표본이 남았습니다. 측정 위치를 확인하고 필요하면 추가 계산하세요.',
        'within_criterion':'검사한 표본은 기준 이상입니다. 다른 항목을 확인하세요.',
    }.get(summary['status'], summary['next_action'])
    if not summary['complete']:
        st.caption('일부 표본 미확인 · 관측한 최솟값입니다.')
    st.write('**할 일** · '+action)
    if criterion_controls is not None:
        criterion_controls()
    samples=wall_samples(report)
    selected=None
    if samples:
        identity=(report.get('model_fingerprint'),detail.get('elapsed_seconds'),report.get('timestamp_utc'))
        if st.session_state.get('wall_sample_result')!=identity or st.session_state.get('wall_sample') not in range(len(samples)):
            st.session_state['wall_sample_result']=identity
            st.session_state['wall_sample']=0
        selected=st.selectbox('확인할 위치 · 얇은 순서',list(range(len(samples))),
            format_func=lambda i:f"위치 {i+1} · {samples[i]['normal_chord_mm']:.5g} mm"+
                (' · 기준 미만' if limit is not None and samples[i]['normal_chord_mm']<limit else ''),
            key='wall_sample')
    if samples:
        show_all=st.session_state.get('wall_show_all_samples',False)
        views=st.columns(2)
        with views[0]:
            st.markdown('**부품에서의 위치**')
            context=wall_context_figure(model,report,selected_sample=selected,show_all=show_all)
            st.plotly_chart(context,width='stretch',config={'scrollZoom':False,'displaylogo':False},key='wall_context_plot')
            omitted=context.layout.meta['omitted_sample_markers']
            if omitted:
                st.caption(f'겹침을 줄이기 위해 {omitted}개 표시 생략 · 모든 위치는 위 선택창에서 확인')
        with views[1]:
            st.markdown(f'**위치 {selected+1} 확대 · 두 면 사이 거리**')
            closeup=wall_measurement_figure(model,report,selected_sample=selected)
            if closeup is not None:
                st.plotly_chart(closeup,width='stretch',config={'scrollZoom':False,'displaylogo':False},key='wall_measurement_plot')
                st.caption('선택한 측정선을 지나는 실제 단면 · 가로·세로 동일 배율')
            else:
                st.info('이 표본의 반대 면 좌표를 확인할 수 없어 확대 단면은 표시하지 않습니다.')
        if wall_sample_geometry(model,report,selected) is None:
            st.info('선택한 표본 좌표가 현재 형상과 맞지 않습니다. 벽 검토를 다시 실행하세요.')
        st.caption('선택 위치 ◆ · 기준 미만 ×' if limit is not None else '선택 위치 ◆ · 측정한 거리')
        st.toggle('나머지 측정 위치도 표시',key='wall_show_all_samples')
    else:
        st.info('측정 위치가 저장되지 않은 결과입니다. 위치를 보려면 벽 검토를 다시 실행하세요.')
    with st.expander('측정 방법·표본과 기준 출처'):
        st.write(summary['observation'])
        st.caption(summary['scope'])
        st.write(summary['next_action'])
        if selected is not None:
            st.caption('선택 위치 (모델 X, Y, Z mm): '+', '.join(f'{v:.5g}' for v in samples[selected]['point_mm']))
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
    title=summary['title']
    if summary['status']=='no_candidates':
        title=(f"검사한 {len(detail['layers']):,}개 층에서 좁은 구간·아래층 지지 부족·"
               '한 층에만 생기는 부분의 후보가 발견되지 않았습니다')
    getattr(st, summary['level'])(title)
    if not detail or not detail.get('layers'):
        st.write(summary['observation'])
        st.write('**할 일** · '+summary['next_action'])
        return
    if not summary['complete']:
        st.caption('일부 범위 미확인 · 추가 후보가 있을 수 있습니다.')
    labels={'thin':'재료 한 줄보다 좁은 부분',
            'unsupported':'아래층 지지가 부족한 부분',
            'single_layer':'한 층에만 나타난 부분'}
    notes=[]
    for check in summary['checks']:
        count=check['candidate_layers']
        if count:
            notes.append(f"{labels[check['key']]} {count}층")
        elif count is None:
            notes.append(f"{labels[check['key']]} 미확인")
    if notes:
        st.caption(' · '.join(notes))
    affected=summary['affected_rows']
    if affected:
        choices=list(range(len(affected)))
        identity=(report.get('model_fingerprint'),report.get('timestamp_utc'),detail.get('elapsed_seconds'))
        if st.session_state.get('layer_result')!=identity or st.session_state.get('layer_location') not in choices:
            st.session_state['layer_result']=identity
            st.session_state['layer_location']=0
        index=st.selectbox('확인할 층 · 위치를 바로 표시합니다',choices,
                           format_func=lambda i:f"{affected[i]['index']+1}층 · 높이 {affected[i]['z_mm']:.4g} mm",
                           key='layer_location')
        row=affected[index]
        st.write(row['action'])
        figure=model_figure(model,report,'layers',transparent=True)
        markers=0
        # Stable colors and line styles keep overlapping regions distinguishable.
        styles={'thin':('#c43c39','solid'),'unsupported':('#c47700','dash'),
                'single_layer':('#6254a4','dot')}
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
                                             line=dict(width=6,color=styles[prefix][0],dash=styles[prefix][1]),showlegend=i==0))
                markers+=1
        figure.update_layout(showlegend=True)
        if markers:
            st.plotly_chart(figure,width='stretch',config={'scrollZoom':False})
            st.caption('사각형: 후보 영역의 위치 범위 · 종류별 최대 50개')
        else:
            st.info('이 결과에는 후보의 위치 경계가 없습니다. 표시된 높이를 슬라이서 미리보기에서 확인하세요.')
        with st.expander(f'확인할 층 {len(affected)}개 · 측정값'):
            st.dataframe(layer_table(affected),hide_index=True)
    elif not summary['complete']:
        st.caption('미확인 범위는 아래 측정값에서 확인하세요.')
    with st.expander('전체 층 측정값·계산 범위'):
        st.write(summary['observation'])
        st.write(summary['next_action'])
        for check in summary['checks']:
            st.write(f"**{check['label']}** · {check['description']}")
            st.caption(f"전체 범위 {check['fully_measured_layers']}층 · 일부 측정 {check['known_layers']}층")
        st.caption(summary['scope'])
        st.write('층 번호는 1부터 표시합니다. 높이는 층 중간의 검사 평면이며 슬라이서 노즐 Z와 다를 수 있습니다. 빈 값은 미확정입니다. 0은 해당 검사 범위에서 후보 면적이 없다는 뜻입니다.')
        st.dataframe(layer_table(detail['layers']),hide_index=True)
        for warning in detail.get('warnings',[]):
            st.caption(warning)
        st.json({'계산 상태':detail.get('status'),'요청 층':detail.get('expected_layers'),
                 '검사한 층':detail.get('examined_layers'),'윤곽 확인 층':detail.get('complete_layers')},expanded=False)
