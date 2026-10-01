from copy import deepcopy
import numpy as np
import pytest
import trimesh
from amdfm.profiles import Profile
from amdfm.orientation import compare_orientations, measure_orientation
from amdfm.ensemble_search import enrich_ensemble
from amdfm.full_search import enrich_full


def setup():
    mesh=trimesh.creation.box([33.,8.,2.])
    mesh.apply_transform(trimesh.transformations.euler_matrix(.2,.6,.4))
    p=Profile()
    return mesh,p,compare_orientations(mesh,p,dense=True)


def test_new_model_retains_previous_queries_and_measures_all_added_values():
    m,p,base=setup();snapshot=deepcopy(base)
    old=enrich_ensemble(m,p,base,timeout_s=30)
    new=enrich_full(m,p,base,timeout_s=30)
    without_pareto=lambda rows:[{k:v for k,v in r.items() if k!='pareto'} for r in rows]
    assert without_pareto(new['rows'][:len(old['rows'])])==without_pareto(old['rows'])
    assert 0<new['metadata']['full_added_count']<=6
    assert new['metadata']['added_count']<=30
    assert base==snapshot
    for row in new['rows'][len(old['rows']):]:
        expected=measure_orientation(m,row['direction'],p)
        for key in ('height_mm','contact_triangle_area_mm2','overhang_projected_area_sum_mm2','build_fit'):
            assert row[key]==expected[key]
        assert np.linalg.norm(row['direction'])==pytest.approx(1.)


def test_missing_model_preserves_previous_measured_candidates(monkeypatch,tmp_path):
    import amdfm.full_search as module
    m,p,base=setup();old=enrich_ensemble(m,p,base,timeout_s=30)
    monkeypatch.setattr(module,'MODEL_PATH',tmp_path/'missing.json')
    new=enrich_full(m,p,base,timeout_s=30)
    assert new['rows']==old['rows']
    assert 'full_model_unavailable_reason' in new['metadata']


def test_explicit_small_budget_and_zero_budget_do_not_expand():
    m,p,base=setup()
    assert enrich_full(m,p,base,max_proposals=2,timeout_s=30)['metadata']['added_count']==2
    assert enrich_full(m,p,base,timeout_s=0)['metadata']['added_count']==0


def test_outside_angle_domain_does_not_propose_untrained_area_queries():
    m,_,_=setup();p=Profile(overhang_angle_deg=80.)
    new=enrich_full(m,p,compare_orientations(m,p,dense=True),timeout_s=30)
    assert new['metadata'].get('full_added_count',0)==0
