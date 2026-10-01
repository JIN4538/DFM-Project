"""Independent dimensional examples and RL contracts; no fabricated CAD labels."""
from copy import deepcopy
import json

import numpy as np
import pytest

from dfm.rl_planner import (ACTION_KINDS, FEATURE_COUNT, _source_hash, action_space, action_vectors, conflicts,
    edits, evaluate_changes, load_model, make_problem, metrics, network_predict, plan_cost, plan_from_state,
    propose_rl_plan, quality, rollout, transition)


def report():
    return dict(process="MILLING_3AXIS", profile=dict(tool_diameter_mm=4.,flute_length_mm=6.,reach_mm=8.,hole_depth_ratio_limit=4.),
        review_context={"priority":"balanced"}, findings=[
        dict(id="cnc_input",status="observed",measurements={"cad_feature_dimensions_available":True}),
        dict(id="cnc_holes",status="attention",measurements={"cylindrical_faces":[dict(face_id=12,diameter_mm=3.,cylindrical_length_mm=16.,axis_aligned=True)]}),
        dict(id="cnc_curved_corners",status="attention",measurements={"cylindrical_faces":[dict(face_id=25,radius_mm=1.)]}),
        dict(id="cnc_rectangular_pockets",status="attention",measurements={"pockets":[dict(floor_face_id=40,width_mm=5.,wall_height_mm=10.)]})])


def choose(problem, state, kind, value=None):
    return next(a for a in action_space(problem,state) if a["kind"]==kind and (value is None or a["value"]==value))


def test_measured_conflicts_have_faces_and_no_missing_zeros():
    p=make_problem(report())
    rows=conflicts(p,p["initial"])
    assert [r["code"] for r in rows]==["hole_tool","hole_reach","hole_ratio","corner_tool","pocket_flute","pocket_reach","pocket_corner"]
    assert {r["cad_face_id"] for r in rows}=={12,25,40}
    bad=report()
    bad["profile"]["reach_mm"]=None
    with pytest.raises(ValueError):make_problem(bad)


def test_flute_action_requires_prior_reach_change_and_rewards_telescope():
    p=make_problem(report(),{"preserve_geometry":True})
    state=p["initial"]
    assert not any(a["kind"]=="flute" for a in action_space(p,state))
    after,r1,done=transition(p,state,choose(p,state,"reach",16.))
    assert not done and after["reach"]==16. and state["reach"]==8.
    after2,r2,done=transition(p,after,choose(p,after,"flute",10.))
    assert after2["flute"]==10.
    expected=2*(len(conflicts(p,state))-len(conflicts(p,after2)))-(plan_cost(p,after2)-plan_cost(p,state))
    assert r1+r2==pytest.approx(expected)
    assert all(r["code"] not in ("hole_reach","pocket_reach","pocket_flute") for r in conflicts(p,after2))


@pytest.mark.parametrize("prefs,forbidden",[
    ({"preserve_geometry":True},set(ACTION_KINDS[4:])),
    ({"allow_tool_change":False},{"tool","flute","reach"}),
    ({"allow_tool_change":False,"preserve_geometry":True},set(ACTION_KINDS[1:])),
])
def test_masks_apply_every_step(prefs,forbidden):
    p=make_problem(report(),prefs)
    state=p["initial"]
    for _ in range(8):
        choices=action_space(p,state)
        assert not forbidden.intersection(a["kind"] for a in choices)
        if len(choices)==1:break
        state,_,_=transition(p,state,choices[-1])
    with pytest.raises(ValueError):
        transition(p,state,dict(kind="unrecognized",index=-1,value=1.))


def test_corner_creation_waits_until_width_accepts_radius():
    data=report()
    data["findings"][-1]["measurements"]["pockets"][0]["width_mm"]=1.
    p=make_problem(data,{"allow_tool_change":False})
    state=p["initial"]
    assert not any(a["kind"]=="pocket_radius" for a in action_space(p,state))
    state,_,_=transition(p,state,choose(p,state,"pocket_width"))
    state,_,_=transition(p,state,choose(p,state,"pocket_radius"))
    assert state["pockets"][0]["width"]==4.
    assert state["pockets"][0]["radius"]==2.


def test_individual_feature_edit_does_not_modify_other_features():
    data=report()
    data["findings"][1]["measurements"]["cylindrical_faces"].append(dict(face_id=19,diameter_mm=2.,cylindrical_length_mm=3.,axis_aligned=True))
    p=make_problem(data,{"allow_tool_change":False})
    state=p["initial"]
    action=next(a for a in action_space(p,state) if a["kind"]=="hole_diameter" and a["index"]==1)
    after,_,_=transition(p,state,action)
    assert after["holes"][0]==state["holes"][0]
    assert after["holes"][1]["diameter"]==4.
    assert edits(p,after)==[dict(field="hole.1.diameter",label="구멍 지름",before=2.,after=4.,unit="mm",cad_face_id=19)]


def test_unresolved_and_wrong_axis_remain_in_proposal():
    data=report()
    data["findings"][1]["measurements"]["cylindrical_faces"][0]["axis_aligned"]=False
    data["findings"].append(dict(id="cnc_visibility",status="unknown",face_indices=[3],measurements={}))
    p=make_problem(data)
    state,steps=rollout(p,policy="greedy")
    plan=plan_from_state(p,state,steps)
    assert "cnc_holes" in plan["remaining_finding_ids"]
    assert "cnc_visibility" in plan["remaining_finding_ids"]
    assert any("미확인" in text for text in plan["remaining"])
    assert not any(r.get("cad_face_id")==12 for r in plan["changes"])


