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
from amdfm.evidence import section_guidance
from amdfm.section_view import render_section_result
from amdfm.detail_view import render_wall_result, render_layer_result, decision_card
from amdfm.workflow import summarize_review, ranked_orientations
from amdfm.io import load_model
from amdfm.gcode import inspect_gcode
from amdfm.models import json_bytes
from amdfm.orientation import candidates, direction_from_angles, direction_angles, unit_direction
from amdfm.presentation import model_figure, orientation_table, html_report, placed_stl
from amdfm.profiles import Profile, PROCESS_LABELS

ROOT=Path(__file__).resolve().parent
ENGINE_REVISION=code_digest()
CUSTOM_DIRECTION="직접 각도 입력"
st.set_page_config(page_title="AM-DFM | 적층제조 설계 검토",page_icon=":material/precision_manufacturing:",layout="wide")
st.title("적층제조 설계 검토")
st.caption(f"AM-DFM {__version__} · 형상을 이해하고, 방향을 비교하고, 바꿀 곳을 결정합니다.")


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


@st.cache_data(max_entries=4,show_spinner=False)
def cached_initial_wall(fingerprint,profile_dict,direction,code_revision,_model):
    result=run_detail(_model,Profile(**profile_dict),direction,mode='wall',timeout_s=5)
    result['execution_trigger']='initial_review'
    result['execution_budget_seconds']=5
    return result


def apply_orientation(vector,presets):
    # Match vectors, since face-candidate names can differ between candidate sets.
    name=next((k for k,v in presets.items() if np.array_equal(unit_direction(v),vector)),None)
    st.session_state["build_direction"]=name or CUSTOM_DIRECTION
    if name is None and st.session_state.get("custom_vector")!=list(vector):
        tilt,azimuth=direction_angles(vector)
        st.session_state["build_tilt"]=tilt
        st.session_state["build_azimuth"]=azimuth
    st.session_state["auto_review"]=True


def navigate_result(target, focus=None, finding=None):
    st.session_state['result_tab']=target
    if focus:
        st.session_state['detail_focus']=focus
    if finding:
        st.session_state['pending_finding']=finding


def apply_wall_criterion(process):
    st.session_state[f'wall_limit_{process}']=st.session_state[f'quick_wall_limit_{process}']
    st.session_state['auto_review']=True
    st.session_state['queued_detail']='wall'


def start_review():
    st.session_state['auto_review']=True


