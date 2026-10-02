from pathlib import Path
import json
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from amdfm import __version__
from amdfm.analysis import review, code_digest
from amdfm.comparison import compare_designs
from amdfm.detail import run_detail, attach_detail
from amdfm.assessment import run_assessment, attach_assessment
from amdfm.evidence import section_guidance
from amdfm.section_view import render_section_result
from amdfm.detail_view import render_wall_result, render_layer_result, decision_card
from amdfm.workflow import summarize_review, ranked_orientations, action_plan
from dfm.enhanced_planning import orientation_recommendation as recommend_orientation
from amdfm.decision_view import render_recommendation
from amdfm.io import load_model
from amdfm.gcode import inspect_gcode
from amdfm.models import json_bytes
from amdfm.orientation import candidates, direction_from_angles, direction_angles, unit_direction, measure_orientation
from amdfm.presentation import model_figure, orientation_table, html_report, placed_stl
from amdfm.profiles import Profile, PROCESS_LABELS
from dfm.conditions_view import (render_condition_picker, condition_context,
                                 conditions_ready, render_condition_evidence, render_literature_library)
from dfm.advisor_view import render_advisor, render_applied_context
from dfm.learned_review import analyze_report
from dfm.defaults import wall_default_value, wall_default_basis, wall_default_context
from dfm.location_navigation import request_problem_location
from dfm.demo_catalog import family_changed

ROOT=Path(__file__).resolve().parent
ENGINE_REVISION=code_digest()
CUSTOM_DIRECTION="직접 각도 입력"
st.set_page_config(page_title="DFM | 제조성 설계 검토",page_icon=":material/precision_manufacturing:",layout="wide")
header = st.empty()
header.markdown('**DFM · 제조성 설계 검토**')


@st.cache_data(max_entries=3,show_spinner=False)
def cached_load(data,name,unit,confirmed,target,deflection,code_revision):
    return load_model(data,name,unit=unit,dimensions_confirmed=confirmed,
                      target_longest_mm=target,deflection_mm=deflection,timeout_s=180)


@st.cache_data(max_entries=4,show_spinner=False)
def cached_review(fingerprint,profile_dict,direction,extended,dense,code_revision,_model):
    return review(_model,Profile(**profile_dict),direction,extended=extended,dense=dense)


@st.cache_data(max_entries=2,show_spinner=False)
def cached_gcode(data,diameter,code_revision):
    return inspect_gcode(data,diameter)


@st.cache_data(max_entries=2,show_spinner=False)
def cached_assessment(fingerprint,profile_dict,direction,code_revision,_model):
    return run_assessment(_model,Profile(**profile_dict),direction,budget_s=45,
                          detail_runner=run_detail)


@st.cache_data(max_entries=8,show_spinner=False)
def cached_orientation_preview(fingerprint,profile_dict,direction,reliable,code_revision,_model):
    return measure_orientation(_model.mesh,direction,Profile(**profile_dict),reliable_normals=reliable)


@st.cache_data(max_entries=4,show_spinner=False)
def cached_neural_search(fingerprint,profile_dict,direction,extended,dense,priority,enabled,code_revision,_model):
    from amdfm.ai_search import extend_review_orientations
    report = cached_review(fingerprint,profile_dict,direction,extended,dense,code_revision,_model)
    return extend_review_orientations(_model,Profile(**profile_dict),report,priority=priority,enabled=enabled)


def orientation_delta(value, baseline, unit):
    difference=value-baseline
    return None if difference == 0 else f'{difference:+.4g} {unit}'


def render_wall_criterion(process, profile):
    with st.expander('찾을 벽 두께 바꾸기',expanded=False):
        criterion_key=f'quick_wall_limit_{process}'
        if st.session_state.get('quick_wall_context')!=(process,profile.minimum_wall_mm):
            st.session_state['quick_wall_context']=(process,profile.minimum_wall_mm)
            st.session_state[criterion_key]=profile.minimum_wall_mm
        quick_limit=st.number_input('이보다 얇은 벽 찾기 (mm)',min_value=.001,value=None,key=criterion_key,
                                    help='입력한 두께보다 얇게 측정된 위치를 표시합니다.')
        st.button('이 기준으로 벽 다시 검토',key='apply_wall_criterion',on_click=apply_wall_criterion,args=(process,),disabled=quick_limit is None)


def apply_orientation(vector,presets):
    # Match vectors, since face-candidate names can differ between candidate sets.
    name=next((k for k,v in presets.items() if np.array_equal(unit_direction(v),vector)),None)
    st.session_state["build_direction"]=name or CUSTOM_DIRECTION
    if name is None and st.session_state.get("custom_vector")!=list(vector):
        tilt,azimuth=direction_angles(vector)
        st.session_state["build_tilt"]=tilt
        st.session_state["build_azimuth"]=azimuth
    st.session_state["auto_review"]=True


