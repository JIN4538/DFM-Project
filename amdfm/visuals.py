"""Display recorded geometry without changing measurements or their scope."""
from __future__ import annotations

import html
import math
import numpy as np
import plotly.graph_objects as go

PREVIOUS = '#315f78'
CURRENT = '#bb570b'
NEUTRAL = '#718596'


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def section_pair(rows, chosen):
    current = rows[chosen]
    previous = rows[chosen-1] if chosen > 0 else None
    comparable = (previous is not None and current.get('complete') and previous.get('complete')
                  and current.get('symmetric_change_from_previous_mm2') is not None)
    return ([('이전 단면', previous, PREVIOUS, 'dash')] if comparable else []) + [
        ('현재 단면', current, CURRENT, 'solid')]


def valid_rings(row):
    result = []
    for ring in row.get('outlines', []):
        try:
            points = np.asarray(ring, dtype=float)
        except (TypeError, ValueError):
            continue
        if points.ndim == 2 and points.shape[1] == 2 and len(points) >= 2 and np.isfinite(points).all():
            result.append(points)
    return result


def section_bounds(pair):
    rings = [ring for _, row, _, _ in pair for ring in valid_rings(row)]
    if not rings:
        return None
    points = np.concatenate(rings)
    low, high = points.min(axis=0), points.max(axis=0)
    padding = np.maximum((high-low)*.06, max(float(np.max(high-low)), 1e-9)*.02)
    return low-padding, high+padding


def section_outline_figure(rows, chosen):
    pair = section_pair(rows, chosen)
    fig = go.Figure()
    for label, row, color, dash in pair:
        for index, ring in enumerate(valid_rings(row)):
            fig.add_trace(go.Scatter(x=ring[:, 0].tolist(), y=ring[:, 1].tolist(), mode='lines',
                name=f"{label} · {row['z_mm']:.4g} mm", legendgroup=label, showlegend=index == 0,
                line=dict(color=color, dash=dash, width=3),
                hovertemplate='X %{x:.4g} mm · Y %{y:.4g} mm<extra>%{fullData.name}</extra>'))
    bounds = section_bounds(pair)
    fig.update_layout(height=420, margin=dict(l=65, r=20, t=20, b=80),
        xaxis=dict(title='빌드 X (mm)', constrain='domain', automargin=True, nticks=6),
        yaxis=dict(title='빌드 Y (mm)', scaleanchor='x', scaleratio=1,
                   constrain='domain', automargin=True, nticks=6),
        legend=dict(orientation='h', y=-.25, x=0, font=dict(size=12)))
    if bounds is not None:
        fig.update_xaxes(range=[float(bounds[0][0]), float(bounds[1][0])])
        fig.update_yaxes(range=[float(bounds[0][1]), float(bounds[1][1])])
    return fig


def section_area_figure(rows, chosen):
    """The selected location remains identifiable without color or hover."""
    known = [(i, row) for i, row in enumerate(rows)
             if row.get('complete') and finite_number(row.get('area_mm2')) and finite_number(row.get('z_mm'))]
    if not known:
        return None
    fig = go.Figure()
    previous_index = chosen-1 if len(section_pair(rows, chosen)) == 2 else None
    categories = [('다른 단면', [r for i, r in known if i not in (chosen, previous_index)], NEUTRAL, 'circle', 7),
                  ('이전 단면', [r for i, r in known if i == previous_index], PREVIOUS, 'square', 11),
                  ('현재 단면', [r for i, r in known if i == chosen], CURRENT, 'diamond', 15)]
    for label, points, color, symbol, size in categories:
        if points:
            fig.add_trace(go.Scatter(x=[r['z_mm'] for r in points], y=[r['area_mm2'] for r in points],
                mode='markers', name=label, marker=dict(color=color, symbol=symbol, size=size,
                    line=dict(color='white', width=1)),
                hovertemplate='높이 %{x:.5g} mm<br>재료 면적 %{y:.5g} mm²<extra>%{fullData.name}</extra>'))
    current = rows[chosen]
    if finite_number(current.get('z_mm')):
        fig.add_vline(x=current['z_mm'], line_dash='dot', line_color=CURRENT, line_width=1)
        fig.add_annotation(x=current['z_mm'], y=1.04, yref='paper', text=f"현재 {current['z_mm']:.4g} mm",
                           showarrow=False, font=dict(color=CURRENT))
    fig.update_layout(height=420, margin=dict(l=70, r=20, t=40, b=80),
        xaxis=dict(title='높이 (mm)', nticks=7, automargin=True),
        yaxis=dict(title='재료 단면적 (mm²)', nticks=5, rangemode='tozero', automargin=True),
        legend=dict(orientation='h', y=-.25, x=0))
    return fig


def wall_samples(report):
    detail = report.get('details', {}).get('wall', {})
    if detail.get('status') not in ('measured', 'partial'):
        return []
    samples = []
    for sample in detail.get('measurements', {}).get('samples', []):
        point = sample.get('point_mm', [])
        if (len(point) == 3 and all(finite_number(v) for v in point)
                and finite_number(sample.get('normal_chord_mm')) and sample['normal_chord_mm'] >= 0):
            samples.append(sample)
    return sorted(samples, key=lambda s: (s['normal_chord_mm'], s['source_face']))