with st.sidebar:
    st.subheader("검토할 형상")
    st.caption('1. 형상 선택 → 2. 공정·방향 선택 → 3. 설계 검토')
    local_test=Path.home()/"Desktop"/"무작위 형상 테스트"
    if not local_test.is_dir():
        local_test=ROOT/'examples/corpus'
    inputs=["CAD 기준형상","내 파일","외부 STL 사례"]
    if local_test.is_dir():inputs.append("검증용 예제")
    if st.session_state.get('source')=='무작위 형상 테스트':st.session_state['source']='검증용 예제'
    source=st.selectbox("입력",inputs,key="source")
    data=None
    if source=="CAD 기준형상":
        manifest=json.loads((ROOT/"examples/cad/manifest.json").read_text(encoding="utf-8"))
        choices={x["title"]:x for x in manifest}
        title=st.selectbox("형상 선택",list(choices),index=6,key="cad_example")
        item=choices[title]
        path=ROOT/"examples/cad"/item["file"]
        data,name=path.read_bytes(),path.name
        st.caption("치수를 정의한 자체 CAD 예제입니다. 원본 STEP을 내려받아 수정할 수 있습니다.")
    elif source=="내 파일":
        upload=st.file_uploader("STEP · STL · 3MF",type=["step","stp","stl","3mf"],key="model_upload")
        if upload is not None:
            data,name=upload.getvalue(),upload.name
    elif source=="검증용 예제":
        files=sorted(p for p in local_test.rglob("*") if p.suffix.lower() in (".step",".stp",".stl",".3mf"))
        if files:
            path=st.selectbox("형상 선택",files,format_func=lambda p:str(p.relative_to(local_test)),key="random_example")
            data,name=path.read_bytes(),path.name
            corpus_location='저장소에 포함된' if local_test==ROOT/'examples/corpus' else '바탕화면의'
            st.caption(f"{corpus_location} {len(files)}개 형상 · 원본 파일을 변경하지 않습니다.")
    else:
        files=sorted((ROOT/"examples/external").glob("*.stl"))
        if files:
            path=st.selectbox("사례 선택",files,format_func=lambda p:p.name,key="external_example")
            data,name=path.read_bytes(),path.name
            st.caption("인터넷에서 받은 부품. 원래 단위·치수·설계 하중은 미확정입니다.")
        else:
            st.info("내 파일에서 외부 STL을 업로드하세요.")
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
    directions=candidates(model.mesh,True,dense=True)
    if st.session_state.get("build_direction") not in [*directions,CUSTOM_DIRECTION]:
        st.session_state["build_direction"]="+Z"
    st.divider()
    process=st.selectbox("적층제조 공정",list(PROCESS_LABELS),format_func=lambda p:PROCESS_LABELS[p],key="process")
    orientation_name=st.selectbox("위로 향할 모델 방향",[*directions,CUSTOM_DIRECTION],key="build_direction",
        help="축 6개, 두 축의 대각선 12개, 세 축의 대각선 8개와 주요 면 방향을 선택하거나 각도를 직접 입력합니다.")
    if orientation_name==CUSTOM_DIRECTION:
        tilt=st.number_input("기울기 · 모델 +Z에서 (°)",min_value=0.,max_value=180.,value=0.,step=5.,format="%.4f",key="build_tilt",persist_state="session")
        azimuth=st.number_input("방위각 · 모델 +X → +Y (°)",min_value=0.,max_value=360.,value=0.,step=5.,format="%.4f",key="build_azimuth",persist_state="session")
        direction=tuple(direction_from_angles(tilt,azimuth))
        st.session_state["custom_vector"]=list(direction)
        st.caption("기울기 0°는 +Z, 90°는 XY 평면, 180°는 −Z입니다. 이 모델 방향이 프린터의 위쪽(+Z)을 향합니다.")
    else:
        direction=tuple(unit_direction(directions[orientation_name]))
    st.caption("적층축 (모델 좌표): "+", ".join(f"{v:.6g}" for v in direction))
    with st.form("review_settings"):
        submitted=st.form_submit_button("설계 검토",type="primary",icon=":material/play_arrow:",width="stretch")
        if process=="PBF_POLYMER":
            angle=45.
            st.caption("고분자 분말베드에는 자립 각도 기준을 적용하지 않습니다. 단면·벽·분말 제거 조건을 확인합니다.")
        else:
            angle=st.number_input("하향면 탐색 각도 · 수평면 기준 (°)",min_value=1.,max_value=90.,value=45.,step=5.,key=f"angle_{process}",persist_state="session")
            st.caption("각도는 사용자 탐색 조건이며 이 공정의 보편적 출력 한계가 아닙니다.")
        dense=st.checkbox("대각선 포함 26방향 비교",value=True,key="compare_diagonals")
        extended=st.checkbox("주요 면 방향까지 비교",value=False,key="extended")
        initial_wall=st.checkbox('작은 형상은 벽도 함께 확인 · 계산 한도 5초',value=True,key='initial_wall')
        st.caption('삼각형 10,000개 이하의 단일 형상에 적용합니다. 큰 형상은 정밀 검토에서 실행할 수 있습니다.')
        with st.expander("장비·재료와 검토 기준"):
            st.caption("장비·재료·수치 기준은 공정별로 따로 보관합니다.")
            st.caption('벽·홀의 적합 여부를 비교하려면 제조사 가이드나 시편에서 정한 기준을 입력하세요. 비워 두어도 형상 측정은 가능합니다.')
            machine=st.text_input("장비",value="미확정",key=f"machine_{process}",persist_state="session")
            material=st.text_input("재료",value="미확정",key=f"material_{process}",persist_state="session")
            slicer=st.text_input("슬라이서·버전",value="미확정",key=f"slicer_{process}",persist_state="session")
            wall_limit=st.number_input("최소 벽 검토 기준 (mm, 선택)",min_value=.001,value=None,key=f"wall_limit_{process}",persist_state="session")
            hole_limit=st.number_input("최소 홀 검토 기준 (mm, 선택)",min_value=.001,value=None,key=f"hole_limit_{process}",persist_state="session")
            basis=st.text_input("기준 출처·시편 기록",value="사용자 탐색 조건; 실물 시편으로 보정하지 않음",key=f"basis_{process}",persist_state="session")
            process_notes=st.text_area("공정 조건·설계 요구",placeholder="온도·속도·공차·하중·후처리 등",key=f"notes_{process}",persist_state="session")
            st.markdown('**기준을 모를 때** · 제조사 가이드에서 같은 장비·재료·방향의 조건을 먼저 찾으세요. '
                        '시편으로 정한다면 요구 치수·형상 유지·강도 중 무엇을 만족해야 하는지 정하고 반복 출력·측정 기록을 남기세요.')
            st.caption('자체 CAD 예제는 계산 확인용이며 ISO/ASTM 52902 표준 시험물로 인증된 형상이 아닙니다. 한 번 출력된 최소 치수를 모든 부품의 기준으로 사용하지 마세요.')
        with st.expander("빌드 공간과 층 설정"):
            use_build=st.checkbox("장비 크기 제한 적용",value=False,key=f"use_build_{process}",persist_state="session")
            st.caption("선택하지 않으면 부품 크기에 제한을 두지 않고 필요한 배치 치수만 계산합니다.")
            dims=tuple(st.number_input(f"{axis} 공간 (mm)",min_value=1.,value=250.,key=f"build_{axis}_{process}",persist_state="session") for axis in "XYZ")
            clearance=st.number_input("각 경계의 여유 (mm)",min_value=0.,value=0.,key=f"clearance_{process}",persist_state="session")
            defaults={"MEX":.2,"VPP":.05,"PBF_POLYMER":.1,"PBF_METAL":.03}
            layer=st.number_input("층 높이 (mm)",min_value=.005,max_value=5.,value=defaults[process],format="%.3f",key=f"layer_{process}",persist_state="session")
            line=st.number_input("MEX 명목 선폭 (mm)",min_value=.01,max_value=5.,value=.4,key="line_width",persist_state="session") if process=="MEX" else .4
    st.caption("기본 각도·선폭은 탐색 조건입니다. 장비가 정해지면 제조사 조건과 시편 기록을 입력하세요.")

