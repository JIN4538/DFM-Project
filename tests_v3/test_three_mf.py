import io
from zipfile import ZipFile

import numpy as np
import pytest
import trimesh

from amdfm.io import load_model
from amdfm.analysis import review
from amdfm.profiles import Profile
from amdfm.three_mf import CORE,PROD,MODEL_REL


def payload(*,unit="millimeter",transform="",production=False,mirror=False,required="",component="",mesh_xml=None):
    box=trimesh.creation.box(extents=[2,3,4])
    vertices="".join(f'<vertex x="{x}" y="{y}" z="{z}"/>' for x,y,z in box.vertices)
    triangles="".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a,b,c in box.faces)
    geometry=mesh_xml or f'<mesh><vertices>{vertices}</vertices><triangles>{triangles}</triangles></mesh>'
    head=f'<model xmlns="{CORE}" xmlns:p="{PROD}" xmlns:q="urn:unsupported" unit="{unit}" requiredextensions="{required}">'
    if mirror: transform="-1 0 0 0 1 0 0 0 1 10 20 30"
    body=f'<object id="1">{geometry}</object>'
    external={}
    if production:
        external['3D/Objects/part.model']=head+f'<resources>{body}</resources><build/></model>'
        body='<object id="2"><components><component objectid="1" p:path="/3D/Objects/part.model" transform="1 0 0 0 1 0 0 0 1 5 0 0"/></components></object>'
    if component:body=component
    root=head+f'<resources>{body}</resources><build><item objectid="{2 if production else 1}" transform="{transform}"/></build></model>'
    buff=io.BytesIO()
    with ZipFile(buff,'w') as z:
        z.writestr('_rels/.rels',f'<Relationships><Relationship Type="{MODEL_REL}" Target="/3D/model.model"/></Relationships>')
        z.writestr('3D/model.model',root)
        for name,text in external.items():z.writestr(name,text)
    return buff.getvalue()


@pytest.mark.parametrize("unit,scale",[("millimeter",1.),("inch",25.4),("micron",.001),("meter",1000.)])
def test_declared_3mf_unit_is_used(unit,scale):
    m=load_model(payload(unit=unit),'box.3mf')
    assert m.mesh.extents==pytest.approx(np.array([2,3,4])*scale)
    assert m.mesh.volume==pytest.approx(24*scale**3)
    assert m.metadata['unit_status']=='declared_in_3mf'


def test_production_path_transform_order_and_rotation():
    # Component translates +5X; build then rotates +90 around Z and translates.
    m=load_model(payload(production=True,required="p",transform="0 1 0 -1 0 0 0 0 1 10 20 30"),'nested.3mf')
    assert m.mesh.extents==pytest.approx([3,2,4])
    assert m.mesh.bounds.mean(axis=0)==pytest.approx([10,25,30])
    assert m.mesh.volume==pytest.approx(24)


def test_mirrored_transform_preserves_outward_material_orientation():
    m=load_model(payload(mirror=True),'mirror.3mf')
    assert m.mesh.volume==pytest.approx(24)
    assert m.mesh.is_winding_consistent
    assert m.mesh.bounds.mean(axis=0)==pytest.approx([10,20,30])
    assert review(m,Profile(),compare=False)['geometry']['mesh_signed_volume_mm3']==pytest.approx(24)


@pytest.mark.parametrize("kwargs",[
    {'required':'q'},{'unit':'parsec'}, {'transform':'1 2 3'},
    {'transform':'1 0 0 0 nan 0 0 0 1 0 0 0'},
    {'component':'<object id="1"><components><component objectid="1"/></components></object>'},
    {'component':'<object id="1"><components><component objectid="99"/></components></object>'},
])
def test_unsupported_or_broken_3mf_is_an_explicit_error(kwargs):
    with pytest.raises(ValueError):load_model(payload(**kwargs),'bad.3mf')


def test_referenced_model_must_remain_inside_package():
    component='<object id="1"><components><component objectid="9" p:path="https://example.com/model"/></components></object>'
    with pytest.raises(ValueError,match="내부 경로"):load_model(payload(component=component),'external.3mf')
