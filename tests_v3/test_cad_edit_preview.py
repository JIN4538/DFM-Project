from copy import deepcopy
import pytest
from dfm.cad_edit_preview import eligible_corner_edit,create_preview,edit_figure
from dfm.cad_edit_pairs import write_step
from tests_v3.test_cad_edit_pairs import cavity


def test_only_single_verified_corner_edit_is_previewed():
    _,pocket=cavity(3)
    edit=dict(field='pocket.0.corner_radius',before=0.,after=1.,cad_face_id=pocket['floor_face_id'])
    report=dict(direction=[0,0,1],plan_recommendation=dict(selected=dict(changes=[edit])),external_feature_recognition=dict(verified_pockets=[pocket]))
    assert eligible_corner_edit(report)['radius']==1.
    broken=deepcopy(report);broken['plan_recommendation']['selected']['changes'].append(dict(field='pocket.0.width',before=1.,after=2.))
    assert eligible_corner_edit(broken) is None
    broken=deepcopy(report);broken['external_feature_recognition']['verified_pockets']=[]
    assert eligible_corner_edit(broken) is None


def test_isolated_preview_exports_mapped_round_faces_and_clear_local_figure(tmp_path):
    from amdfm.io import load_model
    shape,pocket=cavity(4);path=tmp_path/'source.step';write_step(shape,path);raw=path.read_bytes()
    # Re-import face ordinals are checked rather than assumed after STEP export.
    from dfm.cad_graph import read_step_graph
    from dfm.external_features_review import pocket_dimensions
    g=read_step_graph(path)
    group=[m for m in g['measurements'] if abs(m['centroid_mm'][2]-14)<1e-7 or abs(m['centroid_mm'][2]-17)<1e-7]
    p=pocket_dimensions(dict(feature='rectangular_pocket',face_ids=[m['face_id'] for m in group],measured_faces=group),[0,0,1]);p['direction']=[0,0,1]
    modified,audit=create_preview(raw,dict(pocket=p,radius=1.),timeout=50)
    assert raw==path.read_bytes() and modified!=raw
    assert len(audit['rounded_face_ids'])==4
    model=load_model(modified,'after.step');figure=edit_figure(model,audit,after=True)
    colored=[t for t in figure.data if t.name=='수정한 둥근 코너']
    assert len(colored)==1 and len(colored[0].i)>0
    assert figure.layout.scene.xaxis.range[1]-figure.layout.scene.xaxis.range[0]<model.mesh.extents[0]
    before=edit_figure(load_model(raw,'before.step'),audit,after=False)
    assert len([t for t in before.data if '날카로운 코너' in t.name])==4


def test_preview_rejects_empty_and_invalid_source():
    with pytest.raises(ValueError):create_preview(b'',{},timeout=5)
    with pytest.raises(ValueError):create_preview(b'bad CAD',dict(pocket={},radius=1.),timeout=15)


def test_visual_crop_clips_crossing_triangles_instead_of_hiding_the_pocket():
    import numpy as np
    from dfm.cad_edit_preview import clip_triangles
    original=np.array([[[-5.,-5.,0.],[5.,-5.,0.],[0.,5.,0.]]])
    clipped=clip_triangles(original,[-1.,-1.,-1.],[1.,1.,1.])
    assert len(clipped)>0
    assert np.all(clipped>=-1.-1e-12) and np.all(clipped<=1.+1e-12)
    area=np.linalg.norm(np.cross(clipped[:,1]-clipped[:,0],clipped[:,2]-clipped[:,0]),axis=1).sum()/2
    assert area==pytest.approx(4.)
    assert np.array_equal(original,[[[-5.,-5.,0.],[5.,-5.,0.],[0.,5.,0.]]])
