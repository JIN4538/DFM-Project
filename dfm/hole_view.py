"""Measured hole sizes and a single click to re-review an entry direction."""
from __future__ import annotations

import html
import numpy as np
import streamlit as st

from amdfm.orientation import unit_direction, direction_angles

AXES = {'+Z · 위쪽에서': (0, 0, 1), '−Z · 아래쪽에서': (0, 0, -1),
        '+X': (1, 0, 0), '−X': (-1, 0, 0), '+Y': (0, 1, 0), '−Y': (0, -1, 0)}


def entry_choice(holes, current):
    """Most confirmed mouths on one axis; prefer the smallest rotation on ties."""
    current = unit_direction(current)
    candidates = [unit_direction(v) for h in holes for v in h['entry_directions']]
    if not candidates:
        return None
    def coverage(v):
        return sum(any(np.linalg.norm(np.cross(v, d)) <= 1e-8 and float(v @ np.asarray(d)) > 0
                       for d in h['entry_directions']) for h in holes)
    best = max(candidates, key=lambda v: (coverage(v), float(v @ current)))
    return dict(direction=best.tolist(), covered_count=coverage(best), total=len(holes))


def apply_entry_direction(direction, face_id):
    """Widget callback: retain all user conditions and request one new review."""
    v = unit_direction(direction)
    label = next((name for name, d in AXES.items() if np.linalg.norm(v-np.asarray(d)) <= 1e-8), None)
    if label is None:
        tilt, azimuth = direction_angles(v)
        st.session_state.update(cnc_direction='직접 각도 입력', cnc_tilt=float(tilt), cnc_azimuth=float(azimuth))
    else:
        st.session_state['cnc_direction'] = label
    st.session_state.update(cnc_auto_review=True, cnc_pending_hole_focus=int(face_id))


def hole_rows(report):
    return [{'구멍': i, '종류': '관통' if h['hole_kind']=='through' else '막힌 구멍',
             '지름 (mm)': h['diameter_mm'], '깊이 (mm)': h['depth_mm'],
             '현재 방향': '입구 방향 일치' if h.get('entry_matches_direction') else
                         '바닥 쪽 · 방향 변경' if h.get('entry_blocked') else '다른 축 · 방향 변경',
             'CAD 면': ', '.join(map(str, h['face_ids']))}
            for i, h in enumerate(report.get('verified_hole_inventory', {}).get('holes', []), 1)]


def render_hole_overview(report, *, on_select):
    holes = report.get('verified_hole_inventory', {}).get('holes', [])
    if not holes:
        return
    diameters = [h['diameter_mm'] for h in holes]
    sizes = f'Ø {min(diameters):,.4g}' if max(diameters)-min(diameters) < 1e-7 else f'Ø {min(diameters):,.4g}–{max(diameters):,.4g}'
    with st.expander(f"구멍 {len(holes)}개 · {sizes} mm · 깊이 최대 {max(h['depth_mm'] for h in holes):,.4g} mm"):
        st.dataframe(hole_rows(report), hide_index=True, width='stretch',
                     column_config={k: st.column_config.NumberColumn(format='%.4g') for k in ('지름 (mm)', '깊이 (mm)')})
    first = next((h for h in holes if not h['entry_matches_direction']), holes[0])
    with st.container(horizontal=True):
        st.button('구멍 위치 보기', key='cnc_hole_location', on_click=on_select, args=('cnc_holes', first['face_id']))
        if any(not h['entry_matches_direction'] for h in holes):
            choice = entry_choice(holes, report['direction'])
            matching = next(h for h in holes if any(np.linalg.norm(np.asarray(d)-choice['direction']) <= 1e-8 for d in h['entry_directions']))
            st.button(f"구멍 {choice['covered_count']}개의 입구 방향으로 검토", key='cnc_hole_apply_direction',
                      type='primary', on_click=apply_entry_direction, args=(choice['direction'], matching['face_id']))


def hole_summary_html(report):
    rows = hole_rows(report)
    if not rows:
        return ''
    esc = lambda v: html.escape(str(v), quote=True)
    keys = list(rows[0])
    body = ''.join('<tr>'+''.join(f'<td>{esc(f"{r[k]:.6g}" if isinstance(r[k], float) else r[k])}</td>' for k in keys)+'</tr>' for r in rows)
    return f'<details><summary>구멍 {len(rows)}개 · 치수와 입구 방향</summary><table><thead><tr>'+''.join(f'<th>{esc(k)}</th>' for k in keys)+f'</tr></thead><tbody>{body}</tbody></table></details>'


def mark_hole_mouths(fig, report, selected_ids, direction):
    """Draw a native circular opening and size label in the plot's build frame."""
    import plotly.graph_objects as go
    matrix=np.asarray(report['current_orientation']['transform'],float)
    direction=unit_direction(direction)
    marked=False
    for index,h in enumerate(report.get('verified_hole_inventory', {}).get('holes', []),1):
        if not set(h['face_ids']) & set(selected_ids):
            continue
        marked=True
        entry=max(range(len(h['entry_directions'])),key=lambda i: float(direction @ np.asarray(h['entry_directions'][i])))
        n=unit_direction(h['entry_directions'][entry]);center=np.asarray(h['entry_centers_mm'][entry])
        helper=np.eye(3)[int(np.argmin(np.abs(n)))]
        u=np.cross(n,helper);u/=np.linalg.norm(u);v=np.cross(n,u)
        angles=np.linspace(0,2*np.pi,65)
        ring=center+h['diameter_mm']/2*(np.cos(angles)[:,None]*u+np.sin(angles)[:,None]*v)
        ring=ring@matrix[:3,:3].T+matrix[:3,3]
        color='#1476b8'
        label=f"구멍 {index} · Ø {h['diameter_mm']:.4g} · 깊이 {h['depth_mm']:.4g} mm"
        fig.add_trace(go.Scatter3d(x=ring[:,0],y=ring[:,1],z=ring[:,2],mode='lines',line=dict(width=7,color=color),
            name='구멍 입구',showlegend=False,hovertemplate=label+'<extra></extra>'))
        point=(center+n*max(h['diameter_mm']*.3,.3))@matrix[:3,:3].T+matrix[:3,3]
        fig.add_trace(go.Scatter3d(x=[point[0]],y=[point[1]],z=[point[2]],mode='markers+text',
            marker=dict(size=4,color=color),text=[label],textposition='top center',textfont=dict(size=14,color='#174563'),
            showlegend=False,hovertemplate=label+'<extra></extra>'))
    if marked:
        fig.data[0].opacity=.25
        selected=[h for h in report['verified_hole_inventory']['holes'] if set(h['face_ids']) & set(selected_ids)]
        choice=entry_choice(selected,direction)
        axis=unit_direction(np.asarray(choice['direction'])@matrix[:3,:3].T)
        seed=np.eye(3)[int(np.argmin(np.abs(axis)))]
        right=seed-axis*float(seed@axis);right/=np.linalg.norm(right)
        up=np.cross(axis,right)
        eye=2.4*axis+.45*right-.4*up
        fig.update_layout(scene=dict(camera=dict(eye=dict(zip('xyz',eye)),up=dict(zip('xyz',up)),
                                               projection=dict(type='orthographic'))),
                          uirevision=report['model_fingerprint']+'-hole-'+','.join(map(str,sorted(selected_ids))))
    return fig