def add_wall_markers(fig, report, *, selected_sample=None):
    samples = wall_samples(report)
    if not samples:
        return
    matrix = np.asarray(report['current_orientation']['transform'])
    xyz = np.asarray([s['point_mm'] for s in samples]) @ matrix[:3, :3].T + matrix[:3, 3]
    distances = [s['normal_chord_mm'] for s in samples]
    limit = report['profile'].get('minimum_wall_mm')
    groups = [('측정 표본', list(range(len(samples))), NEUTRAL, 'circle')]
    if limit is not None:
        groups = [('기준 미만 표본', [i for i, v in enumerate(distances) if v < limit], '#af3029', 'diamond'),
                  ('기준 이상 표본', [i for i, v in enumerate(distances) if v >= limit], '#718596', 'circle')]
    for label, indices, color, symbol in groups:
        if not indices:
            continue
        marker = dict(size=6, color=color, symbol=symbol, opacity=1)
        if limit is None:
            marker.update(color=[distances[i] for i in indices],
                colorscale=[[0, '#163c56'], [1, '#a9c7d8']], showscale=True,
                colorbar=dict(title='측정 거리<br>(mm)', thickness=12, len=.6))
        points = xyz[indices]
        fig.add_trace(go.Scatter3d(x=points[:, 0].tolist(), y=points[:, 1].tolist(), z=points[:, 2].tolist(),
            mode='markers', name=label, marker=marker,
            customdata=[[distances[i], samples[i]['source_face']] for i in indices],
            hovertemplate='측정 거리 %{customdata[0]:.5g} mm<br>표본 면 %{customdata[1]}<extra>%{fullData.name}</extra>'))
    index = selected_sample if selected_sample in range(len(samples)) else 0
    p = xyz[index]
    fig.add_trace(go.Scatter3d(x=[p[0]], y=[p[1]], z=[p[2]], mode='markers+text',
        name='선택한 표본', text=[f"{distances[index]:.4g} mm"], textposition='top center',
        marker=dict(size=10, color=CURRENT, symbol='diamond', line=dict(color='white', width=2)),
        hovertemplate='선택한 표본 · %{text}<extra></extra>'))
    fig.update_layout(showlegend=True, legend=dict(orientation='h', y=-.03, x=0))


def section_svg(rows, chosen):
    pair = section_pair(rows, chosen)
    bounds = section_bounds(pair)
    if bounds is None:
        return ''
    low, high = bounds
    scale = min(520/(high[0]-low[0]), 300/(high[1]-low[1]))
    center = (low+high)/2
    parts = ["<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 640 410' role='img' aria-label='이전 단면과 현재 단면의 실제 윤곽 비교'>",
             '<title>같은 배율의 단면 윤곽 · 빌드 X/Y 좌표</title>',
             "<rect width='640' height='410' fill='white'/>" ]
    for k, (label, row, color, dash) in enumerate(pair):
        for ring in valid_rings(row):
            points = ' '.join(f'{320+(x-center[0])*scale:.3f},{175-(y-center[1])*scale:.3f}' for x,y in ring)
            parts.append(f"<polyline points='{points}' fill='none' stroke='{color}' stroke-width='2.5'"
                         + (" stroke-dasharray='7 5'" if dash == 'dash' else '') + '/>')
        label_text = html.escape(f"{label} · 높이 {row['z_mm']:.5g} mm · {'점선' if dash=='dash' else '실선'}")
        parts.append(f"<text x='25' y='{355+22*k}' fill='{color}' font-size='15'>{label_text}</text>")
    parts.append('</svg>')
    return ''.join(parts)


def model_svg(model, report):
    """Small offline placement illustration, never a silhouette measurement."""
    if model.fingerprint != report['model_fingerprint']:
        raise ValueError('보고서와 표시할 형상이 다릅니다.')
    matrix = np.asarray(report['current_orientation']['transform'])
    xyz = model.mesh.vertices @ matrix[:3, :3].T + matrix[:3, 3]
    # Fixed isometric camera; painter order preserves the actual placement.
    basis = np.array([[1/2**.5, -1/2**.5, 0], [-1/6**.5, -1/6**.5, 2/6**.5],
                      [1/3**.5, 1/3**.5, 1/3**.5]])
    projected = xyz @ basis.T
    low, high = projected[:, :2].min(axis=0), projected[:, :2].max(axis=0)
    span = np.maximum(high-low, 1e-12)
    scale = min(540/span[0], 310/span[1])
    center = (low+high)/2
    mesh = model.mesh
    budget = 3500
    ids = np.arange(len(mesh.faces)) if len(mesh.faces) <= budget else np.linspace(0, len(mesh.faces)-1, budget, dtype=int)
    faces = mesh.faces[ids]
    depth = projected[faces, 2].mean(axis=1)
    parts = ["<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 640 400' role='img' aria-label='검토 방향으로 배치한 입력 메시 참고도'>",
             '<title>입력 메시의 검토 방향 배치 · 정밀 치수 도면 아님</title>',
             "<rect width='640' height='400' fill='white'/>" ]
    for index in np.argsort(depth):
        tri = projected[faces[index], :2]
        points = ' '.join(f'{320+(x-center[0])*scale:.2f},{180-(y-center[1])*scale:.2f}' for x,y in tri)
        normal = mesh.face_normals[ids[index]] @ matrix[:3, :3].T
        shade = int(115+75*abs(float(np.dot(normal, basis[2]))))
        parts.append(f"<polygon points='{points}' fill='rgb({shade-35},{shade},{min(shade+22,255)})' stroke='white' stroke-width='.2'/>")
    note = ('전체 메시 표시' if len(ids) == len(mesh.faces) else f'표시용 삼각형 {len(ids):,}/{len(mesh.faces):,}개 · 일부 생략')
    parts.append(f"<text x='20' y='370' font-size='14' fill='#394b59'>{note} · 정밀 판단은 원본 형상에서 확인</text></svg>")
    return ''.join(parts)
