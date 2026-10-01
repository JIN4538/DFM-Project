"""A novice sees one conclusion and requests evidence without an API.

Real STEP and detail workers exercise the useful path. Only the explicit worker
timeout case is substituted, so a missing calculation cannot become a pass.
"""
from copy import deepcopy
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import amdfm.detail as detail_module
import dfm.advisor_view as advisor_view
from amdfm.orientation import measure_orientation
from amdfm.presentation import html_report


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_external_ai(monkeypatch):
    monkeypatch.setattr(advisor_view, '_key', lambda: '')

    def forbidden(*args, **kwargs):
        pytest.fail('Local geometry review must not request an external AI')

    monkeypatch.setattr(advisor_view, 'parse_intent', forbidden)


def open_app():
    app = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=100).run()
    assert not app.exception
    return app


def run_review(app):
    next(button for button in app.button if button.label == '설계 검토').click().run()
    assert not app.exception
    return app.session_state['report']


def item(report, finding_id):
    return next(x for x in report['learned_review']['items'] if x['finding_id'] == finding_id)


def visible_text(block):
    """Exclude closed methodology blocks, as the user sees the default screen."""
    parts = []
    for child in block.children.values():
        if child.type == 'expander' and not child.proto.expanded:
            parts.append(child.label)
            continue
        if hasattr(child, 'children'):
            parts.extend(visible_text(child))
        else:
            value = getattr(child, 'value', '')
            if isinstance(value, str):
                parts.append(value)
    return parts


def test_optional_external_helper_is_closed_and_local_wall_card_is_actionable():
    app = open_app()
    optional = next(x for x in app.expander if x.label == '외부 문장 입력 도우미 (선택)')
    assert optional.proto.expanded is False
    assert app.button(key='advisor_interpret').disabled
    assert 'AI 미연결' not in '\n'.join(visible_text(app.main))

    app.selectbox(key='cad_example').select('얇은 판 · 두께 0.3 mm').run()
    app.number_input(key='wall_limit_MEX').set_value(1.)
    report = run_review(app)
    wall = item(report, 'wall')
    assert report['details']['wall']['measurements']['minimum_mm'] == pytest.approx(.3)
    assert wall['state'] == 'confirmed'
    assert wall['origin'] == 'learned_verified'
    assert wall['predicted_issue'] is True
    assert wall['model_action_ids'] == ['thicken_wall']
    assert '1' in wall['action'] and '보강' in wall['action']
    assert report['learned_review']['model']['sha256']
    assert app.session_state['highlight_finding'] == 'wall'
    assert not any(widget.key == 'highlight_finding' for widget in app.selectbox)
    assert not app.get('plotly_chart')
    assert sum(row.value == '종합 결론' for row in app.main.subheader) == 1
    assert app.button(key='am_learned_wall').label == '위치·측정값'
    assert not any(button.key == 'next_review_action' for button in app.button)
    assert not any(button.key == 'action_location_wall' for button in app.button)
    assert next(x for x in app.expander if x.label == '추천·학습 기록').proto.expanded is False
    assert next(x for x in app.expander if x.label == '검토 조건').proto.expanded is False
    app.button(key='am_conclusion_location').click().run()
    assert app.toggle(key='am_location_details').value is True
    assert app.selectbox(key='highlight_finding').value == 'wall'
    assert next(x for x in app.expander if x.label == '측정 방법·표본과 기준 출처').proto.expanded is False
    assert '출력 성공' not in '\n'.join(visible_text(app.main))

    app.selectbox(key='highlight_finding').select('overhang').run()
    app.button(key='am_learned_wall').click().run()
    assert not app.exception
    assert app.session_state['highlight_finding'] == 'wall'
    assert app.selectbox(key='wall_sample').value == 0
    assert app.get('plotly_chart')


def test_changed_priority_refocuses_local_conclusion_and_exports_same_analysis():
    app = open_app()
    app.selectbox(key='cad_example').select('브래킷 · 두께 4 mm').run()
    app.selectbox(key='build_direction').select('-Z').run()
    app.number_input(key='wall_limit_MEX').set_value(5.)
    before = deepcopy(run_review(app))
    assert item(before, 'wall')['state'] == 'confirmed'
    assert item(before, 'overhang')['state'] == 'confirmed'
    assert app.session_state['highlight_finding'] == 'wall'

    app.selectbox(key='advisor_priority_MEX').select('support').run()
    assert not app.segmented_control
    after = deepcopy(run_review(app))
    assert after['timestamp_utc'] == before['timestamp_utc']
    assert after['review_context']['priority'] == 'support'
    assert app.session_state['highlight_finding'] == 'overhang'
    assert after['learned_review']['model']['sha256'] == before['learned_review']['model']['sha256']
    app.toggle(key='am_location_details').set_value(True).run()
    app.selectbox(key='highlight_finding').select('wall').run()
    app.run()
    assert app.selectbox(key='highlight_finding').value == 'wall'

    app.segmented_control(key='result_tab').set_value('근거·내보내기').run()
    assert not app.exception
    exported = app.session_state['report']
    assert exported['learned_review'] == after['learned_review']
    document = html_report(exported).decode('utf-8')
    assert '종합 결론' in document and '내장 AI 검토' not in document
    assert exported['learned_review']['model']['sha256'] in document
    assert item(exported, 'wall')['action'] in document


