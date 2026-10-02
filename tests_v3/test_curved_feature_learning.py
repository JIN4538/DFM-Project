import numpy as np
import pytest
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox,BRepPrimAPI_MakeCylinder,BRepPrimAPI_MakeSphere
from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.gp import gp_Ax2,gp_Pnt,gp_Dir
from dfm.cad_graph import extract_graph
from dfm.feature_learning import CURVED_MODEL_PATH,CURVED_CLASS_NAMES,load_model,recognize_graph,predict_graph

@pytest.mark.parametrize('shape',[lambda:BRepPrimAPI_MakeBox(30,20,10).Shape(),lambda:BRepPrimAPI_MakeCylinder(6,12).Shape(),lambda:BRepPrimAPI_MakeSphere(7).Shape()])
def test_plain_stock_does_not_become_hole_or_pocket(shape):
    model=load_model(CURVED_MODEL_PATH);r=recognize_graph(extract_graph(shape()),model)
    assert r['status']=='measured' and not r['candidates']

def test_new_25_class_graph_recognizes_a_hole_and_keeps_exact_cad_dimensions():
    block=BRepPrimAPI_MakeBox(40,30,12).Shape()
    cut=BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(20,15,-1),gp_Dir(0,0,1)),3,14).Shape()
    shape=BRepAlgoAPI_Cut(block,cut).Shape();g=extract_graph(shape)
    result=recognize_graph(g,load_model(CURVED_MODEL_PATH))
    holes=[c for c in result['candidates'] if c['feature']=='through_hole']
    assert holes and any(m['radius_mm']==pytest.approx(3.) for h in holes for m in h['measured_faces'])
    assert len(load_model(CURVED_MODEL_PATH)['classes'])==25

def test_freeform_is_rejected_by_analytic_training_domain():
    g=extract_graph(BRepPrimAPI_MakeCylinder(6,12).Shape());g['x'][0,:6]=[0,0,0,0,0,1]
    r=recognize_graph(g,load_model(CURVED_MODEL_PATH));assert r['status']=='outside_training_domain'

def test_curved_feature_probabilities_are_invariant_under_rigid_transform():
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
    from OCP.gp import gp_Trsf
    from scipy.spatial.transform import Rotation
    s=BRepPrimAPI_MakeCylinder(6,12).Shape();r=Rotation.from_euler('xyz',[.3,.7,.2]).as_matrix();t=gp_Trsf()
    t.SetValues(*np.column_stack([r,np.array([4,2,-8])]).ravel())
    a,b=extract_graph(s),extract_graph(BRepBuilderAPI_Transform(s,t,True).Shape());m=load_model(CURVED_MODEL_PATH)
    assert np.allclose(predict_graph(a,m),predict_graph(b,m),atol=2e-5)