profile=Profile(process=process,machine=machine,material=material,slicer=slicer,layer_height_mm=layer,
    line_width_mm=line,overhang_angle_deg=angle,minimum_wall_mm=wall_limit,minimum_hole_mm=hole_limit,
    build_volume_mm=dims if use_build else None,clearance_mm=clearance,threshold_basis=basis,process_notes=process_notes)
fingerprint=model.fingerprint
settings_key=json_bytes([fingerprint,profile.to_dict(),direction,extended,dense,ENGINE_REVISION]).decode()
should_review=submitted or st.session_state.pop("auto_review",False)
if should_review:
    try:
        with st.spinner("문제 위치와 방향별 손익을 계산하는 중…"):
            st.session_state["report"]=cached_review(fingerprint,profile.to_dict(),direction,extended,dense,ENGINE_REVISION,model)
            st.session_state["report_settings"]=settings_key
            queued=st.session_state.pop('queued_detail',None)
            if queued:
                with st.spinner('입력한 기준으로 벽을 다시 확인하는 중…'):
                    result=run_detail(model,profile,direction,mode=queued)
                st.session_state['report']=attach_detail(st.session_state['report'],result)
            elif (initial_wall and len(model.mesh.faces)<=10_000
                  and model.metadata.get('cad_geometry_kind')!='surface'
                  and (model.metadata.get('solid_count') or 1)==1):
                with st.spinner('벽의 짧은 거리도 함께 확인하는 중 · 최대 5초…'):
                    result=cached_initial_wall(fingerprint,profile.to_dict(),direction,ENGINE_REVISION,model)
                st.session_state['report']=attach_detail(st.session_state['report'],result)
    except (ValueError,MemoryError) as exc:
        st.error(str(exc))
        st.stop()
