from pathlib import Path
import json
import pytest
import numpy as np
from streamlit.testing.v1 import AppTest

APP=Path(__file__).resolve().parents[1]/"app.py"


def test_initial_wall_is_bounded_and_manual_retry_gets_full_budget(monkeypatch):
    import amdfm.detail as detail_module
    calls=[]
    def fake(model,profile,direction,*,mode='wall',timeout_s=60,**kwargs):
        calls.append(timeout_s)
        return dict(mode=mode,fingerprint=model.fingerprint,status='unknown',
                    reason='계산 시간 한도 확인용',profile=profile.to_dict())
    monkeypatch.setattr(detail_module,'run_detail',fake)
    app=AppTest.from_file(str(APP),default_timeout=60).run()
    app.text_input(key='machine_MEX').set_value('initial-wall-budget-test').run()
    app.button[0].click().run()
    assert calls==[5]
    result=app.session_state['report']['details']['wall']
    assert result['status']=='unknown' and result['execution_trigger']=='initial_review'
    app.segmented_control(key='result_tab').set_value('정밀 검토').run()
    assert any('자동 벽 확인' in w.value for w in app.warning)
    app.button(key='run_wall').click().run()
    assert calls==[5,60] and not app.exception
    app.checkbox(key='initial_wall').uncheck().run()
    next(button for button in app.button if button.label=='설계 검토').click().run()
    assert calls==[5,60] and not app.session_state['report'].get('details')


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
    app.checkbox(key='show_gcode_practice').check().run()
    path=APP.parent/"validation/v3/cura-experiment-02/rib_0.3/toolpaths.gcode"
    app.selectbox(key="gcode_example").select(path).run()
    assert not app.exception and not app.error
    assert app.select_slider(key="gcode_z").value==.2
    assert len(app.get("download_button"))==2  # G-code JSON and optional calibration record template


def test_custom_direction_comparison_application_and_stale_exports():
    app=AppTest.from_file(str(APP),default_timeout=60).run()
    assert len(app.selectbox(key="build_direction").options)>=27
    app.selectbox(key="build_direction").select("직접 각도 입력").run()
    app.number_input(key="build_tilt").set_value(30.).run()
    app.number_input(key="build_azimuth").set_value(60.).run()
    app.button[0].click().run()
    assert not app.exception
    report=app.session_state["report"]
    expected=np.array([.25,np.sqrt(3)/4,np.sqrt(3)/2])
    assert report["current_orientation"]["direction"]==pytest.approx(expected,abs=1e-14)
    assert len(report["orientations"])==27
    assert report["orientation_search"]["continuous_optimum"] is False
    app.segmented_control(key="result_tab").set_value("방향 비교").run()
    app.selectbox(key="orientation_choice").select("현재 지정 방향").run()
    app.button(key="apply_orientation").click().run()
    assert not app.exception
    assert app.session_state["report"]["current_orientation"]["direction"]==pytest.approx(expected,abs=1e-14)
    assert app.number_input(key="build_tilt").value==pytest.approx(30.)
    app.segmented_control(key="result_tab").set_value("근거·내보내기").run()
    assert len(app.get("download_button"))==4
    app.number_input(key="build_tilt").set_value(35.).run()
    assert not app.exception and len(app.get("download_button"))==0
    app.button[0].click().run()
    assert app.session_state["report"]["current_orientation"]["tilt_deg"]==pytest.approx(35.)
    app.segmented_control(key="result_tab").set_value("방향 비교").run()
    app.selectbox(key="orientation_choice").select("+X+Z").run()
    app.button(key="apply_orientation").click().run()
    assert not app.exception
    assert app.selectbox(key="build_direction").value=="+X+Z"
    assert app.session_state["report"]["current_orientation"]["direction"]==pytest.approx([2**-.5,0,2**-.5])
    app.selectbox(key="build_direction").select("직접 각도 입력").run()
    assert app.number_input(key="build_tilt").value==pytest.approx(35.)
    assert app.number_input(key="build_azimuth").value==pytest.approx(60.)
    app.checkbox(key="compare_diagonals").uncheck()
    app.button[0].click().run()
    assert not app.exception
    assert len(app.session_state["report"]["orientations"])==7


