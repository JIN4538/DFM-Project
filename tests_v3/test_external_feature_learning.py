"""Construction dimensions and transform invariance, independent of labels."""
import json
import numpy as np
import pytest
from dfm.cad_graph import extract_graph
from dfm.feature_learning import load_model, predict_graph, recognize_graph
from dfm.external_features_review import pocket_dimensions

def pocket_shape(sides=4,scale=1.,rotation=None):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox,BRepPrimAPI_MakePrism
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakePolygon,BRepBuilderAPI_MakeFace,BRepBuilderAPI_Transform
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
    from OCP.gp import gp_Pnt,gp_Vec,gp_Trsf
    points=([(8,7),(26,7),(26,19),(8,19)] if sides==4 else
      [(20+7*np.cos(t),15+7*np.sin(t)) for t in np.linspace(0,2*np.pi,sides,endpoint=False)])
    poly=BRepBuilderAPI_MakePolygon()
    for x,y in points:poly.Add(gp_Pnt(x,y,4))
    poly.Close();floor=BRepBuilderAPI_MakeFace(poly.Wire()).Face()
    cutter=BRepPrimAPI_MakePrism(floor,gp_Vec(0,0,20)).Shape()
    cut=BRepAlgoAPI_Cut(BRepPrimAPI_MakeBox(40,30,12).Shape(),cutter);cut.Build();shape=cut.Shape()
    if rotation is not None or scale!=1:
        r=np.eye(3) if rotation is None else rotation
        t=gp_Trsf();t.SetValues(*(np.column_stack([r*scale,np.array([5.,-2.,3.])]).ravel()))
        shape=BRepBuilderAPI_Transform(shape,t,True).Shape()
    return shape

def pocket_graph(sides=4,scale=1.,rotation=None):
    return extract_graph(pocket_shape(sides,scale,rotation))

@pytest.mark.parametrize('sides,feature',[(3,'triangular_pocket'),(4,'rectangular_pocket'),(6,'6sides_pocket')])
def test_external_labels_locate_independently_constructed_pockets(sides,feature):
    graph=pocket_graph(sides)
    candidates=recognize_graph(graph)['candidates']
    verified=[pocket_dimensions(c,[0,0,1]) for c in candidates if c['feature']==feature]
    verified=[d for d in verified if d]
    assert len(verified)==1
    assert verified[0]['wall_height_mm']==pytest.approx(8)
    if sides==4:
        assert verified[0]['width_mm']==pytest.approx(12)
        assert verified[0]['entry_circle_diameter_mm']==pytest.approx(12)
    if sides==3:
        assert verified[0]['width_mm']==pytest.approx(10.5)
        assert verified[0]['entry_circle_diameter_mm']==pytest.approx(7)
    if sides==6:
        assert verified[0]['width_mm']==pytest.approx(7*np.sqrt(3))
        assert verified[0]['entry_circle_diameter_mm']==pytest.approx(7*np.sqrt(3))

def test_predictions_do_not_depend_on_cad_scale_rotation_or_translation():
    from scipy.spatial.transform import Rotation
    r=Rotation.from_euler('xyz',[.47,.22,.73]).as_matrix()
    a=pocket_graph();b=pocket_graph(scale=2.5,rotation=r)
    assert a['edges'].tolist()==b['edges'].tolist()
    assert np.allclose(a['x'],b['x'],atol=2e-6)
    assert np.allclose(predict_graph(a),predict_graph(b),atol=2e-4)
    candidate=next(c for c in recognize_graph(b)['candidates'] if c['feature']=='rectangular_pocket')
    exact=pocket_dimensions(candidate,r@[0,0,1])
    assert exact['width_mm']==pytest.approx(30)
    assert exact['wall_height_mm']==pytest.approx(20)
    assert pocket_dimensions(candidate,-r@[0,0,1]) is None
    candidate['measured_faces'].pop()
    assert pocket_dimensions(candidate,r@[0,0,1]) is None

def test_curved_model_is_not_forced_into_planar_training_classes():
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
    result=recognize_graph(extract_graph(BRepPrimAPI_MakeCylinder(5,10).Shape()))
    assert result['status']=='outside_training_domain'
    assert not result['candidates']