def test_worker_timeout_stays_unknown_and_refreshes_export_without_returning_to_actions(monkeypatch):
    app = open_app()
    app.selectbox(key='cad_example').select('얇은 판 · 두께 0.3 mm').run()
    app.number_input(key='wall_limit_MEX').set_value(1.)
    before = deepcopy(run_review(app))
    assert item(before, 'wall')['state'] == 'confirmed'

    def limited(model, profile, direction, *, mode='wall', **kwargs):
        placement = measure_orientation(model.mesh, direction, profile)
        return dict(mode=mode, fingerprint=model.fingerprint, profile=profile.to_dict(),
                    direction=placement['direction'], placement_transform=placement['transform'],
                    status='unknown', reason='의도적으로 제한한 계산 시간')

    monkeypatch.setattr(detail_module, 'run_detail', limited)
    app.segmented_control(key='result_tab').set_value('정밀 검토').run()
    app.button(key='run_wall').click().run()
    assert not app.exception
    assert any('측정하지 못했습니다' in row.value for row in app.warning)
    app.segmented_control(key='result_tab').set_value('근거·내보내기').run()
    assert not app.exception
    report = app.session_state['report']
    assert report['details']['wall']['status'] == 'unknown'
    assert item(report, 'wall')['state'] == 'review'
    assert item(report, 'wall')['predicted_issue'] is None
    assert not item(report, 'wall')['action_ids']
    assert report['learned_review'] != before['learned_review']
    assert item(report, 'wall')['title'] in html_report(report).decode('utf-8')
    app.segmented_control(key='result_tab').set_value('설계 조치').run()
    app.button(key='am_learned_wall').click().run()
    assert app.selectbox(key='highlight_finding').value == 'wall'
    assert app.button(key='inline_retry_wall').label == '이 항목 추가 계산'


def invalid_shape_view():
    """Real open-surface geometry: local AI must not displace the input blocker."""
    import streamlit as st
    import trimesh
    from amdfm.action_view import render_actions
    from amdfm.analysis import review
    from amdfm.detail import run_detail
    from amdfm.io import load_model
    from amdfm.profiles import Profile
    from amdfm.recommendation import recommend_orientation

    profile = Profile()
    if 'invalid_report' not in st.session_state:
        cube = trimesh.creation.box(extents=(10, 10, 10))
        opened = trimesh.Trimesh(vertices=cube.vertices, faces=cube.faces[:-1], process=False)
        model = load_model(opened.export(file_type='stl'), 'open_box.stl', dimensions_confirmed=True)
        st.session_state['invalid_model'] = model
        st.session_state['invalid_report'] = review(model, profile, compare=False)
    model = st.session_state['invalid_model']
    report = st.session_state['invalid_report']
    render_actions(model, report, profile, recommend_orientation(report),
                   on_apply=lambda *args: None, presets={'+Z': (0, 0, 1)},
                   on_navigate=lambda *args: None, criterion_controls=None, detail_runner=run_detail)


def test_input_defect_is_visible_before_learned_missing_condition_cards():
    app = AppTest.from_function(invalid_shape_view, default_timeout=45).run()
    assert not app.exception
    report = app.session_state['invalid_report']
    assert next(x for x in report['findings'] if x['id'] == 'input')['status'] == 'attention'
    assert app.session_state['highlight_finding'] == 'input'
    assert not any(widget.key == 'highlight_finding' for widget in app.selectbox)
    assert app.button(key='am_conclusion_location')
    text = '\n'.join(visible_text(app.main))
    assert '입력 형상을 먼저 수정하세요' in text
    app.toggle(key='am_location_details').set_value(True).run()
    assert not app.exception
    assert app.selectbox(key='highlight_finding').value == 'input'
    assert '입력 결함' in '\n'.join(visible_text(app.main))