report=st.session_state.get("report") if st.session_state.get("report_settings")==settings_key else None

if report is None:
    c1,c2=st.columns([3,2])
    with c1:
        st.plotly_chart(model_figure(model),width="stretch")
    with c2:
        st.subheader(name)
        st.write(" × ".join(f"{x:.3g}" for x in model.mesh.extents)+" mm")
        st.caption(model.metadata["unit_note"])
        st.info('먼저 아래 크기가 의도한 크기인지 확인하세요. 공정을 선택하고 설계 검토를 시작하면 확인할 부위와 다음 행동을 안내합니다.')
        st.button('이 형상으로 설계 검토 시작',type='primary',on_click=start_review,key='start_from_model')
        st.write("**검토 순서**")
        st.write("1. **설계 조치**에서 먼저 볼 위치를 확인합니다.\n2. **방향 비교**에서 목적에 맞는 배치를 고릅니다.\n3. **정밀 검토**에서 벽 기준·층간 관계·단면을 확인합니다.\n4. 수정했다면 **수정 전후**를 비교하고 보고서를 저장합니다.")
        st.caption('장비가 미확정이어도 시작할 수 있습니다. 기본값은 탐색 조건이며 공정의 보편적인 허용 한계가 아닙니다.')
    st.stop()

overview=summarize_review(report)
tab=st.segmented_control("결과 보기",["설계 조치","방향 비교","정밀 검토","수정 전후","근거·내보내기"],
                         default=st.session_state.get('result_tab') or '설계 조치',required=True,
                         persist_state='session',key="result_tab")
summary_panel=st.container(border=True) if tab in ('설계 조치',None) else st.expander('전체 검토 판단 · '+overview['title'])
with summary_panel:
    getattr(st,overview['level'])(overview['title'])
    st.write(overview['observation'])
    next_item=overview['next_item']
    if next_item:
        st.markdown(f"**먼저 할 일 · {next_item['label']}** — {overview['next_action']}")
        st.button(f"{next_item['label']} 확인하기",key='next_review_action',
                  on_click=navigate_result,args=(next_item['target'],next_item['focus'],
                                               next_item['id'] if next_item['target']=='설계 조치' else None))
if tab in ('설계 조치',None):
    with st.container(horizontal=True):
        st.metric("현재 높이",f"{report['current_orientation']['height_mm']:.2f} mm")
        st.metric('검토 공정',report['process_label'])
        vol=report["geometry"]["exact_cad_volume_mm3"]
        st.metric("CAD 재료 체적" if vol is not None else "메시 체적", "미확정" if (vol if vol is not None else report["geometry"]["mesh_signed_volume_mm3"]) is None else
            f"{(vol if vol is not None else report['geometry']['mesh_signed_volume_mm3'])/1000:.3g} cm³")
else:
    st.caption(f"{report['model']['filename']} · {report['process_label']} · 현재 높이 {report['current_orientation']['height_mm']:.4g} mm")
if model.metadata["unit_status"]=="assumed":
    st.warning("치수 미확정 STL입니다. 표시된 mm 값은 선택 단위·배율을 가정한 값입니다.")
st.caption("기하 기반 설계 검토입니다. 출력 성공·강도·표준 적합 여부는 실제 공정 검증이 필요합니다.")

