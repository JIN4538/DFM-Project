"""User-flow checks for concise AM evidence, without altering calculations."""
import json

from streamlit.testing.v1 import AppTest

from tests_v3.test_detail_view import layers, render, wall
from tests_v3.test_section_view import render as render_section, sections


def test_already_selected_maximum_change_needs_no_duplicate_button():
    detail = sections()
    app = render_section(detail)
    assert not app.exception
    assert app.selectbox(key='section_index').value == 2
    assert not any(button.key == 'show_section_change' for button in app.button)
    app.selectbox(key='section_index').set_value(0).run()
    assert app.button(key='show_section_change').label == '변화가 가장 큰 단면으로 돌아가기'
    app.button(key='show_section_change').click().run()
    assert not app.exception
    assert app.selectbox(key='section_index').value == 2
    assert app.session_state['original_detail'] == detail


def test_first_section_explains_only_the_legend_symbols_actually_shown():
    app = render_section(sections())
    app.selectbox(key='section_index').set_value(0).run()
    assert not app.exception
    captions = [caption.value for caption in app.caption]
    assert '주황 실선: 현재 · 같은 배율' in captions
    assert '◆ 현재 · ● 다른 단면' in captions
    assert not any('파란 점선: 이전' in caption or '■ 이전' in caption for caption in captions)


def test_unresolved_selected_section_has_no_current_or_previous_point_legend():
    detail = sections()
    detail.update(status='partial', complete_samples=3)
    detail['rows'][1].update(complete=False, area_mm2=None, outlines=[], outlines_complete=False,
                             symmetric_change_from_previous_mm2=None)
    detail['rows'][2]['symmetric_change_from_previous_mm2'] = None
    app = render_section(detail)
    app.selectbox(key='section_index').set_value(1).run()
    assert not app.exception
    captions = [caption.value for caption in app.caption]
    assert '● 다른 단면' in captions
    assert not any('◆ 현재' in caption or '■ 이전' in caption for caption in captions)


def test_wall_measurement_states_comparison_meaning_and_action_before_plot():
    app = render(wall(), mode='wall', criterion=5.)
    assert not app.exception
    assert [metric.label for metric in app.metric] == ['가장 얇게 측정된 위치', '이보다 얇으면 확인']
    assert [metric.value for metric in app.metric] == ['4 mm', '5 mm']
    assert '곡면' in app.metric[0].proto.help
    elements = list(app.main)
    action = next(i for i, element in enumerate(elements)
                  if element.type == 'markdown' and '**할 일**' in element.value)
    first_plot = next(i for i, element in enumerate(elements) if element.type == 'plotly_chart')
    assert action < first_plot


def test_overlapping_layer_types_have_readable_names_and_noncolor_cues():
    detail = layers()
    for prefix in ('thin', 'unsupported', 'single_layer'):
        detail['layers'][1][prefix + '_candidate_area_mm2'] = 2.
        detail['layers'][1][prefix + '_details'] = [dict(bounds_mm=[1., 2., 3., 4.])]
    app = render(detail)
    assert not app.exception
    assert app.selectbox(key='layer_location').value == 0
    plot = json.loads(app.get('plotly_chart')[0].proto.spec)
    labels = {'재료 한 줄보다 좁은 부분', '아래층 지지가 부족한 부분', '한 층에만 나타난 부분'}
    markers = [trace for trace in plot['data'] if trace.get('name') in labels]
    assert len(markers) == 3
    assert {trace['line']['dash'] for trace in markers} == {'solid', 'dash', 'dot'}
    assert len({trace['line']['color'] for trace in markers}) == 3
    assert app.session_state['original_report']['details']['layers'] == detail


def test_inapplicable_detail_does_not_offer_futile_extra_calculation():
    script = """
from amdfm.action_view import _render_location
explanation = {'label': '층별 얇은 부분', 'state': '해당 없음'}
report = {'details': {'layers': {'status': 'not_applicable', 'reason': '분말 공정'}}}
_render_location(None, report, None, {'layers': explanation}, {}, {},
                 None, None, None)
"""
    app = AppTest.from_string(script).run()
    assert not app.exception
    assert not any(button.key == 'inline_retry_layers' for button in app.button)
    assert any('적용되지 않습니다' in message.value for message in app.info)
    assert not app.success
    assert not any('일부 범위 미확인' in caption.value for caption in app.caption)
