"""Public demos and added machines are usable through the normal input flow."""
from pathlib import Path
from streamlit.testing.v1 import AppTest

ROOT=Path(__file__).resolve().parents[1]

def test_public_demo_and_added_equipment_share_normal_review_inputs():
    app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=90).run()
    app.selectbox(key='source').select('공개 STEP 시연').run()
    assert not app.exception and not app.error
    assert len(app.selectbox(key='public_demo').options)==14
    assert any('브래킷' in x for x in app.selectbox(key='public_demo').options)
    app.selectbox(key='machine_MEX').select('Bambu Lab A1 mini').run()
    assert not app.exception and not app.error
    assert app.number_input(key='build_X_MEX').value==180
    assert app.number_input(key='build_Y_MEX').value==180
    assert app.number_input(key='build_Z_MEX').value==180
    assert app.checkbox(key='use_build_MEX').value is False
    app.selectbox(key='manufacturing_family').select('절삭가공').run()
    assert not app.exception and not app.error
    assert 'Tormach 1100M' in app.selectbox(key='cnc_machine').options
