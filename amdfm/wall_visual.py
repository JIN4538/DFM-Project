"""Problem-focused views of recorded wall rays; never a face thickness map."""
from __future__ import annotations

import numbers
import html

import numpy as np
import plotly.graph_objects as go
import trimesh

from .visuals import finite_number, wall_samples

PROBLEM = '#b42318'
SELECTED = '#54278f'
NEUTRAL = '#718596'


def _face_index(value, mesh):
    return (isinstance(value, numbers.Integral) and not isinstance(value, bool)
            and 0 <= value < len(mesh.faces))


def _on_triangle(point, triangle, tolerance):
    nearest = trimesh.triangles.closest_point(np.asarray([triangle]), np.asarray([point]))[0]
    return bool(np.linalg.norm(nearest-point) <= tolerance)


def wall_sample_geometry(model, report, selected_sample=0):
    """Return the measured segment only when both endpoints match the mesh.

    The worker records the original face centre, inward-normal chord length,
    source face and target face. Recover the endpoint from that exact contract,
    then check it against the recorded target. Older records with no target
    retain their measured location but do not acquire a made-up endpoint.
    """
    samples = wall_samples(report)
    if selected_sample not in range(len(samples)):
        return None
    return _sample_geometry(model.mesh, samples[selected_sample], selected_sample)


def _sample_geometry(mesh, sample, selected_sample):
    point = np.asarray(sample['point_mm'], dtype=float)
    tolerance = max(float(np.max(mesh.extents))*1e-7, 1e-8)
    if (not _face_index(sample.get('source_face'), mesh)
            or not _on_triangle(point, mesh.triangles[sample['source_face']], tolerance)):
        return None
    result = dict(sample=sample, point=point, index=selected_sample, endpoint=None)
    distance = sample['normal_chord_mm']
    if distance <= 0 or not _face_index(sample.get('target_face'), mesh):
        return result
    normal = mesh.face_normals[sample['source_face']]
    endpoint = point-normal*distance
    if (sample['target_face'] == sample['source_face']
            or not _on_triangle(endpoint, mesh.triangles[sample['target_face']], tolerance)):
        return result
    result.update(endpoint=endpoint, inward=-normal)
    return result


def _transform(report):
    matrix = np.asarray(report['current_orientation']['transform'], dtype=float)
    if matrix.shape != (4, 4) or not np.isfinite(matrix).all():
        raise ValueError('표시할 배치 좌표를 확인할 수 없습니다.')
    return matrix