if tab=="설계 조치" or tab is None:
    with st.expander('전체 검토 현황 · 끝난 확인과 남은 확인'):
        st.dataframe(pd.DataFrame([{'항목':x['label'],'현재 판단':x['state'],'다음 행동':x['next_action']}
                                  for x in overview['checklist']]),hide_index=True)
    left,right=st.columns([3,2])
    with right:
        findings={f["id"]:f for f in report["findings"]}
        priority=next((x['id'] for x in overview['checklist'] if x['level']=='warning' and x['id'] in findings),'overhang')
        identity=(report['model_fingerprint'],report['timestamp_utc'])
        if st.session_state.get('finding_result')!=identity:
            st.session_state['finding_result']=identity
            st.session_state['highlight_finding']=priority
        pending_finding=st.session_state.pop('pending_finding',None)
        if pending_finding in findings:
            st.session_state['highlight_finding']=pending_finding
        selected=st.selectbox("강조할 검토 항목",list(findings),format_func=lambda k:findings[k]["title"],
            key="highlight_finding")
        f=findings[selected]
        explanation=next(x for x in overview['checklist'] if x['id']==selected)
        decision_card({**explanation,'title':explanation['state']})
        if explanation['target']!='설계 조치':
            st.button(f"{explanation['target']}에서 이어서 확인",key='finding_action',on_click=navigate_result,
                      args=(explanation['target'],explanation['focus']))
        with st.expander("측정값과 한계"):
            st.caption(f"CAD 면 번호: {', '.join(map(str,f['cad_face_ids'][:20])) or '위치 번호 없음'}")
            st.write(f["reason"])
            st.json({k:v for k,v in f["measurements"].items() if k not in ("samples","problem_face_indices","cylindrical_faces")},expanded=False)
            for text in f["limitations"]:st.caption(text)
    with left:
        transparent=st.toggle("내부 검토면 보기",value=True,key="transparent_model")
        st.plotly_chart(model_figure(model,report,selected,transparent=transparent),width="stretch")
        st.caption('주황색: 선택 항목의 관측 위치 · 녹색: 실제 적층 +Z 방향 · 드래그로 회전. 주황색 자체가 제작 불가를 뜻하지 않습니다.')
        if not f['face_indices']:
            st.caption('이 항목에는 표시할 면 위치가 없습니다. 오른쪽의 판단과 다음 행동을 확인하세요.')
        if len(model.mesh.faces)>250_000:st.caption("화면은 삼각형 일부를 표시합니다. 분석과 내보내기는 전체 원본 형상을 사용합니다.")
        if selected=="cad_holes" and f["measurements"].get("cylindrical_faces"):
            st.dataframe(pd.DataFrame([{"CAD 면":c["face_id"],"역할":{"inner":"내측 원통","outer":"외측 원통"}.get(c["role"],"미확정"),
                "지름 (mm)":c["diameter_mm"],"축 (모델 좌표)":", ".join(f"{v:.3g}" for v in c["axis"])}
                for c in f["measurements"]["cylindrical_faces"]]),hide_index=True)
            st.caption("CAD 원통면의 해석 값입니다. 원통면 수는 구멍 수와 다르고, 설계 공차·관통 여부를 포함하지 않습니다.")
    with st.expander("전체 검토 항목"):
        st.dataframe(pd.DataFrame([{"항목":x['label'],"상태":x['state'],"이유":x['observation'],"설계 조치":x['next_action']} for x in overview['checklist']]),hide_index=True)
