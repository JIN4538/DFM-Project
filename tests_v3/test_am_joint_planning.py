from copy import deepcopy
import pytest
from dfm.am_joint_planning import combine_am_plan,direction_result
from dfm.conclusion import change_text

def inputs(complete=True,transverse=0):
    report=dict(profile=dict(process='MEX',minimum_wall_mm=1.2,minimum_hole_mm=3.),
        details=dict(wall=dict(status='measured' if complete else 'partial',measurements=dict(minimum_mm=.3,
            valid_samples=2,requested_samples=2 if complete else 3,missing_samples=0 if complete else 1,
            samples=[dict(normal_chord_mm=.3,source_face=1),dict(normal_chord_mm=.8,source_face=2)]))),
        findings=[dict(id='cad_holes',status='attention',measurements=dict(transverse_inner_face_count=transverse,
            cylindrical_faces=[dict(face_id=7,role='inner',diameter_mm=2.),dict(face_id=8,role='outer',diameter_mm=1.)]))])
    p=dict(id='orientation:+Z',keep_current=True,changes=[],title='현재 방향 유지',evidence=[],remaining=[],
           covered_finding_ids=['overhang'],remaining_finding_ids=[],orientation=dict(name='+Z',direction=[0,0,1]),score=0.)
    return report,dict(selected=p,ranking=[deepcopy(p)],alternatives=[],status='keep')

def test_measured_edits_are_one_plan_not_duplicate_actions():
    report,result=inputs();before=deepcopy([report,result]);out=combine_am_plan(report,result);p=out['selected']
    assert [c['field'] for c in p['changes']]==['minimum_wall_mm','diameter_mm']
    assert p['changes'][0]['after']==1.2 and p['changes'][1]['cad_face_id']==7
    assert '벽 보강' in p['title'] and '구멍 확대' in p['title']
    assert p['direction_keep_current'] is True and p['keep_current'] is False
    assert p['cad_regenerated'] is False and [report,result]==before
    assert '목표' in change_text(p['changes'][0])

def test_partial_and_transverse_scope_survives_numeric_edits():
    r,p=inputs(complete=False,transverse=2);out=combine_am_plan(r,p)['selected']
    assert set(out['remaining_finding_ids'])>= {'wall','cad_holes'}
    assert '벽 미측정 구간' in out['remaining'] and '구멍 축 방향·천장 형상' in out['remaining']

@pytest.mark.parametrize('bad',[None,0,float('nan'),float('inf'),True,-1])
def test_invalid_criteria_do_not_create_numeric_edits(bad):
    r,p=inputs();r['profile'].update(minimum_wall_mm=bad,minimum_hole_mm=bad)
    assert combine_am_plan(r,p)==p

def test_unknown_material_side_not_assumed_to_be_a_hole():
    r,p=inputs();r['findings'][0]['measurements']['cylindrical_faces'][0]['role']='unknown'
    assert not any(c['field']=='diameter_mm' for c in combine_am_plan(r,p)['selected']['changes'])

def test_no_measurements_do_not_create_a_wall_edit():
    r,p=inputs();r['details']={};r['profile']['minimum_hole_mm']=None
    assert combine_am_plan(r,p)==p
