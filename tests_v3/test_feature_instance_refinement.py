"""Contracts and independent geometry properties for optional affinity models."""
from copy import deepcopy
import hashlib,json
import numpy as np
import pytest
from dfm.feature_instance_refinement import pair_inputs,group_records,refine_groups,load_model
from dfm.feature_localization import load_model as load_joint,predict_localization
from dfm.cad_graph import extract_graph
from scripts.benchmark_disconnected_feature_cad import build_case


def test_independent_separated_passage_pair_features_ignore_pose_and_units():
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Trsf
    from scipy.spatial.transform import Rotation
    shape,g,truth=build_case(6,1,True,3.2,24,.31,10)
    head,back=load_joint();groups=[dict(faces=t['faces'][:6],label=4,confidence=.99) for t in truth]
    groups.append(dict(faces=truth[0]['faces'][6:],label=4,confidence=.99))
    expected,pairs=pair_inputs(g,groups,back)
    t=gp_Trsf();r=Rotation.from_euler('xyz',[.2,-.51,.83]).as_matrix()
    t.SetValues(*(np.column_stack([r*2.7,[9,-14,21]]).ravel()))
    moved=extract_graph(BRepBuilderAPI_Transform(shape,t,True).Shape())
    actual,actual_pairs=pair_inputs(moved,groups,back)
    assert pairs==actual_pairs==[(0,1)]
    assert np.allclose(actual,expected,atol=1e-4)


def test_complete_link_rejects_single_bridge_between_distinct_features():
    groups=[dict(faces=[i],label=1,confidence=.999) for i in range(3)]
    refined=refine_groups(groups,[(0,1),(1,2),(0,2)],[.99,.99,.01],.98)
    assert sorted(len(g['faces']) for g in refined)==[1,2]
    assert set().union(*(set(g['faces']) for g in refined))=={0,1,2}


def test_affinity_inputs_never_use_semantic_or_instance_truth():
    _,g,truth=build_case(0,1,True,3.2,24,.31,10)
    head,back=load_joint();p=predict_localization(g,head,back);groups=group_records(g,p,head['edge_threshold'])
    x,pairs=pair_inputs(g,groups,back);altered=deepcopy(g)
    altered['y']=np.random.default_rng(1).integers(0,25,len(g['x']))
    altered['inst']=np.zeros((len(g['x']),len(g['x'])))
    other,other_pairs=pair_inputs(altered,groups,back)
    assert pairs==other_pairs and np.array_equal(x,other)


def test_affinity_model_checks_payload_before_loading_tensors(tmp_path):
    path=tmp_path/'model.json';path.write_text('{}',encoding='utf8')
    path.with_suffix('.manifest.json').write_text(json.dumps(dict(sha256='0'*64)),encoding='utf8')
    with pytest.raises(ValueError,match='checksum'):load_model(path)


def test_optional_refinement_missing_artifact_preserves_existing_candidates(tmp_path):
    from dfm.feature_instance_refinement import recognize_refined_features
    from dfm.feature_routing import recognize_cad_features
    from tests_v3.test_external_feature_learning import pocket_graph
    g=pocket_graph();old=recognize_cad_features(g)
    actual=recognize_refined_features(g,tmp_path/'missing.json')
    assert actual['candidates']==old['candidates']
    assert actual['routing_policy']=='cad-feature-agreement-v1'
    assert 'refinement_unavailable' in actual


def test_recovered_through_passage_does_not_invent_pocket_dimensions():
    from types import SimpleNamespace
    from dfm.feature_instance_refinement import recognize_refined_features
    from dfm.external_features_review import attach_external_features,pocket_dimensions
    _,g,truth=build_case(6,1,True,3.2,24,.31,10)
    result=recognize_refined_features(g)
    candidate=next(c for c in result['candidates'] if c['feature']=='6sides_passage')
    assert set(candidate['face_ids'])=={i+1 for i in truth[0]['faces']}
    assert candidate['fragments']==2
    assert pocket_dimensions(candidate,[0,0,1]) is None
    model=SimpleNamespace(metadata=dict(external_feature_recognition=[dict(result,body_id=1)]),face_ids=np.arange(1,len(g['x'])+1))
    report=dict(input=dict(solid_count=1),direction=[0,0,1],profile={},findings=[])
    attach_external_features(report,model)
    assert report['external_feature_recognition']['verified_pockets']==[]
    assert not any(f['id']=='cnc_learned_pockets' for f in report['findings'])


def test_installed_optional_model_keeps_original_face_budget():
    from dfm.feature_instance_refinement import recognize_refined_features
    _,g,_=build_case(0,1,False,3.2,24,.31,10)
    g['x']=np.tile(np.eye(22)[0],(201,1))
    assert recognize_refined_features(g)['status']=='outside_training_domain'


@pytest.mark.parametrize('sides',[3,6])
def test_raw_step_recovered_location_highlights_only_cutter_wall_faces(sides,tmp_path):
    from amdfm.io import load_model
    from OCP.STEPControl import STEPControl_Writer,STEPControl_AsIs
    shape,_,_=build_case(sides,1,True,3.2,24,.31,10)
    path=tmp_path/'independent.step';writer=STEPControl_Writer();writer.Transfer(shape,STEPControl_AsIs);writer.Write(str(path))
    model=load_model(path.read_bytes(),path.name)
    candidates=[c for r in model.metadata['external_feature_recognition'] for c in r['candidates']]
    feature='triangular_passage' if sides==3 else '6sides_passage'
    candidate=next(c for c in candidates if c['feature']==feature)
    selected=np.isin(model.face_ids,candidate['face_ids']);assert selected.any()
    centers=np.asarray(model.mesh.triangles_center)[selected]
    polygon=np.array([(3.2*np.cos(t+.31),3.2*np.sin(t+.31)) for t in np.linspace(0,2*np.pi,sides,endpoint=False)])
    distance=[]
    for a,b in zip(polygon,np.roll(polygon,-1,axis=0)):
        u=(b-a)/np.linalg.norm(b-a);n=np.array([-u[1],u[0]])
        distance.append(np.abs((centers[:,:2]-a)@n))
    assert np.max(np.min(distance,axis=0))<1e-6
    assert np.min(np.abs(centers[:,2]))>=24*.12-1e-6
    assert len(set(candidate['face_ids']))==2*sides
    assert candidate['fragments']==2
