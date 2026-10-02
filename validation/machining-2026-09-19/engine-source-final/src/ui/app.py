"""AM-DFM Evaluator — Streamlit 웹 애플리케이션 (v2)

v1 대비 주요 변경
-----------------
1. 평가 시점의 설정(공정/방향/프린터/단위)을 결과와 함께 저장하고 그것만 표시한다.
   v1은 결과는 이전 값, 표시는 현재 위젯 값이라 사이드바만 만지면
   화면의 '빌드 방향'이 실제 계산과 달라졌다.
2. 3D 뷰어 facecolor 를 Plotly가 받는 색 문자열 배열로 넘긴다.
   v1은 0~1 실수 배열을 넘겨서 오버행 하이라이트가 렌더링되지 않을 수 있었다.
3. 하드 게이트 결과와 메시 진단 경고를 최상단에 표시한다.
4. STL 단위 선택 UI를 추가했다(STL 파일에는 단위 정보가 없다).
5. 방향 비교를 6방향으로 하고, 결과를 한 번만 계산해 재사용한다.
   v1은 evaluate_all_orientations + find_optimal_orientation 로 6회 중복 평가했다.
6. N/A 규칙을 100점이 아니라 N/A로 표시하고 가중치 재분배를 명시한다.
7. 가중치 민감도 분석 버튼을 추가했다(가중치 근거가 임의라는 한계 대응).
"""

import os
import sys
import tempfile
import inspect
import hashlib

import numpy as np
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.core.model_loader import load_model, generate_sample_models, diagnose, UNIT_SCALE
from src.core.scoring import (evaluate_orientations, pick_best, results_to_rows,
                              sensitivity_analysis, pareto_front, AXIS_ORIENTATIONS)
from src.core import geometry_analyzer as ga
from src.core.reproducibility import APP_VERSION, json_text, runtime_record
from src.core.mesh_diagnostics import inspect_mesh, cleanup_preview, mesh_digest
from src.core.weights import ahp, pair_list, SAATY_SCALE, compare_weight_sets
from src.processes.additive import (AMRuleEngine, PROCESS_PARAMS, ProcessType,
                                     PROCESS_TERMS, process_label, BASE_WEIGHTS,
                                     RULE_LABELS, provenance_report)

# ──────────────────────────────────────────────────────────────
def render_3d(mesh, build_direction, overhang_faces=None, in_plane_rotation_deg=0,
              highlight_label='지지구조 필요 면'):
    """빌드 좌표계로 회전한 메시를 그린다. 화면의 위쪽이 항상 적층 방향이다."""
    m = ga.to_build_frame(mesh, build_direction)
    if in_plane_rotation_deg:
        import trimesh
        m.apply_transform(trimesh.transformations.rotation_matrix(np.radians(in_plane_rotation_deg), [0, 0, 1]))
    v, f = m.vertices, m.faces
    base, hot = 'rgb(90,140,205)', 'rgb(225,60,55)'
    colors = np.array([base] * len(f), dtype=object)
    if overhang_faces is not None and len(overhang_faces):
        idx = np.asarray(overhang_faces, dtype=int)
        colors[idx[(idx >= 0) & (idx < len(f))]] = hot
    fig = go.Figure(go.Mesh3d(
        x=v[:, 0], y=v[:, 1], z=v[:, 2],
        i=f[:, 0], j=f[:, 1], k=f[:, 2],
        facecolor=colors.tolist(), flatshading=True,
        lighting=dict(ambient=.55, diffuse=.8, specular=.15),
    ))
    fig.update_layout(scene=dict(xaxis_title='X (mm)', yaxis_title='Y (mm)',
                                 zaxis_title='빌드 방향 (mm)', aspectmode='data'),
                      margin=dict(l=0, r=0, t=28, b=0), height=460,
                      title=f"빌드 좌표계 (빨강 = {highlight_label})")
    return fig


def render_mesh_diagnostics(report):
    if not report:
        return
    st.subheader('입력 메시 진단')
    if report.get('geometry_available'):
        columns = st.columns(4)
        for col, title, key in zip(columns,
                ('열린 경계', '비정상 면 연결', '중복 삼각형', '퇴화 삼각형'),
                ('boundary_edges', 'nonmanifold_edges', 'duplicate_faces', 'degenerate_faces')):
            col.metric(title, f"{report[key]:,}")
    st.caption('비정상 면 연결은 한 모서리에 3개 이상 면이 붙은 경우입니다. '
               '중복면과 퇴화면의 개수는 서로 겹칠 수 있습니다. 자기교차 전체를 검증하는 검사는 아닙니다.')
    if report.get('highlight_truncated'):
        st.caption(f"문제 면 {report['problem_face_count']:,}개 중 앞 {len(report['problem_face_indices']):,}개를 강조합니다.")


@st.cache_resource(max_entries=4, ttl=900, show_spinner=False)
def layer_preview_frame(mesh_key, direction, version, _mesh):
    """Cache by geometry and transform; query() leaves the shared index unchanged."""
    from src.core.section_index import FaceZIndex
    m=ga.to_build_frame(_mesh,direction)
    return m,FaceZIndex(m)


@st.cache_data(max_entries=64, ttl=900, show_spinner=False)
def layer_preview_section(mesh_key, direction, z, version, _mesh):
    from src.core.sections import section_mesh
    m,index=layer_preview_frame(mesh_key,direction,version,_mesh)
    return section_mesh(m,[0,0,z],[0,0,1],axes=np.eye(3)[:2],
                        local_faces=index.query(z,1e-8),vertex_projection=index.projection,
                        mesh_scale_mm=index.scale_mm)


