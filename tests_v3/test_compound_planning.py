from copy import deepcopy
import hashlib
import itertools
import json

import numpy as np
import pytest

from dfm import compound_planning as cp, rl_planner as env, plan_learning as prior
from scripts.train_rl_planner import scenario


def mixed():
    report=scenario(2026093043, 3, 2)['report']
    report['review_context']['priority']='balanced'
    return report


def model_file(tmp_path):
    value = dict(schema=cp.SCHEMA, features=list(cp.FEATURES), sources=cp.source_hashes(),
                 intercept=0., learning_rate=1., trees=[[[-2,-2,-1,-1,0.]]])
    path=tmp_path/'model.json'
    raw=json.dumps(value).encode()
    path.write_bytes(raw)
    path.with_suffix('.manifest.json').write_text(json.dumps({'sha256':hashlib.sha256(raw).hexdigest()}))
    return path


def test_compound_targets_improve_over_uniform_geometry_modes():
    report=mixed()
    original=deepcopy(report)
    problem=env.make_problem(report)
    states=[]
    plans,_,_=prior._cnc_candidates(report, prior._preferences(report))
    for plan in plans:
        checked=env.evaluate_changes(report,plan['changes'])
        states.append((checked['conflicts'],checked['cost']))
    state,audit=cp.search(problem,policy='all')
    checked=env.evaluate_changes(report,env.edits(problem,state))
    assert checked['conflicts']==0
    assert checked['cost'] < min(states)[1]-.01
    assert audit['configuration_count'] > 8
    assert report==original


def test_feature_dynamic_programming_matches_independent_cartesian_enumeration():
    report=mixed()
    problem=env.make_problem(report)
    for configuration in cp.tool_configurations(problem):
        tool,flute,reach=configuration
        rows=problem['initial']['holes']
        hole_choices=[]
        for row in rows:
            limit=problem['ratio_limit']
            diameters={max(row['diameter'],tool)}
            if limit:
                diameters|={max(row['diameter'],tool,row['depth']/limit),
                            max(row['diameter'],tool,min(row['depth'],reach)/limit)}
            hole_choices.append([(diameter,min(row['depth'],reach,diameter*limit if limit else row['depth']))
                                 for diameter in diameters])
        states=[]
        for holes in itertools.product(*hole_choices):
            state=deepcopy(problem['initial'])
            state.update(tool=tool,flute=flute,reach=reach)
            for row,(diameter,depth) in zip(state['holes'],holes): row.update(diameter=diameter,depth=depth)
            for row in state['corners']:row['radius']=max(row['radius'],tool/2)
            for row in state['pockets']:row.update(width=max(row['width'],tool),depth=min(row['depth'],flute,reach),radius=tool/2)
            states.append(env.quality(problem,state))
        result=cp.complete_configuration(problem,configuration)
        assert env.quality(problem,result)==min(states)


@pytest.mark.parametrize('prefs',[{'preserve_geometry':True},{'allow_tool_change':False},
                                 {'preserve_geometry':True,'allow_tool_change':False}])
def test_locks_and_missing_measurements_are_retained(prefs):
    report=mixed()
    report['findings'].append(dict(id='cnc_visibility',status='unknown',measurements={}))
    problem=env.make_problem(report,prefs)
    state,_=cp.search(problem,policy='all')
    changes=env.edits(problem,state)
    if prefs.get('preserve_geometry'):assert all('.' not in row['field'] for row in changes)
    if prefs.get('allow_tool_change') is False:assert all('.' in row['field'] for row in changes)
    checked=env.evaluate_changes(report,changes,preferences=prefs)
    assert 'cnc_visibility' in checked['plan']['remaining_finding_ids']


def test_prediction_budget_and_source_input_are_preserved(tmp_path,monkeypatch):
    report=mixed();original=deepcopy(report)
    model=model_file(tmp_path)
    monkeypatch.setattr(cp,'EXACT_THRESHOLD',0)
    calls=[];complete=cp.complete_configuration
    def recorded(problem,configuration):
        calls.append(configuration)
        return complete(problem,configuration)
    monkeypatch.setattr(cp,'complete_configuration',recorded)
    result=cp.propose_compound_plan(report,model_path=model,budget=3)
    assert result['status']=='proposed'
    assert len(calls)==3
    assert result['proposal']['engine']=='learned_tool_proposals_exact_feature_completion'
    assert result['proposal']['id'].startswith('cnc-compound:')
    assert '강화학습' not in str(result['proposal']['evidence'])
    assert report==original


def test_small_search_uses_exact_completion_without_neural_overhead(tmp_path):
    result=cp.propose_compound_plan(mixed(),model_path=model_file(tmp_path))
    assert result['search']['used_learning'] is False
    assert result['search']['evaluated_count']==result['search']['configuration_count']
    assert result['proposal']['engine']=='exact_compound_feature_completion'


def test_missing_or_tampered_model_does_not_fabricate_a_plan(tmp_path):
    assert cp.propose_compound_plan(mixed(),model_path=tmp_path/'missing.json')['proposal'] is None
    path=model_file(tmp_path)
    path.write_text(path.read_text()+' ')
    assert cp.propose_compound_plan(mixed(),model_path=path)['status']=='unavailable'


def test_invalid_dimensions_and_configuration_limits_fail_closed(tmp_path,monkeypatch):
    report=mixed();report['profile']['tool_diameter_mm']=None
    assert cp.propose_compound_plan(report,model_path=model_file(tmp_path))['proposal'] is None
    problem=env.make_problem(mixed())
    with pytest.raises(ValueError):cp.complete_configuration(problem,(float('nan'),2.,3.))
    monkeypatch.setattr(cp,'MAX_CONFIGURATIONS',1)
    with pytest.raises(ValueError):cp.tool_configurations(problem)


def test_portable_tree_threshold_and_malformed_cycle(tmp_path):
    values=np.zeros((2,len(cp.FEATURES)));values[:,0]=[.25,.75]
    model=dict(intercept=.2,learning_rate=.1,trees=[[[0,.5,1,2,0],[-2,-2,-1,-1,2],[-2,-2,-1,-1,6]]])
    assert np.allclose(cp.predict(model,values),[.4,.8])
    path=model_file(tmp_path);data=json.loads(path.read_text());data['trees'][0]=[[0,.5,0,0,0]]
    raw=json.dumps(data).encode();path.write_bytes(raw)
    path.with_suffix('.manifest.json').write_text(json.dumps({'sha256':hashlib.sha256(raw).hexdigest()}))
    with pytest.raises(ValueError):cp.load_model(path)
