"""Independent topology counterexamples for the native pocket supplement."""
from copy import deepcopy
from pathlib import Path
import json
import numpy as np
import pytest
from amdfm.cad_worker import convert
from amdfm.io import exact_weld
from amdfm.models import Model
from dfm.verified_pockets import measure_pockets, attach_verified_pockets

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def native(tmp_path_factory):
    folder = tmp_path_factory.mktemp('certified-pockets')
    result = {}
    for path in (ROOT/'examples/machining').glob('*.step'):
        target = folder/path.stem
        convert(path, target, .1)
        info = json.loads(Path(str(target)+'.json').read_text(encoding='utf8'))
        faces = info.pop('features')
        info.update(source_format='step', dimensions_confirmed=True)
        with np.load(str(target)+'.npz') as arrays:
            result[path.stem] = Model(exact_weld(arrays['vertices'], arrays['faces']), info,
                faces, arrays['face_ids'].copy(), arrays['body_ids'].copy())
    return result


@pytest.mark.parametrize('name', ['03_rounded_pocket', '06_boss', '07_sealed_cavity',
    '08_open_channel', '09_island_pocket', '10_plain_block', '12_two_solids'])
def test_unsupported_geometry_is_not_certified_as_a_closed_sharp_prism(native, name):
    assert measure_pockets(native[name], [0, 0, 1]) == []


@pytest.mark.parametrize('name,axis,width,depth', [
    ('01_rectangular_pocket', [0, 0, 1], 12., 8.),
    ('02_narrow_deep_pocket', [0, 0, 1], 3., 20.),
    ('11_rotated_pocket', [1, 0, 0], 12., 8.)])
def test_certified_local_dimensions_and_direction(native, name, axis, width, depth):
    found = measure_pockets(native[name], axis)
    assert len(found) == 1
    pocket, candidate = found[0]
    assert pocket['entry_circle_diameter_mm'] == pytest.approx(width)
    assert pocket['wall_height_mm'] == pytest.approx(depth)
    assert candidate['source'] == 'native_closed_prism'
    assert candidate['confidence'] is None
    assert not measure_pockets(native[name], [-v for v in axis])


def test_native_certificate_does_not_relabel_neural_candidates_or_fill_unknowns(native):
    model = native['01_rectangular_pocket']
    candidates = [dict(feature='triangular_pocket', face_ids=[9], confidence=.72)]
    report = dict(direction=[0,0,1], profile={}, findings=[],
        external_feature_recognition=dict(candidates=deepcopy(candidates)))
    attach_verified_pockets(report, model)
    assert report['external_feature_recognition']['candidates'] == candidates
    rows = report['findings'][0]['measurements']['pockets']
    assert rows[0]['width_too_small'] is None
    assert rows[0]['exceeds_flute_length'] is None
    assert rows[0]['exceeds_reach'] is None
    assert len(report['external_feature_recognition']['geometry_candidates']) == 1
    attach_verified_pockets(report, model)
    assert len(report['external_feature_recognition']['verified_pockets']) == 1
    assert len(report['external_feature_recognition']['geometry_candidates']) == 1
    assert len(report['findings']) == 1


def test_uncertain_material_side_cannot_create_a_certificate(native):
    model = deepcopy(native['01_rectangular_pocket'])
    for face in model.cad_features:
        face['material_normal_confirmed'] = False
    assert not measure_pockets(model, [0,0,1])


def test_only_certified_floor_is_removed_from_unresolved_list_and_original_is_preserved(native):
    model = native['01_rectangular_pocket']
    floor = measure_pockets(model,[0,0,1])[0][0]['floor_face_id']
    raw = dict(id='cnc_rectangular_pockets', status='unknown',
        measurements=dict(pockets=[], unresolved_floor_face_ids=[floor,999], incomplete_boundary_face_ids=[]))
    report = dict(direction=[0,0,1],profile={}, findings=[deepcopy(raw)],
        external_feature_recognition=dict(candidates=[]))
    attach_verified_pockets(report,model)
    assert report['native_rectangular_review'] == raw
    assert report['findings'][0]['measurements']['unresolved_floor_face_ids'] == [999]
    assert report['findings'][0]['status'] == 'unknown'