def render_layer_review(mesh, result):
    review = result.layer_review
    if not review or review.get('status') in ('not_applicable', 'not_requested'):
        return
    st.subheader('FDM 층별 제조성 검토')
    if review['status'] == 'complete':
        st.success(f"FDM 단면 검토 완료 · {review['examined_layers']}개 층 계산. 검토 영역과 조건을 아래에서 확인하세요.")
    elif review['status'] == 'partial':
        st.warning(f"FDM 단면 검토 · {review['complete_layers']}/{review['expected_layers']}개 층 단면 확정. 미확정 단면·지표를 확인하세요.")
    else:
        st.warning(review.get('reason', 'FDM 단면을 구성하지 못했습니다.'))
        return
    st.caption(f"선폭 {review['line_width_mm']:g}mm · 층 높이 {review['layer_height_mm']:g}mm · "
               f"경사 기준 {review['critical_angle_deg']:g}°. 단면 검토는 실제 출력 성공이나 3D 종합 점수의 통과를 뜻하지 않습니다.")
    c = st.columns(3)
    c[0].metric('확정 단면 / 요청 층', f"{review['complete_layers']} / {review['expected_layers']}")
    volume = review.get('volume_estimate_mm3')
    c[1].metric('층단면 부피 (근사 mm³)', f'{volume:,.2f}' if volume is not None else '미확정')
    contact = review.get('first_layer_area_mm2')
    c[2].metric('첫 층 단면적 (mm²)', f'{contact:,.2f}' if contact is not None else '미확정')
    labels = {'risk':'검토 영역 있음', 'clear_in_layers':'해당 층에서 미검출', 'unresolved':'미확정', 'details_only':'작은 세부만 기록'}
    table=[]
    for check in review['checks']:
        value = labels[check['status']]
        if check['name'] == '단면 구성' and check['status'] == 'clear_in_layers': value='계산 완료'
        table.append({'검사':check['name'], '결과':value,
                      '전체 범위 측정 층':f"{check.get('fully_measured_layers',0)} / {review['expected_layers']}",
                      '부분 포함 측정 층':check['measured_layers'],
                      '해당 층 수':check.get('risk_layers'),
                      '우선 검토 합(mm²)':round(check['sum_mm2'],6) if check.get('sum_mm2') is not None else None,
                      '작은 세부 합(mm²)':round(check['detail_sum_mm2'],6) if check.get('detail_sum_mm2') is not None else None,
                      '전체 후보 합(mm²)':round(check['candidate_sum_mm2'],6) if check.get('candidate_sum_mm2') is not None else None})
    st.dataframe(table, use_container_width=True, hide_index=True)
    st.caption(f"세 검사 모두 표시 하한 {review.get('display_floor_mm2',0):g}mm² 미만을 작은 세부로 기록합니다. "
               "성분 전체가 해당하는 경우에는 크기와 무관하게 우선 검토합니다. 전체 후보 합 = 우선 검토 합 + 작은 세부 합입니다.")
    if review.get('partial_component_layers',0):
        st.info(f"전체 단면이 미확정인 {review['partial_component_layers']}개 층에서도 손상 영역에서 분리된 닫힌 성분을 검사했습니다. "
                "합산값은 확인한 부분에만 해당하며 전체 면적이나 전체 처리율로 환산하지 않습니다.")
    with st.expander('단면 검사 항목의 의미와 계산 조건'):
        for check in review['checks']:
            st.write(f"**{check['name']}** — {check['description']}")
        for warning in review['warnings']: st.caption(warning)
        st.caption('합산 면적은 여러 층의 검토 영역을 더한 값이며 실제 서포트 부피가 아닙니다. '
                   '일부 층만 측정했다면 합산값도 그 층들에 한합니다. '
                   '얇은 단면 특징에는 작은 모서리 세부도 포함됩니다. 검출 면적과 위치를 함께 확인하세요.')
    rows=review['layers']
    if not rows: return
    default=max(range(len(rows)), key=lambda i: rows[i]['thin_area_mm2'] or 0)
    if len(rows)>1:
        index=st.slider('확인할 단면 층',0,len(rows)-1,default)
    else:
        index=0
    overlay=st.selectbox('단면 표시 항목',['선폭 기준 얇은 특징','작은 선폭 세부','지지·브리지 검토 영역','작은 지지·브리지 세부','한 층에만 나타나는 영역','작은 한 층 세부','기본 단면'])
    row=rows[index]
    st.caption(f"층 {index+1} · 계산 높이 Z={row['z_mm']:.8g}mm · "
               f"{'단면 확정' if row['complete'] else '단면 미확정'}")
    try:
        import shapely as sh
        from src.core.sections import opening_residual
        from src.core.layer_regions import classify_thin_regions, classify_difference_regions, comparison_scope
        digest=mesh_digest(mesh);direction=tuple(result.build_direction)
        def preview(j):
            return layer_preview_section(digest,direction,rows[j]['z_mm'],APP_VERSION,mesh)
        def known(section):
            return section.material if section.diagnostics['complete'] else (section.known_material if section.known_material is not None else sh.GeometryCollection())
        s=preview(index);material=known(s)
        fig=go.Figure()
        angle=np.radians(result.in_plane_rotation_deg)
        rotate=np.array([[np.cos(angle),np.sin(angle)],[-np.sin(angle),np.cos(angle)]])
        def draw(geometry,color,label,width):
            x,y=[],[]
            for polygon in sh.get_parts(geometry):
                if polygon.geom_type!='Polygon': continue
                for ring in [polygon.exterior,*polygon.interiors]:
                    xy=np.asarray(ring.coords)@rotate
                    x.extend(xy[:,0]); x.append(None); y.extend(xy[:,1]); y.append(None)
            if x: fig.add_trace(go.Scatter(x=x,y=y,mode='lines',line=dict(color=color,width=width),name=label))
        draw(material,'#64748b','확인된 단면 경계 (구멍 포함)',1)
        for bounds in row['diagnostics'].get('unknown_bounds_mm',[]):
            draw(sh.box(*bounds),'#9ca3af','미확정 영역 범위',1)
        if row['thin_area_mm2'] is not None and overlay in ('선폭 기준 얇은 특징','작은 선폭 세부'):
            major,minor,_=classify_thin_regions(material,opening_residual(material,review['line_width_mm']),review['line_width_mm'],s.diagnostics['grid_mm'])
            draw(sh.union_all(major if overlay=='선폭 기준 얇은 특징' else minor),
                 '#dc2626' if overlay=='선폭 기준 얇은 특징' else '#2563eb',overlay,3)
        elif overlay in ('지지·브리지 검토 영역','작은 지지·브리지 세부') and index>0 and row['unsupported_area_mm2'] is not None:
            previous=known(preview(index-1));step=row['z_mm']-rows[index-1]['z_mm']
            angle=review['critical_angle_deg'];reach=step/np.tan(np.radians(angle)) if angle<90 else 0.
            eligible=comparison_scope(material,[rows[index-1]],reach)
            under=previous.buffer(reach) if reach else previous
            major,minor,_=classify_difference_regions(eligible,under,review['line_width_mm'],s.diagnostics['grid_mm'],'unsupported')
            draw(sh.union_all(minor if overlay=='작은 지지·브리지 세부' else major),
                 '#2563eb' if overlay=='작은 지지·브리지 세부' else '#d97706',overlay,3)
        elif overlay in ('한 층에만 나타나는 영역','작은 한 층 세부') and row['single_layer_area_mm2'] is not None:
            adjacent=[j for j in (index-1,index+1) if 0<=j<review['expected_layers']]
            eligible=comparison_scope(material,[rows[j] if j<len(rows) else None for j in adjacent])
            neighbors=sh.union_all([known(preview(j)) for j in adjacent if j<len(rows)])
            major,minor,_=classify_difference_regions(eligible,neighbors,review['line_width_mm'],s.diagnostics['grid_mm'],'single_layer')
            draw(sh.union_all(minor if overlay=='작은 한 층 세부' else major),
                 '#2563eb' if overlay=='작은 한 층 세부' else '#7c3aed',overlay,3)
        fig.update_layout(height=400,margin=dict(l=20,r=20,t=30,b=20),
                          xaxis_title='빌드 X (mm)',yaxis_title='빌드 Y (mm)',
                          yaxis=dict(scaleanchor='x',scaleratio=1),legend=dict(orientation='h'))
        st.plotly_chart(fig,use_container_width=True)
        if not row['complete']: st.warning(row['diagnostics'].get('reason','열린 단면 또는 계산 한도 확인이 필요합니다.'))
    except Exception as exc:
        st.warning(f'단면 표시를 완료하지 못했습니다: {exc}')
    for prefix,label in (('thin','선폭'),('unsupported','지지·브리지'),('single_layer','한 층')):
        if row.get(prefix+'_details'):
            with st.expander(f'선택 층의 {label} 세부 기록'):
                st.caption('2 × 면적 ÷ 둘레는 영역의 크기를 설명하는 보조값이며 국소 벽두께가 아닙니다. 원에서는 지름이 아닌 반지름에 해당합니다.')
                st.dataframe([{'분류':'우선 검토' if p['priority']=='review' else '작은 세부',
                               '면적(mm²)':p['area_mm2'],'둘레(mm)':p['perimeter_mm'],
                               '면적 둘레 크기(mm)':p['area_perimeter_scale_mm'],
                               '성분 전체 해당':p['whole_component_affected']} for p in row[prefix+'_details']],hide_index=True)
                if row.get(prefix+'_details_truncated'):st.caption('면적이 큰 순으로 50개만 표에 표시합니다. 모든 후보의 수와 면적 합계는 결과에 보존합니다.')
    with st.expander('층별 수치 보기'):
        st.dataframe([{'층':r['index']+1,'Z(mm)':r['z_mm'],'단면 확정':r['complete'],
                       '전체 단면적(mm²)':r['area_mm2'],'확인 부분 면적(mm²)':r['known_area_mm2'],
                       '선폭 검토(mm²)':r['thin_area_mm2'],'선폭 세부(mm²)':r['thin_detail_area_mm2'],
                       '지지 검토(mm²)':r['unsupported_area_mm2'],'지지 세부(mm²)':r['unsupported_detail_area_mm2'],
                       '한 층만 존재(mm²)':r['single_layer_area_mm2'],'한 층 세부(mm²)':r['single_layer_detail_area_mm2']} for r in rows],
                     use_container_width=True,hide_index=True)


