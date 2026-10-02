"""Optional, isolated CAD previews for verified pocket corner edits."""
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile
from amdfm.processes import run_bounded


def eligible_corner_edit(report):
    selected = (report.get('plan_recommendation') or {}).get('selected') or {}
    changes = selected.get('changes') or []
    geometry = [r for r in changes if r['field'] not in ('tool_diameter_mm', 'flute_length_mm', 'reach_mm')]
    from .multi_cad_edit import MAX_POCKETS
    if not 1 <= len(geometry) <= MAX_POCKETS or any(not r['field'].startswith('pocket.') or not r['field'].endswith('.corner_radius') for r in geometry):
        return None
    pockets = (report.get('external_feature_recognition') or {}).get('verified_pockets') or []
    requests, seen = [], set()
    for edit in geometry:
        radius = edit.get('after')
        if edit.get('before') != 0. or not edit.get('cad_face_id') or edit['cad_face_id'] in seen or type(radius) not in (int, float) or not math.isfinite(radius) or radius <= 0:
            return None
        pocket = next((p for p in pockets if p['floor_face_id'] == edit['cad_face_id']), None)
        if pocket is None:
            return None
        seen.add(edit['cad_face_id'])
        requests.append(dict(pocket=dict(pocket, direction=report['direction']), radius=radius))
    return requests[0] if len(requests) == 1 else dict(pockets=requests)


