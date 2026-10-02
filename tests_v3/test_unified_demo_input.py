import hashlib
import re
from pathlib import Path
from streamlit.testing.v1 import AppTest
from dfm.demo_catalog import demo_catalog, INPUTS

ROOT=Path(__file__).resolve().parents[1]


def test_purpose_catalog_has_korean_titles_real_files_and_no_byte_duplicates():
    for family in ('적층제조','절삭가공'):
        rows=demo_catalog(ROOT,family)
        assert len(rows)>30
        assert len({r['title'] for r in rows})==len(rows)
        assert len({r['sha256'] for r in rows})==len(rows)
        for row in rows:
            assert re.search('[가-힣]',row['title'])
            assert not re.search(r'CadQuarry|bracket|cavity|plate|Mesh_Arm|inch|Raspberry|SG90',row['title'])
            assert hashlib.sha256(row['path'].read_bytes()).hexdigest()==row['sha256']
            assert row['download_name'].endswith(row['path'].suffix.lower())
        if family=='절삭가공':assert all(r['path'].suffix.lower() in ('.step','.stp') for r in rows)


def test_three_inputs_synchronize_process_and_keep_upload_selection():
    app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=90).run()
    assert not app.exception and app.selectbox(key='source').options==list(INPUTS)
    assert app.selectbox(key='demo_example').value=='브래킷 · 두께 4 mm'
    app.selectbox(key='source').select('절삭 시연용 형상').run()
    assert not app.exception and app.selectbox(key='manufacturing_family').value=='절삭가공'
    assert '3개 포켓 · 수정 전' in app.selectbox(key='demo_example').options
    app.selectbox(key='manufacturing_family').select('적층제조').run()
    assert not app.exception and app.selectbox(key='source').value=='적층 시연용 형상'
    app.selectbox(key='source').select('업로드').run()
    assert not app.exception and len(app.get('file_uploader'))==1
    app.selectbox(key='manufacturing_family').select('절삭가공').run()
    assert not app.exception and app.selectbox(key='source').value=='업로드'


def test_previous_source_value_migrates_to_a_valid_purpose():
    app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=90)
    app.session_state['source']='CAD 기준형상'
    app.run()
    assert not app.exception and app.selectbox(key='source').value=='적층 시연용 형상'
