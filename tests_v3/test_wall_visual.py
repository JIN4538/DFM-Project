"""Geometry-grounded regression tests for the wall location and close-up views."""
from copy import deepcopy
import json
from pathlib import Path

import numpy as np
import pytest
import trimesh
from streamlit.testing.v1 import AppTest

from amdfm.analysis import review
from amdfm.detail import attach_detail
from amdfm.detail_worker import normal_chords
from amdfm.io import load_model
from amdfm.models import Model, json_bytes
from amdfm.profiles import Profile
from amdfm.visuals import wall_samples
from amdfm.wall_visual import wall_context_figure, wall_measurement_figure, wall_sample_geometry, wall_report_svg

ROOT = Path(__file__).resolve().parents[1]


def measured(model, limit=1.2, direction=(0, 0, 1)):
    report = review(model, Profile(minimum_wall_mm=limit), direction=direction)
    detail = normal_chords(model.mesh, limit)
    detail.update(mode='wall', fingerprint=model.fingerprint)
    return attach_detail(report, detail)


@pytest.fixture
def plate():
    model = Model(trimesh.creation.box(extents=[40, 30, .3]), {})
    return model, measured(model)


def test_thin_plate_is_framed_by_part_not_build_arrow_and_normals_are_hidden(plate):
    model, report = plate
    fig = wall_context_figure(model, report)
    assert not any(trace.type == 'cone' for trace in fig.data)
    assert not any(trace.name == '나머지 측정 위치' for trace in fig.data)
    assert len([trace for trace in fig.data if trace.type == 'mesh3d']) == 1
    assert list(fig.layout.scene.zaxis.range) == pytest.approx([-.6, .9])
    assert fig.layout.scene.aspectmode == 'manual'
    spans = np.array([fig.layout.scene[f'{axis}axis'].range[1]-fig.layout.scene[f'{axis}axis'].range[0]
                      for axis in 'xyz'])
    ratios = np.array([fig.layout.scene.aspectratio[axis] for axis in 'xyz'])
    assert ratios.max() == pytest.approx(1.)
    # Every millimetre keeps the same display scale on all axes.
    assert ratios / spans == pytest.approx(np.repeat(1./spans.max(), 3))
    selected = next(trace for trace in fig.data if trace.name == '선택 위치 ◆')
    assert selected.marker.size <= 6 and selected.text == ('위치 1',)
    assert next(trace for trace in fig.data if trace.name == '기준 미만 위치').marker.symbol != selected.marker.symbol
    all_fig = wall_context_figure(model, report, show_all=True)
    normal = next(trace for trace in all_fig.data if trace.name == '나머지 측정 위치')
    assert normal.marker.size < selected.marker.size


def test_plate_closeup_is_actual_point_three_mm_and_equal_scale(plate):
    model, report = plate
    before = json_bytes(report)
    fig = wall_measurement_figure(model, report)
    ray = next(trace for trace in fig.data if trace.name == '선택 위치 측정선')
    assert list(ray.y) == pytest.approx([0, .3])
    assert fig.layout.yaxis.scaleanchor == 'x' and fig.layout.yaxis.scaleratio == 1
    assert list(fig.layout.yaxis.range) == pytest.approx([-.105, .405])
    assert any('0.3 mm' in annotation.text for annotation in fig.layout.annotations)
    # A real cut of a plate has parallel surfaces at the measured endpoints.
    contour = next(trace for trace in fig.data if trace.name == '실제 단면 윤곽')
    assert set(round(y, 6) for y in contour.y if y is not None and np.isfinite(y)) == {0., .3}
    endpoints = np.asarray([fig.layout.meta['source_point_mm'], fig.layout.meta['target_point_mm']])
    assert np.linalg.norm(endpoints[1]-endpoints[0]) == pytest.approx(.3)
    assert json_bytes(report) == before


def test_rotated_translated_placement_transforms_both_ray_endpoints(plate):
    model, report = plate
    matrix = trimesh.transformations.rotation_matrix(.73, [1, 2, 3])
    matrix[:3, 3] = [42., -71., 13.]
    report['current_orientation']['transform'] = matrix.tolist()
    geometry = wall_sample_geometry(model, report)
    expected = np.asarray([geometry['point'], geometry['endpoint']])@matrix[:3, :3].T+matrix[:3, 3]
    fig = wall_context_figure(model, report)
    ray = next(trace for trace in fig.data if trace.name == '측정선')
    assert np.column_stack((ray.x, ray.y, ray.z)) == pytest.approx(expected)
    vertices = model.mesh.vertices@matrix[:3, :3].T+matrix[:3, 3]
    for axis, dim in zip('xyz', range(3)):
        bounds = fig.layout.scene[f'{axis}axis'].range
        assert bounds[0] < vertices[:, dim].min() <= vertices[:, dim].max() < bounds[1]
    local = wall_measurement_figure(model, report)
    assert list(next(t for t in local.data if t.name == '선택 위치 측정선').y) == pytest.approx([0, .3])