def wall_context_figure(model, report, *, selected_sample=0, show_all=False):
    """Full part, true aspect ratio, bounded axes and a small selected marker.

    No build arrow is added: a wall location does not need an arrow that changes
    the viewport bounds. Sample coordinates cannot enlarge these bounds.
    """
    matrix = _transform(report)
    mesh = model.mesh
    vertices = mesh.vertices @ matrix[:3, :3].T + matrix[:3, 3]
    count = min(len(mesh.faces), 250_000)
    indices = np.arange(len(mesh.faces)) if count == len(mesh.faces) else np.linspace(0, len(mesh.faces)-1, count, dtype=int)
    faces = mesh.faces[indices]
    fig = go.Figure(go.Mesh3d(x=vertices[:, 0], y=vertices[:, 1], z=vertices[:, 2],
        i=faces[:, 0], j=faces[:, 1], k=faces[:, 2], color='#bac7ce', opacity=.48,
        name='부품', hoverinfo='skip', showscale=False,
        lighting=dict(ambient=.7, diffuse=.5, specular=.1)))
    samples = wall_samples(report)
    limit = report.get('profile', {}).get('minimum_wall_mm')
    limit = limit if finite_number(limit) and limit > 0 else None
    good, bad = [], []
    for index, sample in enumerate(samples):
        if index == selected_sample:
            continue
        is_bad = limit is not None and sample['normal_chord_mm'] < limit
        if not is_bad and not show_all:
            continue
        geometry = _sample_geometry(mesh, sample, index)
        if geometry is not None:
            (bad if is_bad else good).append(geometry)
    # A dense sample cloud hides the shape. The selector and table retain all
    # samples; deterministic representative points keep the overview legible.
    omitted = 0
    for rows, label, color, symbol in [(bad, '기준 미만 위치', PROBLEM, 'x'),
                                        (good, '나머지 측정 위치', NEUTRAL, 'circle')]:
        omitted += max(0, len(rows)-80)
        rows = rows[:80]
        if not rows:
            continue
        points = np.asarray([row['point'] for row in rows]) @ matrix[:3, :3].T + matrix[:3, 3]
        fig.add_trace(go.Scatter3d(x=points[:, 0], y=points[:, 1], z=points[:, 2], mode='markers',
            marker=dict(size=4 if symbol == 'x' else 2.5, color=color, symbol=symbol), name=label,
            customdata=[[row['index']+1, row['sample']['normal_chord_mm']] for row in rows],
            hovertemplate='위치 %{customdata[0]} · %{customdata[1]:.5g} mm<extra>%{fullData.name}</extra>'))
    selected = wall_sample_geometry(model, report, selected_sample)
    if selected is not None:
        point = selected['point'] @ matrix[:3, :3].T + matrix[:3, 3]
        fig.add_trace(go.Scatter3d(x=[point[0]], y=[point[1]], z=[point[2]], mode='markers+text',
            text=[f'위치 {selected_sample+1}'], textposition='top center',
            marker=dict(size=6, color=SELECTED, symbol='diamond', line=dict(color='white', width=1)),
            name='선택 위치 ◆', hovertemplate=f"위치 {selected_sample+1} · {selected['sample']['normal_chord_mm']:.5g} mm<extra></extra>"))
        if selected['endpoint'] is not None:
            endpoint = selected['endpoint'] @ matrix[:3, :3].T + matrix[:3, 3]
            segment = np.asarray([point, endpoint])
            fig.add_trace(go.Scatter3d(x=segment[:, 0], y=segment[:, 1], z=segment[:, 2], mode='lines',
                line=dict(color=SELECTED, width=5), name='측정선', showlegend=False, hoverinfo='skip'))
    low, high = vertices.min(axis=0), vertices.max(axis=0)
    padding = np.maximum((high-low)*.08, max(float(np.max(high-low)), 1e-9)*.015)
    axes = {f'{axis}axis': dict(title=f'빌드 {axis.upper()} (mm)',
             range=[float(low[i]-padding[i]), float(high[i]+padding[i])], nticks=4)
            for i, axis in enumerate('xyz')}
    # Plotly's data aspect scales a near-planar scene by its tiny third extent.
    # Normalize the whole scene to its longest span, preserving actual ratios
    # without magnifying a thin plate beyond the viewport.
    scene_extent = high-low+2*padding
    aspect = dict(zip('xyz', (scene_extent / np.max(scene_extent)).tolist()))
    fig.update_layout(height=370, margin=dict(l=0, r=0, t=5, b=20),
        paper_bgcolor='rgba(0,0,0,0)', showlegend=True,
        legend=dict(orientation='h', x=0, y=-.03, font=dict(size=11)),
        scene=dict(**axes, aspectmode='manual', aspectratio=aspect, camera=dict(eye=dict(x=1.3, y=1.3, z=1.2),
                   projection=dict(type='orthographic'))),
        uirevision=f"wall-context-{report.get('model_fingerprint', model.fingerprint)}",
        meta=dict(omitted_sample_markers=omitted, display_faces=count, total_faces=len(mesh.faces)))
    return fig


def _clip_segment(a, b, lower, upper):
    """Clip actual section segments to the displayed local rectangle."""
    delta = b-a
    first, last = 0., 1.
    for axis in range(2):
        if delta[axis] == 0:
            if a[axis] < lower[axis] or a[axis] > upper[axis]:
                return None
            continue
        at_lower = (lower[axis]-a[axis])/delta[axis]
        at_upper = (upper[axis]-a[axis])/delta[axis]
        first, last = max(first, min(at_lower, at_upper)), min(last, max(at_lower, at_upper))
        if first > last:
            return None
    return np.asarray([a+first*delta, a+last*delta])


