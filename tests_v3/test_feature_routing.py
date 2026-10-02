from copy import deepcopy
import numpy as np
import pytest
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeSphere
from dfm.cad_graph import extract_graph
from dfm.feature_routing import recognize_cad_features
from dfm.external_features_review import pocket_dimensions
from tests_v3.test_external_feature_learning import pocket_graph


@pytest.mark.parametrize('sides,name',[(3,'triangular_pocket'),(4,'rectangular_pocket'),(6,'6sides_pocket')])
def test_independent_cad_pockets_keep_exact_dimensions(sides,name):
    graph=pocket_graph(sides)
    original=deepcopy(graph['measurements'])
    found=recognize_cad_features(graph)
    candidates=[r for r in found['candidates'] if r['feature']==name]
    dimensions=[pocket_dimensions(r,[0,0,1]) for r in candidates]
    dimensions=[r for r in dimensions if r is not None]
    assert len(dimensions)==1
    assert dimensions[0]['wall_height_mm']==pytest.approx(8.)
    assert graph['measurements']==original
    assert found['routing_policy']=='cad-feature-agreement-v1'


@pytest.mark.parametrize('shape',[lambda:BRepPrimAPI_MakeBox(40,30,12).Shape(),
    lambda:BRepPrimAPI_MakeCylinder(6,12).Shape(),lambda:BRepPrimAPI_MakeSphere(7).Shape()])
def test_plain_stock_remains_without_feature_candidates(shape):
    assert not recognize_cad_features(extract_graph(shape()))['candidates']


def test_disagreeing_specialist_cannot_replace_joint_class(monkeypatch):
    from dfm import feature_routing as module
    g=extract_graph(BRepPrimAPI_MakeBox(8,10,12).Shape())
    for row in g['measurements']:row['face_id']+=900
    joint=np.tile(np.eye(25)[13],(len(g['x']),1))
    planar=np.tile(np.eye(16)[10],(len(g['x']),1))
    fake=dict(semantic=joint,edge=np.ones(len(g['edges'])),bottom=np.ones(len(g['x'])))
    monkeypatch.setattr(module,'predict_localization',lambda *a:fake)
    monkeypatch.setattr(module,'predict_graph',lambda *a:planar)
    found=recognize_cad_features(g)['candidates']
    assert len(found)==1 and found[0]['feature']=='triangular_pocket'
    assert found[0]['confidence_source']=='joint'
    assert found[0]['face_ids']==list(range(901,907))
    assert found[0]['bottom_face_ids']==list(range(901,907))


def test_agreement_never_enables_an_unconfirmed_class(monkeypatch):
    from dfm import feature_routing as module
    g=extract_graph(BRepPrimAPI_MakeBox(8,10,12).Shape())
    fake=dict(semantic=np.tile(np.eye(25)[2],(len(g['x']),1)),edge=np.ones(len(g['edges'])),bottom=np.zeros(len(g['x'])))
    monkeypatch.setattr(module,'predict_localization',lambda *a:fake)
    monkeypatch.setattr(module,'predict_graph',lambda *a:np.tile(np.eye(16)[1],(len(g['x']),1)))
    result=recognize_cad_features(g)
    assert 'triangular_passage' in result['unconfirmed_classes']
    assert not result['candidates']


def test_original_face_budget_and_freeform_boundary_are_retained():
    g=extract_graph(BRepPrimAPI_MakeBox(8,10,12).Shape())
    g['x'][0,:6]=[0,0,0,0,0,1]
    assert recognize_cad_features(g)['status']=='outside_training_domain'
    g['x']=np.tile(np.eye(22)[0],(201,1))
    assert recognize_cad_features(g)['status']=='outside_training_domain'


def test_unavailable_specialist_does_not_drop_valid_joint_result(monkeypatch):
    from dfm import feature_routing as module
    g=pocket_graph(3)
    monkeypatch.setattr(module,'load_semantic',lambda *a:(_ for _ in ()).throw(OSError('unavailable auxiliary')))
    found=recognize_cad_features(g)
    assert any(r['feature']=='triangular_pocket' for r in found['candidates'])