def render_gauge(score, grade):
    color = {'A': '#27ae60', 'B': '#2ecc71', 'C': '#f39c12',
             'D': '#e67e22', 'F': '#e74c3c'}.get(grade, '#95a5a6')
    fig = go.Figure(go.Indicator(
        mode="gauge+number", value=score,
        title={'text': f"등급 {grade}", 'font': {'size': 22}},
        gauge={'axis': {'range': [0, 100]}, 'bar': {'color': color, 'thickness': .6},
               'steps': [{'range': [0, 60], 'color': '#fdeaea'},
                         {'range': [60, 80], 'color': '#fdf4d8'},
                         {'range': [80, 100], 'color': '#e3f4e6'}]},
        number={'font': {'size': 40}}))
    fig.update_layout(height=260, margin=dict(l=30, r=30, t=50, b=0))
    return fig


def render_radar(rules):
    scored = [r for r in rules if r.score is not None]
    if len(scored) < 3:
        return None
    names = [r.label.split(' (')[0] for r in scored]
    vals = [r.score for r in scored]
    fig = go.Figure(go.Scatterpolar(r=vals + [vals[0]], theta=names + [names[0]],
                                    fill='toself', line=dict(color='#2980b9', width=2),
                                    fillcolor='rgba(41,128,185,.2)'))
    fig.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                      showlegend=False, height=380, title="규칙별 점수 (N/A 규칙 제외)")
    return fig