def wall_measurement_figure(model, report, *, selected_sample=0):
    """An actual plane cut through the selected ray, equally scaled on X/Y.

    This local coordinate system is independent of the build placement: its
    vertical axis is inward along the recorded measurement, starting at zero.
    The viewport deliberately crops the part around the ray, not its thickness.
    """
    geometry = wall_sample_geometry(model, report, selected_sample)
    if geometry is None or geometry['endpoint'] is None:
        return None
    mesh = model.mesh
    sample, point, inward = geometry['sample'], geometry['point'], geometry['inward']
    triangle = mesh.triangles[sample['source_face']]
    edges = np.roll(triangle, -1, axis=0)-triangle
    tangent = edges[np.argmax(np.linalg.norm(edges, axis=1))]
    tangent = tangent-inward*np.dot(tangent, inward)
    tangent /= np.linalg.norm(tangent)
    plane_normal = np.cross(tangent, inward)
    distance = sample['normal_chord_mm']
    half_width = distance*.9
    yrange = [-distance*.35, distance*1.35]
    # Avoid work on remote geometry: only triangles whose local projection
    # overlaps the crop can contribute a visible segment. The cut is still made
    # on the original triangles, without simplification or synthetic surfaces.
    relative = mesh.vertices-point
    xx, yy = relative@tangent, relative@inward
    tx, ty = xx[mesh.faces], yy[mesh.faces]
    nearby = np.flatnonzero((tx.max(axis=1) >= -half_width) & (tx.min(axis=1) <= half_width)
                            & (ty.max(axis=1) >= yrange[0]) & (ty.min(axis=1) <= yrange[1]))
    segments = trimesh.intersections.mesh_plane(mesh, plane_normal, point, local_faces=nearby)
    fig = go.Figure()
    if len(segments):
        local = segments-point
        xy = np.stack((local@tangent, local@inward), axis=2)
        clipped = [_clip_segment(a, b, [-half_width, yrange[0]], [half_width, yrange[1]]) for a, b in xy]
        clipped = [segment for segment in clipped if segment is not None]
        xs = [value for segment in clipped for value in [*segment[:, 0].tolist(), None]]
        ys = [value for segment in clipped for value in [*segment[:, 1].tolist(), None]]
        fig.add_trace(go.Scatter(x=xs, y=ys, mode='lines', line=dict(color='#334155', width=3),
            name='실제 단면 윤곽', hoverinfo='skip', showlegend=False))
    fig.add_trace(go.Scatter(x=[0, 0], y=[0, distance], mode='lines+markers',
        line=dict(color=SELECTED, width=5), marker=dict(color=SELECTED, size=8, symbol=['diamond', 'square']),
        name='선택 위치 측정선', customdata=['입구', '반대 면'],
        hovertemplate='%{customdata}<br>입구에서 %{y:.5g} mm<extra></extra>', showlegend=False))
    fig.add_annotation(x=0, y=distance/2, text=f'<b>{distance:.5g} mm</b>',
        ax=70, ay=0, arrowhead=2, arrowcolor=SELECTED, font=dict(color=SELECTED, size=18), bgcolor='white')
    for y, text, shift in [(0, '① 입구', -18), (distance, '② 반대 면', 18)]:
        fig.add_annotation(x=0, y=y, text=text, showarrow=False, yshift=shift, xshift=-40,
                           font=dict(size=12), bgcolor='rgba(255,255,255,.85)')
    fig.update_layout(height=370, margin=dict(l=55, r=20, t=15, b=45),
        paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='white',
        xaxis=dict(title='측정선에서 좌우 거리 (mm)', range=[-half_width, half_width],
                   constrain='domain', zeroline=False, nticks=5),
        yaxis=dict(title='입구에서 안쪽 거리 (mm)', range=yrange, scaleanchor='x', scaleratio=1,
                   constrain='domain', zeroline=False, nticks=5),
        uirevision=f'wall-detail-{selected_sample}-{distance}',
        meta=dict(source_face=sample['source_face'], target_face=sample['target_face'],
                  source_point_mm=point.tolist(), target_point_mm=geometry['endpoint'].tolist(),
                  local_tangent=tangent.tolist(), local_inward=inward.tolist(), equal_scale=True))
    return fig


