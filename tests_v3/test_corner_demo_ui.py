"""A first-time user can select a reference, review, and obtain actual CAD."""
from pathlib import Path
from streamlit.testing.v1 import AppTest

def test_reference_corner_edit_is_reachable_from_normal_review():
    root=Path(__file__).resolve().parents[1]
    app=AppTest.from_file(str(root/'app.py'),default_timeout=90).run()
    app.selectbox(key='manufacturing_family').select('절삭가공').run()
    app.selectbox(key='source').select('절삭 검증 형상').run()
    app.selectbox(key='cnc_example').select('삼각 포켓 · 수정 전').run()
    assert not app.exception and not app.error
    next(b for b in app.button if b.label=='절삭 설계 검토').click().run()
    assert not app.exception and not app.error
    preview=next(b for b in app.button if b.label=='개선 형상 보기 · 코너 수정')
    preview.click().run()
    assert not app.exception and not app.error
    assert 'cnc_edit_preview_result' in app.session_state
    modified,audit=app.session_state['cnc_edit_preview_result']
    assert modified.startswith(b'ISO-10303-21;')
    assert audit['modified_corner_edges']==3
    assert len(audit['rounded_face_ids'])==3
    assert any('수정 후 · 둥근 반경' in row.value for row in app.markdown)
    assert not any(b.key=='cnc_create_edit_preview' for b in app.button)