def apply_recommended_orientation(vector,presets):
    # This button explicitly promises a complete set of applicable checks.
    st.session_state['initial_wall']=True
    st.session_state['result_tab']='설계 조치'
    apply_orientation(vector,presets)


def navigate_result(target, focus=None, finding=None):
    st.session_state['result_tab']=target
    if focus:
        st.session_state['detail_focus']=focus
    if finding:
        st.session_state['pending_finding']=finding
        request_problem_location('am')


def apply_wall_criterion(process):
    st.session_state[f'wall_limit_{process}']=st.session_state[f'quick_wall_limit_{process}']
    st.session_state['auto_review']=True
    st.session_state['queued_detail']='wall'


def apply_hole_criterion(process):
    st.session_state[f'hole_limit_{process}']=st.session_state[f'quick_hole_limit_{process}']
    st.session_state['auto_review']=True
    st.session_state['pending_finding']='cad_holes'
    request_problem_location('am')


def render_hole_criterion(process, profile):
    criterion_key=f'quick_hole_limit_{process}'
    if st.session_state.get('quick_hole_context')!=(process,profile.minimum_hole_mm):
        st.session_state['quick_hole_context']=(process,profile.minimum_hole_mm)
        st.session_state[criterion_key]=profile.minimum_hole_mm
    value=st.number_input('이보다 작은 구멍 찾기 (지름, mm)',min_value=.001,value=None,key=criterion_key,
                          placeholder='예: 2',help='현재 측정한 구멍을 이 지름과 비교합니다.')
    st.button('이 지름으로 구멍 비교',key='apply_hole_criterion',on_click=apply_hole_criterion,
              args=(process,),disabled=value is None)


def start_review():
    st.session_state['auto_review']=True
    st.session_state['result_tab']='설계 조치'
    st.session_state['am_location_details']=False


def render_overview(overview, report):
    getattr(st,overview['level'])(overview['title'])
    st.write(overview['observation'])
    item=action_plan(report)['primary']
    if item:
        st.markdown(f"**먼저 할 일 · {item['label']}** — {item['next_action']}")
        if item['id']=='wall' and report.get('details',{}).get('wall',{}).get('status') in ('measured','partial'):
            st.write(item['observation'])
        st.button(f"{item['label']} 확인하기",key='next_review_action',
                  on_click=navigate_result,args=(item['target'],item['focus'],
                                               item['id'] if item['target']=='설계 조치' else None))


with st.sidebar:
    family=st.selectbox("제조 공정",["적층제조","절삭가공"],key="manufacturing_family",persist_state="session",on_change=family_changed)
    st.subheader("검토할 형상")
    from dfm.demo_catalog import render_input
    data,name=render_input(ROOT)
    unit,confirmed,target,deflection="mm",False,None,.05
    is_stl=data is not None and name.lower().endswith(".stl")
    if is_stl:
        unit=st.selectbox("STL 좌표 단위",["mm","cm","inch","m"],key="stl_unit")
        target=st.number_input("최장 외곽 길이 지정 (mm, 선택)",min_value=.001,value=None,key="target_size")
        confirmed=st.checkbox("이 치수·배율로 검토하는 것을 확인함",key="dimensions_confirmed")
    elif data is not None and name.lower().endswith((".step",".stp")):
        with st.expander("CAD 메시 정밀도"):
            deflection=st.number_input("목표 선형 편차 (mm)",min_value=.001,max_value=1.,value=.05,step=.01,format="%.3f")
            st.caption("CAD 해석 값과 메시 근사 값은 별도로 기록됩니다.")
    elif data is not None:
        st.caption("3MF에 선언된 단위와 객체·빌드 변환을 적용합니다. 슬라이서의 재료·서포트 설정은 가져오지 않습니다.")

if data is None:
    st.info("왼쪽에서 STEP·STL·3MF를 선택하세요. STEP은 CAD 치수·곡면을, STL·3MF는 메시 형상을 검토합니다.")
    st.stop()
try:
    with st.spinner("형상과 단위를 읽는 중…"):
        full_model=cached_load(data,name,unit,confirmed,target,deflection,ENGINE_REVISION)
except (ValueError,MemoryError) as exc:
    st.error(str(exc))
    st.stop()