@pytest.mark.parametrize("process",["VPP","PBF_POLYMER","PBF_METAL"])
def test_non_fdm_sections_work_and_exports_preserve_measurements(process):
    app=AppTest.from_file(str(APP),default_timeout=90).run()
    app.selectbox(key="process").select(process).run()
    app.button[0].click().run()
    app.segmented_control(key="result_tab").set_value("정밀 검토").run()
    app.segmented_control(key="detail_focus").set_value("층간").run()
    assert app.button(key="run_layers").disabled
    app.segmented_control(key="detail_focus").set_value("단면").run()
    assert all(n.key!="line_width" for n in app.number_input)
    app.selectbox(key="section_method").select("균등 간격 · 높이별 비교").run()
    app.number_input(key="section_samples").set_value(8).run()
    app.button(key="run_sections").click().run()
    assert not app.exception
    report=app.session_state["report"]
    assert report["profile"]["build_volume_mm"] is None
    assert report["details"]["sections"]["complete_samples"]==8
    assert next(f for f in report["findings"] if f["id"]=="sections")["status"]=="observed"
    app.segmented_control(key="result_tab").set_value("근거·내보내기").run()
    assert not app.exception and len(app.get("download_button"))==4


def test_event_section_default_and_switch_keep_result_method_visible():
    app=AppTest.from_file(str(APP),default_timeout=90).run()
    app.selectbox(key="process").select("VPP").run()
    app.button[0].click().run()
    app.segmented_control(key="result_tab").set_value("정밀 검토").run()
    app.segmented_control(key="detail_focus").set_value("단면").run()
    assert app.selectbox(key="section_method").value.startswith("자동")
    app.button(key="run_sections").click().run()
    assert not app.exception
    result=app.session_state["report"]["details"]["sections"]
    assert result["sampling"]=="events"
    assert result['requested_sampling']=='auto' and result['fallback_performed'] is False
    assert result["status"] in ("complete","partial")
    app.selectbox(key="section_method").select("균등 간격 · 높이별 비교").run()
    assert app.session_state["report"]["details"]["sections"]["sampling"]=="events"
    assert any("형상 변화 기준 결과" in element.value for element in app.caption)
    assert any("이전 설정으로 계산한 결과" in element.value for element in app.info)


def test_inline_wall_criterion_recomputes_and_does_not_reuse_old_profile():
    app=AppTest.from_file(str(APP),default_timeout=90).run()
    app.button(key='start_from_model').click().run()
    app.segmented_control(key='result_tab').set_value('정밀 검토').run()
    app.button(key='run_wall').click().run()
    assert any('벽은 측정됐지만 비교 기준이 없습니다' in x.value for x in app.info)
    app.number_input(key='quick_wall_limit_MEX').set_value(1.).run()
    app.button(key='apply_wall_criterion').click().run()
    assert not app.exception
    report=app.session_state['report']
    assert report['profile']['minimum_wall_mm']==1.
    assert report['details']['wall']['profile']==report['profile']
    assert any('입력한 벽 기준 미만이 없습니다' in x.value for x in app.success)
    app.number_input(key='quick_wall_limit_MEX').set_value(5.).run()
    app.button(key='apply_wall_criterion').click().run()
    assert not app.exception
    report=app.session_state['report']
    assert report['profile']['minimum_wall_mm']==5.
    assert report['details']['wall']['measurements']['below_limit_face_indices']
    assert any('입력한 벽 기준보다 작은 구간' in x.value for x in app.warning)
    app.selectbox(key='process').select('VPP').run()
    app.button[0].click().run()
    assert app.session_state['report']['profile']['minimum_wall_mm'] is None
    fresh=app.session_state['report'].get('details',{})
    assert not ({'sections','layers'} & set(fresh))
    if 'wall' in fresh:
        assert fresh['wall']['profile']==app.session_state['report']['profile']
        assert fresh['wall']['profile']['minimum_wall_mm'] is None


def test_next_action_reaches_wall_and_zero_layers_have_no_flat_chart():
    app=AppTest.from_file(str(APP),default_timeout=90).run()
    app.selectbox(key='cad_example').select('직육면체 · 10×20×30 mm').run()
    app.button[0].click().run()
    app.button(key='next_review_action').click().run()
    assert not app.exception
    assert app.segmented_control(key='result_tab').value=='정밀 검토'
    assert app.segmented_control(key='detail_focus').value=='벽'
    app.segmented_control(key='detail_focus').set_value('층간').run()
    app.button(key='run_layers').click().run()
    assert not app.exception
    assert any('150개 층' in x.value and '후보' in x.value for x in app.success)
    assert len(app.get('arrow_vega_lite_chart'))==0
    assert len(app.get('plotly_chart'))==0
    assert app.dataframe[0].value['층'].iloc[0]==1
    app.segmented_control(key='result_tab').set_value('근거·내보내기').run()
    assert len(app.get('download_button'))==4