elif tab=="방향 비교":
    st.subheader('방향을 바꾸면 무엇이 좋아지고 나빠지나요?')
    goals=['높이를 낮추기']
    if report['current_orientation']['overhang_projected_area_sum_mm2'] is not None:
        goals.append('하향면 후보 줄이기')
    if process=='MEX' and report['current_orientation']['contact_triangle_area_mm2'] is not None:
        goals.append('평평한 바닥 넓히기')
    goal=st.selectbox('이번에 개선하고 싶은 항목',goals,key='orientation_goal')
    ranked=ranked_orientations(report,goal)
    if ranked:
        best=ranked[0]
        if all(r['build_fit'] is False for r in report['orientations']):
            st.warning('비교한 방향 중 입력한 빌드 공간에 들어가는 후보가 없습니다. 장비 공간 또는 부품 분할을 검토하세요. 아래는 지표별 비교용 순서입니다.')
        st.info(f"「{goal}」 기준으로 먼저 비교할 후보: **{best['name']}**")
        st.caption('입력한 공간을 초과하는 후보는 뒤에 배치합니다. 같은 값의 후보는 이름순이며, 첫 후보가 모든 조건에서 더 좋은 방향이라는 뜻은 아닙니다.')
        if st.button('이 후보를 아래 비교에 선택',key='select_ranked_direction'):
            st.session_state['orientation_choice']=best['name']
    choices=[r["name"] for r in report["orientations"]]
    if st.session_state.get('orientation_choice') not in choices:
        st.session_state['orientation_choice']=next((r['name'] for r in report['orientations']
            if np.allclose(r['direction'],report['current_orientation']['direction'],atol=1e-12,rtol=0)),choices[0])
    chosen=st.selectbox("적용할 방향",choices,key="orientation_choice")
    choice=next(r for r in report["orientations"] if r["name"]==chosen)
    current=report["current_orientation"]
    with st.container(horizontal=True):
        st.metric('선택 방향의 높이',f"{choice['height_mm']:.3g} mm",delta=f"{choice['height_mm']-current['height_mm']:+.3g} mm",delta_color='inverse')
        if choice['overhang_projected_area_sum_mm2'] is not None and current['overhang_projected_area_sum_mm2'] is not None:
            st.metric('하향면 투영면적 합 · 중복 포함',f"{choice['overhang_projected_area_sum_mm2']:.3g} mm²",
                      delta=f"{choice['overhang_projected_area_sum_mm2']-current['overhang_projected_area_sum_mm2']:+.3g} mm²",delta_color='inverse')
        if process=='MEX' and choice['contact_triangle_area_mm2'] is not None and current['contact_triangle_area_mm2'] is not None:
            st.metric('평평한 바닥 면적',f"{choice['contact_triangle_area_mm2']:.3g} mm²",
                      delta=f"{choice['contact_triangle_area_mm2']-current['contact_triangle_area_mm2']:+.3g} mm²",delta_color='normal')
    if choice['build_fit'] is False:
        st.warning('이 방향은 입력한 빌드 공간을 초과합니다. 다른 방향이나 장비 공간을 검토하세요.')
    st.caption('증감은 현재 방향 대비입니다. 낮은 높이는 출력 시간, 작은 하향면 투영 합은 서포트량, 넓은 바닥은 접착력을 직접 예측하지 않습니다.')
    preview={**report,'current_orientation':choice}
    st.plotly_chart(model_figure(model,preview,'orientation_preview'),width='stretch')
    st.button("이 방향으로 검토",on_click=apply_orientation,args=(choice["direction"],directions),type="primary",key="apply_orientation")
    with st.expander(f"전체 {len(report['orientations'])}개 방향의 수치 비교"):
        st.dataframe(pd.DataFrame(orientation_table(report)).rename(columns={'비지배 대안':'다른 지표와 절충되는 후보'}),hide_index=True)
        st.caption('절충되는 후보는 한 지표를 더 개선하면 다른 지표가 악화되는 후보입니다. 명시된 후보만 비교하며 연속 각도 전체의 최적 방향은 아닙니다.')