with st.sidebar:
    bodies=full_model.metadata.get("bodies",[])
    selected_body=None
    if len(bodies)>1:
        body_lookup={b["body_id"]:b for b in bodies}
        body_order=[b["body_id"] for b in sorted(bodies,key=lambda b:b["volume_mm3"],reverse=True)]
        if st.session_state.get("body_model_sha")!=full_model.metadata["source_sha256"]:
            st.session_state["body"]=body_order[0]
            st.session_state["body_model_sha"]=full_model.metadata["source_sha256"]
        selected_body=st.selectbox("CAD 솔리드 · 체적순",[None]+body_order,
            index=1,format_func=lambda x:"전체 조립체 (배치 미리보기)" if x is None else
                f"솔리드 {x} · {body_lookup[x]['volume_mm3']/1000:.4g} cm³",key="body")
        st.caption(f"{len(bodies)}개 솔리드 중 검토할 부품을 선택합니다. 처음에는 체적이 가장 큰 부품을 보여줍니다.")
    model=full_model.select_body(selected_body)

if family=="절삭가공":
    from dfm.machining_view import render_machining
    with header.container():
        st.title("절삭가공 설계 검토")
    render_machining(model,name,data,ENGINE_REVISION)
    st.stop()

with st.sidebar:
    directions=candidates(model.mesh,True,dense=True)
    if st.session_state.get("build_direction") not in [*directions,CUSTOM_DIRECTION]:
        st.session_state["build_direction"]="+Z"
    process=st.selectbox("적층제조 공정",list(PROCESS_LABELS),format_func=lambda p:PROCESS_LABELS[p],key="process")
    condition_library=render_condition_picker(process,compact=True)

from dfm.am_settings_view import render_am_settings
review_context=render_advisor(process,condition_library,settings_renderer=render_am_settings)
output_settings=review_context.pop('settings')
machine,material=review_context['equipment'],review_context['material']
wall_limit=output_settings['minimum_wall_mm']
with st.sidebar:
    orientation_name=st.selectbox("현재 배치 방향",[*directions,CUSTOM_DIRECTION],key="build_direction",
        help="모델에서 위쪽을 향할 방향입니다. 모르면 +Z로 시작하세요. 검토할 때 다른 방향도 비교해 추천합니다.")
    if orientation_name==CUSTOM_DIRECTION:
        tilt=st.number_input("기울기 · 모델 +Z에서 (°)",min_value=0.,max_value=180.,value=0.,step=5.,format="%.4f",key="build_tilt",persist_state="session")
        azimuth=st.number_input("방위각 · 모델 +X → +Y (°)",min_value=0.,max_value=360.,value=0.,step=5.,format="%.4f",key="build_azimuth",persist_state="session")
        direction=tuple(direction_from_angles(tilt,azimuth))
        st.session_state["custom_vector"]=list(direction)
        st.caption("기울기 0°는 +Z, 90°는 XY 평면, 180°는 −Z입니다. 이 모델 방향이 프린터의 위쪽(+Z)을 향합니다.")
    else:
        direction=tuple(unit_direction(directions[orientation_name]))
    submitted=st.button("설계 검토",key='run_am_review',type="primary",icon=":material/play_arrow:",width="stretch",
                                       disabled=not conditions_ready(condition_library,process))
    with st.expander('검토 범위·방향 탐색 설정',expanded=False):
        if process=="PBF_POLYMER":
            angle=45.
        else:
            angle=st.number_input("받침 검토에 사용할 경사각 (°)",min_value=1.,max_value=90.,value=45.,step=5.,key=f"angle_{process}",persist_state="session",
                                  help='수평면에서 잰 각도입니다. 아래로 향한 면 중 이 각도보다 완만한 곳을 찾습니다.')
        dense=st.checkbox("대각선 포함 26방향 비교",value=True,key="compare_diagonals")
        extended=st.checkbox("주요 면 방향까지 비교",value=False,key="extended")
        neural_search=st.checkbox('AI 추가 방향 탐색',value=True,key='neural_direction_search')
        st.session_state.setdefault('initial_wall',True)
        initial_wall=st.checkbox('벽·층간·단면까지 한 번에 검토',key='initial_wall')

profile_values=dict(process=process,machine=machine,material=material,overhang_angle_deg=angle,**output_settings)
profile_evidence=condition_context(condition_library,process,profile_values)
equipment_defaults=st.session_state.get(f'equipment_defaults_{process}')
if equipment_defaults and condition_library and equipment_defaults.get('digest')==condition_library.digest:
    review_context['equipment_defaults']={**equipment_defaults,
        'effective_build_volume_mm':profile_values['build_volume_mm'],
        'edited':profile_values['build_volume_mm'] is not None and list(profile_values['build_volume_mm'])!=equipment_defaults.get('build_volume_mm'),
        'effective_layer_height_mm':profile_values['layer_height_mm']}
profile=Profile(**profile_values,condition_evidence=profile_evidence,
                name=profile_evidence.get('label','장비 미정 · 탐색용 조건'))