# ──────────────────────────────────────────────────────────────
# AHP — 쌍대비교로 가중치 도출
# ──────────────────────────────────────────────────────────────
AHP_ITEMS = ['wall_thickness', 'overhang_area', 'support_volume',
             'aspect_ratio', 'build_margin']


def render_ahp():
    st.markdown("---")
    st.subheader("가중치 도출 (AHP 쌍대비교)")
    st.caption("현재 가중치는 판단으로 정한 값입니다. 두 항목씩 비교하면 "
               "가중치를 산출하고 응답의 논리적 일관성까지 검증할 수 있습니다. "
               "5개 항목이므로 10번만 비교하면 됩니다.")

    with st.expander("쌍대비교 설문 열기", expanded=False):
        st.caption("각 쌍에서 어느 쪽이 제조성 판단에 더 중요한지, 얼마나 더 중요한지 고르세요.")
        pairs = pair_list(AHP_ITEMS)
        comps = {}
        for i, (a, b) in enumerate(pairs):
            la = RULE_LABELS[a].split(' (')[0]
            lb = RULE_LABELS[b].split(' (')[0]
            st.markdown(f"**{i+1}. {la}  vs  {lb}**")
            c1, c2 = st.columns([1, 1])
            side = c1.radio("더 중요한 쪽", [la, "동등", lb],
                            index=1, key=f"ahp_side_{i}", horizontal=True,
                            label_visibility="collapsed")
            if side == "동등":
                comps[(a, b)] = 1.0
                c2.caption("동등하게 중요")
            else:
                lvl = c2.select_slider(
                    "정도", options=list(SAATY_SCALE), value=3,
                    format_func=lambda v: f"{v} · {SAATY_SCALE[v]}",
                    key=f"ahp_lvl_{i}", label_visibility="collapsed")
                comps[(a, b)] = float(lvl) if side == la else 1.0 / float(lvl)
            st.divider()

        if st.button("가중치 계산", type="primary"):
            try:
                st.session_state.ahp = ahp(AHP_ITEMS, comps)
            except Exception as e:
                st.error(f"계산 실패: {e}")

    res = st.session_state.get('ahp')
    if not res:
        return

    cr = res['consistency_ratio']
    m = st.columns(3)
    m[0].metric("일관성 비율 CR", f"{cr:.4f}")
    m[1].metric("판정", "일관됨" if res['consistent'] else "재검토 필요")
    m[2].metric("최대 고윳값", f"{res['lambda_max']:.4f}")
    if res['consistent']:
        st.success("CR이 0.10 미만입니다. 응답 일관성 기준을 통과했지만 제조성 예측 타당성을 검증한 것은 아닙니다.")
    else:
        st.warning("CR이 0.10 이상입니다. 응답에 모순이 있습니다"
                   "(예: A>B, B>C 인데 C>A). 몇 개 문항을 재검토하세요.")

    rows = compare_weight_sets({
        '현재(5항목 내 정규화)': {k: BASE_WEIGHTS[k] / sum(BASE_WEIGHTS[x] for x in AHP_ITEMS) for k in AHP_ITEMS},
        'AHP(고유벡터)': res['weights'],
        'AHP(기하평균)': res['weights_geometric'],
    })
    for r in rows:
        r['규칙'] = RULE_LABELS.get(r['규칙'], r['규칙']).split(' (')[0]
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.caption("이 설문은 5항목 내부 비교이며 현재 평가 결과에 자동 적용되지 않습니다. "
               "두 AHP 산출법의 결과가 비슷하면 계산이 안정적이라는 뜻입니다. "
               "'현재'와 차이가 크다면 판단 근거를 재검토할 근거가 됩니다. "
               "여러 명에게 받은 뒤 기하평균으로 종합하는 것이 표준 절차입니다.")


# ──────────────────────────────────────────────────────────────
# 소스코드 뷰어 — 지금 실행 중인 코드를 그대로 보여준다
# ──────────────────────────────────────────────────────────────
def _key_functions():
    """미팅에서 자주 물어볼 핵심 함수들."""
    from src.processes import additive as ad
    from src.core.layer_review import inspect_layers
    return {
        "① 오버행 판정 — compute_overhang": ga.compute_overhang,
        "② 빌드 좌표계 변환 — to_build_frame": ga.to_build_frame,
        "③ 지지구조물 부피 — compute_support_volume": ga.compute_support_volume,
        "④ 벽두께 측정 — compute_wall_thickness": ga.compute_wall_thickness,
        "⑤ 종횡비 — compute_aspect_ratio": ga.compute_aspect_ratio,
        "⑥ 점수 함수(작을수록 좋음) — score_at_most": ad.score_at_most,
        "⑦ 점수 함수(클수록 좋음) — score_at_least": ad.score_at_least,
        "⑧ 하드 게이트 — _run_gates": ad.AMRuleEngine._run_gates,
        "⑨ 가중치 재정규화 — _normalize_weights": ad.AMRuleEngine._normalize_weights,
        "⑩ FDM 층별 제조성 검토 — inspect_layers": inspect_layers,
    }


def _source_files():
    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    rel = ['src/core/geometry_analyzer.py', 'src/processes/additive.py',
           'src/core/sections.py', 'src/core/layer_review.py', 'src/core/mesh_diagnostics.py',
           'src/core/scoring.py', 'src/core/model_loader.py',
           'src/core/cura_records.py', 'src/core/validation_metrics.py',
           'src/core/reproducibility.py', 'cura_check.py', 'audit_models.py',
           'src/ui/app.py', 'verify.py', 'requirements.txt']
    return {r: os.path.join(root, *r.split('/')) for r in rel}