elif tab=="정밀 검토":
    st.subheader('확인하려는 질문을 선택하세요')
    focus=st.segmented_control('자세히 확인할 질문',['벽','층간','단면'],
                               default=st.session_state.get('detail_focus') or '벽',required=True,
                               persist_state='session',key='detail_focus') or '벽'
    if focus=='벽':
        st.markdown('**벽이 입력한 최소 기준보다 얇은가요?**')
        st.write('반대 면까지의 거리를 표본 위치에서 측정하고, 내가 입력한 벽 기준과 비교합니다.')
        with st.expander('이 화면에서 벽 기준 입력·변경',expanded=profile.minimum_wall_mm is None):
            st.write('사용할 장비·재료의 제조사 권장값이나 시편에서 정한 최소 벽 기준을 입력하세요. 기준을 모르면 비워 둔 채 측정 위치부터 볼 수 있습니다.')
            criterion_key=f'quick_wall_limit_{process}'
            if st.session_state.get('quick_wall_context')!=(process,profile.minimum_wall_mm):
                st.session_state['quick_wall_context']=(process,profile.minimum_wall_mm)
                st.session_state[criterion_key]=profile.minimum_wall_mm
            quick_limit=st.number_input('비교할 최소 벽 기준 (mm)',min_value=.001,value=None,key=criterion_key)
            st.caption(f'기준 출처: {profile.threshold_basis}. 출처는 왼쪽 「장비·재료와 검토 기준」에서 기록합니다.')
            st.button('이 기준으로 벽 다시 검토',key='apply_wall_criterion',on_click=apply_wall_criterion,args=(process,),disabled=quick_limit is None)
        if st.button('벽 검토 실행',key='run_wall',type='primary'):
            with st.spinner('벽의 표본 거리를 측정하는 중 · 최대 60초…'):
                result=run_detail(model,profile,report['current_orientation']['direction'],mode='wall')
            st.session_state['report']=attach_detail(report,result)
            st.rerun()
        render_wall_result(model,report)
        with st.expander('실측으로 최소 벽·홀 기준을 정하는 방법'):
            st.write('1. 같은 장비·재료·방향·슬라이서·층 조건의 제조사 가이드를 확인합니다.\n'
                     '2. 사용할 형상과 치수 범위의 시편을 여러 번 출력하고, 측정 위치·도구·허용오차·실패를 함께 기록합니다.\n'
                     '3. 출력 여부뿐 아니라 요구 치수·형상 유지·강도 등 필요한 조건을 만족한 범위를 정합니다.\n'
                     '4. 적용 가능한 조건과 여유를 정해 왼쪽 최소 벽·홀 기준과 기준 출처에 기록합니다.')
            st.caption('기준형상 14개는 수치 알고리즘 검증용입니다. 특정 프린터 능력이나 ISO/ASTM 52902 적합성을 검증한 시편 세트는 아닙니다.')
            st.download_button('시편 측정 기록 양식 CSV',
                (ROOT/'docs/templates/calibration_measurements.csv').read_bytes(),
                file_name='AM-DFM_calibration_measurements.csv',mime='text/csv',key='calibration_template')
    elif focus=='층간':
        st.markdown('**프린팅 층마다 놓치거나 받쳐 줄 곳이 있나요?**')
        if process!='MEX':
            st.info('이 검사는 압출 선폭과 아래층 관계를 사용하는 MEX(FDM) 전용입니다. 현재 공정에서는 벽과 단면을 확인하세요.')
        else:
            st.write(f'층 높이 {profile.layer_height_mm:g} mm · 선폭 {profile.line_width_mm:g} mm · 수평 기준 탐색 각도 {profile.overhang_angle_deg:g}°로 후보를 찾습니다.')
            st.caption('설정은 왼쪽 「빌드 공간과 층 설정」에서 바꿀 수 있습니다. 실제 슬라이서 경로와는 별도의 형상 검사입니다.')
        if st.button('층간 검토 실행',disabled=process!='MEX',key='run_layers',type='primary'):
            with st.spinner('각 층과 이웃한 층을 비교하는 중 · 최대 90초…'):
                result=run_detail(model,profile,report['current_orientation']['direction'],mode='layers',timeout_s=90)
            st.session_state['report']=attach_detail(report,result)
            st.rerun()
        if process=='MEX':
            render_layer_result(model,report)
    else:
        st.markdown('**어느 높이에서 단면 모양과 넓이가 크게 바뀌나요?**')
        guidance=section_guidance(process)
        st.markdown(f"**{guidance['title']}**")
        st.write(guidance["reason"])
        st.caption(guidance["action"])
        section_method=st.selectbox("단면 배치 방법",["자동 · 가능한 방법으로 단면 확인","형상 변화 기준 · 체적 정밀 검산","균등 간격 · 높이별 비교"],key="section_method")
        sampling='auto' if section_method.startswith('자동') else "events" if section_method.startswith("형상") else "uniform"
        samples=64
        if sampling in ('uniform','auto'):
            samples=st.number_input('균등 전환 시 사용할 단면 수' if sampling=='auto' else "높이 방향 단면 표본 수",min_value=2,max_value=1024,value=64,step=16,key="section_samples")
            st.caption('자동은 형상 변화 기준을 먼저 시도하고 계산 예산을 넘을 때만 위 개수의 균등 단면으로 이어갑니다. 전환 사유와 원래 시도를 결과에 보존합니다.' if sampling=='auto' else "현재 배치 높이를 균등 분할한 중간 단면입니다. 얇은 판을 표본 사이에서 놓칠 수 있습니다. 실제 출력 층 수와는 다릅니다.")
        else:
            st.caption("얇은 높이 구간도 포함하도록 검사할 높이를 자동으로 정합니다. 계산한 단면을 비교해 확인할 위치를 안내합니다.")
        if st.button("단면 검토 실행",key="run_sections",type="primary"):
            with st.spinner("단면 면적·둘레·변화를 계산하는 중 · 최대 90초…"):
                result=run_detail(model,profile,report["current_orientation"]["direction"],mode="sections",sample_count=samples,sampling=sampling,timeout_s=90)
            st.session_state["report"]=attach_detail(report,result)
            st.rerun()
        sections=report.get("details",{}).get("sections")
        if sections:
            if sections.get('requested_sampling',sections.get("sampling","uniform"))!=sampling or (sampling in ('uniform','auto') and sections.get("sample_count",samples)!=samples):
                st.info("아래는 이전 설정으로 계산한 결과입니다. 변경한 설정을 적용하려면 단면 검토 실행을 누르세요.")
            render_section_result(sections,process,report['geometry'].get('mesh_signed_volume_mm3'))
            with st.expander('이 공정에서 단면 결과를 사용하는 범위'):
                for limitation in guidance['limitations']:st.write(limitation)
    if process=="MEX":
        with st.expander("슬라이서 경로 확인 · G-code"):
            st.markdown('**실제 슬라이서에서도 이 부위가 남아 있나요?**')
            st.write("슬라이서가 실제로 생성한 경로를 읽어 얇은 특징의 누락·확대를 확인할 수 있습니다. 현재 형상과의 파일·배율·방향 일치는 자동 확정하지 않습니다.")
            st.write('현재 방향 STL을 내보내 슬라이싱한 뒤 G-code를 넣으세요. 확인할 높이를 선택하고 얇은 부위에 압출 경로가 남아 있는지 확인합니다.')
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
            st.write('하향면 후보와 높이가 줄었는지, 벽 거리와 체적이 어떻게 바뀌었는지 함께 확인하세요. 체적 증가나 거리 증가만으로 기능·강도가 개선됐다고 판단하지 않습니다.')
        st.dataframe(pd.DataFrame(comparison["metrics"]),hide_index=True)
        st.caption(comparison["scope"])
        st.download_button("전후 비교 JSON",json_bytes(comparison),file_name="AM-DFM_design_comparison.json",mime="application/json")