fingerprint=model.fingerprint
settings_key=json_bytes([fingerprint,profile.to_dict(),direction,extended,dense,neural_search,initial_wall,review_context,ENGINE_REVISION]).decode()
should_review=(submitted or st.session_state.pop("auto_review",False)) and conditions_ready(condition_library,process)
if submitted:
    st.session_state['result_tab']='설계 조치'
    st.session_state['am_location_details']=False
if should_review:
    try:
        with st.spinner("문제 위치와 종합 추천 방향을 계산하는 중…"):
            st.session_state["report"]=cached_neural_search(fingerprint,profile.to_dict(),direction,extended,dense,
                review_context.get('priority','balanced'),neural_search,ENGINE_REVISION,model)
            st.session_state["report"]["review_context"]=review_context
            st.session_state["report"]["wall_default"]=wall_default_context(process,wall_limit)
            st.session_state["report_settings"]=settings_key
            queued=st.session_state.pop('queued_detail',None)
            if initial_wall:
                with st.spinner('벽·층간·단면을 함께 확인하는 중 · 상세 계산 총 45초 예산…'):
                    bundle=cached_assessment(fingerprint,profile.to_dict(),direction,ENGINE_REVISION,model)
                st.session_state['report']=attach_assessment(st.session_state['report'],bundle)
            if queued and (not initial_wall or st.session_state['report'].get('details',{}).get(queued,{}).get('status') not in ('measured','complete')):
                with st.spinner('입력한 기준으로 벽을 다시 확인하는 중…'):
                    result=run_detail(model,profile,direction,mode=queued)
                st.session_state['report']=attach_detail(st.session_state['report'],result)
            st.session_state['report']['orientation_recommendation']=recommend_orientation(st.session_state['report'])
            st.session_state['report']['learned_review']=analyze_report(st.session_state['report'])
            # The conditions panel was rendered before this first result. Render
            # again from cached measurements so the result opens with it closed.
            st.rerun()
    except (ValueError,MemoryError) as exc:
        st.error(str(exc))
        st.stop()
report=(st.session_state.get("report") if st.session_state.get("report_settings")==settings_key
        and conditions_ready(condition_library,process) else None)

if report is None:
    with header.container():
        st.title('적층제조 설계 검토')
        st.caption(f'AM-DFM {__version__} · 문제 위치와 개선안을 한 번에 확인하세요.')
    st.subheader(name)
    st.caption('크기 · '+" × ".join(f"{x:.3g}" for x in model.mesh.extents)+" mm")
    if st.session_state.get('report'):
        st.info('형상 또는 조건이 바뀌었습니다. 다시 검토하면 새 결과로 바뀝니다.')
    st.button('이 형상으로 설계 검토 시작',type='primary',on_click=start_review,key='start_from_model',
              disabled=not conditions_ready(condition_library,process))
    st.plotly_chart(model_figure(model),width="stretch",config={'scrollZoom':False})
    if model.metadata.get('unit_status')=='assumed':
        st.warning(model.metadata['unit_note'])
    with st.expander('파일 정보·사용 방법'):
        st.caption(model.metadata['unit_note'])
        st.write('형상과 공정을 선택 → 검토 시작 → 문제 위치 확인 → 개선안 적용·결과 저장')
    st.stop()

# A detail-only recalculation also refreshes the learned conclusions before
# another tab exports them. The renderer performs the same defensive check.
report['learned_review']=analyze_report(report)
overview=summarize_review(report)
recommendation=recommend_orientation(report)
report['orientation_recommendation']=recommendation
plan=action_plan(report)
render_applied_context(report,process)
tab=st.segmented_control("결과 보기",["설계 조치","방향 비교","정밀 검토","수정 전후","근거·내보내기"],
                         format_func=lambda value:{'설계 조치':'종합 결론','정밀 검토':'상세 검사','근거·내보내기':'저장·근거'}.get(value,value),
                         default=None if 'result_tab' in st.session_state else '설계 조치',required=True,
                         persist_state='session',key="result_tab")
if tab not in ('설계 조치',None):
    st.caption(f"{report['model']['filename']} · {report['process_label']} · 현재 높이 {report['current_orientation']['height_mm']:.4g} mm")
if model.metadata["unit_status"]=="assumed":
    st.warning("치수 미확정 STL입니다. 표시된 mm 값은 선택 단위·배율을 가정한 값입니다.")
if tab=='근거·내보내기':
    render_condition_evidence(report['profile'].get('condition_evidence'))

if tab=="설계 조치" or tab is None:
    from amdfm.action_view import render_actions
    render_actions(model,report,profile,recommendation,on_apply=apply_recommended_orientation,presets=directions,
                   on_navigate=navigate_result,criterion_controls=lambda:render_wall_criterion(process,profile),
                   detail_runner=run_detail,hole_controls=lambda:render_hole_criterion(process,profile))
    st.download_button('검토 보고서 저장',html_report(st.session_state.get('report',report),model),
                       file_name='AM-DFM_review.html',mime='text/html',key='am_quick_report',on_click='ignore')
