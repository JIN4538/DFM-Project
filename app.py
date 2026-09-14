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
from amdfm.io import load_model
from amdfm.gcode import inspect_gcode
from amdfm.models import json_bytes
from amdfm.orientation import candidates, direction_from_angles, direction_angles, unit_direction
from amdfm.presentation import model_figure, orientation_table, html_report, placed_stl, STATUS
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


def apply_orientation(vector,presets):
    # Match vectors, since face-candidate names can differ between candidate sets.
    name=next((k for k,v in presets.items() if np.array_equal(unit_direction(v),vector)),None)
    st.session_state["build_direction"]=name or CUSTOM_DIRECTION
    if name is None and st.session_state.get("custom_vector")!=list(vector):
        tilt,azimuth=direction_angles(vector)
        st.session_state["build_tilt"]=tilt
        st.session_state["build_azimuth"]=azimuth
    st.session_state["auto_review"]=True


with st.sidebar:
    st.subheader("검토할 형상")
    local_test=Path.home()/"Desktop"/"무작위 형상 테스트"
    inputs=["CAD 기준형상","내 파일","외부 STL 사례"]
    if local_test.is_dir():inputs.append("무작위 형상 테스트")
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
    elif source=="무작위 형상 테스트":
        files=sorted(p for p in local_test.rglob("*") if p.suffix.lower() in (".step",".stp",".stl",".3mf"))
        if files:
            path=st.selectbox("형상 선택",files,format_func=lambda p:str(p.relative_to(local_test)),key="random_example")
            data,name=path.read_bytes(),path.name
            st.caption(f"바탕화면의 {len(files)}개 형상 · 원본 파일을 변경하지 않습니다.")
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
        with st.expander("장비·재료와 검토 기준"):
            st.caption("장비·재료·수치 기준은 공정별로 따로 보관합니다.")
            machine=st.text_input("장비",value="미확정",key=f"machine_{process}",persist_state="session")
            material=st.text_input("재료",value="미확정",key=f"material_{process}",persist_state="session")
            slicer=st.text_input("슬라이서·버전",value="미확정",key=f"slicer_{process}",persist_state="session")
            wall_limit=st.number_input("최소 벽 검토 기준 (mm, 선택)",min_value=.001,value=None,key=f"wall_limit_{process}",persist_state="session")
            hole_limit=st.number_input("최소 홀 검토 기준 (mm, 선택)",min_value=.001,value=None,key=f"hole_limit_{process}",persist_state="session")
            basis=st.text_input("기준 출처·시편 기록",value="사용자 탐색 조건; 실물 시편으로 보정하지 않음",key=f"basis_{process}",persist_state="session")
            process_notes=st.text_area("공정 조건·설계 요구",placeholder="온도·속도·공차·하중·후처리 등",key=f"notes_{process}",persist_state="session")
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
        st.info("왼쪽의 **설계 검토**를 누르면 수정할 위치와 방향별 손익을 확인할 수 있습니다.")
        st.write("**검토 순서**")
        st.write("1. 크기와 공정을 정합니다.\n2. 표시된 부위와 방향 대안을 확인합니다.\n3. 필요한 경우 벽·층간 검토로 좁혀갑니다.")
    st.stop()

with st.container(horizontal=True):
    st.metric("우선 조치 후보",report["summary"]["attention_items"])
    st.metric("현재 높이",f"{report['current_orientation']['height_mm']:.2f} mm")
    vol=report["geometry"]["exact_cad_volume_mm3"]
    st.metric("CAD 재료 체적" if vol is not None else "메시 체적", "미확정" if (vol if vol is not None else report["geometry"]["mesh_signed_volume_mm3"]) is None else
        f"{(vol if vol is not None else report['geometry']['mesh_signed_volume_mm3'])/1000:.3g} cm³")
    st.metric("빠른 검토",f"{report['elapsed_seconds']:.2f} s")
if model.metadata["unit_status"]=="assumed":
    st.warning("치수 미확정 STL입니다. 표시된 mm 값은 선택 단위·배율을 가정한 값입니다.")
st.caption("기하 기반 설계 검토입니다. 출력 성공·강도·표준 적합 여부는 실제 공정 검증이 필요합니다.")
tab=st.segmented_control("결과 보기",["설계 조치","방향 비교","정밀 검토","수정 전후","근거·내보내기"],default="설계 조치",key="result_tab")

