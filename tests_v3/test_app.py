from pathlib import Path
import json
import pytest
from streamlit.testing.v1 import AppTest

APP=Path(__file__).resolve().parents[1]/"app.py"


def test_complete_design_workflow_and_stale_results():
    app=AppTest.from_file(str(APP),default_timeout=45).run()
    assert not app.exception
    app.button[0].click().run()
    assert not app.exception
    assert app.metric
    app.segmented_control(key="result_tab").set_value("방향 비교").run()
    assert not app.exception
    app.selectbox(key="orientation_choice").select("+Y").run()
    app.button(key="apply_orientation").click().run()
    assert not app.exception
    assert app.selectbox(key="build_direction").value=="+Y"
    assert app.session_state["report"]["current_orientation"]["direction"]==[0.,1.,0.]
    app.segmented_control(key="result_tab").set_value("근거·내보내기").run()
    assert not app.exception
    assert len(app.get("download_button"))==4
    app.selectbox(key="process").select("VPP").run()
    assert not app.exception
    assert len(app.get("download_button"))==0


def test_wall_review_stays_attached_and_exportable():
    app=AppTest.from_file(str(APP),default_timeout=60).run()
    app.button[0].click().run()
    app.segmented_control(key="result_tab").set_value("정밀 검토").run()
    app.button(key="run_wall").click().run()
    assert not app.exception
    assert "wall" in app.session_state["report"]["details"]
    app.segmented_control(key="result_tab").set_value("근거·내보내기").run()
    assert len(app.get("download_button"))==4


def test_design_comparison_and_cura_example_workflow():
    manifest=json.loads((APP.parent/"examples/cad/manifest.json").read_text(encoding="utf-8"))
    names={c["id"]:c["title"] for c in manifest}
    app=AppTest.from_file(str(APP),default_timeout=60).run()
    app.selectbox(key="cad_example").select(names["02_thin_plate"]).run()
    app.button[0].click().run()
    app.segmented_control(key="result_tab").set_value("수정 전후").run()
    app.button(key="save_baseline").click().run()
    app.selectbox(key="cad_example").select(names["14_thin_plate_improved"]).run()
    app.button[0].click().run()
    app.segmented_control(key="result_tab").set_value("수정 전후").run()
    assert not app.exception
    assert app.session_state["comparison_baseline"]["model_fingerprint"]!=app.session_state["report"]["model_fingerprint"]
    table=app.dataframe[0].value
    assert table.loc[table["항목"]=="CAD 체적 (mm³)","차이"].iloc[0]==pytest.approx(540,abs=1e-8)
    app.segmented_control(key="result_tab").set_value("정밀 검토").run()
    app.selectbox(key="gcode_source").select("Cura 기준 실험").run()
    path=APP.parent/"validation/v3/cura-experiment-02/rib_0.3/toolpaths.gcode"
    app.selectbox(key="gcode_example").select(path).run()
    assert not app.exception and not app.error
    assert app.select_slider(key="gcode_z").value==.2
    assert len(app.get("download_button"))==1