def create_preview(data, request, timeout=25.):
    if not data or len(data) > 80*1024*1024:
        raise ValueError('STEP input exceeds preview byte budget')
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(prefix='dfm-edit-') as tmp:
        folder = Path(tmp)
        (folder/'before.step').write_bytes(data)
        (folder/'request.json').write_text(json.dumps(request), encoding='utf8')
        try:
            result = run_bounded([sys.executable, '-m', 'dfm.cad_edit_worker', str(folder)], cwd=root, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            raise ValueError('CAD 수정 계산이 시간 한도를 초과했습니다.') from error
        path = folder/'result.json'
        if not path.exists():
            raise ValueError('CAD 수정 작업을 완료하지 못했습니다.')
        info = json.loads(path.read_text(encoding='utf8'))
        if result.returncode or info.get('error'):
            raise ValueError(info.get('error', 'CAD 수정 실패'))
        modified = (folder/'after.step').read_bytes()
        if hashlib.sha256(modified).hexdigest() != info['after_sha256']:
            raise ValueError('Modified STEP checksum mismatch')
        return modified, info


def render_preview(report, model, data, filename, revision):
    import streamlit as st
    request = eligible_corner_edit(report)
    if request is None or model.metadata.get('selected_body') is not None or model.metadata.get('source_format') not in ('step', 'stp'):
        return
    identity = hashlib.sha256((model.fingerprint+json.dumps(request, sort_keys=True)+revision).encode()).hexdigest()
    if st.session_state.get('cnc_edit_preview_identity') != identity:
        st.session_state.pop('cnc_edit_preview_result', None)
        st.session_state['cnc_edit_preview_identity'] = identity
    launch = st.empty()
    edits = request.get('pockets', [request])
    help_text = (f"날카로운 안쪽 코너를 반경 {edits[0]['radius']:g} mm로 둥글게 만든 STEP을 생성합니다."
                 if len(edits) == 1 else f"포켓 {len(edits)}개의 안쪽 코너를 각각 추천한 반경으로 수정합니다.")
    if not st.session_state.get('cnc_edit_preview_result') and launch.button(
            '추천 수정 적용·재검토', key='cnc_create_edit_preview',
            help=help_text):
        with st.spinner('추천 반경으로 CAD를 수정하고 검산하는 중…'):
            try:
                modified, audit = cached_preview(data, request, revision)
                from .edit_reinspection import compare_plan
                audit['dimensional_reinspection'] = compare_plan(report, audit)
                try:
                    from .edit_learning import descriptor, features, predict, load_model
                    recognition = report.get('external_feature_recognition', {})
                    candidates = recognition.get('candidates', [])+recognition.get('geometry_candidates', [])
                    measured = [m for c in candidates for m in c.get('measured_faces', [])]
                    inputs = [features(descriptor(r['pocket'], measured), r['radius']) for r in edits]
                    learner = load_model(); prediction = predict(inputs, learner)
                    audit['learned_edit_assessment'] = dict(model_sha256=learner['sha256'],
                        predicted_geometry_validity=prediction['validity'].tolist(),
                        predicted_material_log_fraction=prediction['material'].tolist(),
                        measured_values_used_for_acceptance=True)
                except (OSError, ValueError, KeyError, StopIteration) as error:
                    audit['learned_edit_assessment'] = dict(status='unavailable', reason=str(error))
                st.session_state['cnc_edit_preview_result'] = (modified, audit)
                launch.empty()
            except (OSError, ValueError) as error:
                st.warning('이 형상의 코너 수정은 완료하지 못했습니다. CAD에서 직접 수정하세요.')
                with st.expander('계산 결과'):
                    st.write(str(error))
    result = st.session_state.get('cnc_edit_preview_result')
    if result:
        modified, audit = result
        try:
            after = cached_modified_model(modified, revision)
        except (ValueError, OSError) as error:
            st.warning('수정 STEP의 미리보기를 읽지 못했습니다.')
            with st.expander('계산 결과'):
                st.write(str(error))
            return
        with st.container(border=True):
            checked = audit['dimensional_reinspection']
            st.success(f"수정 STEP 재검토 완료 · 치수 문제 {checked['before_conflicts']} → {checked['after_conflicts']}개")
            st.caption('코너 반경·홈 깊이 재측정 · 원래 구멍과 바깥 크기 유지')
            if checked['remaining']:
                with st.expander('남아 있는 항목'):
                    for item in checked['remaining']:
                        st.write(item)
            focus = audit
            if audit.get('edited_pocket_count', 1) > 1:
                selected = st.selectbox('살펴볼 수정 위치', range(len(audit['edits'])),
                    format_func=lambda i: f"포켓 {i+1} · 코너 반경 {audit['edits'][i]['after_corner_radius_mm']:g} mm",
                    key='cnc_edit_focus')
                focus = audit['edits'][selected]
            remeasured = next(r for r in audit['remeasurement']['pockets'] if r['floor_face_id_before'] == focus['source_floor_face_id'])
            metrics = st.columns(3)
            metrics[0].metric('안쪽 코너 반경', f"{remeasured['radius_before_mm']:g} → {remeasured['radius_after_mm']:g} mm")
            metrics[1].metric('홈 깊이', f"{remeasured['depth_after_mm']:g} mm", '유지', delta_color='off')
            metrics[2].metric('재료 부피 변화', f"+{audit['remeasurement']['material_change_percent']:.3g}%")
            left, right = st.columns(2)
            with left:
                st.markdown('**수정 전 · 날카로운 코너**')
                st.plotly_chart(edit_figure(model, focus, after=False), width='stretch', key='cnc_before_edit', config={'scrollZoom': False})
            with right:
                st.markdown(f"**수정 후 · 둥근 반경 {focus['after_corner_radius_mm']:g} mm**")
                st.plotly_chart(edit_figure(after, focus, after=True), width='stretch', key='cnc_after_edit', config={'scrollZoom': False})
            st.caption('빨간 선 · 기존 날카로운 코너 / 주황 면 · 둥글게 수정한 코너')
            if audit.get('edited_pocket_count', 1) > 1:
                st.caption(f"다운로드 STEP에는 포켓 {audit['edited_pocket_count']}개의 수정이 모두 반영됩니다.")
            st.download_button('코너를 수정한 STEP 다운로드', modified,
                file_name=Path(filename).stem+'_코너개선.step', mime='application/step', key='cnc_download_edit')
            with st.expander('수정 검산'):
                st.write(f"코너 {audit['modified_corner_edges']}곳 수정 · 바깥 크기 유지")
                st.write(f"재료 부피 변화 {audit['measured_material_addition_mm3']:.4g} mm³ · 별도 기하 공식과 대조 완료")
                st.json(dict(geometry=audit['remeasurement'], comparison=checked,
                             learning=audit.get('learned_edit_assessment')), expanded=False)


# Lazy decorated wrappers keep native/worker code usable without Streamlit.
def cached_preview(data, request, revision):
    import streamlit as st
    return st.cache_data(max_entries=4)(_preview_cached)(data, request, revision)


def _preview_cached(data, request, revision):
    return create_preview(data, request)


def cached_modified_model(data, revision):
    import streamlit as st
    return st.cache_data(max_entries=4)(_load_modified)(data, revision)


def _load_modified(data, revision):
    from amdfm.io import load_model
    return load_model(data, 'corner_improved.step')


def edit_figure(model, audit, *, after):
    """The same local crop and corner markers make a small fillet visible."""
    import numpy as np
    import plotly.graph_objects as go
    mesh = model.mesh
    low, high = np.asarray(audit['edit_bounds_mm'], dtype=float)
    margin = max(float(np.max(high-low))*.08, audit['after_corner_radius_mm']*1.3)
    low -= margin; high += margin
    vertices = np.asarray(mesh.vertices)
    triangles = vertices[mesh.faces]
    selected = np.flatnonzero(np.all(triangles.max(1) >= low, axis=1) & np.all(triangles.min(1) <= high, axis=1))
    if len(selected) > 100_000:
        selected = selected[np.linspace(0, len(selected)-1, 100_000, dtype=int)]
    colored = []
    if after:
        ids = audit.get('rounded_face_ids', [])
        if ids and model.face_ids is not None:
            colored = selected[np.isin(model.face_ids[selected], ids)].tolist()
    plain = selected[~np.isin(selected, colored)]
    figure = go.Figure()
    def surface(indices, color, name):
        clipped=clip_triangles(triangles[indices],low,high)
        points=clipped.reshape(-1,3)
        f=np.arange(len(points)).reshape(-1,3)
        figure.add_trace(go.Mesh3d(x=points[:,0], y=points[:,1], z=points[:,2], i=f[:,0], j=f[:,1], k=f[:,2],
            color=color, opacity=1., name=name, hovertemplate=name+'<extra></extra>', flatshading=False,
            lighting=dict(ambient=.85, diffuse=.5, specular=.1)))
    surface(plain, '#cad3dc', '포켓 주변 형상')
    if colored:
        surface(colored, '#e27735', '수정한 둥근 코너')
        # Show the actual upper boundary of the new cylindrical faces. It
        # remains visible where opaque surrounding material hides the wall.
        edges=set()
        direction = np.asarray(audit.get('direction', [0,0,1]), dtype=float)
        direction /= np.linalg.norm(direction)
        top=max(float(np.asarray(p) @ direction) for axis in audit['corner_axes_mm'] for p in axis)
        for face in mesh.faces[colored]:
            for a,b in ((face[0],face[1]),(face[1],face[2]),(face[2],face[0])):
                if abs(vertices[a] @ direction-top)<1e-7 and abs(vertices[b] @ direction-top)<1e-7:
                    edges.add(tuple(sorted((int(a),int(b)))))
        boundary=[]
        for a,b in sorted(edges):boundary.extend([vertices[a],vertices[b],[float('nan')]*3])
        if boundary:
            xyz=np.asarray(boundary)
            figure.add_trace(go.Scatter3d(x=xyz[:,0],y=xyz[:,1],z=xyz[:,2],mode='lines',
                line=dict(color='#e27735',width=7),name='수정한 코너의 실제 위쪽 경계',
                hovertemplate=f"수정 코너 · R {audit['after_corner_radius_mm']:g} mm<extra></extra>"))
    if not after:
        for i, axis in enumerate(audit['corner_axes_mm']):
            xyz = np.asarray(axis)
            figure.add_trace(go.Scatter3d(x=xyz[:,0], y=xyz[:,1], z=xyz[:,2], mode='lines',
                line=dict(color='#c93235', width=7), name=f'날카로운 코너 {i+1}',
                hovertemplate=f'기존 코너 {i+1} · R 0 mm<extra></extra>'))
        direction = np.asarray(audit.get('direction', [0,0,1]), dtype=float)
        tops=np.asarray([max(axis,key=lambda p:np.asarray(p) @ direction) for axis in audit['corner_axes_mm']])
        figure.add_trace(go.Scatter3d(x=tops[:,0],y=tops[:,1],z=tops[:,2],mode='markers+text',
            marker=dict(color='#c93235',size=6,symbol='diamond'),text=[f'코너 {i+1}' for i in range(len(tops))],
            textposition='top center',textfont=dict(color='#a32326',size=12),name='수정할 코너 위치',
            hovertemplate='날카로운 코너 · R 0 mm<extra></extra>'))
    # Look into the pocket from its measured entry axis, including rotated CAD.
    axis=np.asarray(audit.get('direction',[0,0,1]),dtype=float)
    axis/=np.linalg.norm(axis)
    seed=np.eye(3)[int(np.argmin(np.abs(axis)))]
    right=seed-axis*float(seed@axis)
    right/=np.linalg.norm(right)
    up=np.cross(axis,right)
    eye=2.4*axis+.7*right-.9*up
    figure.update_layout(height=400, margin=dict(l=0,r=0,t=10,b=0), showlegend=False,
        uirevision=model.fingerprint+'-corner-edit',
        scene=dict(aspectmode='data', camera=dict(eye=dict(zip('xyz',eye)),up=dict(zip('xyz',up)),projection=dict(type='orthographic')),
            **{name+'axis':dict(title=name.upper()+' (mm)', range=[float(low[i]),float(high[i])]) for i,name in enumerate('xyz')}))
    return figure


def clip_triangles(triangles, low, high):
    """Clip display triangles to the crop, without modifying the CAD/mesh."""
    import numpy as np
    result=[]
    for triangle in triangles:
        polygon=list(triangle)
        for axis in range(3):
            for bound,sign in ((low[axis],1),(high[axis],-1)):
                if not polygon:break
                output=[];previous=polygon[-1];pd=sign*(previous[axis]-bound)
                for point in polygon:
                    distance=sign*(point[axis]-bound)
                    if (distance>=0)!=(pd>=0):
                        output.append(previous+(point-previous)*(pd/(pd-distance)))
                    if distance>=0:output.append(point)
                    previous,pd=point,distance
                polygon=output
        for i in range(1,len(polygon)-1):
            candidate=np.asarray([polygon[0],polygon[i],polygon[i+1]])
            if np.linalg.norm(np.cross(candidate[1]-candidate[0],candidate[2]-candidate[0]))>1e-14:
                result.append(candidate)
    return np.asarray(result,dtype=float).reshape(-1,3,3)