if tab=="설계 조치" or tab is None:
    left,right=st.columns([3,2])
    with right:
        visible=[f for f in report["findings"] if f["status"]=="attention"]
        if not visible:
            st.info("빠른 검토에서 우선 조치할 후보가 검출되지 않았습니다. 벽 검토와 미평가 조건을 이어서 확인하세요.")
        for f in visible[:4]:
            with st.container(border=True):
                st.markdown(f"**{f['title']}**")
                st.write(f["reason"])
                st.write(f["action"])
        findings={f["id"]:f for f in report["findings"]}
        selected=st.selectbox("강조할 검토 항목",list(findings),format_func=lambda k:findings[k]["title"],
            index=list(findings).index("overhang"),key="highlight_finding")
        f=findings[selected]
        st.caption(f"상태: {STATUS[f['status']]} · CAD 면 번호: {', '.join(map(str,f['cad_face_ids'][:20])) or '—'}")
        with st.expander("측정값과 한계"):
            st.write(f["reason"])
            st.json({k:v for k,v in f["measurements"].items() if k not in ("samples","problem_face_indices","cylindrical_faces")},expanded=False)
            for text in f["limitations"]:st.caption(text)
    with left:
        transparent=st.toggle("내부 검토면 보기",value=True,key="transparent_model")
        st.plotly_chart(model_figure(model,report,selected,transparent=transparent),width="stretch")
        st.caption("주황색: 선택 항목의 검토 위치 · 녹색: 실제 적층 +Z 방향 · 드래그로 회전")
        if len(model.mesh.faces)>250_000:st.caption("화면은 삼각형 일부를 표시합니다. 분석과 내보내기는 전체 원본 형상을 사용합니다.")
        if selected=="cad_holes" and f["measurements"].get("cylindrical_faces"):
            st.dataframe(pd.DataFrame([{"CAD 면":c["face_id"],"역할":{"inner":"내측 원통","outer":"외측 원통"}.get(c["role"],"미확정"),
                "지름 (mm)":c["diameter_mm"],"축 (모델 좌표)":", ".join(f"{v:.3g}" for v in c["axis"])}
                for c in f["measurements"]["cylindrical_faces"]]),hide_index=True)
            st.caption("CAD 원통면의 해석 값입니다. 원통면 수는 구멍 수와 다르고, 설계 공차·관통 여부를 포함하지 않습니다.")
    with st.expander("전체 검토 항목"):
        st.dataframe(pd.DataFrame([{"항목":f["title"],"상태":STATUS[f["status"]],"이유":f["reason"],"설계 조치":f["action"]} for f in report["findings"]]),hide_index=True)
elif tab=="방향 비교":
    st.subheader("어느 방향에서 무엇이 달라지는가")
    st.caption(f"현재 {len(report['orientations'])}개 후보 비교 · 직접 지정한 방향도 함께 비교합니다. 전체 각도 공간의 최적해를 찾는 기능은 아닙니다.")
    st.caption("비지배 대안은 현재 후보들의 기하 지표 간 절충안입니다. 서포트 체적·인쇄 시간·강도의 최적해를 뜻하지 않습니다.")
    st.dataframe(pd.DataFrame(orientation_table(report)),hide_index=True)
    choices=[r["name"] for r in report["orientations"]]
    chosen=st.selectbox("적용할 방향",choices,key="orientation_choice")
    choice=next(r for r in report["orientations"] if r["name"]==chosen)
    current=report["current_orientation"]
    if choice["overhang_projected_area_sum_mm2"] is not None and current["overhang_projected_area_sum_mm2"] is not None:
        st.write(f"현재 대비 투영면적 합 {choice['overhang_projected_area_sum_mm2']-current['overhang_projected_area_sum_mm2']:+.2f} mm² · 높이 {choice['height_mm']-current['height_mm']:+.2f} mm")
    st.button("이 방향으로 검토",on_click=apply_orientation,args=(choice["direction"],directions),type="primary",key="apply_orientation")
