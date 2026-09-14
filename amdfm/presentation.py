from __future__ import annotations

import html
import json
import numpy as np
import plotly.graph_objects as go
import trimesh

from .models import json_bytes

STATUS = {"attention":"검토 필요", "observed":"측정됨", "not_detected":"범위 내 미검출",
          "unknown":"추가 확인", "not_applicable":"해당 없음"}


def model_figure(model, report=None, finding_id="overhang", *, transparent=False):
    mesh=model.mesh
    vertices=mesh.vertices.copy()
    if report:
        matrix=np.asarray(report["current_orientation"]["transform"])
        vertices=vertices@matrix[:3,:3].T+matrix[:3,3]
    # Display budget affects only the viewport, never measurement or export mesh.
    max_display=250_000
    indices=np.arange(len(mesh.faces)) if len(mesh.faces)<=max_display else np.linspace(0,len(mesh.faces)-1,max_display,dtype=int)
    finding=next((f for f in report["findings"] if f["id"]==finding_id),None) if report else None
    highlighted=np.asarray(finding["face_indices"][:max_display],dtype=int) if finding else np.array([],dtype=int)
    indices=indices[~np.isin(indices,highlighted)]
    faces=mesh.faces[indices]
    fig=go.Figure(go.Mesh3d(x=vertices[:,0],y=vertices[:,1],z=vertices[:,2],
        i=faces[:,0],j=faces[:,1],k=faces[:,2],color="#6b8ba4",opacity=.18 if transparent else 1,
        flatshading=False,lighting=dict(ambient=.5,diffuse=.8,specular=.2),
        name="입력 형상",hoverinfo="skip",showscale=False))
    if report:
        if finding and finding["face_indices"]:
            selected=mesh.faces[highlighted]
            fig.add_trace(go.Mesh3d(x=vertices[:,0],y=vertices[:,1],z=vertices[:,2],
                i=selected[:,0],j=selected[:,1],k=selected[:,2],color="#e27735",opacity=1,
                name=finding["title"],hovertemplate=html.escape(finding["title"])+"<extra></extra>"))
    extent=max(mesh.extents)
    arrow=vertices.min(axis=0)-[extent*.08,extent*.08,0]
    fig.add_trace(go.Scatter3d(x=[arrow[0]]*2,y=[arrow[1]]*2,z=[arrow[2],arrow[2]+extent*.6],mode="lines+text",
        text=["","적층 +Z"],textposition="top center",line=dict(color="#3d6e53",width=5),
        hoverinfo="skip",showlegend=False))
    fig.update_layout(height=540,margin=dict(l=0,r=0,t=0,b=0),showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)",uirevision=(report or {}).get("model_fingerprint",model.fingerprint),
        scene=dict(aspectmode="data",xaxis_title="X (mm)",yaxis_title="Y (mm)",zaxis_title="Z (mm)",
                   camera=dict(eye=dict(x=1.6,y=1.6,z=1.15))))
    return fig


def orientation_table(report):
    return [{"방향":r["name"],"비지배 대안":r["pareto"],
        "모델 적층축 (X, Y, Z)":", ".join(f"{v:.6g}" for v in r["direction"]),
        "기울기 (°)":r.get("tilt_deg"),"방위각 (°)":r.get("azimuth_deg"),
        "투영면적 합 (mm²)":r["overhang_projected_area_sum_mm2"],"높이 (mm)":r["height_mm"],
        "바닥 면적 (mm²)":r["contact_triangle_area_mm2"],
        "공간":("미지정" if r["build_fit"] is None else "수용" if r["build_fit"] else "초과")}
        for r in report["orientations"]]