else:
    st.subheader('결과를 전달하거나 다음 작업으로 가져가세요')
    st.write('**사람에게 설명하기:** HTML 보고서 · **슬라이서에서 확인하기:** 현재 방향 STL · **측정값과 조건 재현하기:** 전체 결과 JSON · **CAD 수정하기:** STEP 입력 원본')
    with st.container(horizontal=True):
        st.download_button("검토 보고서 HTML",html_report(report),file_name="AM-DFM_review.html",mime="text/html")
        st.download_button("전체 결과 JSON",json_bytes(report),file_name="AM-DFM_review.json",mime="application/json")
        st.download_button("현재 방향 STL · mm",placed_stl(model,report),file_name="AM-DFM_oriented_mm.stl",mime="model/stl")
        st.download_button("입력 원본",data,file_name=name,mime="application/octet-stream")
    st.caption("방향 STL에는 단위가 저장되지 않습니다. 슬라이서에서 mm로 읽고 JSON의 변환 행렬·배율을 함께 보관하세요.")
    st.info('보고서에는 현재까지 실행한 검사와 아직 확인하지 않은 항목이 함께 저장됩니다. 정밀 검토를 추가로 실행하면 새 보고서에 반영됩니다.')
    st.write("**별도 확인할 제조 조건**")
    st.write(" · ".join(report["unassessed"]))
    st.write("**규칙의 이유와 출처**")
    for key,s in report["sources"].items():
        with st.expander(f"{key} · {s['title']}"):
            st.write(s["use"])
            st.caption(f"{s['locator']} · {s['access']}")
            if s["url"]:st.link_button("원출처",s["url"])
    with st.expander("입력·환경·조건 기록"):
        st.json({"입력":report["model"],"프로필":report["profile"],"환경":report["provenance"]},expanded=False)
