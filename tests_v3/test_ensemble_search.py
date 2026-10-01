from copy import deepcopy
import numpy as np
import trimesh
from amdfm.profiles import Profile
from amdfm.orientation import compare_orientations,measure_orientation
from amdfm.neural_orientation import enrich_orientations
from amdfm.ensemble_search import enrich_ensemble

def shape():
    s=trimesh.creation.box([17,8,3]);s.apply_transform(trimesh.transformations.euler_matrix(.32,.16,.68));return s

def test_ensemble_retains_old_measurements_and_exactly_checks_new_queries():
    mesh=shape();p=Profile();base=compare_orientations(mesh,p,dense=True);before=deepcopy(base)
    old=enrich_orientations(mesh,p,base,timeout_s=30);new=enrich_ensemble(mesh,p,base,timeout_s=30)
    assert [{k:v for k,v in r.items() if k!='pareto'} for r in new['rows'][:len(old['rows'])]]==[{k:v for k,v in r.items() if k!='pareto'} for r in old['rows']]
    assert new['metadata']['expanded_added_count']==6
    assert new['metadata']['added_count']<=18 and base==before
    assert len(new['metadata']['ensemble_models'])==2
    for row in new['rows'][len(old['rows']):]:
        exact=measure_orientation(mesh,row['direction'],p)
        for key in ('height_mm','overhang_projected_area_sum_mm2','contact_triangle_area_mm2','build_fit'):
            assert row[key]==exact[key]

def test_missing_expanded_model_keeps_old_data(monkeypatch,tmp_path):
    import amdfm.ensemble_search as e
    monkeypatch.setattr(e,'EXPANDED_MODEL',tmp_path/'absent.json');mesh=shape();p=Profile();base=compare_orientations(mesh,p,dense=True)
    old=enrich_orientations(mesh,p,base,timeout_s=30);new=enrich_ensemble(mesh,p,base,timeout_s=30)
    assert new['rows']==old['rows'] and 'expanded_model_unavailable_reason' in new['metadata']

def test_small_query_budget_stays_bounded():
    mesh=shape();p=Profile();base=compare_orientations(mesh,p,dense=True)
    assert enrich_ensemble(mesh,p,base,max_proposals=3,timeout_s=30)['metadata']['added_count']==3
