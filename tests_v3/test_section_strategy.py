"""Automatic choices preserve the method, failed attempt and unknown scope."""
import copy
import numpy as np
import pytest
import trimesh

from amdfm.analysis import review
from amdfm.detail import run_detail, attach_detail
from amdfm.detail_worker import inspect_section_strategy
from amdfm.models import Model
from amdfm.io import load_model
from amdfm.presentation import html_report
from amdfm.profiles import Profile
from amdfm.section_summary import summarize_sections


@pytest.mark.parametrize('process',['MEX','VPP','PBF_POLYMER','PBF_METAL'])
def test_auto_budget_fallback_preserves_original_attempt_and_exported_method(process):
    mesh=trimesh.creation.box(extents=[10,5,4])
    model=load_model(mesh.export(file_type='stl'),'strategy-box.stl',dimensions_confirmed=True)
    profile=Profile(process=process)
    report=review(model,profile,[1,1,1],compare=False)
    result=run_detail(model,profile,[1,1,1],mode='sections',sampling='auto',max_event_samples=2,sample_count=8)
    assert result['status']=='complete' and result['sampling']=='uniform'
    assert result['requested_sampling']=='auto' and result['sample_count']==8
    assert result['fallback_performed'] is True
    assert result['event_attempt']['failure_code']=='event_budget_exceeded'
    assert result['event_attempt']['volume_quadrature_estimate_mm3'] is None
    assert result['event_attempt']['rows']==[]
    assert result['volume_midpoint_estimate_mm3'] is not None
    assert np.allclose(result['placement_transform'],report['current_orientation']['transform'])
    summary=summarize_sections(result,process,200)
    assert '체적 검산은 미완료' in summary['completion_title']
    assert '얇은' in summary['next_step']
    document=html_report(attach_detail(report,result)).decode('utf-8')
    assert '전체 구간 체적 검산은 미완료' in document and '계산 예산' in document
    assert '균등 단면의 체적은 표본 추정' in document


def test_auto_representation_partial_is_not_replaced_by_uniform_or_complete():
    mesh=trimesh.creation.icosphere(subdivisions=2,radius=10)
    original=mesh.vertices.copy()
    result=inspect_section_strategy(mesh,'auto')
    assert result['sampling']=='events' and not result['fallback_performed']
    assert result['status']=='partial' and result['volume_quadrature_estimate_mm3'] is None
    summary=summarize_sections(result,'VPP',mesh.volume)
    assert summary['partial_volume']['representation_only']
    assert summary['partial_volume']['known_mm3']>0
    assert summary['partial_volume']['omitted_envelope_mm3']>0
    assert not summary['volume']['available']
    assert '수치 표현 한계' in summary['completion_title']
    np.testing.assert_array_equal(mesh.vertices,original)


@pytest.mark.parametrize('failure_code',['input_topology','event_runtime_budget_exceeded',None])
def test_auto_never_hides_non_preflight_failures(monkeypatch,failure_code):
    import amdfm.event_sections as events
    import amdfm.cross_sections as uniform
    monkeypatch.setattr(events,'inspect_event_sections',lambda *a,**kw:dict(status='unknown',rows=[],failure_code=failure_code,reason='Gauss budget words are not a machine code'))
    def forbidden(*args,**kwargs):
        raise AssertionError('Must not replace topology/section/runtime failure')
    monkeypatch.setattr(uniform,'inspect_cross_sections',forbidden)
    result=inspect_section_strategy(trimesh.creation.box(),'auto')
    assert result['status']=='unknown' and not result['fallback_performed']


def test_partial_claim_cannot_hide_unexamined_or_failed_intervals():
    result=inspect_section_strategy(trimesh.creation.icosphere(subdivisions=2),'events')
    assert result['representation_limit_only']
    for mutation in ('missing','failure','bad_index'):
        broken=copy.deepcopy(result)
        if mutation=='missing':broken['intervals'].pop()
        elif mutation=='failure':
            next(i for i in broken['intervals'] if not i['complete'])['unresolved_cause']='section_failure'
        else:broken['intervals'][0]['index']=999
        s=summarize_sections(broken,'MEX',1)
        assert not s['partial_volume']['representation_only']
        assert not s['volume']['available'] and s['status']=='partial'


@pytest.mark.parametrize('budget',[True,8193,float('nan')])
def test_auto_validates_event_budget_before_worker_start(budget):
    with pytest.raises(ValueError):
        run_detail(Model(trimesh.creation.box(),{}),Profile(),mode='sections',sampling='auto',max_event_samples=budget)


def test_auto_timeout_does_not_invent_a_uniform_method_in_report():
    model=load_model(trimesh.creation.box().export(file_type='stl'),'timeout-box.stl',dimensions_confirmed=True)
    profile=Profile()
    report=review(model,profile,compare=False)
    result=run_detail(model,profile,mode='sections',sampling='auto',timeout_s=.001)
    assert result['status']=='unknown' and result['requested_sampling']=='auto'
    assert not result.get('fallback_performed') and not result.get('method')
    finding=next(f for f in attach_detail(report,result)['findings'] if f['id']=='sections')
    assert finding['method']=='calculation_not_completed'