def render_source_viewer():
    st.markdown("---")
    with st.expander("💻 소스코드 보기 (지금 실행 중인 코드)", expanded=False):
        tab1, tab2 = st.tabs(["핵심 함수", "전체 파일"])

        with tab1:
            funcs = _key_functions()
            pick = st.selectbox("함수 선택", list(funcs), key="src_fn")
            fn = funcs[pick]
            try:
                src = inspect.getsource(fn)
                file = inspect.getsourcefile(fn)
                line = inspect.getsourcelines(fn)[1]
                st.caption(f"{os.path.basename(file)} : {line}행")
                st.code(src, language='python')
            except Exception as e:
                st.error(f"소스를 읽을 수 없습니다: {e}")

        with tab2:
            files = _source_files()
            pick = st.selectbox("파일 선택", list(files), key="src_file")
            try:
                with open(files[pick], encoding='utf-8') as fh:
                    text = fh.read()
                st.caption(f"{files[pick]}  ·  {len(text.splitlines())}행")
                st.code(text, language='python')
            except Exception as e:
                st.error(f"파일을 읽을 수 없습니다: {e}")


# ──────────────────────────────────────────────────────────────
def main():
    st.set_page_config(page_title=f"AM-DFM Evaluator v{APP_VERSION}", page_icon="🔧",
                      layout="wide", initial_sidebar_state="expanded")
    # Initialize for EVERY session, not once when this module is imported.
    for key in ('result', 'ctx', 'orient', 'sens', 'ahp', 'assessed_mesh'):
        st.session_state.setdefault(key, None)
    with st.sidebar:
        st.title("🔧 AM-DFM Evaluator")
        st.caption(f"v{APP_VERSION} · 하드 게이트 + 소프트 점수")
        st.markdown("---")

        st.subheader("모델 입력")
        source = st.radio("입력 방식", ["샘플 모델", "STL 업로드"], index=0)
        mesh, model_name, warns = None, "", []
        unit = "mm"
        source_file_sha256 = None
        preprocessing = {}

        if source == "샘플 모델":
            try:
                samples = generate_sample_models()
                keys = list(samples)
                key = st.selectbox("샘플 선택", keys,
                                   format_func=lambda k: samples[k]['name'])
                mesh, model_name = samples[key]['mesh'], samples[key]['name']
                st.caption(samples[key]['description'])
                warns = diagnose(mesh)
            except RuntimeError as exc:
                st.error(str(exc))
        else:
            unit = st.selectbox("파일 단위", list(UNIT_SCALE), index=0,
                                help="STL 파일에는 단위 정보가 없습니다. 잘못 고르면 모든 임계값이 어긋납니다. "
                                     "근거: KS D ISO/ASTM 52910 7.10 (STL 단위 부재로 인한 크기 오류)")
            up = st.file_uploader("STL 파일", type=['stl'])
            if up is not None:
                source_file_sha256 = hashlib.sha256(up.getvalue()).hexdigest()
                with tempfile.NamedTemporaryFile(suffix='.stl', delete=False) as fh:
                    fh.write(up.getvalue()); tmp = fh.name
                try:
                    d = load_model(tmp, unit=unit)
                    mesh, model_name, warns = d['mesh'], up.name, d['warnings']
                except Exception as e:
                    st.error(f"로드 실패: {e}")
                finally:
                    os.unlink(tmp)

        if mesh is not None:
            mode = st.radio('분석에 사용할 메시', ['원본', '보수적 정리본'], horizontal=True,
                            help='정리본은 면적 0인 면과 같은 방향의 정확한 중복면만 제거합니다. '
                                 '형상 복구나 제조 가능을 보장하지 않습니다.')
            if mode == '보수적 정리본':
                candidate, preprocessing = cleanup_preview(mesh)
                preprocessing['mode'] = 'conservative_cleanup'
                preprocessing['source_file_sha256'] = source_file_sha256
                preprocessing['export_unit'] = 'mm'
                st.caption(f"제거: 퇴화면 {preprocessing['removed_zero_area_faces']:,}개 · "
                           f"같은 방향 중복면 {preprocessing['removed_oriented_duplicates']:,}개")
                st.caption(preprocessing['note'])
                delta = preprocessing.get('bounds_max_change_mm')
                if delta is not None:
                    st.caption(f'외곽 좌표 최대 변화: {delta:.6g} mm')
                if preprocessing['after']['geometry_available']:
                    mesh = candidate
                    warns = diagnose(mesh)
                    st.caption('후보 STL은 mm 좌표로 저장됩니다. 다시 업로드할 때 파일 단위를 mm로 선택하세요.')
                    st.download_button('정리 후보 STL 다운로드 (mm)', mesh.export(file_type='stl'),
                        file_name=os.path.splitext(os.path.basename(model_name))[0] + '_mm_cleanup_candidate.stl',
                        mime='application/octet-stream')
                else:
                    st.error('정리 후보에 분석 가능한 면이 없습니다. 원본을 선택해 입력을 검토하세요.')
                    mesh = None
                st.download_button('메시 정리 내역 JSON', json_text(preprocessing),
                                   file_name='mesh_cleanup_review.json', mime='application/json')
            else:
                fingerprint = mesh_digest(mesh)
                preprocessing = dict(mode='original', source_file_sha256=source_file_sha256,
                    source_mesh_sha256=fingerprint, analyzed_mesh_sha256=fingerprint,
                    changes_applied=False)
                mesh.metadata['preprocessing'] = preprocessing

        st.markdown("---")
        st.subheader("공정 및 장비")
        process = st.selectbox(
            "공정", [p.value for p in ProcessType], index=0,
            format_func=lambda v: process_label(v, short=True),
            help="FDM·SLA·SLS 등은 상표에서 유래한 통칭입니다. "
                 "괄호 안이 KS D ISO/ASTM 52910 3.1절의 표준 용어입니다.")
        ptype = ProcessType[process]
        P = PROCESS_PARAMS[ptype]
        T = PROCESS_TERMS[ptype]
        st.caption(f"표준 용어: {T['std_ko']} ({T['std_en']}) — 52910 {T['clause']}")
        st.caption(f"임계각 {P['critical_angle']:.0f}° · 권장 벽두께 {P['thr_wall']}mm · "
                   f"프로필 하한 {P['hard_wall']}mm · 서포트 밀도 {P['support_density']*100:.0f}%")
        st.caption(f"수치 출처: {P['source']}")
        with st.expander("현재 프로필 수치의 근거"):
            st.dataframe(provenance_report(process), hide_index=True)

        layer_settings = None
        if process == 'FDM':
            with st.expander('FDM 단면 검토 설정'):
                layer_settings = dict(
                    layer_height=st.number_input('단면 층 높이 (mm)', min_value=0.01, max_value=5.0,
                                                 value=float(P['layer_height']), step=0.01, format='%.2f'),
                    line_width=st.number_input('단면 선폭 (mm)', min_value=0.01, max_value=10.0,
                                               value=float(P['line_width']), step=0.05, format='%.2f'),
                    critical_angle=st.number_input('단면 경사 기준 (°)', min_value=1.0, max_value=90.0,
                                                   value=float(P['critical_angle']), step=1.0))
                st.caption('실제 슬라이서의 선폭·층 높이에 맞추세요. 이 설정은 층 단면 검사와 '
                           '그 방향 비교에 적용됩니다. 기존 3D 점수·Cura 보정식은 위 프로필을 사용합니다.')

        bdir_label = st.selectbox("빌드 방향", list(AXIS_ORIENTATIONS), index=0)
        build_direction = AXIS_ORIENTATIONS[bdir_label]

        c1, c2, c3 = st.columns(3)
        px = c1.number_input("X", value=250, min_value=10)
        py = c2.number_input("Y", value=250, min_value=10)
        pz = c3.number_input("Z", value=250, min_value=10)
        printer = (float(px), float(py), float(pz))

        mf_on = st.checkbox("정밀 최소특징 검사 (복셀, 느림)", value=False,
                            help="끄면 해당 규칙은 N/A 이고 가중치가 재분배됩니다.")
        tg_on = st.checkbox("두께 변화 검사 (오탐 있음)", value=False,
                            help="단순 솔리드에서 오탐이 납니다. 40x30x20 직육면체는 "
                                 "두께 급변이 없으나 측정 방향에 따라 비 2.0 이 나옵니다. "
                                 "급변 유무 확인용으로만 켜세요.")

        st.markdown("---")
        run = st.button("🔍 제조성 평가", type="primary", use_container_width=True,
                        disabled=(mesh is None))

    st.title("적층제조 제조성 검토 (DfAM)")
    st.caption("KS D ISO/ASTM 52910 (ISO/ASTM 52910:2018 IDT) 기반 프레임워크 · "
               "공정별 수치는 표준 범위 밖이므로 별도 출처를 명시합니다")

    if mesh is None:
        st.info("사이드바에서 모델을 선택하거나 STL을 업로드하세요.")
        render_source_viewer()
        return

    for w in warns:
        st.warning(f"메시 진단: {w}")

    ext = mesh.extents
    c = st.columns(5)
    volume_cell = c[0].empty()
    volume_cell.metric("부피 (mm³)", '평가 후 제공')
    c[1].metric("삼각형 면적 합 (mm², 참고)", f"{mesh.area:,.1f}")
    c[2].metric("치수 (mm)", f"{ext[0]:.1f}×{ext[1]:.1f}×{ext[2]:.1f}")
    c[3].metric("면 / 정점", f"{len(mesh.faces):,} / {len(mesh.vertices):,}")
    c[4].metric("면 연결 조건", "충족" if mesh.is_watertight else "검토 필요")

    mesh_id = hashlib.sha256(mesh.vertices.tobytes() + mesh.faces.tobytes()).hexdigest()
    if run:
        for key in ('result', 'ctx', 'orient', 'sens', 'assessed_mesh'):
            st.session_state[key] = None
        with st.spinner("평가 중..."):
            engine = AMRuleEngine()
            try:
                res = engine.evaluate(mesh, process, build_direction, printer,
                                      min_feature_enabled=mf_on,
                                      thickness_gradient_enabled=tg_on,
                                      layer_settings=layer_settings)
            except Exception as exc:
                st.error(f"평가를 완료하지 못했습니다: {exc}")
                return
            st.session_state.assessed_mesh = mesh.copy()
            st.session_state.result = res
            # 결과와 함께 '그때의 설정'을 저장한다 (표시 불일치 방지)
            st.session_state.ctx = dict(model=model_name, process=process,
                                        bdir_label=bdir_label, bdir=build_direction,
                                        printer=printer, mf=mf_on, tg=tg_on, unit=unit, mesh_id=mesh_id,
                                        layer_settings=layer_settings,
                                        preprocessing_mode=preprocessing.get('mode'),
                                        source_file_sha256=source_file_sha256,
                                        runtime=runtime_record())
            st.session_state.orient = None
            st.session_state.sens = None

    res, ctx = st.session_state.result, st.session_state.ctx
    if res is None:
        st.info("좌측에서 평가를 실행하세요.")
        render_source_viewer()
        return

    if ((ctx or {}).get('runtime',{}).get('app_version') != APP_VERSION
            or getattr(res,'engine_version',None) != APP_VERSION):
        st.warning('프로그램 버전이 변경되었습니다. 현재 버전의 결과를 보려면 [제조성 평가]를 다시 실행하세요.')
        return

    stale = (ctx['model'] != model_name or ctx['process'] != process
             or ctx['bdir_label'] != bdir_label or ctx['printer'] != printer
             or ctx['mf'] != mf_on or ctx.get('tg') != tg_on
             or ctx.get('layer_settings') != layer_settings
             or ctx.get('unit') != unit or ctx.get('mesh_id') != mesh_id
             or ctx.get('preprocessing_mode') != preprocessing.get('mode')
             or ctx.get('source_file_sha256') != source_file_sha256)
    if stale:
        st.warning("사이드바 설정이 바뀌었습니다. 아래 결과는 **이전 설정** 기준입니다 — "
                   "다시 평가하려면 [제조성 평가]를 누르세요.")
        return
    mesh = st.session_state.assessed_mesh
    if res.mesh_diagnostics.get('solid_check_passed'):
        volume_cell.metric('부피 (mm³)', f'{mesh.volume:,.1f}')
    else:
        volume_cell.metric('부피 (mm³)', '검토 필요')

    st.markdown("---")
    st.subheader(f"결과 — {ctx['model']} / {process_label(ctx['process'], short=True)} "
                 f"/ 빌드 방향 {ctx['bdir_label']}")

    render_layer_review(mesh, res)

    # 하드 게이트
    st.markdown("**3D 형상 규칙 · 입력 유효성 및 프로필 제약 검토**")
    gc = st.columns(len(res.gates))
    for col, g in zip(gc, res.gates):
        col.markdown(f"{'✅' if g.passed else ('❔' if g.status == 'unknown' else '⛔')} **{g.name}**")
        col.caption(g.detail)
        if g.clause:
            col.caption(f"근거: KS D ISO/ASTM 52910 {g.clause}")

    if not res.feasible:
        (st.warning if res.analysis_scope == 'partial' or res.evaluation_status == 'indeterminate' else st.error)(res.summary)
        for s in res.suggestions:
            st.info(s)
        st.caption("프로필 미충족·입력 오류·판정 보류 상태에서는 종합 점수를 산출하지 않습니다. "
                   "표시된 판정 상태와 해당 근거를 확인하세요.")

    render_mesh_diagnostics(res.mesh_diagnostics)
    if res.partial_metrics:
        st.subheader('계산 가능한 항목 — 외곽 치수')
        fit = res.partial_metrics['build_volume_fit']
        st.write({'검사한 치수(mm)': fit['part_size'], '장비 크기 조건': '충족' if fit['fits'] else '미충족',
                  'XY 배치 회전(도)': fit['placement_rotation_deg']})
        st.caption('3D 솔리드 부피·벽두께·서포트량·공동·종합 점수는 메시 검토 후 계산합니다. '
                   '위 FDM 단면 검토는 별도의 형상 해석 결과입니다. '
                   '장비 크기는 0/90° XY 배치만 검사하며 서포트·래프트·여유 공간을 제외합니다.')

    for warning in res.warnings:
        st.warning(warning)
    if res.feasible:
        # 소프트 점수
        st.markdown("**2단계 · 형상 규칙 선별 점수**")
        a, b = st.columns([1, 2])
        with a:
            st.markdown(f"## {res.total_score}점 · {res.grade}등급")
            na = [r for r in res.rule_results if r.score is None]
            st.caption(f"평가 규칙 {len(res.rule_results)-len(na)}개"
                       + (f" · N/A {len(na)}개 (가중치 재분배됨)" if na else ""))
        with b:
            st.plotly_chart(render_gauge(res.total_score, res.grade), use_container_width=True)

    layers = {'메시 연결 검토 위치': res.mesh_diagnostics.get('problem_face_indices', []), '전체 형상': []}
    for rule in res.rule_results:
        if rule.rule_name == 'overhang_area':
            layers['지지구조 필요 면'] = rule.problem_face_indices
        if rule.rule_name == 'wall_thickness':
            layers['권장 벽두께 미만 표본 면'] = rule.problem_face_indices
    default_layer = list(layers).index('지지구조 필요 면') if res.feasible and '지지구조 필요 면' in layers else 0
    layer = st.selectbox('3D 표시 항목', list(layers), index=default_layer)
    st.plotly_chart(render_3d(mesh, ctx['bdir'], layers[layer], res.in_plane_rotation_deg,
                              highlight_label=layer), use_container_width=True)
    if not res.feasible and res.rule_results:
        st.info('아래는 계산 가능한 규칙별 결과입니다. 종합 점수와 방향 추천은 보류 상태를 유지합니다.')

    radar = render_radar(res.rule_results)
    if radar:
        st.plotly_chart(radar, use_container_width=True)

    st.subheader("규칙별 상세")
    icon = {'pass': '✅', 'warn': '⚠️', 'fail': '❌', 'na': '➖'}
    for r in res.rule_results:
        c1, c2, c3 = st.columns([3, 3, 1])
        c1.markdown(f"{icon[r.status]} **{r.label}**")
        c1.caption(f"가중치 {r.weight*100:.1f}%" if r.score is not None else "가중치 재분배됨")
        if r.clause:
            c1.caption(f"근거 조항: {r.clause}")
        c2.markdown(f"`{r.value}` {r.unit}" + (f" / 기준 `{r.threshold}`" if r.threshold else ""))
        c2.caption(r.detail)
        if r.score is None:
            c3.markdown("### N/A")
        else:
            c3.markdown(f"### {r.score:.0f}")
            c3.progress(min(r.score, 100) / 100)

    st.subheader("개선 제안")
    for s in res.suggestions:
        (st.success if "충족" in s else st.warning)(s)

    # 방향 비교 (한 번만 계산해서 캐시)
    st.markdown("---")
    st.subheader("빌드 방향 비교 (6방향)")
    if st.button("6방향 비교 실행"):
        st.session_state.orient = None
        with st.spinner("6방향 평가 중..."):
            try:
                st.session_state.orient = evaluate_orientations(
                    mesh, ctx['process'], ctx['printer'], min_feature_enabled=ctx['mf'],
                    thickness_gradient_enabled=ctx['tg'], layer_settings=ctx['layer_settings'])
            except Exception as exc:
                st.error(f'방향 비교를 완료하지 못했습니다: {exc}')
    if st.session_state.orient:
        rows = results_to_rows(st.session_state.orient)
        st.dataframe([{k: str(v) for k, v in row.items()} for row in rows], use_container_width=True, hide_index=True)
        best = pick_best(st.session_state.orient)
        if best['best_orientation']:
            st.success(f"🏆 검사한 6방향 중 최고 점수 방향: **{best['best_orientation']}** — "
                       f"{best['best_score']}점 ({best['best_grade']}등급) · "
                       f"프로필 통과 방향 {best['feasible_count']}/6")
            if best.get('note'):
                st.info(best['note'])
        else:
            st.info(best['note'])
        layer_rows=[]
        for direction,r in st.session_state.orient.items():
            lr=r.layer_review
            if lr.get('status') in ('complete','partial','unavailable'):
                row={'방향':direction,'단면 검토':lr['status'],
                     '확정 층':f"{lr.get('complete_layers',0)}/{lr.get('expected_layers',0)}"}
                for check in lr.get('checks',[])[1:]:
                    full=check.get('fully_measured_layers',0)==lr['expected_layers']
                    row[check['name']+' 우선 합(mm²)']=round(check['sum_mm2'],4) if full and check.get('sum_mm2') is not None else '미확정'
                    row[check['name']+' 세부 합(mm²)']=round(check['detail_sum_mm2'],6) if full and check.get('detail_sum_mm2') is not None else '미확정'
                layer_rows.append(row)
        if layer_rows:
            st.write('**FDM 단면 기준 방향 비교**')
            st.dataframe(layer_rows,use_container_width=True,hide_index=True)
            st.caption('같은 선폭·층 높이에서 계산한 우선 영역과 작은 세부의 합을 각각 비교합니다. 실제 서포트 재료량이나 자동 최적 방향 판정은 아닙니다.')
        pf = pareto_front(st.session_state.orient)
        if not pf.get('comparable', True) or len(pf['front']) < 2:
            st.info(pf['note'])
        elif pf.get('weight_free'):
            st.info(f"**가중치 검증** — 가중합 1위({pf['best_by_weights']})가 나머지 방향을 "
                    f"모든 평가 규칙에서 지배하거나 동점입니다. 지배 관계가 성립하면 어떤 양수 가중치를 써도 "
                    f"순위가 바뀌지 않으므로, 이 선택에는 가중치가 필요하지 않습니다.")
        else:
            st.warning(f"**가중치 검증** — 파레토 최적 방향이 {len(pf['front'])}개"
                       f"({', '.join(pf['front'])})이며 서로 지배하지 않습니다. "
                       f"트레이드오프가 있으므로 하나를 고르려면 선호 정보(가중치)가 필요하고, "
                       f"이 경우 가중치의 근거가 결과를 좌우합니다.")
        st.caption("v1은 X/Y/Z 3방향만 비교했습니다. +Z와 -Z는 부품을 뒤집는 것이라 "
                   "오버행 분포가 완전히 다릅니다.")

    # 민감도 분석
    st.markdown("---")
    st.subheader("가중치 민감도 분석")
    st.caption("가중치는 현재 임의 설정입니다. ±50% 무작위 교란 200회로 등급이 얼마나 바뀌는지 봅니다.")
    if st.button("민감도 분석 실행"):
        st.session_state.sens = None
        with st.spinner("형상 분석 후 가중치 200회 비교 중..."):
            try:
                st.session_state.sens = sensitivity_analysis(
                    mesh, ctx['process'], ctx['bdir'], ctx['printer'],
                    min_feature_enabled=ctx['mf'], thickness_gradient_enabled=ctx['tg'])
            except Exception as exc:
                st.error(f'민감도 분석을 완료하지 못했습니다: {exc}')
    if st.session_state.sens:
        s = st.session_state.sens
        if 'base_score' in s:
            m = st.columns(4)
            m[0].metric("기준 점수", f"{s['base_score']} ({s['base_grade']})")
            m[1].metric("점수 범위", f"{s['score_min']:.1f} ~ {s['score_max']:.1f}")
            m[2].metric("표준편차", f"{s['score_std']:.2f}")
            m[3].metric("등급 변동률", f"{s['grade_changed_ratio']*100:.1f}%",
                        help="가중치를 흔들었을 때 등급이 바뀐 비율")
            st.metric("등급 경계까지 거리", f"{s['boundary_distance']:.1f}점")
            if s['boundary_distance'] > 4.0 and s['grade_changed_ratio'] < 0.05:
                st.warning("변동률이 낮지만 이 부품은 등급 경계에서 멀리 떨어져 있습니다. "
                           "경계 근처 부품은 변동률이 훨씬 커지므로, 이 수치만으로 "
                           "가중치가 강건하다고 결론지을 수 없습니다.")
            else:
                st.caption("등급 경계에 가까울수록 가중치의 영향이 커집니다.")
        else:
            st.info(s.get('note', ''))

    st.download_button('평가·방향 비교 결과 JSON 다운로드',
                       json_text({'schema_version': 2, 'context': ctx, 'result': res,
                                  'orientation_comparison': st.session_state.orient,
                                  'sensitivity': st.session_state.sens,
                                  'json_null_meaning': '미측정, 적용 불가 또는 정의되지 않는 수치'}),
                       file_name='am_dfm_result.json', mime='application/json')

    render_ahp()

    render_source_viewer()

    st.markdown("---")
    st.caption(f"AM-DFM Evaluator v{APP_VERSION} · KS D ISO/ASTM 52910(2024 확인) 프레임워크 "
               "(ISO/ASTM 52910:2018 IDT) · "
               "Ref: Oh, Ko, Sprock, Bernstein & Kwon (2021), Additive Manufacturing, 37, 101702")


if __name__ == "__main__":
    main()
