from copy import deepcopy
import hashlib,json
import numpy as np
import pytest
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox,BRepPrimAPI_MakeCylinder,BRepPrimAPI_MakeSphere
from dfm.cad_graph import extract_graph
from dfm.feature_localization import MODEL_PATH,load_model,recognize_instances,predict_localization


@pytest.mark.parametrize('shape',[lambda:BRepPrimAPI_MakeBox(30.,20.,2.).Shape(),lambda:BRepPrimAPI_MakeCylinder(6.,12.).Shape(),lambda:BRepPrimAPI_MakeSphere(7.).Shape()])
def test_plain_stock_is_not_a_feature_instance(shape):
    assert not recognize_instances(extract_graph(shape()))['candidates']


def test_joint_predictions_are_rigid_transform_invariant():
    from OCP.gp import gp_Trsf
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    import trimesh
    shape=BRepPrimAPI_MakeBox(9.,14.,3.).Shape()
    rotate=trimesh.transformations.euler_matrix(.3,.5,.9)[:3,:3]
    tr=gp_Trsf();tr.SetValues(*np.column_stack([rotate,np.array([17.,-50.,20.])]).ravel())
    a=extract_graph(shape);b=extract_graph(BRepBuilderAPI_Transform(shape,tr,True).Shape())
    head,semantic=load_model();p,q=predict_localization(a,head,semantic),predict_localization(b,head,semantic)
    for name in p:assert q[name]==pytest.approx(p[name],abs=2e-5)
    assert 'unconfirmed_classes' in recognize_instances(a)


def test_freeform_instances_are_not_confirmed():
    graph=extract_graph(BRepPrimAPI_MakeBox(8.,10.,12.).Shape());graph['x'][0,:6]=[0,0,0,0,0,1]
    assert recognize_instances(graph)['status']=='outside_training_domain'


def copy_models(tmp_path):
    heads,_=load_model();path=tmp_path/MODEL_PATH.name
    for p in (MODEL_PATH,MODEL_PATH.with_suffix('.manifest.json'),MODEL_PATH.with_name('external_feature_mfinstseg_v2.json'),MODEL_PATH.with_name('external_feature_mfinstseg_v2.manifest.json')):
        (tmp_path/p.name).write_bytes(p.read_bytes())
    return path,deepcopy(heads)


def write_heads(path,model):
    raw=json.dumps(model).encode();path.write_bytes(raw)
    path.with_suffix('.manifest.json').write_text(json.dumps(dict(sha256=hashlib.sha256(raw).hexdigest())))


def test_corrupt_heads_and_escaping_backbone_are_rejected(tmp_path):
    path,model=copy_models(tmp_path);model['semantic_filename']='../outside.json';write_heads(path,model)
    with pytest.raises(ValueError):load_model(path)
    path,model=copy_models(tmp_path);model['class_thresholds']=[.1]*24;write_heads(path,model)
    with pytest.raises(ValueError):load_model(path)


def test_cache_rechecks_backbone_manifest_without_weight_mutation(tmp_path):
    path,_=copy_models(tmp_path);load_model(path)
    path.with_name('external_feature_mfinstseg_v2.manifest.json').write_text(json.dumps(dict(sha256='0'*64)))
    with pytest.raises(ValueError):load_model(path)


def test_disabled_class_and_original_face_ids(monkeypatch):
    from dfm import feature_localization as module
    g=extract_graph(BRepPrimAPI_MakeBox(8.,10.,12.).Shape());head,semantic=load_model();head=deepcopy(head)
    for m in g['measurements']:m['face_id']+=900
    fake=dict(semantic=np.tile(np.eye(25)[13],(len(g['x']),1)),edge=np.ones(len(g['edges'])),bottom=np.ones(len(g['x'])))
    monkeypatch.setattr(module,'load_model',lambda *a:(head,semantic));monkeypatch.setattr(module,'predict_localization',lambda *a:fake)
    found=recognize_instances(g)['candidates']
    assert found and found[0]['face_ids']==list(range(901,907)) and found[0]['bottom_face_ids']==list(range(901,907))
    head['class_thresholds'][13]=None
    assert not recognize_instances(g)['candidates']
