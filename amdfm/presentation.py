from __future__ import annotations

import html
import json
import numpy as np
import plotly.graph_objects as go
import trimesh

from .models import json_bytes
from .visuals import wall_samples, add_wall_markers, section_svg, model_svg

STATUS = {"attention":"검토 필요", "observed":"측정됨", "not_detected":"범위 내 미검출",
          "unknown":"추가 확인", "not_applicable":"해당 없음"}


def model_figure(model, report=None, finding_id="overhang", *, transparent=False,
                 selected_sample=None, build_plate=False, height=460):
    mesh=model.mesh
    vertices=mesh.vertices.copy()
    if report:
        matrix=np.asarray(report["current_orientation"]["transform"])
        vertices=vertices@matrix[:3,:3].T+matrix[:3,3]
    # Display budget affects only the viewport, never measurement or export mesh.
    max_display=250_000
    indices=np.arange(len(mesh.faces)) if len(mesh.faces)<=max_display else np.linspace(0,len(mesh.faces)-1,max_display,dtype=int)
    finding=next((f for f in report["findings"] if f["id"]==finding_id),None) if report else None
    is_wall = report is not None and finding_id == 'wall'
    samples = wall_samples(report) if is_wall else []
    # A ranked face list is not a thickness map. Walls use measured points.
    highlighted=np.asarray(finding["face_indices"][:max_display],dtype=int) if finding and not is_wall else np.array([],dtype=int)
    indices=indices[~np.isin(indices,highlighted)]
    faces=mesh.faces[indices]
    fig=go.Figure(go.Mesh3d(x=vertices[:,0],y=vertices[:,1],z=vertices[:,2],
        i=faces[:,0],j=faces[:,1],k=faces[:,2],color="#91a4b2",opacity=.3 if transparent and (len(highlighted) or samples or finding_id=='layers') else 1,
        flatshading=False,lighting=dict(ambient=.5,diffuse=.8,specular=.2),
        name="입력 형상",hoverinfo="skip",showscale=False))
    if report:
        if len(highlighted):
            selected=mesh.faces[highlighted]
            fig.add_trace(go.Mesh3d(x=vertices[:,0],y=vertices[:,1],z=vertices[:,2],
                i=selected[:,0],j=selected[:,1],k=selected[:,2],color="#e27735",opacity=1,
                name=finding["title"],hovertemplate=html.escape(finding["title"])+"<extra></extra>"))
    extent=max(mesh.extents)
    arrow=vertices.min(axis=0)-[extent*.08,extent*.08,0]
    fig.add_trace(go.Scatter3d(x=[arrow[0]]*2,y=[arrow[1]]*2,z=[arrow[2],arrow[2]+extent*.6],mode="lines+text",
        text=["","적층 +Z"],textposition="top center",line=dict(color="#3d6e53",width=5),
        hoverinfo="skip",showlegend=False))
    fig.add_trace(go.Cone(x=[arrow[0]], y=[arrow[1]], z=[arrow[2]+extent*.6], u=[0], v=[0], w=[1],
        sizemode='absolute', sizeref=extent*.075, anchor='tip', showscale=False,
        colorscale=[[0,'#275c41'],[1,'#275c41']], hoverinfo='skip', showlegend=False))
    if build_plate:
        low, high = vertices.min(axis=0), vertices.max(axis=0)
        margin = extent*.1
        x0,y0 = low[:2]-margin
        x1,y1 = high[:2]+margin
        fig.add_trace(go.Mesh3d(x=[x0,x1,x1,x0], y=[y0,y0,y1,y1], z=[0]*4,
            i=[0,0], j=[1,2], k=[2,3], color='#c0c9d0', opacity=.45,
            name='가상 바닥 · Z=0', hovertemplate='가상 바닥 · Z=0 mm<extra></extra>', showscale=False))
        fig.add_trace(go.Scatter3d(x=[x0,x1,x1,x0,x0], y=[y0,y0,y1,y1,y0], z=[0]*5,
            mode='lines', line=dict(color='#718596',width=3), name='가상 바닥', showlegend=False,hoverinfo='skip'))
    fig.update_layout(height=height,margin=dict(l=0,r=0,t=15,b=15),showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)",uirevision=(report or {}).get("model_fingerprint",model.fingerprint),
        scene=dict(aspectmode="data",xaxis_title="X (mm)",yaxis_title="Y (mm)",zaxis_title="Z (mm)",
                   camera=dict(eye=dict(x=1.6,y=1.6,z=1.15))))
    if samples:
        add_wall_markers(fig, report, selected_sample=selected_sample)
    return fig


