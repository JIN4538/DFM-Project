"""One editable equipment/output settings panel, with evidence kept internally."""
import streamlit as st
from .defaults import wall_default_value, wall_default_basis

def render_am_settings(process):
    with st.expander('벽·구멍 크기와 출력 설정', expanded=False):
        return _render_am_settings(process)


def _render_am_settings(process):
    st.session_state.setdefault(f'wall_limit_{process}',wall_default_value(process))
    st.session_state.setdefault(f'basis_{process}',wall_default_basis(process))
    c1,c2=st.columns(2)
    wall=c1.number_input('이보다 얇은 벽 찾기 (mm)',min_value=.001,value=None,key=f'wall_limit_{process}',persist_state='session',
                        help='예: 1.2를 입력하면 측정한 벽 중 1.2 mm보다 얇은 곳을 표시합니다. 기본값으로 시작하고 필요할 때 바꾸세요.')
    hole=c2.number_input('이보다 작은 구멍 찾기 (지름, mm)',min_value=.001,value=None,key=f'hole_limit_{process}',persist_state='session',
                        placeholder='비워 두면 지름만 측정',help='예: 2를 입력하면 지름 2 mm보다 작은 구멍을 표시합니다. 비워 두면 구멍 크기의 적합 여부는 판단하지 않습니다.')
    use_build=st.checkbox('장비 안에 들어가는지도 확인',value=False,key=f'use_build_{process}',persist_state='session',
                          help='선택한 장비의 출력 가능 크기와 비교합니다. 끄면 부품 크기에 제한을 두지 않습니다.')
    dims=None
    if use_build:
        cols=st.columns(3)
        dims=tuple(col.number_input(f'{label} (mm)',min_value=1.,value=250.,key=f'build_{axis}_{process}',
                                   persist_state='session') for col,axis,label in zip(cols,'XYZ',('가로 X','세로 Y','높이 Z')))
    defaults={'MEX':.2,'VPP':.05,'PBF_POLYMER':.1,'PBF_METAL':.03}
    c1,c2=st.columns(2)
    layer=c1.number_input('한 층의 두께 (mm)',min_value=.005,max_value=5.,value=defaults[process],format='%.3f',key=f'layer_{process}',persist_state='session',
                         help='한 번 쌓는 층의 두께입니다. 프린터·슬라이서에서 쓰는 층 높이 값을 입력하세요.')
    line=c2.number_input('재료 한 줄의 너비 (mm)',min_value=.01,max_value=5.,value=.4,key='line_width',persist_state='session',
                        help='노즐이 한 줄로 쌓는 재료의 폭입니다. 슬라이서의 선폭 설정과 맞추세요.') if process=='MEX' else .4
    with st.expander('추가 설정'):
        clearance=st.number_input('장비 경계에서 띄울 거리 (mm)',min_value=0.,value=0.,key=f'clearance_{process}',persist_state='session',
                                  help='장비 크기 확인을 켰을 때 각 방향의 양쪽 끝에 확보할 여유입니다.')
        slicer=st.text_input('슬라이서·버전',value='미확정',key=f'slicer_{process}',persist_state='session')
        notes=st.text_area('공정 조건·설계 요구',placeholder='공차·하중·후처리 등',key=f'notes_{process}',persist_state='session')
    return dict(slicer=slicer,minimum_wall_mm=wall,minimum_hole_mm=hole,build_volume_mm=dims if use_build else None,
                layer_height_mm=layer,line_width_mm=line,clearance_mm=clearance,
                threshold_basis=st.session_state[f'basis_{process}'],process_notes=notes)