def test_recheck_rejects_hidden_edits_and_face_mismatch():
    change=dict(field="hole.0.diameter",before=3.,after=4.,unit="mm",cad_face_id=12)
    checked=evaluate_changes(report(),[change])
    assert checked["conflicts"]==5  # tool and depth/diameter clear together: 16/4=4.
    assert checked["plan"]["changes"][0]["cad_face_id"]==12
    for invalid in ([dict(change,cad_face_id=999)], [dict(change,before=4.)], [change,change], [dict(change,after=float("nan"))]):
        with pytest.raises(ValueError):evaluate_changes(report(),invalid)
    with pytest.raises(ValueError):evaluate_changes(report(),[change],preferences={"preserve_geometry":True})


def test_scale_invariance_features_and_cost():
    first=make_problem(report())
    data=report()
    for k in ("tool_diameter_mm","flute_length_mm","reach_mm"):data["profile"][k]*=1000.
    data["findings"][1]["measurements"]["cylindrical_faces"][0]["diameter_mm"]*=1000.
    data["findings"][1]["measurements"]["cylindrical_faces"][0]["cylindrical_length_mm"]*=1000.
    data["findings"][2]["measurements"]["cylindrical_faces"][0]["radius_mm"]*=1000.
    for k in ("width_mm","wall_height_mm"):data["findings"][3]["measurements"]["pockets"][0][k]*=1000.
    second=make_problem(data)
    x=action_vectors(first,first["initial"],action_space(first,first["initial"]),24)
    y=action_vectors(second,second["initial"],action_space(second,second["initial"]),24)
    np.testing.assert_allclose(x,y,atol=1e-12)


def test_network_training_and_json_inference_agree():
    from scripts.train_rl_planner import Network
    rng=np.random.default_rng(718)
    net=Network(rng)
    x=rng.normal(0,.3,(40,FEATURE_COUNT))
    y=.1*x[:,0]-.2*x[:,7]
    before=float(np.mean((net.predict(x)-y)**2))
    for _ in range(60):net.train(x,y)
    after=float(np.mean((net.predict(x)-y)**2))
    assert after<before*.2
    model=json.loads(json.dumps({"layers":net.export()}))
    np.testing.assert_allclose(network_predict(model,x),net.predict(x),rtol=1e-12,atol=1e-12)


def test_invalid_model_falls_back_without_mutating_report(tmp_path):
    data=report()
    saved=deepcopy(data)
    path=tmp_path/"bad.json"
    path.write_text('{"schema":"old"}',encoding="utf-8")
    result=propose_rl_plan(data,model_path=path)
    assert result["status"]=="unavailable" and result["proposal"] is None
    assert data==saved


def test_existing_flute_reach_input_contract_is_preserved():
    data=report()
    data["profile"].update(flute_length_mm=12.,reach_mm=8.)
    with pytest.raises(ValueError,match="날 길이"):
        make_problem(data)
    result=propose_rl_plan(data)
    assert result["status"]=="unavailable"


def test_overflow_dimensions_never_return_a_verified_plan():
    data=report()
    data["profile"].update(tool_diameter_mm=.001,flute_length_mm=1.,reach_mm=1e308)
    with pytest.raises(ValueError,match="유한한"):
        make_problem(data)
    assert propose_rl_plan(data)["status"]=="unavailable"
    with pytest.raises(ValueError,match="유한한"):
        evaluate_changes(report(),[dict(field="tool_diameter_mm",before=4.,after=1e-320)])


def test_generator_has_independent_priority_and_lock_combinations():
    from scripts.train_rl_planner import scenario
    combinations={(scenario(27,1,i)["report"]["review_context"]["priority"],json.dumps(scenario(27,1,i)["preferences"],sort_keys=True)) for i in range(9)}
    assert len(combinations)==9


def test_runtime_model_has_double_dqn_training_provenance():
    model=load_model()
    assert model["source_sha256"]==_source_hash()
    assert model["training"]["method"]=="Double DQN"
    assert model["training"]["action_labels"] is False
    assert model["training"]["gradient_updates"]>0
    assert len(model["layers"])==3
    result=propose_rl_plan(report())
    assert result["status"] in ("keep","proposed")
    proposal=result["proposal"]
    checked=evaluate_changes(report(),proposal["changes"])
    assert checked["conflicts"]==proposal["outcomes"]["remaining_numeric_conflicts"]
    assert checked["cost"]==pytest.approx(proposal["planning_cost"])


def test_runtime_model_rejects_weight_tampering(tmp_path):
    from dfm.rl_planner import MODEL_PATH
    model=json.loads(MODEL_PATH.read_text(encoding="utf-8"))
    model["layers"][0]["weights"][0][0]+=.01
    path=tmp_path/"modified.json"
    path.write_text(json.dumps(model),encoding="utf-8")
    path.with_suffix(".manifest.json").write_bytes(MODEL_PATH.with_suffix(".manifest.json").read_bytes())
    with pytest.raises(ValueError,match="해시"):
        load_model(path)


def test_runtime_model_cache_rechecks_current_sources(monkeypatch):
    import dfm.rl_planner as rl
    rl.load_model()
    monkeypatch.setattr(rl,"_source_hash",lambda:"changed-source")
    with pytest.raises(ValueError,match="해시"):
        rl.load_model()
