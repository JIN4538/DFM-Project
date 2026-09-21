"""A shared report must explain decisions without requiring the application."""
from copy import deepcopy
from html.parser import HTMLParser

import pytest
import trimesh

from amdfm.analysis import review
from amdfm.detail import attach_detail
from amdfm.io import load_model
from amdfm.presentation import html_report
from amdfm.profiles import Profile


class ReportText(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.detail_depth = 0
        self.ignored_depth = 0
        self.visible = []
        self.tags = []
        self.details_open = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag == 'details':
            self.detail_depth += 1
            self.details_open.append('open' in dict(attrs))
        if tag in ('style', 'script', 'title'):
            self.ignored_depth += 1

    def handle_endtag(self, tag):
        if tag == 'details':
            self.detail_depth -= 1
        if tag in ('style', 'script', 'title'):
            self.ignored_depth -= 1

    def handle_data(self, data):
        if not self.detail_depth and not self.ignored_depth:
            self.visible.append(data)


def model():
    return load_model(trimesh.creation.box(extents=[10, 20, 30]).export(file_type='stl'),
                      'known-box.stl', dimensions_confirmed=True)


@pytest.fixture
def report():
    return review(model(), Profile())


def with_wall(report, *, limit=None, partial=False):
    result = deepcopy(report)
    result['profile']['minimum_wall_mm'] = limit
    measurements = dict(minimum_mm=4., area_weighted_p05_mm=4., minimum_wall_mm=limit,
                        requested_samples=24, valid_samples=23 if partial else 24,
                        missing_samples=1 if partial else 0, samples=[],
                        below_limit_face_indices=[1] if limit and limit > 4 else [],
                        thinnest_face_indices=[1, 2])
    return attach_detail(result, dict(mode='wall', fingerprint=result['model_fingerprint'],
        status='partial' if partial else 'measured', measurements=measurements))


def with_zero_layers(report, n=200):
    result = deepcopy(report)
    rows = [dict(index=i, z_mm=.1 + .2*i, complete=True,
                 thin_candidate_area_mm2=0., unsupported_candidate_area_mm2=0.,
                 single_layer_candidate_area_mm2=0., thin_full_scope=True,
                 unsupported_full_scope=True, single_layer_full_scope=True) for i in range(n)]
    result.setdefault('details', {})['layers'] = dict(status='complete', layers=rows,
        expected_layers=n, examined_layers=n, complete_layers=n)
    return result


def visible(report):
    return ''.join(ReportText(html_report(report).decode()).visible)


def test_first_page_contains_decision_action_without_raw_technical_records(report):
    rendered = html_report(report).decode()
    document = ReportText(rendered)
    text = ''.join(document.visible)
    assert '다음에 할 일' in text
    assert '추가 확인' in text
    assert text.index('다음에 할 일') < text.index('항목별 판단')
    assert 'source_sha256' not in text and 'placement_transform' not in text
    assert report['model']['source_sha256'] in rendered
    assert report['provenance']['code_sha256'] in rendered
    assert document.details_open and not any(document.details_open)
    assert 'script' not in document.tags


@pytest.mark.parametrize('limit,partial,expected', [
    (None, False, '벽은 측정됐지만 비교 기준이 없습니다'),
    (1., False, '검사한 표본에서 입력한 벽 기준 미만이 없습니다'),
    (5., False, '입력한 벽 기준보다 작은 구간이 있습니다'),
    (1., True, '벽의 일부 표본을 확인하지 못했습니다'),
])
def test_wall_decisions_explain_the_same_4mm_measurement(report, limit, partial, expected):
    text = visible(with_wall(report, limit=limit, partial=partial))
    assert expected in text
    assert '가장 짧게 측정한 거리 4 mm' in text
    assert '입력한 최소 벽 기준' in text
    assert 'p05' not in text
    assert '전체 최소 벽두께' in text


def test_complete_zero_layers_are_explained_without_two_hundred_visible_rows(report):
    result = with_zero_layers(report)
    document = ReportText(html_report(result).decode())
    text = ''.join(document.visible)
    assert '검사한 200개 층에서 세 종류의 후보가 발견되지 않았습니다' in text
    assert '먼저 확인할 층' not in text
    assert 'thin_full_scope' not in text
    assert '층 중간 단면' in text


@pytest.mark.parametrize('breakage', ['missing_value', 'missing_row', 'partial_scope'])
def test_unknown_layer_scope_never_appears_as_zero_candidate_success(report, breakage):
    result = with_zero_layers(report)
    layers = result['details']['layers']
    if breakage == 'missing_value':
        layers['layers'][0]['thin_candidate_area_mm2'] = None
    elif breakage == 'missing_row':
        layers['layers'].pop()
    else:
        layers['layers'][0]['unsupported_full_scope'] = False
    text = visible(result)
    assert '일부 층간 검토를 확인하지 못했습니다' in text
    assert '세 종류의 후보가 발견되지 않았습니다' not in text


def test_tiny_candidate_keeps_location_and_next_action_in_shared_report(report):
    result = with_zero_layers(report)
    result['details']['layers']['layers'][24]['thin_candidate_area_mm2'] = 1e-18
    text = visible(result)
    assert '확인할 후보가 있는 1개 층' in text
    assert '먼저 확인할 층' in text
    assert '25' in text and '4.9' in text
    assert '경로가 생략되면 선폭 설정이나 형상을 조정하세요' in text


@pytest.mark.parametrize('partial', [False, True])
def test_section_volume_check_is_subordinate_and_partial_stale_value_is_not_promoted(report, partial):
    result = deepcopy(report)
    volume = result['geometry']['mesh_signed_volume_mm3']
    result['details'] = dict(sections=dict(status='partial' if partial else 'complete',
        requested_samples=2, complete_samples=1 if partial else 2, examined_samples=2,
        sampling='events', method='vertex_event_sections/1',
        volume_quadrature_estimate_mm3=volume*(1+1e-14), rows=[
            dict(index=0, z_mm=1., area_mm2=20., complete=True),
            dict(index=1, z_mm=2., area_mm2=20., complete=not partial,
                 symmetric_change_from_previous_mm2=0. if not partial else None)]))
    rendered = html_report(result).decode()
    text = ''.join(ReportText(rendered).visible)
    assert '부피 차이' not in text
    if partial:
        assert '전체 단면 계산이 완료되지 않아' in rendered
        assert '두 계산 방법의 부피 차이' not in rendered
    else:
        assert '두 계산 방법의 부피 차이' in rendered
        assert '0.0001% 미만' in rendered


@pytest.mark.parametrize('process', ['VPP', 'PBF_POLYMER', 'PBF_METAL'])
def test_other_process_report_does_not_offer_mex_layer_review(process):
    result = review(model(), Profile(process=process))
    text = visible(result)
    assert 'MEX 층간 관계' not in text
    assert '현재 공정' in text or result['process_label'] in text


def test_user_text_is_escaped_and_report_remains_unchanged(report):
    result = with_wall(with_zero_layers(report), limit=1.)
    attack = '<img src=x onerror="alert(1)"> & </details><script>alert(2)</script>'
    result['model']['filename'] = attack
    result['profile']['threshold_basis'] = attack
    result['findings'][0]['reason'] = attack
    before = deepcopy(result)
    rendered = html_report(result).decode()
    document = ReportText(rendered)
    assert 'img' not in document.tags and 'script' not in document.tags
    assert '&lt;img' in rendered and '&lt;/details&gt;' in rendered
    assert result == before