def orientation_table(report):
    return [{"방향":r["name"],"비지배 대안":r["pareto"],
        "모델 적층축 (X, Y, Z)":", ".join(f"{v:.6g}" for v in r["direction"]),
        "기울기 (°)":r.get("tilt_deg"),"방위각 (°)":r.get("azimuth_deg"),
        "투영면적 합 · 중복 포함 (mm²)":r["overhang_projected_area_sum_mm2"],"높이 (mm)":r["height_mm"],
        "바닥 면적 (mm²)":r["contact_triangle_area_mm2"],
        "공간":("미지정" if r["build_fit"] is None else "수용" if r["build_fit"] else "초과")}
        for r in report["orientations"]]


def html_report(report, model=None):
    """Portable illustrated decisions; full unmodified data is exported as JSON."""
    from .detail_summary import summarize_wall, summarize_layers
    from .section_summary import summarize_sections
    from .workflow import summarize_review

    esc=lambda x: html.escape(str(x))
    def value(x):
        if x is None:return "미확정"
        if isinstance(x,float):return f"{x:.5g}"
        if isinstance(x,(dict,list)):return esc(json.dumps(x,ensure_ascii=False))
        return esc(x)

    def table(rows):
        if not rows:return ""
        keys=list(rows[0])
        header="".join(f"<th scope='col'>{esc(k)}</th>" for k in keys)
        body="".join("<tr>"+"".join(f"<td>{value(row.get(k))}</td>" for k in keys)+"</tr>" for row in rows)
        return f"<div class='table-scroll'><table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>"

    def raw(label, data):
        return f"<details><summary>{esc(label)}</summary><pre>{esc(json.dumps(data,ensure_ascii=False,indent=2))}</pre></details>"

    def decision(level,title,observation,action):
        level=level if level in ('success','warning','info') else 'info'
        return (f"<div class='decision {level}'><h3>{esc(title)}</h3><p>{esc(observation)}</p>"
                f"<p><b>다음에 할 일</b> · {esc(action)}</p></div>")

    overview=summarize_review(report)
    profile=report['profile']
    details=report.get('details',{})
    findings={f['id']:f for f in report['findings']}
    cards=[]
    for item in overview['checklist']:
        key=item['id']
        card=(f"<section id='check-{esc(key)}'><h2>{esc(item['label'])}</h2>"
              +decision(item['level'],item['state'],item['observation'],item['next_action']))
        if key=='wall':
            wall=summarize_wall(details.get('wall'),profile.get('minimum_wall_mm'))
            if wall['minimum_mm'] is not None:
                criterion=value(wall['minimum_wall_mm'])+' mm' if wall['criterion_available'] else '미입력'
                card+=(f"<p><b>가장 짧게 측정한 거리</b> {value(wall['minimum_mm'])} mm · "
                       f"<b>입력한 최소 벽 기준</b> {criterion}</p>")
                card+=f"<p><b>기준 근거</b> · {esc(profile.get('threshold_basis','미입력'))}</p>"
            card+=f"<p class='scope'>{esc(wall['scope'])}</p>"
        elif key=='layers':
            layers=summarize_layers(details.get('layers'))
            if details.get('layers'):
                card+=table([{'검토 항목':c['label'],'후보가 관측된 층 수':c['candidate_layers'],
                              '전체 비교 범위를 계산한 층 수':c['fully_measured_layers']}
                             for c in layers['checks']])
                if layers['affected_rows']:
                    card+="<h3>먼저 확인할 층</h3>"+table([
                        {'층':r['display_layer'],'높이 (mm)':r.get('z_mm'),
                         '확인할 내용':' · '.join(r['types']),'다음 행동':r['action']}
                        for r in layers['affected_rows']])
                if layers['reason']:card+=f"<p>{esc(layers['reason'])}</p>"
            card+=f"<p class='scope'>{esc(layers['scope'])}</p>"
        elif key=='sections' and details.get('sections'):
            sections=details['sections']
            section=summarize_sections(sections,profile['process'],report['geometry'].get('mesh_signed_volume_mm3'))
            card+=f"<p>{esc(section['completion_text'])}</p><p>{esc(section['interpretation'])}</p>"
            if section['reason']:card+=f"<p>{esc(section['reason'])}</p>"
            if section['selection_note']:card+=f"<p><b>계산 방법 안내</b> · {esc(section['selection_note'])}</p>"
            if sections.get('rows'):
                index=section['default_row_index'] or 0
                card+=section_svg(sections['rows'],index)
                card+="<p class='scope'>기록된 단면 윤곽입니다. 비교 가능한 이전 단면이 있으면 파란 점선으로 함께 표시하고, 현재 단면은 주황 실선으로 표시합니다. 위험 등급이 아니며, 미확정 단면이나 표본 사이 형상을 추정해 채우지 않습니다.</p>"
            partial=section['partial_volume']
            if partial['available']:
                card+=(f"<p><b>확인한 구간의 부피 합</b> {value(partial['known_mm3'])} mm³ · "
                       f"<b>빠진 높이 구간의 부피 기여 상한</b> {value(partial['omitted_envelope_mm3'])} mm³</p>"
                       f"<p>{esc(partial['explanation'])}</p>")
            volume=section['volume']
            volume_html=f"<p>{esc(volume['explanation'])}</p>"
            if volume['available']:
                display=volume['display']
                if display.startswith('<'):display=display[1:]+' 미만'
                volume_html=(f"<p>두 계산 방법의 부피 차이: <b>{esc(display)}</b></p>"
                    f"<p>단면 체적 {value(volume['section_volume_mm3'])} mm³ · 메시 체적 {value(volume['mesh_volume_mm3'])} mm³</p>"
                    f"<p>원본 상대차: {esc(format(volume['relative_difference_percent'],'.16g'))}%</p>"+volume_html)
            card+=f"<details><summary>계산 확인 · 부피 검산</summary>{volume_html}</details>"
        if key in findings:
            f=findings[key]
            if f['face_indices']:
                card+=(f"<p><b>위치 확인</b> · 프로그램의 설계 조치에서 「{esc(f['title'])}」 항목을 선택하면 "
                       "해당 표본 또는 검토 위치를 형상에서 확인할 수 있습니다.</p>")
            refs=' · '.join(f"<a href='#source-{esc(k)}'>{esc(k)}</a>" for k in f['evidence'])
            card+=("<details><summary>측정값·방법·위치 번호와 적용 범위</summary>"
                   f"<p><b>원래 측정 설명</b> · {esc(f['reason'])}</p><p>방법: {esc(f['method'])}</p>"
                   f"<p>CAD 면 번호(최대 50개 표시): {value(f['cad_face_ids'][:50])}</p>"
                   f"<p>{' '.join(esc(x) for x in f['limitations'])}</p><p>근거: {refs}</p>"
                   +table([{'측정 키':k,'값':v} for k,v in f['measurements'].items() if not isinstance(v,(dict,list))])+'</details>')
        cards.append(card+'</section>')

    sources=[]
    for key,s in report["sources"].items():
        title=f"<a href='{esc(s['url'])}'>{esc(s['title'])}</a>" if s["url"] else esc(s["title"])
        sources.append(f"<li id='source-{esc(key)}'><b>{esc(key)}</b> {title}. {esc(s['locator'])}. {esc(s['access'])}. {esc(s['use'])}</li>")
    navigation=''.join(f"<li><a href='#check-{esc(i['id'])}'>{esc(i['label'])}</a> · {esc(i['state'])}</li>"
                       for i in overview['checklist'])
    conditions=table([{'조건':'장비','설정':profile.get('machine')},
                      {'조건':'재료','설정':profile.get('material')},
                      {'조건':'슬라이서','설정':profile.get('slicer')},
                      {'조건':'빌드 공간','설정':'크기 제한 미적용' if profile.get('build_volume_mm') is None else profile['build_volume_mm']},
                      {'조건':'검토 기준의 근거','설정':profile.get('threshold_basis')}])
    goals=['높이']
    if report['current_orientation'].get('overhang_projected_area_sum_mm2') is not None:
        goals.append('하향면 후보')
    if profile['process']=='MEX' and report['current_orientation'].get('contact_triangle_area_mm2') is not None:
        goals.append('바닥 접촉면')
    goals_text='·'.join(goals)
    provenance=dict(timestamp_utc=report['timestamp_utc'],source_sha256=report['model']['source_sha256'],
                    model_fingerprint=report['model_fingerprint'],profile=profile,
                    placement_transform=report['current_orientation']['transform'],**report['provenance'])
    content=f"""<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AM-DFM 설계 검토 — {esc(report['model']['filename'])}</title>
<style>body{{font-family:'Malgun Gothic',system-ui,sans-serif;max-width:1000px;margin:40px auto;padding:0 24px;color:#222;line-height:1.65}}h1{{font-size:28px}}h2{{font-size:21px;margin-top:34px}}h3{{font-size:17px;margin:0}}.scope,small{{font-size:13px;color:#555}}.decision{{padding:18px 20px;border-left:5px solid #315f78;background:#f3f7fa;border-radius:4px}}.decision.warning{{border-color:#a76818;background:#fff6e8}}.decision.success{{border-color:#39715a;background:#eff8f2}}table{{border-collapse:collapse;width:100%;font-size:13px;margin:12px 0}}td,th{{border:1px solid #ddd;padding:8px;text-align:left;overflow-wrap:anywhere}}th{{background:#f4f4f4}}.table-scroll{{overflow-x:auto}}pre{{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}}a{{color:#245d87}}details{{margin:14px 0;padding:12px;border:1px solid #ddd;border-radius:5px}}summary{{cursor:pointer;font-weight:bold}}svg{{display:block;width:100%;max-width:640px;height:auto;margin:16px auto}}section{{break-inside:avoid}}@media print{{body{{margin:0;max-width:none}}.decision{{break-inside:avoid}}}}</style>
<h1>적층제조 설계 검토</h1><p>{esc(report['model']['filename'])} · {esc(report['process_label'])} · AM-DFM {esc(report['app_version'])}</p>
{decision(overview['level'],overview['title'],overview['observation'],overview['next_action'])}
<p class='scope'>형상과 입력 조건을 이용한 설계 검토입니다. 검사별 판단은 해당 범위에 한정되며 실제 출력 성공·강도·표준 적합을 보증하지 않습니다.</p>
{model_svg(model, report) if model is not None else ''}
<p>전체 표본·층별 원자료는 별도 <code>AM-DFM_review.json</code>에 보존됩니다. 재현할 때는 프로그램에서 「전체 결과 JSON」도 함께 내려받아 이 보고서와 보관하세요. 이 HTML은 그림과 판단을 읽는 용도입니다.</p>
<h2>항목별 판단과 다음 행동</h2><ul>{navigation}</ul>
<details><summary>이번 검토의 형상·공정 조건</summary><p>{esc(report['model']['unit_note'])}</p>{conditions}
<p>현재 높이: {value(report['current_orientation']['height_mm'])} mm · 모델 적층축: {value(report['current_orientation']['direction'])}. 이 방향이 프린터 +Z를 향합니다.</p></details>
{''.join(cards)}
<h2>방향을 바꿀 때</h2><p>프로그램의 방향 비교에서 {esc(goals_text)} 중 원하는 목적을 고르고 현재 방향과의 손익을 확인하세요. 적용 후에는 같은 방향으로 정밀 검토를 다시 실행하세요.</p>
<details><summary>방향별 전체 측정값</summary><p>비교한 후보 안에서의 기하 지표입니다. 비지배 대안은 지표 간 절충안이며 전체 방향의 최적해가 아닙니다. 투영면적 합은 실제 서포트 부피가 아니며 높이는 인쇄 시간이 아닙니다.</p>{table(orientation_table(report))}</details>
<h2>실제 제작 전에 확인할 내용</h2><p>{esc(' · '.join(report['unassessed']))}</p>
<h2>검토 근거와 재현 기록</h2><details><summary>검토 규칙의 이유와 출처</summary><ol>{''.join(sources)}</ol></details>
{raw('입력·설정·코드 식별자와 실행 환경',provenance)}
</html>"""
    return content.encode("utf-8")


def placed_stl(model,report):
    if model.fingerprint != report["model_fingerprint"]:
        raise ValueError("평가한 모델과 내보낼 모델이 다릅니다.")
    matrix=np.asarray(report["current_orientation"]["transform"])
    # Do not let apply_transform's near-identity shortcut drop a small real tilt.
    mesh=trimesh.Trimesh(vertices=model.mesh.vertices@matrix[:3,:3].T+matrix[:3,3],
        faces=model.mesh.faces.copy(),process=False)
    return mesh.export(file_type="stl")
