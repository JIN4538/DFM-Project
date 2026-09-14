"""Cross-check display semantics without erasing small genuine components."""
from pathlib import Path
import unittest
from unittest.mock import patch,PropertyMock
import numpy as np
import shapely as sh
import trimesh
from src.core.layer_regions import classify_difference_regions,comparison_scope
from src.core.layer_review import inspect_layers
from src.core.sections import section_mesh
from src.core.section_index import WindingLimit,FaceZIndex
from src.core.mesh_diagnostics import mesh_digest
from src.core.model_loader import load_model


def box(size=(4,3,2),at=(0,0,0)):
    m=trimesh.creation.box(size);m.apply_translation(at);return m


def difference(material,reference,prefix):
    return classify_difference_regions(material,reference,.4,1e-10,prefix)


class LayerReview26(unittest.TestCase):
    def test_small_partial_residuals_stay_recorded_for_both_checks(self):
        material=sh.box(0,0,1,1);reference=sh.box(0,0,1-1e-4,1)
        for prefix in ('unsupported','single_layer'):
            major,minor,data=difference(material,reference,prefix)
            self.assertEqual(len(major),0);self.assertEqual(len(minor),1)
            self.assertAlmostEqual(data[prefix+'_candidate_area_mm2'],1e-4)
            self.assertEqual(data[prefix+'_candidate_area_mm2'],data[prefix+'_detail_area_mm2'])
            self.assertFalse(data[prefix+'_details'][0]['whole_component_affected'])

    def test_whole_small_component_is_prominent_for_both_checks(self):
        material=sh.box(0,0,.02,.02)
        for prefix in ('unsupported','single_layer'):
            major,minor,data=difference(material,sh.GeometryCollection(),prefix)
            self.assertEqual(len(major),1);self.assertFalse(minor)
            self.assertTrue(data[prefix+'_details'][0]['whole_component_affected'])
            self.assertLess(data[prefix+'_area_mm2'],data[prefix+'_display_floor_mm2'])

    def test_boundary_contact_is_not_positive_area_support(self):
        material=sh.box(0,0,.02,.02);reference=sh.box(-1,0,0,.02)
        _,_,data=difference(material,reference,'unsupported')
        self.assertTrue(data['unsupported_details'][0]['whole_component_affected'])
        self.assertAlmostEqual(data['unsupported_area_mm2'],.0004)

    def test_tiny_positive_contact_does_not_become_wholly_missing(self):
        material=sh.box(0,0,.02,.02);reference=sh.box(0,0,1e-5,.02)
        _,_,data=difference(material,reference,'single_layer')
        self.assertFalse(data['single_layer_details'][0]['whole_component_affected'])
        self.assertEqual(data['single_layer_area_mm2'],0)
        self.assertGreater(data['single_layer_detail_area_mm2'],0)

    def test_exact_display_threshold_uses_inclusive_comparison(self):
        floor=.01*.4**2
        material=sh.box(0,0,1,1);reference=sh.box(floor,0,1,1)
        _,_,data=difference(material,reference,'unsupported')
        self.assertAlmostEqual(data['unsupported_area_mm2'],floor)
        self.assertEqual(data['unsupported_detail_area_mm2'],0)

    def test_details_cap_preserves_support_and_single_layer_totals(self):
        material=sh.union_all([sh.box(i,0,i+.02,.02) for i in range(60)])
        for prefix in ('unsupported','single_layer'):
            _,_,data=difference(material,sh.GeometryCollection(),prefix)
            self.assertEqual(len(data[prefix+'_details']),50)
            self.assertTrue(data[prefix+'_details_truncated'])
            self.assertEqual(data[prefix+'_candidate_regions'],60)
            self.assertAlmostEqual(data[prefix+'_candidate_area_mm2'],.024)

    def test_tiny_floating_plate_survives_both_layer_priorities(self):
        m=trimesh.util.concatenate([box((4,3,.2)),box((.02,.02,.2),(5,0,.4))])
        r=inspect_layers(m)
        self.assertEqual(r['status'],'complete')
        for index in (2,3):
            self.assertEqual(r['checks'][index]['status'],'risk')
        tiny=r['layers'][-1]
        self.assertAlmostEqual(tiny['unsupported_area_mm2'],.0004)
        self.assertAlmostEqual(tiny['single_layer_area_mm2'],.0004)

    def test_unknown_neighbor_stays_unresolved_without_false_whole_promotion(self):
        broken=box();broken.update_faces(broken.face_normals[:,0]<.9)
        good=box(at=(20,0,0));m=trimesh.util.concatenate([broken,good])
        r=inspect_layers(m)
        self.assertEqual(r['status'],'partial')
        for c in r['checks'][1:]:
            self.assertEqual(c['status'],'unresolved')
            self.assertEqual(c['fully_measured_layers'],0)
        current=sh.box(0,0,1,1)
        unknown={'complete':False,'diagnostics':{'unknown_bounds_mm':[[0,0,2,2]]}}
        self.assertTrue(comparison_scope(current,[unknown]).is_empty)

    def test_failed_difference_measurement_is_not_zero_or_details_only(self):
        with patch('src.core.layer_review.classify_difference_regions',side_effect=RuntimeError('injected')):
            r=inspect_layers(box())
        self.assertEqual(r['status'],'partial')
        for c in r['checks'][2:]:
            self.assertEqual(c['status'],'unresolved')
            self.assertIsNone(c['sum_mm2']);self.assertIsNone(c['candidate_sum_mm2']);self.assertIsNone(c['detail_sum_mm2'])

    def test_no_material_has_no_measured_candidate_totals(self):
        a=box();b=a.copy();b.invert();r=inspect_layers(trimesh.util.concatenate([a,b]))
        self.assertEqual(r['status'],'unavailable')
        for c in r['checks'][1:]:
            self.assertIsNone(c['candidate_sum_mm2']);self.assertEqual(c['status'],'unresolved')

    def test_cached_scale_preserves_grid_and_section_geometry(self):
        m=trimesh.creation.icosphere(subdivisions=2,radius=10);m.apply_translation([80,-5,7])
        index=FaceZIndex(m)
        a=section_mesh(m,[0,0,7.123],[0,0,1])
        b=section_mesh(m,[0,0,7.123],[0,0,1],mesh_scale_mm=index.scale_mm)
        self.assertEqual(a.diagnostics['grid_mm'],b.diagnostics['grid_mm'])
        self.assertLess(a.material.symmetric_difference(b.material).area,1e-12)

    def test_cached_section_does_not_read_extents(self):
        m=box();scale=float(max(m.extents))
        with patch.object(trimesh.Trimesh,'extents',new_callable=PropertyMock,side_effect=AssertionError('uncached extent')):
            r=section_mesh(m,[0,0,.1],[0,0,1],mesh_scale_mm=scale)
        self.assertTrue(r.diagnostics['complete'])

    def test_every_layer_and_retry_receives_its_current_mesh_scale(self):
        m=box();m.update_faces(m.face_normals[:,0]<.9)
        with patch('src.core.layer_review.section_mesh',wraps=section_mesh) as calls:
            inspect_layers(m)
        self.assertGreater(calls.call_count,10)
        for call in calls.call_args_list:self.assertEqual(call.kwargs['mesh_scale_mm'],4.)

    def test_invalid_cached_scale_is_rejected(self):
        for value in (-1,float('inf'),float('nan')):
            with self.assertRaises(ValueError):section_mesh(box(),[0,0,0],[0,0,1],mesh_scale_mm=value)

    def test_limit_before_winding_index_has_a_safe_diagnostic(self):
        with patch('src.core.sections.component_rings',side_effect=WindingLimit('early injected limit')):
            result=section_mesh(box(),[0,0,.1],[0,0,1])
        self.assertFalse(result.diagnostics['complete'])
        self.assertEqual(result.diagnostics['winding_tests'],0)
        self.assertIn('early injected',result.diagnostics['reason'])

    def test_nist_single_layer_candidates_are_retained_as_details(self):
        path=Path(__file__).resolve().parents[1]/'cura_run/NIST_Test_Artifact_online__posZ.stl'
        m=load_model(str(path))['mesh'];before=mesh_digest(m);r=inspect_layers(m)
        self.assertEqual(r['status'],'complete');self.assertEqual(mesh_digest(m),before)
        c=r['checks'][3]
        self.assertEqual(c['status'],'details_only');self.assertEqual(c['risk_layers'],0)
        self.assertEqual(c['detail_layers'],61)
        self.assertAlmostEqual(c['candidate_sum_mm2'],.004140852844466045,places=10)
        self.assertEqual(c['candidate_sum_mm2'],c['detail_sum_mm2'])
        support=r['checks'][2]
        self.assertEqual(support['status'],'risk')
        self.assertAlmostEqual(support['candidate_sum_mm2'],61.053961686345595,places=8)
        self.assertAlmostEqual(support['candidate_sum_mm2'],support['sum_mm2']+support['detail_sum_mm2'],places=10)


if __name__=='__main__':unittest.main()