elif tab=="방향 비교":
    st.subheader('추천 방향을 확인하고 바로 적용하세요')
    render_recommendation(recommendation,on_apply=apply_recommended_orientation,presets=directions,key_prefix='directions')
    goals=['종합 균형 · 기본 추천','높이를 낮추기']
    if report['current_orientation']['overhang_projected_area_sum_mm2'] is not None:
        goals.append('하향면 후보 줄이기')
    if process=='MEX' and report['current_orientation']['contact_triangle_area_mm2'] is not None:
        goals.append('평평한 바닥 넓히기')
    with st.expander('다른 목적·방향을 직접 비교하기',expanded=False):
        goal=st.selectbox('비교 순서',goals,key='orientation_goal')
    ranked=(recommendation['ranking'] if goal==goals[0] else ranked_orientations(report,goal))
    choices=[r["name"] for r in report["orientations"]]
    context=(report['model_fingerprint'],json_bytes(report['profile']).decode(),
             json_bytes([(r['name'],r['direction']) for r in report['orientations'] if r.get('candidate_role')!='current_only']).decode(),
             tuple(report['current_orientation']['direction']),json_bytes(review_context).decode(),goal)
    if st.session_state.get('orientation_comparison_context')!=context or st.session_state.get('orientation_choice') not in choices:
        st.session_state['orientation_comparison_context']=context
        current_choice=next((r['name'] for r in report['orientations'] if np.allclose(r['direction'],report['current_orientation']['direction'],rtol=0,atol=1e-12)),None)
        st.session_state['orientation_choice']=(current_choice if goal==goals[0] and recommendation['keep_current'] and current_choice
                                              else ranked[0]['name'] if ranked else choices[0])
    if ranked:
        best=ranked[0]
        st.caption(f"비교표의 첫 후보: {best['name']} · {goal}")
        if st.button('첫 후보로 돌아가기',key='select_ranked_direction'):
            st.session_state['orientation_choice']=best['name']
    chosen=st.selectbox("비교할 방향 · 적용 전 미리보기",choices,key="orientation_choice")
    choice=next(r for r in report["orientations"] if r["name"]==chosen)
    current=report["current_orientation"]
    current_name=next((r['name'] for r in report['orientations'] if np.array_equal(r['direction'],current['direction'])),'현재 지정 방향')
    st.markdown(f"**현재 {current_name} → 비교 {chosen}** · 아래 수치와 오른쪽 형상은 모두 **{chosen}**입니다.")
    with st.container(horizontal=True):
        st.metric('비교 방향의 높이',f"{choice['height_mm']:,.4g} mm",delta=orientation_delta(choice['height_mm'],current['height_mm'],'mm'),delta_color='inverse')
        if choice['overhang_projected_area_sum_mm2'] is not None and current['overhang_projected_area_sum_mm2'] is not None:
            st.metric('하향면 투영면적 합 · 중복 포함',f"{choice['overhang_projected_area_sum_mm2']:,.4g} mm²",
                      delta=orientation_delta(choice['overhang_projected_area_sum_mm2'],current['overhang_projected_area_sum_mm2'],'mm²'),delta_color='inverse')
        if process=='MEX' and choice['contact_triangle_area_mm2'] is not None and current['contact_triangle_area_mm2'] is not None:
            st.metric('평평한 바닥 면적',f"{choice['contact_triangle_area_mm2']:,.4g} mm²",
                      delta=orientation_delta(choice['contact_triangle_area_mm2'],current['contact_triangle_area_mm2'],'mm²'),delta_color='normal')
    if choice['build_fit'] is False:
        st.warning('이 방향은 입력한 빌드 공간을 초과합니다. 다른 방향이나 장비 공간을 검토하세요.')
    st.caption('증감은 현재 방향 대비입니다.')
    reliable=current.get('overhang_projected_area_sum_mm2') is not None
    measured=cached_orientation_preview(model.fingerprint,profile.to_dict(),tuple(choice['direction']),reliable,ENGINE_REVISION,model)
    preview={**report,'current_orientation':choice,'findings':[{'id':'overhang','title':'비교 방향 하향면 후보','face_indices':measured['overhang_face_indices']}]}
    comparison_columns=st.columns(2)
    for column, title, shown in ((comparison_columns[0],f'현재 · {current_name}',report),(comparison_columns[1],f'비교 · {chosen}',preview)):
        with column:
            st.markdown('**'+title+'**')
            figure=model_figure(model,shown,'overhang',build_plate=True,height=400)
            spans=np.maximum(current['placed_extents_mm'],choice['placed_extents_mm'])
            margin=float(np.max(spans))*.12
            figure.update_layout(scene=dict(xaxis=dict(range=[-spans[0]/2-margin,spans[0]/2+margin]),
                yaxis=dict(range=[-spans[1]/2-margin,spans[1]/2+margin]),zaxis=dict(range=[0,spans[2]*1.15])))
            st.plotly_chart(figure,width='stretch',key='orientation_plot_'+title,config={'scrollZoom':False})
    st.caption('회색: 바닥 · 주황: 하향면 후보 · 두 형상은 같은 배율')
    st.button("이 방향으로 검토",on_click=apply_orientation,args=(choice["direction"],directions),key="apply_orientation",
              disabled=np.allclose(choice['direction'],current['direction'],rtol=0,atol=1e-12))
    with st.expander(f"전체 {len(report['orientations'])}개 방향의 수치 비교"):
        st.dataframe(pd.DataFrame(orientation_table(report)).rename(columns={'비지배 대안':'다른 지표와 절충되는 후보'}),hide_index=True)
