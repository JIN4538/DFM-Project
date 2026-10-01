from copy import deepcopy
import time

import numpy as np
import pytest

from amdfm import adaptive_search as adaptive


def test_local_residual_learns_measured_error_without_changing_frozen_prediction(monkeypatch):
    def fixed(*args, height_only=False, **kwargs):
        count=len(args[2])
        return {key:np.full(count,.6) for key in (('height',) if height_only else ('height','overhang'))}
    monkeypatch.setattr(adaptive,'predict_surrogates',fixed)
    observed=[dict(direction=[1.,0.,0.],height_mm=2.,overhang_projected_area_sum_mm2=8.)]
    snapshot=deepcopy(observed)
    descriptor=dict(diagonal_mm=10.,area_mm2=10.,height=[.2,.8],overhang=[.1,.8])
    result=adaptive.residual_predictions({},descriptor,[[1.,0.,0.],[-1.,0.,0.]],observed,45.,ridge=.01)
    assert result['height'][0]==pytest.approx(result['height'][1])
    assert abs(result['height'][0]-.2)<.01
    assert result['overhang'][0]>.79
    assert result['overhang'][1]<.601
    assert observed==snapshot


def test_queries_only_use_returned_exact_measurements_and_respect_budget(monkeypatch):
    def fixed(model,descriptor,directions,observed,angle,**kwargs):
        return dict(height=np.arange(len(directions),dtype=float)/len(directions))
    monkeypatch.setattr(adaptive,'residual_predictions',fixed)
    original=[dict(direction=[0.,0.,1.],height_mm=1.,candidate_role='search')]
    snapshot=deepcopy(original)
    directions=np.array([[1.,0.,0.],[0.,1.,0.],[-1.,0.,0.],[0.,-1.,0.]])
    calls=[]
    def measure(direction):
        calls.append(direction.tolist())
        return dict(direction=direction.tolist(),height_mm=100.+len(calls),build_fit=None)
    rows,trace=adaptive.adaptive_queries({},dict(height=[.1,.9]),directions,['sphere']*4,
        original,45.,measure,height_only=True,budget=2)
    assert len(calls)==len(rows)==2
    assert [row['height_mm'] for row in rows]==[101.,102.]
    assert all(row['build_fit'] is None for row in rows)
    assert [record['observations'] for record in trace]==[1,2]
    assert original==snapshot


def test_expired_deadline_performs_no_prediction_or_measurement(monkeypatch):
    def forbidden(*args,**kwargs):
        pytest.fail('No operation should run beyond an expired deadline')
    monkeypatch.setattr(adaptive,'residual_predictions',forbidden)
    rows,trace=adaptive.adaptive_queries({}, {},[[1.,0.,0.]],['sphere'],
        [dict(direction=[0.,0.,1.])],45.,forbidden,deadline=time.monotonic()-1.)
    assert rows==trace==[]


def test_retained_candidates_are_still_measured_before_adaptive_choice(monkeypatch):
    def fixed(model,descriptor,directions,observed,angle,**kwargs):
        return dict(height=np.arange(len(directions),dtype=float)/len(directions))
    monkeypatch.setattr(adaptive,'residual_predictions',fixed)
    directions=np.array([[1.,0.,0.],[0.,1.,0.],[-1.,0.,0.],[0.,-1.,0.]])
    calls=[]
    def measure(direction):
        calls.append(direction.tolist())
        return dict(direction=direction.tolist(),height_mm=10.+len(calls))
    rows,trace=adaptive.adaptive_queries({},dict(height=[.1,.9]),directions,['sphere']*4,
        [dict(direction=[0.,0.,1.],height_mm=1.)],45.,measure,height_only=True,budget=3,
        warm_start=[directions[3],directions[2]])
    assert calls==directions[[3,2,0]].tolist()
    assert [row['height_mm'] for row in rows]==[11.,12.,13.]
    assert [record['observations'] for record in trace]==[1,2,3]
