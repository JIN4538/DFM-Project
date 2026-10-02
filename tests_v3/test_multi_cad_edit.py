from copy import deepcopy
import math
import pytest
from dfm.cad_edit_pairs import write_step,read_shape,bounds
from dfm.multi_cad_edit import round_multiple_corners
from dfm.cad_edit_preview import create_preview,eligible_corner_edit,edit_figure
from scripts.prepare_compound_edit_demo import mixed_cavity,measured_requests,SPECS


@pytest.mark.parametrize('rotated',[False,True])
def test_three_different_pockets_preserve_design_and_match_independent_math(rotated):
    shape=mixed_cavity(rotated)
    requests=measured_requests(shape,rotated)
    original=bounds(shape)
    after,audit=round_multiple_corners(shape,requests)
    before=90*60*20-sum(sides*.5*81*math.sin(2*math.pi/sides)*depth for sides,_,depth,_ in SPECS)
    added=sum((sides/math.tan(math.pi*(sides-2)/(2*sides))-math.pi)*radius**2*depth for sides,_,depth,radius in SPECS)
    assert audit['before_volume_mm3']==pytest.approx(before,abs=1e-6)
    assert audit['measured_material_addition_mm3']==pytest.approx(added,abs=1e-6)
    assert bounds(after)==pytest.approx(original)
    assert audit['edited_pocket_count']==3 and audit['modified_corner_edges']==13
    assert [r['after_corner_radius_mm'] for r in audit['edits']]==[1.,.8,1.5]


def test_exported_step_maps_each_pocket_and_preview_uses_its_own_radius(tmp_path):
    from amdfm.io import load_model
    path=tmp_path/'three.step'
    write_step(mixed_cavity(),path)
    request=dict(pockets=measured_requests(read_shape(path)))
    raw=path.read_bytes()
    modified,audit=create_preview(raw,request,timeout=60)
    assert path.read_bytes()==raw and len(audit['rounded_face_ids'])==13
    model=load_model(modified,'modified.step')
    for expected,edit in zip((3,4,6),audit['edits']):
        assert len(edit['rounded_face_ids'])==expected
        figure=edit_figure(model,edit,after=True)
        assert any(t.name=='수정한 둥근 코너' and len(t.i)>0 for t in figure.data)
        assert figure.layout.scene.xaxis.range[1]-figure.layout.scene.xaxis.range[0]<30
        assert any('실제 위쪽 경계' in t.name for t in figure.data)


def test_shared_source_duplicate_and_partial_proposals_are_rejected():
    shape=mixed_cavity()
    requests=measured_requests(shape)
    with pytest.raises(ValueError,match='share source faces'):
        round_multiple_corners(shape,[requests[0],requests[0]])
    bad=deepcopy(requests);bad[1]['radius']=100.
    with pytest.raises(ValueError):round_multiple_corners(shape,bad)
    for n in (0,9):
        with pytest.raises(ValueError):round_multiple_corners(shape,[requests[0]]*n)
    changes=[dict(field=f'pocket.{i}.corner_radius',before=0.,after=r['radius'],cad_face_id=r['pocket']['floor_face_id']) for i,r in enumerate(requests)]
    report=dict(direction=[0,0,1],plan_recommendation=dict(selected=dict(changes=changes)),
        external_feature_recognition=dict(verified_pockets=[r['pocket'] for r in requests]))
    assert len(eligible_corner_edit(report)['pockets'])==3
    bad=deepcopy(report);bad['plan_recommendation']['selected']['changes'].append(changes[0])
    assert eligible_corner_edit(bad) is None
    bad=deepcopy(report);bad['plan_recommendation']['selected']['changes'][0]['after']=math.nan
    assert eligible_corner_edit(bad) is None


def test_rotated_single_pocket_export_keeps_actual_entry_axis_for_highlighting(tmp_path):
    from amdfm.io import load_model
    path=tmp_path/'rotated.step'
    write_step(mixed_cavity(True),path)
    request=measured_requests(read_shape(path),True)[1]
    modified,audit=create_preview(path.read_bytes(),request,timeout=60)
    assert audit['direction']==[1,0,0]
    figure=edit_figure(load_model(modified,'after.step'),audit,after=True)
    boundary=next(t for t in figure.data if '실제 위쪽 경계' in t.name)
    import numpy as np
    xs=np.asarray(boundary.x,dtype=float)
    assert xs[np.isfinite(xs)]==pytest.approx([20.]*np.isfinite(xs).sum(),abs=1e-7)
    camera=figure.layout.scene.camera
    assert camera.eye.x==pytest.approx(2.4)
    assert camera.up.x==pytest.approx(0.)
    assert camera.up.z==pytest.approx(1.)
