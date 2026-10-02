"""One purpose-based, Korean-labelled picker; original CAD bytes stay intact."""
from pathlib import Path
import hashlib
import json

INPUTS = ('적층 시연용 형상', '절삭 시연용 형상', '업로드')
FORMATS = {'.step', '.stp', '.stl', '.3mf'}
CORPUS_NAMES = {
    '11.1 Mesh_Arm_2.stp': '연결 암', '12.1 Bracket.stp': '장착 브래킷',
    '13.1 Submodelv150.stp': '복합 부품', '2.1 Cap_fillets.stp': '둥근 모서리 덮개',
    '3.1 Gear_Set_2D.stp': '기어 세트', '3.3 Bolt_Plates.stp': '볼트 체결 판',
    '3.4 Valve_RM_20130113.stp': '밸브', '4.2 assembly_solid.stp': '조립 부품',
    '7.1 Pump_assy_3.stp': '펌프 조립체', '7.2 Flange Mount.stp': '플랜지 마운트',
    '8.1 Machine_Frame.stp': '기계 프레임', '9.1 Pump_housing.stp': '펌프 하우징',
    'Arduino-UNO.stl': '아두이노 기판', 'Arduino-UNO.stp': '아두이노 기판',
    'build_tray_v3.step': '제작 트레이', 'Raspberry Pi 4 Model B.step': '라즈베리파이 기판',
    'Raspberry Pi 4 Model B.stl': '라즈베리파이 기판', 'SG90-Servo.stl': '소형 서보 모터',
    'SG90-Servo.stp': '소형 서보 모터',
    'the-over-engineered-backpack-wall-mount-v2.3mf': '가방 벽걸이',
    'the-over-engineered-backpack-wall-mount-v2.stl': '가방 벽걸이',
    'flange_h204-6_3-uf31-225-ga65.stp': '산업용 플랜지',
    'cooling_fan_uf21-h204-6_3.stp': '냉각 팬', 'gearbox_b204hs_a-6_3.stp': '기어박스',
    'E_00300_010_A.stp': '산업용 부품 1', '900-602.stp': '산업용 부품 2',
}


def demo_catalog(root, family):
    root = Path(root)
    rows = []
    def add(path, title, metadata=None):
        if path.is_file() and path.suffix.lower() in FORMATS:
            rows.append(dict(path=path, title=title, metadata=metadata or {}))
    def manifest(folder):
        path = root/folder/'manifest.json'
        return json.loads(path.read_text(encoding='utf8')) if path.exists() else []
    if family == '적층제조':
        for item in manifest('examples/cad'):
            title = item['title'].replace('inch 선언 STEP · 실제', '인치 단위 정육면체 · 한 변')
            add(root/'examples/cad'/item['file'], title, item)
    else:
        for item in manifest('examples/machining'):
            add(root/'examples/machining'/item['file'], item['title'], item)
        labels = {'triangular_pocket': '삼각 포켓', 'rectangular_pocket': '직사각 포켓', '6sides_pocket': '육각 포켓'}
        for item in manifest('examples/learning_validation/corner_edits'):
            title = labels[item['feature']]+(' · 수정 전' if item['phase'] == 'before' else ' · 코너 반경 1 mm 수정 후')
            add(root/'examples/learning_validation/corner_edits'/item['file'], title, item)
        for file, title in (('three_pockets_before.step', '3개 포켓 · 수정 전'),
                            ('three_pockets_after.step', '3개 포켓 · 부위별 코너 수정 후')):
            add(root/'examples/learning_validation/compound_edits'/file, title)
        for item in manifest('examples/learning_validation/hole_review'):
            add(root/'examples/learning_validation/hole_review'/item['file'], item['title'], item)
    for item in manifest('examples/public_demo'):
        if family == '절삭가공' and (item.get('cad_geometry_kind') != 'solid' or item['dataset'] == 'NIST'):
            continue
        title = item['title'].replace(' · CadQuarry', ' · 공개 예제').replace('NIST', '미국 표준기술연구소')
        add(root/'examples/public_demo'/item['file'], title, item)
    for path in sorted((root/'examples/corpus').rglob('*')):
        if family == '절삭가공' and path.suffix.lower() not in ('.step', '.stp'):
            continue
        if path.suffix.lower() in FORMATS:
            title = CORPUS_NAMES.get(path.name, '검토 부품')+' · '+path.suffix[1:].upper()
            add(path, title)
    if family == '적층제조':
        titles = {'3DP_20546_S-0039.stl': '공개 부품 · 메시 예제',
                  'strong_corner_bracket_vcd.stl': '보강 코너 브래킷',
                  'strong_garden_tool_hook_vcd.stl': '원예 도구 걸이'}
        for file, title in titles.items():
            add(root/'examples/external'/file, title)
    # Identical bytes appear once in each purpose; duplicate titles are made
    # distinct without exposing the old English paths as another submenu.
    output, seen, titles = [], set(), {}
    for row in rows:
        sha = hashlib.sha256(row['path'].read_bytes()).hexdigest()
        if sha in seen:
            continue
        seen.add(sha)
        title = row['title']; titles[title] = titles.get(title, 0)+1
        if titles[title] > 1:
            row['title'] += f" · {titles[title]}"
        row['sha256'] = sha
        row['download_name'] = row['title'].replace(' · ', '_').replace('/', '_')+row['path'].suffix.lower()
        output.append(row)
    return output


def family_changed():
    import streamlit as st
    if st.session_state.get('source') != '업로드':
        st.session_state['source'] = INPUTS[0 if st.session_state['manufacturing_family'] == '적층제조' else 1]
        st.session_state.pop('demo_example', None)


def source_changed():
    import streamlit as st
    source = st.session_state['source']
    if source != '업로드':
        st.session_state['manufacturing_family'] = '적층제조' if source == INPUTS[0] else '절삭가공'
    st.session_state.pop('demo_example', None)


def render_input(root):
    import streamlit as st
    family = st.session_state['manufacturing_family']
    if st.session_state.get('source') not in INPUTS:
        st.session_state['source'] = INPUTS[0 if family == '적층제조' else 1]
    source = st.selectbox('입력', INPUTS, key='source', on_change=source_changed)
    if source == '업로드':
        uploaded = st.file_uploader('STEP 파일 업로드' if family == '절삭가공' else 'STEP · STL · 3MF 업로드',
            type=['step', 'stp'] if family == '절삭가공' else ['step', 'stp', 'stl', '3mf'], key='model_upload')
        return (uploaded.getvalue(), uploaded.name) if uploaded is not None else (None, None)
    rows = demo_catalog(root, family)
    choices = {row['title']: row for row in rows}
    default = '브래킷 · 두께 4 mm' if family == '적층제조' else '직사각 포켓 · 20×12 / 깊이 8 mm'
    if st.session_state.get('demo_example') not in choices:
        st.session_state['demo_example'] = default if default in choices else next(iter(choices), None)
    if not choices:
        st.info('시연용 형상이 없습니다. 파일을 업로드하세요.')
        return None, None
    title = st.selectbox('형상 선택', list(choices), key='demo_example')
    row = choices[title]; data = row['path'].read_bytes(); name = row['download_name']
    st.download_button('형상 다운로드', data, file_name=name, key='demo_download')
    item = row['metadata']
    if item.get('source_url'):
        with st.expander('형상 출처'):
            st.markdown(f"[{item.get('dataset', '공개 자료')}]({item['source_url']})")
            st.caption(item.get('license', ''))
    return data, name