elif tab=="정밀 검토":
    focus=st.segmented_control('자세히 확인할 질문',['벽','층간','단면'],
                               format_func=lambda value:{'벽':'벽 두께','층간':'층별 얇은 부분·받침','단면':'높이별 단면'}[value],
                               default=st.session_state.get('detail_focus') or '벽',required=True,
                               persist_state='session',key='detail_focus') or '벽'
    if focus=='벽':
        st.markdown('**얇은 벽이 어디에 있나요?**')
        wall_ready=bool(report.get('details',{}).get('wall',{}).get('measurements'))
        if st.button('벽 다시 계산' if wall_ready else '벽 두께 계산',key='run_wall',type='secondary' if wall_ready else 'primary'):
            with st.spinner('벽의 표본 거리를 측정하는 중 · 최대 60초…'):
                result=run_detail(model,profile,report['current_orientation']['direction'],mode='wall')
            st.session_state['report']=attach_detail(report,result)
            st.rerun()
        render_wall_result(model,report,criterion_controls=lambda:render_wall_criterion(process,profile))
    elif focus=='층간':
        st.markdown('**프린팅 층마다 놓치거나 받쳐 줄 곳이 있나요?**')
        if process!='MEX':
            st.info('층별 얇은 부분·받침 검사는 FDM 전용입니다. 위에서 벽 두께 또는 높이별 단면을 선택하세요.')
        else:
            st.caption(f'한 층 {profile.layer_height_mm:g} mm · 재료 한 줄 {profile.line_width_mm:g} mm · 설정 변경: 검토 조건 → 벽·구멍 크기와 출력 설정')
        layers_ready=bool(report.get('details',{}).get('layers',{}).get('layers'))
        if st.button('층별 결과 다시 계산' if layers_ready else '층별 얇은 부분·받침 계산',disabled=process!='MEX',key='run_layers',type='secondary' if layers_ready else 'primary'):
            with st.spinner('각 층과 이웃한 층을 비교하는 중 · 최대 90초…'):
                result=run_detail(model,profile,report['current_orientation']['direction'],mode='layers',timeout_s=90)
            st.session_state['report']=attach_detail(report,result)
            st.rerun()
        if process=='MEX':
            render_layer_result(model,report)
    else:
        st.markdown('**어느 높이에서 단면 모양과 넓이가 크게 바뀌나요?**')
        guidance=section_guidance(process)
        with st.expander('단면 계산 방법·표본 수',expanded=False):
            section_method=st.selectbox("단면 배치 방법",["자동 · 가능한 방법으로 단면 확인","형상 변화 기준 · 체적 정밀 검산","균등 간격 · 높이별 비교"],key="section_method")
            sampling='auto' if section_method.startswith('자동') else "events" if section_method.startswith("형상") else "uniform"
            samples=64
            if sampling in ('uniform','auto'):
                samples=st.number_input('균등 전환 시 사용할 단면 수' if sampling=='auto' else "높이 방향 단면 표본 수",min_value=2,max_value=1024,value=64,step=16,key="section_samples")
                st.caption('자동은 형상 변화 기준을 먼저 시도하고 계산 예산을 넘을 때만 위 개수의 균등 단면으로 이어갑니다. 전환 사유와 원래 시도를 결과에 보존합니다.' if sampling=='auto' else "현재 배치 높이를 균등 분할한 중간 단면입니다. 얇은 판을 표본 사이에서 놓칠 수 있습니다. 실제 출력 층 수와는 다릅니다.")
            else:
                st.caption("얇은 높이 구간도 포함하도록 검사할 높이를 자동으로 정합니다. 계산한 단면을 비교해 확인할 위치를 안내합니다.")
        sections_ready=bool(report.get('details',{}).get('sections',{}).get('rows'))
        if st.button('단면 다시 계산' if sections_ready else '높이별 단면 계산',key="run_sections",type='secondary' if sections_ready else 'primary'):
            with st.spinner("단면 면적·둘레·변화를 계산하는 중 · 최대 90초…"):
                result=run_detail(model,profile,report["current_orientation"]["direction"],mode="sections",sample_count=samples,sampling=sampling,timeout_s=90)
            st.session_state["report"]=attach_detail(report,result)
            st.rerun()
        sections=report.get("details",{}).get("sections")
        if sections:
            if sections.get('requested_sampling',sections.get("sampling","uniform"))!=sampling or (sampling in ('uniform','auto') and sections.get("sample_count",samples)!=samples):
                st.info("아래는 이전 설정의 결과입니다. 위 계산 버튼을 누르면 변경한 설정을 적용합니다.")
            render_section_result(sections,process,report['geometry'].get('mesh_signed_volume_mm3'))
            with st.expander('이 공정에서 단면 결과를 사용하는 범위'):
                st.write(guidance['reason'])
                st.write(guidance['action'])
                for limitation in guidance['limitations']:st.write(limitation)
    if process=="MEX":
        with st.expander("슬라이서 경로 확인 · G-code"):
            st.markdown('**실제 슬라이서에서도 이 부위가 남아 있나요?**')
            st.write('현재 방향의 STL로 만든 G-code를 넣고, 얇은 부위에 재료 경로가 남는지 확인하세요.')
            st.download_button('슬라이싱할 STL 받기',placed_stl(model,report),file_name='AM-DFM_oriented_mm.stl',
                               mime='model/stl',key='gcode_input_stl',on_click='ignore')
            practice=st.checkbox('사용법 연습 · 현재 부품과 무관한 Cura 예제 보기',value=False,key='show_gcode_practice')
            gcode_mode='Cura 기준 실험' if practice else '내 G-code'
            gd=None
            gsource_name=None
            if gcode_mode=="내 G-code":
                gfile=st.file_uploader("Marlin 계열 G0/G1 G-code",type=["gcode"],key="gcode_upload")
                if gfile:gd,gsource_name=gfile.getvalue(),gfile.name
            else:
                gfiles=sorted((ROOT/"validation/v3/cura-experiment-02").glob("rib_*/toolpaths.gcode"))
                if gfiles:
                    gpath=st.selectbox("리브 폭 실험",gfiles,format_func=lambda p:p.parent.name,key="gcode_example")
                    gd=gpath.read_bytes()
                    gsource_name=gpath.name
                    st.caption("노즐 0.4 · 층 0.2 · 최소 특징 0.1 · 최소 비드 0.34 mm의 합성 CLI 조건입니다. 현재 모델의 G-code가 아닙니다.")
            diameter=st.number_input("필라멘트 지름 (mm)",min_value=.1,max_value=5.,value=1.75,key="filament_diameter")
            if gd:
                try:
                    parsed=cached_gcode(gd,diameter,ENGINE_REVISION)
                    if gcode_mode=='Cura 기준 실험':
                        st.info('연습용 실험 경로입니다. 현재 부품의 검사 결과가 아닙니다.')
                    else:
                        st.info('경로를 읽었습니다. 현재 모델의 파일·배율·방향과 일치하는지는 직접 확인해야 합니다.')
                    st.write(f"읽은 압출 경로 구간: {parsed['parsed_segments']:,}개")
                    if parsed['status']=='partial':
                        st.warning('일부 명령을 완전히 해석하지 못했습니다. 아래 사유를 확인하고 원래 슬라이서에서도 경로를 확인하세요.')
                    if parsed["issues"]:st.warning(" · ".join(parsed["issues"]))
                    st.dataframe(pd.DataFrame([{"경로 종류":k,**v} for k,v in parsed["by_type"].items()]),hide_index=True)
                    if parsed["segments"]:
                        heights=sorted(set(round(s["end"][2],5) for s in parsed["segments"]))
                        z=st.select_slider("노즐 Z (mm)",options=heights,key="gcode_z")
                        segments=[s for s in parsed["segments"] if abs(s["end"][2]-z)<1e-5]
                        figure=go.Figure()
                        for kind in dict.fromkeys(s["type"] for s in segments):
                            relevant=[s for s in segments if s["type"]==kind][:20_000]
                            xs=[v for s in relevant for v in (s["start"][0],s["end"][0],None)]
                            ys=[v for s in relevant for v in (s["start"][1],s["end"][1],None)]
                            figure.add_trace(go.Scatter(x=xs,y=ys,mode="lines",name=kind))
                        figure.update_layout(height=350,xaxis_title="X (mm)",yaxis_title="Y (mm)",yaxis=dict(scaleanchor="x",scaleratio=1))
                        st.plotly_chart(figure,width="stretch")
                    st.caption("선은 이동 중심선이며 비드 외곽이 아닙니다. 재료량은 지령값이고 제작 측정값이 아닙니다. 노즐 Z와 기하 단면의 높이는 층 기준을 맞춰 비교하세요.")
                    gcode_record={**parsed,'input_origin':'bundled_practice' if practice else 'user_upload',
                                  'source_filename':gsource_name,
                                  'current_model_relation':'not_current_model' if practice else 'unverified'}
                    st.download_button("G-code 검토 JSON",json_bytes(gcode_record),file_name="AM-DFM_gcode_review.json",mime="application/json")
                except (ValueError,MemoryError) as exc:st.error(str(exc))