def wall_report_svg(model, report, *, selected_sample=0):
    """Small, offline report illustrations using the same validated geometry.

    No Plotly runtime, screenshot, or external URL is required to read the
    exported report. The context has a display-only triangle budget; the local
    section and ray use the original geometry used by the interactive view.
    """
    geometry = wall_sample_geometry(model, report, selected_sample)
    if geometry is None:
        return '<p>선택한 표본의 위치 좌표를 현재 형상에서 확인할 수 없습니다.</p>'
    context = wall_context_figure(model, report, selected_sample=selected_sample)
    mesh = context.data[0]
    vertices = np.column_stack((mesh.x, mesh.y, mesh.z))
    basis = np.array([[1/2**.5, -1/2**.5, 0], [-1/6**.5, -1/6**.5, 2/6**.5],
                      [1/3**.5, 1/3**.5, 1/3**.5]])
    projected = vertices@basis.T
    low, high = projected[:, :2].min(axis=0), projected[:, :2].max(axis=0)
    span, center = np.maximum(high-low, 1e-12), (low+high)/2
    scale = min(540/span[0], 260/span[1])
    def place_context(points):
        xy = np.asarray(points)@basis[:2].T
        return np.column_stack((320+(xy[:, 0]-center[0])*scale, 175-(xy[:, 1]-center[1])*scale))
    def points_text(points):
        return ' '.join(f'{x:.4f},{y:.4f}' for x, y in points)
    def svg_start(label):
        return ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 640 400' role='img' "
                f"aria-label='{html.escape(label, quote=True)}'><title>{html.escape(label)}</title>"
                "<rect width='640' height='400' fill='white'/>")
    distance = geometry['sample']['normal_chord_mm']
    title = f'부품에서의 위치 {selected_sample+1} · 측정 거리 {distance:.5g} mm'
    parts = [svg_start(title)]
    faces = np.column_stack((mesh.i, mesh.j, mesh.k))
    if len(faces) > 600:
        faces = faces[np.linspace(0, len(faces)-1, 600, dtype=int)]
    pixels = place_context(vertices)
    for index in np.argsort(projected[faces, 2].mean(axis=1)):
        parts.append(f"<polygon points='{points_text(pixels[faces[index]])}' fill='#bac7ce' fill-opacity='.65' "
                     "stroke='#8e9aa4' stroke-width='.4'/>")
    for trace in context.data[1:]:
        xyz = np.column_stack((trace.x, trace.y, trace.z))
        xy = place_context(xyz)
        if trace.name == '기준 미만 위치':
            for x, y in xy:
                parts.append(f"<path d='M{x-3:.4f},{y-3:.4f}L{x+3:.4f},{y+3:.4f}M{x-3:.4f},{y+3:.4f}L{x+3:.4f},{y-3:.4f}' "
                             f"stroke='{PROBLEM}' stroke-width='2' fill='none'/>")
        elif trace.name == '선택 위치 ◆':
            x, y = xy[0]
            parts.append(f"<polygon points='{x:.4f},{y-6:.4f} {x+6:.4f},{y:.4f} {x:.4f},{y+6:.4f} {x-6:.4f},{y:.4f}' "
                         f"fill='{SELECTED}' stroke='white' stroke-width='1'/>")
            # Label inside the canvas even when the selected point is near an edge.
            text_x = min(max(x+10, 25), 505)
            parts.append(f"<text x='{text_x:.4f}' y='{max(y-12,25):.4f}' fill='{SELECTED}' font-size='17' font-weight='bold'>위치 {selected_sample+1}</text>")
        elif trace.name == '측정선':
            parts.append(f"<polyline points='{points_text(xy)}' stroke='{SELECTED}' stroke-width='3' fill='none'/>")
    selection = next(trace for trace in context.data if trace.name == '선택 위치 ◆')
    coordinate = ', '.join(f'{float(values[0]):.5g}' for values in (selection.x, selection.y, selection.z))
    has_limit = report.get('profile', {}).get('minimum_wall_mm') is not None
    legend = '선택 위치 ◆ · 기준 미만 ×' if has_limit else '선택 위치 ◆ · 측정한 거리'
    parts.append(f"<text x='20' y='344' font-size='14'>{legend}</text>"
                 f"<text x='20' y='368' font-size='13'>선택 위치의 빌드 X, Y, Z (mm): {coordinate}</text>")
    if len(faces) < len(model.mesh.faces):
        parts.append(f"<text x='20' y='389' font-size='12' fill='#555'>부품 표시: 삼각형 {len(faces):,}/{len(model.mesh.faces):,}개 · 일부 생략</text>")
    parts.append('</svg>')
    detail = wall_measurement_figure(model, report, selected_sample=selected_sample)
    if detail is None:
        return ''.join(parts)+'<p>반대 면 좌표를 확인할 수 없어 확대 단면은 표시하지 않습니다.</p>'
    label = f'위치 {selected_sample+1} 확대 · 실제 단면 · {distance:.5g} mm · 가로 세로 동일 배율'
    parts.append(svg_start(label))
    xlimits, ylimits = detail.layout.xaxis.range, detail.layout.yaxis.range
    local_scale = min(440/(xlimits[1]-xlimits[0]), 245/(ylimits[1]-ylimits[0]))
    xcenter, ycenter = np.mean(xlimits), np.mean(ylimits)
    def px(x): return 300+(x-xcenter)*local_scale
    def py(y): return 160-(y-ycenter)*local_scale
    for x in np.linspace(*xlimits, 5):
        parts.append(f"<line x1='{px(x):.4f}' x2='{px(x):.4f}' y1='{py(ylimits[1]):.4f}' y2='{py(ylimits[0]):.4f}' stroke='#e2e8f0'/>"
                     f"<text x='{px(x):.4f}' y='{py(ylimits[0])+20:.4f}' text-anchor='middle' font-size='12'>{x:.3g}</text>")
    for y in np.linspace(*ylimits, 5):
        parts.append(f"<line x1='{px(xlimits[0]):.4f}' x2='{px(xlimits[1]):.4f}' y1='{py(y):.4f}' y2='{py(y):.4f}' stroke='#e2e8f0'/>"
                     f"<text x='{px(xlimits[0])-10:.4f}' y='{py(y)+4:.4f}' text-anchor='end' font-size='12'>{y:.3g}</text>")
    for trace in detail.data:
        if trace.name != '실제 단면 윤곽':
            continue
        for start in range(0, len(trace.x), 3):
            points = [[px(trace.x[k]), py(trace.y[k])] for k in (start, start+1)]
            parts.append(f"<polyline points='{points_text(points)}' fill='none' stroke='#334155' stroke-width='3'/>")
    x, y0, y1 = px(0), py(0), py(distance)
    parts.append(f"<line x1='{x:.4f}' x2='{x:.4f}' y1='{y0:.4f}' y2='{y1:.4f}' stroke='{SELECTED}' stroke-width='4' data-measurement-mm='{distance:.16g}'/>"
                 f"<polygon points='{x:.4f},{y0-5:.4f} {x+5:.4f},{y0:.4f} {x:.4f},{y0+5:.4f} {x-5:.4f},{y0:.4f}' fill='{SELECTED}'/>"
                 f"<rect x='{x-4:.4f}' y='{y1-4:.4f}' width='8' height='8' fill='{SELECTED}'/>"
                 f"<text x='{x-15:.4f}' y='{y0+22:.4f}' text-anchor='end' font-size='14'>① 입구</text>"
                 f"<text x='{x-15:.4f}' y='{y1-13:.4f}' text-anchor='end' font-size='14'>② 반대 면</text>"
                 f"<text x='{x+20:.4f}' y='{(y0+y1)/2+5:.4f}' font-size='20' font-weight='bold' fill='{SELECTED}'>{distance:.5g} mm</text>"
                 "<text x='300' y='330' text-anchor='middle' font-size='13'>측정선에서 좌우 거리 (mm)</text>"
                 "<text x='20' y='25' font-size='13'>세로: 입구에서 안쪽 거리 (mm)</text>"
                 "<text x='20' y='368' font-size='14'>선택한 측정선을 지나는 실제 단면 · 가로·세로 동일 배율</text></svg>")
    return ''.join(parts)
