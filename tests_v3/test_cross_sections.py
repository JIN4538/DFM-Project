import numpy as np
import pytest
import trimesh

from amdfm.analysis import review
from amdfm.cross_sections import inspect_cross_sections
from amdfm.detail import attach_detail,run_detail
from amdfm.models import Model
from amdfm.profiles import Profile


def model(mesh):
    return Model(mesh,dict(source_format='stl',unit_status='user_confirmed',surface_component_count=1))


def test_box_sections_have_analytic_area_perimeter_volume_and_no_changes():
    result=inspect_cross_sections(trimesh.creation.box(extents=[10,5,4]),16)
    assert result['status']=='complete'
    assert result['sampled_max_area_mm2']==pytest.approx(50)
    assert result['sampled_max_perimeter_mm']==pytest.approx(30)
    assert result['sampled_max_area_per_perimeter_mm']==pytest.approx(50/30)
    assert result['volume_midpoint_estimate_mm3']==pytest.approx(200)
    assert result['rows'][0]['symmetric_change_from_previous_mm2'] is None
    assert all(r['symmetric_change_from_previous_mm2']==0 for r in result['rows'][1:])


def test_annular_mesh_loops_are_not_claimed_to_be_a_suction_cup():
    count=64
    mesh=trimesh.creation.annulus(r_min=2,r_max=5,height=10,sections=count)
    result=inspect_cross_sections(mesh,8)
    area=count/2*np.sin(2*np.pi/count)*(25-4)
    perimeter=2*count*np.sin(np.pi/count)*7
    assert result['status']=='complete'
    assert result['sampled_max_area_mm2']==pytest.approx(area,abs=1e-7)
    assert result['sampled_max_perimeter_mm']==pytest.approx(perimeter,abs=1e-7)
    assert all(r['internal_loops']==1 for r in result['rows'])
    assert all(r['material_regions']==1 for r in result['rows'])
    assert 'suction certification' in result['scope']
    assert 'suction_risk' not in result


@pytest.mark.parametrize('process',['MEX','VPP','PBF_POLYMER','PBF_METAL'])
@pytest.mark.parametrize('sampling',['uniform','events'])
def test_sections_work_for_every_process_without_fdm_rules(process,sampling):
    m=model(trimesh.creation.box(extents=[10,5,4]))
    p=Profile(process=process,build_volume_mm=None)
    r=review(m,p,[1,0,0],compare=False)
    d=run_detail(m,p,[1,0,0],mode='sections',sample_count=8,sampling=sampling)
    assert d['status']=='complete'
    assert d['sampled_max_area_mm2']==pytest.approx(20)
    if sampling=='uniform':
        assert d['volume_midpoint_estimate_mm3']==pytest.approx(200)
        assert d['rows'][0]['z_mm']==pytest.approx(.625)
    else:
        assert d['volume_quadrature_estimate_mm3']==pytest.approx(200)
        assert d['complete_samples']==2
        assert d['rows'][0]['z_mm']==pytest.approx(5*(1-1/np.sqrt(3)))
    assert 'thin_candidate_area_mm2' not in d['rows'][0]
    assert attach_detail(r,d)['details']['sections']['coordinate_frame']=='build_mm'


@pytest.mark.parametrize('sampling,max_events',[('bad',8192),('events',True),('events',8193),('events',float('nan'))])
def test_invalid_section_method_or_event_budget_rejected(sampling,max_events):
    with pytest.raises(ValueError):
        run_detail(model(trimesh.creation.box()),Profile(),mode='sections',sampling=sampling,max_event_samples=max_events)


def test_event_budget_unknown_preserves_method_in_attached_report():
    mesh=trimesh.creation.box(extents=[10,5,4])
    m=model(mesh);p=Profile(process='VPP')
    report=review(m,p,[1,1,1],compare=False)
    detail=run_detail(m,p,[1,1,1],mode='sections',sampling='events',max_event_samples=2)
    assert detail['status']=='unknown' and detail['sampling']=='events'
    assert detail['volume_quadrature_estimate_mm3'] is None
    finding=next(f for f in attach_detail(report,detail)['findings'] if f['id']=='sections')
    assert finding['status']=='unknown'


def test_partial_budget_does_not_become_total_volume_or_zero():
    r=inspect_cross_sections(trimesh.creation.box(extents=[10,5,4]),16,max_total_segments=20)
    assert r['status']=='partial'
    assert 0<r['complete_samples']<16
    assert r['volume_midpoint_estimate_mm3'] is None


def test_open_surface_does_not_claim_material_sections():
    mesh=trimesh.creation.box();mesh.update_faces(np.arange(11))
    r=inspect_cross_sections(mesh,16)
    assert r['status']=='unknown'
    assert r['sampled_max_area_mm2'] is None


@pytest.mark.parametrize('n',[0,1,1025,2.5,True,float('nan'),float('inf')])
def test_invalid_sample_count_is_rejected(n):
    with pytest.raises(ValueError):inspect_cross_sections(trimesh.creation.box(),n)


def test_sheared_prism_same_area_still_records_shape_change():
    mesh=trimesh.creation.box(extents=[10,5,4])
    mesh.vertices[:,0]+=mesh.vertices[:,2]
    r=inspect_cross_sections(mesh,4)
    # Consecutive sections translate 1 mm: two strips of area 1*5.
    assert r['status']=='complete'
    assert all(row['area_mm2']==pytest.approx(50) for row in r['rows'])
    assert all(row['symmetric_change_from_previous_mm2']==pytest.approx(10) for row in r['rows'][1:])


@pytest.mark.parametrize('mode',['wall','sections','layers'])
def test_closed_shell_without_cad_material_does_not_become_a_solid(mode):
    m=Model(trimesh.creation.box(),dict(source_format='step',cad_geometry_kind='surface',solid_count=0))
    result=run_detail(m,Profile(),mode=mode)
    assert result['status']=='unknown'
    assert '재료 내부' in result['reason']