elif tab=="수정 전후":
    st.subheader("형상을 바꾼 이유를 수치로 확인")
    st.write("변경 전 결과를 저장한 뒤 다른 CAD나 수정 파일을 검토하세요. 동일 조건일 때 기하 지표의 차이를 계산합니다.")
    if st.button("현재 결과를 변경 전 기준으로 저장",key="save_baseline"):
        st.session_state["comparison_baseline"]=report
        st.success("비교 기준을 저장했습니다. 이제 수정 형상을 선택해 검토하세요.")
    baseline=st.session_state.get("comparison_baseline")
    if baseline:
        comparison=compare_designs(baseline,report)
        st.write(f"{comparison['before']} → {comparison['after']}")
        if baseline['model_fingerprint']==report['model_fingerprint']:
            st.info('비교 기준과 현재 형상이 같습니다. 왼쪽에서 수정한 파일을 선택하고 설계 검토를 실행하세요.')
        elif comparison['reasons']:
            st.warning('조건이 달라 개선량을 비교할 수 없습니다. '+ ' '.join(comparison['reasons']))
            st.write('변경 전과 같은 공정·기준·방향·배율로 다시 검토하세요. 값은 참고용으로 나란히 표시합니다.')
        else:
            st.success('같은 검토 조건으로 전후 수치를 비교할 수 있습니다.')
            st.write('하향면·높이·벽 거리·체적의 변화를 비교하세요.')
        same_shape=baseline['model_fingerprint']==report['model_fingerprint']
        comparison_panel=st.expander('같은 형상의 비교 수치',expanded=False) if same_shape else st.container()
        with comparison_panel:
            st.dataframe(pd.DataFrame(comparison["metrics"]).style.format(
                {column:'{:,.4g}' for column in ('변경 전','변경 후','차이')},na_rep='미비교'),hide_index=True)
            with st.expander('비교 조건'):
                st.caption('두 형상의 좌표계·공정·기준·방향·배율이 같아야 개선량을 비교할 수 있습니다.')
            st.download_button("전후 비교 JSON",json_bytes(comparison),file_name="AM-DFM_design_comparison.json",mime="application/json",on_click='ignore')
