"""Independent checks of what a novice is actually shown, not new geometry rules."""
from copy import deepcopy
from pathlib import Path
import json
import re

import numpy as np
import pytest
import trimesh
from streamlit.testing.v1 import AppTest

from amdfm.analysis import review
from amdfm.detail import attach_detail
from amdfm.detail_worker import normal_chords
from amdfm.io import load_model
from amdfm.models import json_bytes
from amdfm.presentation import model_figure, html_report
from amdfm.profiles import Profile
from amdfm.visuals import section_outline_figure, section_area_figure, section_svg, wall_samples

ROOT=Path(__file__).resolve().parents[1]


def bracket_report(limit=None):
    path=ROOT/'examples/cad/07_bracket.step'
    model=load_model(path.read_bytes(),path.name)
    report=review(model,Profile(minimum_wall_mm=limit),direction=(1,1,1))
    result=normal_chords(model.mesh,limit)
    result.update(mode='wall',fingerprint=model.fingerprint)
    return model,attach_detail(report,result)


@pytest.mark.parametrize('limit',[None,1.,5.])
def test_wall_points_do_not_paint_24_faces_as_equally_thin_and_use_recorded_transform(limit):
    model,report=bracket_report(limit)
    before=json_bytes(report)
    samples=wall_samples(report)
    assert len(samples)==24 and samples[-1]['normal_chord_mm']/samples[0]['normal_chord_mm']>9
    figure=model_figure(model,report,'wall',transparent=True,selected_sample=len(samples)-1)
    meshes=[trace for trace in figure.data if trace.type=='mesh3d']
    assert len(meshes)==1 and len(meshes[0].i)==24
    traces=[trace for trace in figure.data if trace.type=='scatter3d' and trace.name in ('측정 표본','기준 미만 표본','기준 이상 표본')]
    assert sum(len(trace.x) for trace in traces)==24
    selection=next(trace for trace in figure.data if trace.name=='선택한 표본')
    matrix=np.asarray(report['current_orientation']['transform'])
    expected=np.asarray(samples[-1]['point_mm'])@matrix[:3,:3].T+matrix[:3,3]
    assert [selection.x[0],selection.y[0],selection.z[0]]==pytest.approx(expected)
    assert '40' in selection.text[0]
    if limit==5:
        bad=next(trace for trace in traces if trace.name=='기준 미만 표본')
        good=next(trace for trace in traces if trace.name=='기준 이상 표본')
        assert bad.marker.symbol!=good.marker.symbol
        assert all(row[0]<5 for row in bad.customdata)
        assert all(row[0]>=5 for row in good.customdata)
    assert json_bytes(report)==before


def test_no_finding_does_not_make_model_invisible():
    model=load_model(trimesh.creation.box().export(file_type='stl'),'box.stl')
    report=review(model,Profile())
    figure=model_figure(model,report,'missing-finding',transparent=True,build_plate=True)
    assert figure.data[0].opacity==1
    plane=next(t for t in figure.data if t.name=='가상 바닥 · Z=0')
    assert list(plane.z)==[0,0,0,0]


def rows():
    return [dict(z_mm=z,area_mm2=a,complete=True,symmetric_change_from_previous_mm2=None if i==0 else 10,
                 outlines=[[[-20,-15],[20,-15],[20,15],[-20,15],[-20,-15]]])
            for i,(z,a) in enumerate([(1,1200),(3,1200),(12,120),(32,120)])]


def test_section_equal_scale_does_not_expand_x_range_to_empty_canvas():
    data=rows()
    figure=section_outline_figure(data,2)
    assert list(figure.layout.xaxis.range)==pytest.approx([-22.4,22.4])
    assert figure.layout.xaxis.constrain=='domain' and figure.layout.yaxis.scaleanchor=='x'
    assert figure.data[0].x==tuple(p[0] for p in data[1]['outlines'][0])
    assert 'polyline' in section_svg(data,2)


def test_section_choice_has_non_color_cues_and_does_not_bridge_unmeasured_rows():
    data=rows()
    data[1].update(complete=False,area_mm2=None)
    data[2]['symmetric_change_from_previous_mm2']=None
    figure=section_area_figure(data,2)
    assert all(trace.mode=='markers' for trace in figure.data)
    assert not any(trace.name=='이전 단면' for trace in figure.data)
    assert not any(3 in trace.x for trace in figure.data)
    selected=next(t for t in figure.data if t.name=='현재 단면')
    others=next(t for t in figure.data if t.name=='다른 단면')
    assert selected.marker.symbol!=others.marker.symbol and selected.marker.size>others.marker.size
    data[2].update(complete=False,area_mm2=None)
    figure=section_area_figure(data,2)
    assert not any(trace.name=='현재 단면' for trace in figure.data)
    assert all(0 not in trace.y for trace in figure.data)


def test_illustrated_report_keeps_json_separate_without_losing_partial_status():
    model,report=bracket_report()
    detail=dict(mode='sections',fingerprint=model.fingerprint,sampling='uniform',status='partial',
                rows=rows(),sample_count=5,complete_samples=4,requested_samples=5,reason='한 단면 미확정')
    report=attach_detail(report,detail)
    report.setdefault('details',{})['layers']={'status':'unknown','reason':'미실행 대조용','raw_payload':'x'*500000}
    before=json_bytes(report)
    document=html_report(report,model).decode()
    assert document.count('<svg')>=2 and '한 단면 미확정' in document
    assert 'AM-DFM_review.json' in document and 'x'*1000 not in document
    assert len(document)<100000 and sum(len(s) for s in re.findall(r'<pre>(.*?)</pre>',document,re.S))<10000
    assert json_bytes(report)==before
    wrong=load_model(trimesh.creation.box().export(file_type='stl'),'other.stl')
    with pytest.raises(ValueError): html_report(report,wrong)


def test_orientation_default_numbers_manual_choice_and_apply_are_distinct():
    app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=60).run()
    app.button(key='start_from_model').click().run()
    app.segmented_control(key='result_tab').set_value('방향 비교').run()
    assert not app.exception
    assert app.selectbox(key='orientation_choice').value=='+Y'
    assert app.metric[0].value=='30 mm'
    assert app.session_state['report']['current_orientation']['direction']==[0,0,1]
    assert len(app.get('plotly_chart'))==2
    app.selectbox(key='orientation_choice').set_value('+Z').run()
    app.run()
    assert app.selectbox(key='orientation_choice').value=='+Z'
    assert all(metric.delta=='' for metric in app.metric)
    app.button(key='select_ranked_direction').click().run()
    assert app.selectbox(key='orientation_choice').value=='+Y'
    app.button(key='apply_orientation').click().run()
    assert not app.exception and app.session_state['report']['current_orientation']['direction']==[0,1,0]