def html_report(report):
    """Portable, script-free report. Every user-provided string is HTML escaped."""
    esc=lambda x: html.escape(str(x))
    def value(x):
        if x is None:return "미확정"
        if isinstance(x,float):return f"{x:.5g}"
        if isinstance(x,(dict,list)):return esc(json.dumps(x,ensure_ascii=False))
        return esc(x)
    rows="".join(f"<tr><th>{esc(k)}</th><td>{value(v)}</td></tr>" for k,v in report["profile"].items())
    cards=[]
    for f in report["findings"]:
        visible={k:v for k,v in f["measurements"].items() if k not in ("samples","cylindrical_faces","problem_face_indices","below_limit_face_indices","thinnest_face_indices")}
        metrics="".join(f"<tr><th>{esc(k)}</th><td>{value(v)}</td></tr>" for k,v in visible.items())
        refs=" · ".join(f"<a href='#source-{esc(k)}'>{esc(k)}</a>" for k in f["evidence"])
        cards.append(f"<section><h2>{esc(f['title'])} <small>{esc(STATUS[f['status']])}</small></h2>"
            f"<p>{esc(f['reason'])}</p><p><b>설계 조치</b> {esc(f['action'])}</p><table>{metrics}</table>"
            f"<p>방법: {esc(f['method'])}</p><p>CAD 면 번호: {esc(f['cad_face_ids'])}</p>"
            f"<p>{' '.join(esc(x) for x in f['limitations'])}</p><p>근거: {refs}</p></section>")
    sources=[]
    for key,s in report["sources"].items():
        title=f"<a href='{esc(s['url'])}'>{esc(s['title'])}</a>" if s["url"] else esc(s["title"])
        sources.append(f"<li id='source-{esc(key)}'><b>{esc(key)}</b> {title}. {esc(s['locator'])}. {esc(s['access'])}. {esc(s['use'])}</li>")
    orientations=orientation_table(report)
    orientation_html=""
    if orientations:
        keys=list(orientations[0])
        orientation_html="<table><tr>"+"".join(f"<th>{esc(k)}</th>" for k in keys)+"</tr>"
        orientation_html+="".join("<tr>"+"".join(f"<td>{value(row[k])}</td>" for k in keys)+"</tr>" for row in orientations)+"</table>"
    details=report.get("details",{})
    layers=details.get("layers")
    layer_html=""
    if layers:
        layer_html=f"<h2>층간 상세 검토</h2><p>상태: {esc(layers['status'])}; 확정 층: {esc(layers.get('complete_layers'))}/{esc(layers.get('expected_layers'))}</p>"
        layer_html+="<p>"+esc(layers.get("reason",""))+"</p>"
        layer_html+="<pre>"+esc(json.dumps(layers.get("checks",[]),ensure_ascii=False,indent=2))+"</pre>"
    content=f"""<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AM-DFM 설계 검토 — {esc(report['model']['filename'])}</title>
<style>body{{font-family:'Malgun Gothic',system-ui,sans-serif;max-width:1000px;margin:40px auto;padding:0 24px;color:#222;line-height:1.65}}h1{{font-size:28px}}h2{{font-size:20px;margin-top:34px}}small{{font-size:13px;color:#666}}table{{border-collapse:collapse;width:100%;font-size:13px;margin:12px 0}}td,th{{border:1px solid #ddd;padding:8px;text-align:left;overflow-wrap:anywhere}}th{{background:#f4f4f4}}pre{{white-space:pre-wrap;overflow-wrap:anywhere}}a{{color:#245d87}}section{{break-inside:avoid}}@media print{{body{{margin:0;max-width:none}}}}</style>
<h1>적층제조 설계 검토</h1><p>{esc(report['model']['filename'])} · {esc(report['process_label'])} · AM-DFM {esc(report['app_version'])}</p>
<p>{esc(report['summary']['decision'])}</p><p>단위 상태: {esc(report['model']['unit_status'])}. {esc(report['model']['unit_note'])}</p>
<p>원본 SHA-256: {esc(report['model']['source_sha256'])}</p><p>모델·선택 솔리드 식별자: {esc(report['model_fingerprint'])}</p>
<p>코드 SHA-256: {esc(report['provenance']['code_sha256'])} · {esc(report['timestamp_utc'])}</p>
<h2>조건</h2><table>{rows}</table>
<h2>현재 배치</h2><p>모델 좌표의 적층축: {value(report['current_orientation']['direction'])}. 이 방향이 프린터 +Z를 향합니다.</p>
<p>배치 변환 행렬 (모델 mm → 빌드 mm): {value(report['current_orientation']['transform'])}</p>{''.join(cards)}
<h2>방향별 손익</h2><p>명시된 유한 후보 집합의 비교입니다. 비지배 대안은 선택한 기하 지표 중 하나를 개선하면 다른 지표가 악화되는 후보이며 제조 성공을 뜻하지 않습니다. 투영면적 합은 서포트 부피가 아닙니다.</p>{orientation_html}{layer_html}
<h2>별도 확인할 제조 조건</h2><p>{esc(' · '.join(report['unassessed']))}</p>
<h2>근거</h2><ol>{''.join(sources)}</ol><h2>실행 환경</h2><pre>{esc(json.dumps(report['provenance'],ensure_ascii=False,indent=2))}</pre>
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