else:
    st.subheader('결과를 전달하거나 다음 작업으로 가져가세요')
    st.write('**사람에게 설명하기:** HTML 보고서 · **슬라이서에서 확인하기:** 현재 방향 STL · **측정값과 조건 재현하기:** 전체 결과 JSON · **CAD 수정하기:** STEP 입력 원본')
    with st.container(horizontal=True):
        st.download_button("검토 보고서 HTML",html_report(report,model),file_name="AM-DFM_review.html",mime="text/html")
        st.download_button("전체 결과 JSON",json_bytes(report),file_name="AM-DFM_review.json",mime="application/json")
        st.download_button("현재 방향 STL · mm",placed_stl(model,report),file_name="AM-DFM_oriented_mm.stl",mime="model/stl")
        st.download_button("입력 원본",data,file_name=name,mime="application/octet-stream")
    st.caption("방향 STL에는 단위가 저장되지 않습니다. 슬라이서에서 mm로 읽고 JSON의 변환 행렬·배율을 함께 보관하세요.")
    with st.expander('검토에 포함되지 않은 항목'):
        st.write(" · ".join(report["unassessed"]))
    st.write("**규칙의 이유와 출처**")
    for key,s in report["sources"].items():
        with st.expander(f"{key} · {s['title']}"):
            st.write(s["use"])
            st.caption(f"{s['locator']} · {s['access']}")
            if s["url"]:st.link_button("원출처",s["url"])
    with st.expander("입력·환경·조건 기록"):
        st.json({"입력":report["model"],"프로필":report["profile"],"환경":report["provenance"]},expanded=False)
    render_literature_library(process)