elif tab=="정밀 검토":
    st.subheader("문제가 의심되는 부분을 더 자세히")
    st.write("공통 단면에서 면적·둘레와 높이별 변화를 확인하고, 의심되는 벽이나 MEX 층간 관계를 더 자세히 검토합니다.")
    guidance=section_guidance(process)
    st.markdown(f"**{guidance['title']}**")
    st.write(guidance["reason"])
    st.caption(guidance["action"])
    section_method=st.selectbox("단면 배치 방법",["형상 변화 기준 · 체적 정밀 검산","균등 간격 · 높이별 비교"],key="section_method")
    sampling="events" if section_method.startswith("형상") else "uniform"
    samples=64
    if sampling=="uniform":
        samples=st.number_input("높이 방향 단면 표본 수",min_value=2,max_value=1024,value=64,step=16,key="section_samples")
        st.caption("현재 배치 높이를 균등 분할한 중간 단면입니다. 얇은 판을 표본 사이에서 놓칠 수 있습니다. 실제 출력 층 수와는 다릅니다.")
    else:
        st.caption("메시 형상이 변하는 높이 사이마다 두 단면을 배치해 체적을 검산합니다. 최대 8,192개 단면·교차 선분 150만 개이며, 한도 초과 시 미확정으로 표시합니다. 표본 최대 면적은 전역 최대값이 아닙니다.")
    if st.button("단면 검토 실행",key="run_sections",type="primary"):
        with st.spinner("단면 면적·둘레·변화를 계산하는 중 · 최대 90초…"):
            result=run_detail(model,profile,report["current_orientation"]["direction"],mode="sections",sample_count=samples,sampling=sampling,timeout_s=90)
        st.session_state["report"]=attach_detail(report,result)
        st.rerun()
    sections=report.get("details",{}).get("sections")
    if sections:
        result_method="형상 변화 기준" if sections.get("sampling")=="events" else "균등 간격"
        st.write(f"{result_method} 결과: {sections['status']} · 확정 {sections.get('complete_samples',0)} / 요청 {sections.get('requested_samples',sections.get('sample_count','—'))}")
        if sections.get("reason"):st.info(sections["reason"])
        integral=sections.get("volume_quadrature_estimate_mm3") if sections.get("sampling")=="events" else sections.get("volume_midpoint_estimate_mm3")
        reference=report["geometry"].get("mesh_signed_volume_mm3")
        if integral is not None and reference is not None and reference>0:
            st.metric("단면 적분 체적과 메시 체적의 상대차",f"{100*abs(integral-reference)/reference:.4g}%")
            st.caption("같은 메시를 서로 다른 방법으로 집계한 검산입니다. 작은 차이도 국소 형상의 정확성이나 출력 성공을 보증하지 않습니다.")
        if sections.get("rows"):
            section_rows=pd.DataFrame([{"높이 (mm)":r["z_mm"],"면적 (mm²)":r["area_mm2"],"둘레 (mm)":r["perimeter_mm"],
                "면적/둘레 (mm)":r["area_per_perimeter_mm"],"형상 변화 면적 (mm²)":r["symmetric_change_from_previous_mm2"],
                "영역 수":r["material_regions"],"내부 윤곽 수":r["internal_loops"],"확정":r["complete"]} for r in sections["rows"]])
            st.line_chart(section_rows.set_index("높이 (mm)")[["면적 (mm²)","형상 변화 면적 (mm²)"]])
            st.caption("선은 측정 표본을 연결합니다. 표본 사이의 면적이나 이전 단면과의 높이 간격이 같은 것을 뜻하지 않습니다.")
            chosen_section=st.select_slider("확인할 단면 번호",options=list(range(len(sections["rows"]))),key="section_index")
            sr=sections["rows"][chosen_section]
            if sr["outlines"]:
                fig=go.Figure()
                for ring in sr["outlines"]:
                    fig.add_trace(go.Scatter(x=[p[0] for p in ring],y=[p[1] for p in ring],mode="lines",showlegend=False))
                fig.update_layout(height=330,xaxis_title="빌드 X (mm)",yaxis_title="빌드 Y (mm)",yaxis=dict(scaleanchor="x",scaleratio=1))
                st.plotly_chart(fig,width="stretch")
            elif sr["complete"] and not sr["outlines_complete"]:st.caption("이 단면은 표시 점 수 한도로 윤곽을 생략했습니다. 수치 집계는 전체 윤곽을 사용했습니다.")
            st.dataframe(section_rows,hide_index=True)
        for limitation in guidance["limitations"]:st.caption(limitation)
    st.divider()
    c1,c2=st.columns(2)
    with c1:
        st.markdown("**벽·세부 특징**")
        st.caption("전체 최소 두께를 보증하지 않는 표본 측정입니다. 실제 공정의 검토 기준과 대조합니다.")
        if st.button("벽 검토 실행",key="run_wall",width="stretch"):
            with st.spinner("법선 관통거리 측정 중 · 최대 60초…"):
                result=run_detail(model,profile,report["current_orientation"]["direction"],mode="wall")
            st.session_state["report"]=attach_detail(report,result)
            st.rerun()
        wall=next(f for f in report["findings"] if f["id"]=="wall")
        st.write(wall["reason"])
        if "minimum_mm" in wall["measurements"]:
            st.metric("최소 법선 관통거리",f"{wall['measurements']['minimum_mm']:.4g} mm")
            st.metric("면적 가중 하위 5% 거리",f"{wall['measurements']['area_weighted_p05_mm']:.4g} mm")
            st.caption("곡면·모서리의 짧은 관통거리는 평행한 벽 두께와 다를 수 있습니다. 강조 위치와 표본을 함께 확인하세요.")
            st.caption(f"유효 표본 {wall['measurements']['valid_samples']} / 요청 {wall['measurements']['requested_samples']}")
    with c2:
        st.markdown("**MEX 층간 검토**")
        st.caption("고정 선폭의 잔여·층간 미지지·한 층 영역을 찾습니다. 실제 슬라이서 경로와 별도의 기하 검토입니다.")
        if st.button("층간 검토 실행",disabled=process!="MEX",key="run_layers",width="stretch"):
            with st.spinner("층간 관계 계산 중 · 최대 90초…"):
                result=run_detail(model,profile,report["current_orientation"]["direction"],mode="layers",timeout_s=90)
            st.session_state["report"]=attach_detail(report,result)
            st.rerun()
    details=report.get("details",{})
    if "wall" in details and details["wall"]["status"] in ("measured","partial"):
        st.plotly_chart(model_figure(model,report,"wall"),width="stretch")
    if "layers" in details:
        layers=details["layers"]
        st.write(f"층간 결과: {layers['status']} · 확정 {layers.get('complete_layers',0)} / 요청 {layers.get('expected_layers','—')} 층")
        if layers.get("reason"):st.info(layers["reason"])
        if layers.get("layers"):
            rows=pd.DataFrame([{ "층":r["index"],"높이 (mm)":r["z_mm"],"전체 윤곽 확정":r["complete"],
                "선폭 후보 (mm²)":r.get("thin_candidate_area_mm2"),"미지지 후보 (mm²)":r.get("unsupported_candidate_area_mm2"),
                "한 층 후보 (mm²)":r.get("single_layer_candidate_area_mm2")} for r in layers["layers"]])
            st.line_chart(rows.set_index("높이 (mm)")[["선폭 후보 (mm²)","미지지 후보 (mm²)","한 층 후보 (mm²)"]])
            st.dataframe(rows,hide_index=True)
            st.caption("후보 면적에는 작은 세부가 포함됩니다. 미확정 값은 0으로 채우지 않습니다.")
    if process=="MEX":
        with st.expander("슬라이서 경로 확인 · G-code"):
            st.write("슬라이서가 실제로 생성한 경로를 읽어 얇은 특징의 누락·확대를 확인할 수 있습니다. 현재 형상과의 파일·배율·방향 일치는 자동 확정하지 않습니다.")
            gcode_mode=st.selectbox("G-code 입력",["내 G-code","Cura 기준 실험"],key="gcode_source")
            gd=None
            if gcode_mode=="내 G-code":
                gfile=st.file_uploader("Marlin 계열 G0/G1 G-code",type=["gcode"],key="gcode_upload")
                if gfile:gd=gfile.getvalue()
            else:
                gfiles=sorted((ROOT/"validation/v3/cura-experiment-02").glob("rib_*/toolpaths.gcode"))
                if gfiles:
                    gpath=st.selectbox("리브 폭 실험",gfiles,format_func=lambda p:p.parent.name,key="gcode_example")
                    gd=gpath.read_bytes()
                    st.caption("노즐 0.4 · 층 0.2 · 최소 특징 0.1 · 최소 비드 0.34 mm의 합성 CLI 조건입니다. 현재 모델의 G-code가 아닙니다.")
            diameter=st.number_input("필라멘트 지름 (mm)",min_value=.1,max_value=5.,value=1.75,key="filament_diameter")
            if gd:
                try:
                    parsed=cached_gcode(gd,diameter,ENGINE_REVISION)
                    st.write(f"해석 구간 {parsed['parsed_segments']:,}개 · 상태 {parsed['status']}")
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
                    st.download_button("G-code 검토 JSON",json_bytes(parsed),file_name="AM-DFM_gcode_review.json",mime="application/json")
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
        if comparison["reasons"]:st.info(" ".join(comparison["reasons"])+" 값은 나란히 표시하며 개선량은 계산하지 않습니다.")
        st.dataframe(pd.DataFrame(comparison["metrics"]),hide_index=True)
        st.caption(comparison["scope"])
        st.download_button("전후 비교 JSON",json_bytes(comparison),file_name="AM-DFM_design_comparison.json",mime="application/json")
else:
    st.subheader("재현 가능한 검토 기록")
    with st.container(horizontal=True):
        st.download_button("검토 보고서 HTML",html_report(report),file_name="AM-DFM_review.html",mime="text/html")
        st.download_button("전체 결과 JSON",json_bytes(report),file_name="AM-DFM_review.json",mime="application/json")
        st.download_button("현재 방향 STL · mm",placed_stl(model,report),file_name="AM-DFM_oriented_mm.stl",mime="model/stl")
        st.download_button("입력 원본",data,file_name=name,mime="application/octet-stream")
    st.caption("방향 STL에는 단위가 저장되지 않습니다. 슬라이서에서 mm로 읽고 JSON의 변환 행렬·배율을 함께 보관하세요.")
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