def test_four_mm_bracket_preserves_distinct_thicker_rays_and_original_faces():
    path = ROOT/'examples/cad/07_bracket.step'
    model = load_model(path.read_bytes(), path.name)
    report = measured(model, limit=5, direction=(1, 1, 1))
    samples = wall_samples(report)
    for selected, expected in [(0, 4), (len(samples)-1, 40)]:
        fig = wall_measurement_figure(model, report, selected_sample=selected)
        assert fig is not None
        assert fig.layout.meta['source_face'] == samples[selected]['source_face']
        ray = next(t for t in fig.data if t.name == '선택 위치 측정선')
        assert list(ray.y) == pytest.approx([0, expected])
    assert len([t for t in wall_context_figure(model, report).data if t.type == 'mesh3d']) == 1


@pytest.mark.parametrize('fault', ['outside_source', 'outside_target', 'missing_target', 'invalid_face'])
def test_corrupt_or_legacy_endpoint_never_creates_a_false_thickness_diagram(plate, fault):
    model, report = plate
    report = deepcopy(report)
    sample = deepcopy(wall_samples(report)[0])
    if fault == 'outside_source': sample['point_mm'] = [1e9, 2e9, 3e9]
    if fault == 'outside_target': sample['normal_chord_mm'] = 1e9
    if fault == 'missing_target': sample.pop('target_face')
    if fault == 'invalid_face': sample['source_face'] = -1
    report['details']['wall']['measurements']['samples'] = [sample]
    assert wall_measurement_figure(model, report) is None
    context = wall_context_figure(model, report)
    assert not any(trace.name == '측정선' for trace in context.data)
    assert max(context.layout.scene.zaxis.range) < 1
    if fault in ('outside_source', 'invalid_face'):
        assert not any(trace.name == '선택 위치 ◆' for trace in context.data)


def test_no_samples_does_not_claim_a_local_diagram(plate):
    model, report = plate
    report['details']['wall']['measurements']['samples'] = []
    assert wall_measurement_figure(model, report) is None
    assert wall_sample_geometry(model, report) is None
    assert len(wall_context_figure(model, report).data) == 1


def test_wall_view_defaults_to_location_and_magnified_measurement():
    script = '''
import streamlit as st
import trimesh
from amdfm.models import Model
from amdfm.detail_worker import normal_chords
from amdfm.detail_view import render_wall_result
model = Model(trimesh.creation.box(extents=[40,30,.3]), {})
report = dict(model_fingerprint=model.fingerprint, profile=dict(minimum_wall_mm=1.2,threshold_basis='시험 기준'),
    details=dict(wall=normal_chords(model.mesh,1.2)), findings=[],
    current_orientation=dict(transform=[[1.,0.,0.,0.],[0.,1.,0.,0.],[0.,0.,1.,.15],[0.,0.,0.,1.]]))
render_wall_result(model,report)
'''
    app = AppTest.from_string(script, default_timeout=30).run()
    assert not app.exception
    assert len(app.get('plotly_chart')) == 2
    assert app.toggle(key='wall_show_all_samples').value is False
    assert '기준 미만' in app.selectbox(key='wall_sample').options[0]
    app.selectbox(key='wall_sample').set_value(11).run()
    assert not app.exception
    zoom = json.loads(app.get('plotly_chart')[1].proto.spec)
    assert zoom['layout']['meta']['equal_scale'] is True
    assert any('40 mm' in annotation['text'] for annotation in zoom['layout']['annotations'])


def test_offline_report_contains_numbered_location_and_exact_local_section(plate):
    import re
    import xml.etree.ElementTree as ET
    from amdfm.presentation import html_report

    model = load_model(plate[0].mesh.export(file_type='stl'), 'thin_plate.stl')
    report = measured(model)
    before = json_bytes(report)
    document = html_report(report, model).decode('utf-8')
    assert '가장 얇게 측정한 위치와 확대 단면' in document
    wall_card = document.split("<section id='check-wall'>", 1)[1].split('</section>', 1)[0]
    figures = re.findall(r'(<svg.*?</svg>)', wall_card, re.S)
    assert len(figures) == 2
    context, detail = [ET.fromstring(figure) for figure in figures]
    assert '부품에서의 위치 1' in context.attrib['aria-label']
    assert '0.3 mm' in detail.attrib['aria-label'] and '동일 배율' in detail.attrib['aria-label']
    ray = next(element for element in detail.iter() if 'data-measurement-mm' in element.attrib)
    assert float(ray.attrib['data-measurement-mm']) == pytest.approx(.3)
    assert 'plotly.js' not in document and '<script src' not in document
    assert json_bytes(report) == before


def test_offline_report_does_not_draw_unverified_endpoint(plate):
    model, report = plate
    report = deepcopy(report)
    for sample in report['details']['wall']['measurements']['samples']:
        sample.pop('target_face')
    document = wall_report_svg(model, report)
    assert document.count('<svg') == 1
    assert '반대 면 좌표를 확인할 수 없어' in document
    assert 'data-measurement-mm' not in document
