from copy import deepcopy
import hashlib
import json
from pathlib import Path
import numpy as np
import pytest
from dfm.edit_learning import descriptor,features,predict,load_model,candidate_order
from dfm.cad_graph import extract_graph
from dfm.edit_reinspection import inspect_export
from dfm.cad_edit_pairs import round_corners,write_step,read_shape
from tests_v3.test_cad_edit_pairs import cavity


def test_geometry_surrogate_is_finite_deterministic_and_cannot_override_constraints():
    shape,pocket=cavity(3);p=descriptor(pocket,extract_graph(shape)['measurements'])
    x=features(p,1.);y=predict([x,x])
    assert all(np.isfinite(a).all() for a in y.values())
    assert y['validity'][0]==y['validity'][1] and 0<=y['validity'][0]<=1
    order,audit=candidate_order(p,[.5,1.,2.],minimum_radius=.9,max_radius=1.1)
    assert order==[1] and audit['model_sha256']
    assert candidate_order(p,[.5],minimum_radius=1.)[0]==[]
    with pytest.raises(ValueError):candidate_order(p,[float('nan')])


def test_exported_measurements_reject_forged_corner_and_changed_depth(tmp_path):
    shape,p=cavity(4);after,audit=round_corners(shape,p,1.)
    path=tmp_path/'after.step';write_step(after,path);exported=read_shape(path)
    graph=extract_graph(exported);audit['rounded_face_ids']=[r['face_id'] for r in graph['measurements'] if r['surface_kind']==1]
    measured=inspect_export(shape,exported,[dict(pocket=p,radius=1.)],audit)
    assert measured['status']=='verified' and measured['pockets'][0]['radius_after_mm']==pytest.approx(1.)
    assert measured['pockets'][0]['depth_after_mm']==pytest.approx(6.)
    with pytest.raises(ValueError):inspect_export(shape,exported,[dict(pocket=p,radius=1.1)],audit)
    forged=deepcopy(p);forged['wall_height_mm']=7.
    with pytest.raises(ValueError):inspect_export(shape,exported,[dict(pocket=forged,radius=1.)],audit)


def test_invalid_network_tensor_is_rejected_even_if_checksum_matches(tmp_path):
    root=Path(__file__).resolve().parents[1];model=json.loads((root/'data/models/cad_edit_surrogate_v1.json').read_text())
    model['networks']['validity']['scale'][0]=0.
    path=tmp_path/'broken.json';raw=json.dumps(model).encode();path.write_bytes(raw)
    path.with_suffix('.manifest.json').write_text(json.dumps(dict(model_sha256=hashlib.sha256(raw).hexdigest())))
    with pytest.raises(ValueError,match='normalization'):load_model(path)
