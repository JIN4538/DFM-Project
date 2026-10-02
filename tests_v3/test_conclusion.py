"""Decision semantics independent of the learned ranker's synthetic labels."""
from copy import deepcopy

from dfm.conclusion import summarize_conclusion, conclusion_html


NO_PLAN = dict(status='unavailable', selected=None, alternatives=[], model={})


def wall_report(value=.3, complete=True):
    return dict(profile=dict(process='VPP', minimum_wall_mm=1.),
                findings=[dict(id='wall', status='unknown', measurements={})],
                details=dict(wall=dict(status='measured' if complete else 'partial',
                     measurements=dict(minimum_mm=value, valid_samples=12 if complete else 8,
                     requested_samples=12, missing_samples=0 if complete else 4))))


def test_complete_measurement_and_partial_measurement_have_different_conclusions():
    good = summarize_conclusion(wall_report(2), plan_result=NO_PLAN)
    partial = summarize_conclusion(wall_report(2, False), plan_result=NO_PLAN)
    assert good['level'] == 'success' and not good['pending']
    assert partial['level'] == 'info' and partial['pending']
    assert '추가 확인' in partial['title']


def test_observed_partial_issue_keeps_both_issue_and_missing_scope():
    result = summarize_conclusion(wall_report(.3, False), plan_result=NO_PLAN)
    assert result['level'] == 'warning'
    assert result['issues'][0]['id'] == result['partial'][0]['id'] == 'wall'
    assert '1 mm' in result['actions'][0]['text']


def test_input_defect_wins_over_learned_candidate_and_raw_data_unchanged():
    report = wall_report()
    report['findings'].append(dict(id='input', status='attention', title='입력 결함',
                                  reason='열린 경계', action='닫힌 형상으로 수정하세요'))
    before = deepcopy(report)
    result = summarize_conclusion(report, plan_result=NO_PLAN)
    assert result['level'] == 'error' and result['first']['id'] == 'input'
    assert result['issues'] and report == before


def test_unlearned_partial_finding_and_missing_report_never_pass():
    report = dict(profile=dict(process='MILLING_3AXIS'), findings=[
        dict(id='cnc_coverage', status='partial', title='미확인 형상', action='나머지 면을 확인하세요')])
    result = summarize_conclusion(report, plan_result=NO_PLAN)
    assert result['pending'][0]['id'] == 'cnc_coverage' and result['level'] != 'success'
    assert summarize_conclusion({}, plan_result=NO_PLAN)['level'] != 'success'


def test_unknown_process_does_not_hide_raw_numeric_warning():
    report = dict(profile={}, findings=[dict(id='cnc_holes', status='attention',
        title='구멍', measurements={'cylindrical_faces': []}, action='공구를 확인하세요')])
    result = summarize_conclusion(report, plan_result=NO_PLAN)
    assert result['issues'] or result['pending']


def test_plan_suppresses_only_resolved_generic_action_and_keeps_remaining_issue():
    report = wall_report()
    report['findings'].append(dict(id='overhang', status='attention', measurements={'projected_area_sum_mm2': 20.}))
    plan = dict(NO_PLAN, selected=dict(id='one', title='방향 변경', changes=[], covered_finding_ids=['wall', 'overhang'],
                                      remaining_finding_ids=['overhang']))
    result = summarize_conclusion(report, plan_result=plan)
    assert {x['id'] for x in result['issues']} == {'wall', 'overhang'}
    assert [x['id'] for x in result['visible_actions']] == ['overhang']


def test_html_escapes_user_content_and_uses_one_conclusion_heading():
    report = wall_report()
    report['findings'].append(dict(id='extra', status='attention', title='<script>bad()</script>',
                                  action='<img onerror=bad()>'))
    page = conclusion_html(report)
    assert page.count('<h2>종합 결론</h2>') == 1
    assert '<script>bad()' not in page and '&lt;img' in page
    assert '<details><summary>판단 근거' in page


def test_plan_change_keeps_verified_cad_face_identity():
    from dfm.conclusion import change_text
    assert 'CAD 면 12' in change_text(dict(field='width_mm', before=3., after=4., unit='mm', cad_face_id=12))


def test_residual_plan_keeps_issue_but_does_not_repeat_conflicting_generic_action():
    report = wall_report()
    plan = dict(NO_PLAN, selected=dict(id='one', title='허용한 변경', changes=[], covered_finding_ids=['wall'],
                                      remaining_finding_ids=['wall'], remaining=['형상을 유지하면 얇은 벽은 남음']))
    result = summarize_conclusion(report, plan_result=plan)
    assert [item['id'] for item in result['issues']] == ['wall']
    assert not result['visible_actions']
    assert result['plan']['selected']['remaining'] == ['형상을 유지하면 얇은 벽은 남음']