def test_unmodified_box_has_no_machining_feature_candidate():
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    assert not recognize_graph(extract_graph(BRepPrimAPI_MakeBox(40,30,12).Shape()))['candidates']

def test_feature_model_checksum_is_required(tmp_path):
    from dfm.feature_learning import MODEL_PATH
    target=tmp_path/'model.json';target.write_bytes(MODEL_PATH.read_bytes()+b' ')
    target.with_suffix('.manifest.json').write_bytes(MODEL_PATH.with_suffix('.manifest.json').read_bytes())
    with pytest.raises(ValueError,match='checksum'):load_model(target)

@pytest.mark.parametrize('sides',[3,6])
def test_full_step_pipeline_adds_real_corner_action_and_exports_evidence(sides,tmp_path):
    from amdfm.io import load_model
    from dfm.machining import MachiningProfile,review_machining
    from dfm.external_features_review import attach_external_features
    from dfm.conclusion import summarize_conclusion
    from dfm.machining_view import machining_html
    from OCP.STEPControl import STEPControl_Writer,STEPControl_AsIs
    source=tmp_path/'independent.step';writer=STEPControl_Writer();writer.Transfer(pocket_shape(sides),STEPControl_AsIs);writer.Write(str(source))
    model=load_model(source.read_bytes(),source.name)
    report=review_machining(model,MachiningProfile(tool_diameter_mm=5.,flute_length_mm=6.,reach_mm=10.),visibility=False)
    attach_external_features(report,model)
    finding=next(f for f in report['findings'] if f['id']=='cnc_learned_pockets')
    assert finding['status']=='attention'
    assert finding['face_indices']
    assert finding['measurements']['pockets'][0]['wall_height_mm']==pytest.approx(8.)
    assert '날 길이' in ' '.join(finding['measurements']['pockets'][0]['problems'])
    assert finding['measurements']['pockets'][0]['internal_corner_radius_mm']==0.
    summary=summarize_conclusion(report)
    assert any(i['id']=='cnc_learned_pockets' for i in summary['issues'])
    assert 'MFCAD' in machining_html(report,model)

def test_triangle_caliper_width_must_not_clear_an_oversized_tool():
    from types import SimpleNamespace
    from dfm.external_features_review import attach_external_features
    graph=pocket_graph(3);record=recognize_graph(graph);record['body_id']=1
    model=SimpleNamespace(metadata={'external_feature_recognition':[record]},face_ids=np.array([m['face_id'] for m in graph['measurements']]))
    report=dict(input={'solid_count':1},direction=[0,0,1],profile=dict(tool_diameter_mm=9.,flute_length_mm=10.,reach_mm=12.),findings=[])
    attach_external_features(report,model)
    finding=report['findings'][0];pocket=finding['measurements']['pockets'][0]
    assert pocket['width_mm']>9.>pocket['entry_circle_diameter_mm']
    assert pocket['width_too_small'] is True
    assert '7 mm보다 작은 공구' in finding['action']
    assert 'R 4.5' not in finding['action']

def test_triangular_pocket_fills_missing_tool_from_verified_entry_circle(tmp_path):
    from OCP.STEPControl import STEPControl_Writer,STEPControl_AsIs
    from amdfm.io import load_model
    from dfm.machining import MachiningProfile
    from dfm.tool_recommendation import review_with_tool_recommendation
    path=tmp_path/'triangle.step';writer=STEPControl_Writer();writer.Transfer(pocket_shape(3),STEPControl_AsIs);writer.Write(str(path))
    model=load_model(path.read_bytes(),path.name)
    report=review_with_tool_recommendation(model,MachiningProfile())
    tool=report['tool_recommendation'];assert tool['values']['tool_diameter_mm']==pytest.approx(5.6)
    assert tool['values']['flute_length_mm']==pytest.approx(9.)
    assert any(c['kind']=='verified_polygon_pocket' for c in tool['constraints'])
    assert any(c['suggested_minimum_radius_mm']==pytest.approx(2.8) for c in tool['geometry_changes'])
    assert len([f for f in report['findings'] if f['id']=='cnc_learned_pockets'])==1
