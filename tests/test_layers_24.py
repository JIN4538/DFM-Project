"""Independent geometric contracts for the FDM section review."""
import json
import unittest
from unittest.mock import patch

import numpy as np
import trimesh

from src.core.layer_review import inspect_layers
from src.core.mesh_diagnostics import mesh_digest
from src.core.sections import section_mesh, opening_residual
from src.core.reproducibility import json_text
from src.processes.additive import AMRuleEngine


def box(size=(4, 3, 2)):
    return trimesh.creation.box(size)


class LayerReview24(unittest.TestCase):
    def test_box_area_volume_and_no_false_risk(self):
        r = inspect_layers(box())
        self.assertEqual(r['status'], 'complete')
        self.assertEqual(r['expected_layers'], 10)
        self.assertAlmostEqual(r['volume_estimate_mm3'], 24, places=7)
        for c in r['checks']:
            self.assertEqual(c['status'], 'clear_in_layers')

    def test_last_partial_layer_has_correct_volume(self):
        r = inspect_layers(box((4, 3, 2.05)))
        self.assertEqual(r['expected_layers'], 11)
        self.assertAlmostEqual(r['layers'][-1]['thickness_mm'], .05)
        self.assertAlmostEqual(r['volume_estimate_mm3'], 24.6, places=7)

    def test_cavity_is_not_filled(self):
        outside=box((4,4,4)); inside=box((2,2,2)); inside.invert()
        m=trimesh.util.concatenate([outside,inside])
        s=section_mesh(m,[0,0,0],[0,0,1])
        self.assertTrue(s.diagnostics['complete'])
        self.assertAlmostEqual(s.material.area,12)
        r=inspect_layers(m)
        self.assertAlmostEqual(r['volume_estimate_mm3'],56,places=6)

    def test_overlapping_material_is_counted_once(self):
        a=box((4,4,4)); b=a.copy(); b.apply_translation([2,0,0])
        m=trimesh.util.concatenate([a,b])
        r=inspect_layers(m)
        self.assertEqual(r['status'],'complete')
        self.assertAlmostEqual(r['volume_estimate_mm3'],96,places=6)

    def test_global_winding_reversal_preserves_material(self):
        m=box(); a=inspect_layers(m); m.invert(); b=inspect_layers(m)
        self.assertEqual(b['status'],'complete')
        self.assertAlmostEqual(a['volume_estimate_mm3'],b['volume_estimate_mm3'])

    def test_missing_vertical_wall_stays_unresolved(self):
        m=box(); m.update_faces(m.face_normals[:,0]<.9)
        r=inspect_layers(m)
        self.assertNotEqual(r['status'],'complete')
        self.assertIsNone(r['volume_estimate_mm3'])
        self.assertEqual(r['checks'][0]['status'],'unresolved')

    def test_open_cavity_wall_is_not_discarded_as_internal_seam(self):
        outer=box((4,4,4)); inner=box((2,2,2)); inner.invert()
        inner.update_faces(inner.face_normals[:,0]<.9)
        r=inspect_layers(trimesh.util.concatenate([outer,inner]))
        self.assertNotEqual(r['status'],'complete')
        self.assertIsNone(r['volume_estimate_mm3'])

    def test_open_top_allows_sections_but_never_unblocks_solid_grade(self):
        m=box(); m.update_faces(m.face_normals[:,2]<.9)
        r=AMRuleEngine().evaluate(m)
        self.assertEqual(r.layer_review['status'],'complete')
        self.assertFalse(r.feasible)
        self.assertIsNone(r.total_score)
        self.assertEqual(r.evaluation_status,'invalid_input')

    def test_vertical_thin_wall_is_detected(self):
        r=inspect_layers(box((4,.3,2)))
        c=r['checks'][1]
        self.assertEqual(c['status'],'risk')
        self.assertEqual(c['risk_layers'],10)

    def test_small_cylindrical_pin_is_not_removed_by_area_fraction(self):
        base=box((8,8,2)); pin=trimesh.creation.cylinder(radius=.15,height=2,sections=32)
        pin.apply_translation([0,0,1.9])
        m=trimesh.boolean.union([base,pin],engine='manifold')
        r=inspect_layers(m)
        self.assertEqual(r['status'],'complete')
        self.assertGreater(r['checks'][1]['risk_layers'],0)

    def test_triangular_pin_is_detected_even_if_its_faces_are_adjacent(self):
        m=trimesh.creation.cylinder(radius=.15,height=2,sections=3)
        r=inspect_layers(m)
        self.assertEqual(r['status'],'complete')
        self.assertEqual(r['checks'][1]['risk_layers'],10)

    def test_single_thin_horizontal_layer_is_not_called_thick(self):
        r=inspect_layers(box((4,3,.15)))
        self.assertEqual(r['checks'][1]['status'],'clear_in_layers')
        self.assertEqual(r['checks'][3]['status'],'risk')
        self.assertAlmostEqual(r['checks'][3]['sum_mm2'],12,places=7)

    def test_floating_platform_has_unsupported_regions(self):
        post=box((1,1,3)); slab=box((5,5,.8)); slab.apply_translation([0,0,1.7])
        r=inspect_layers(trimesh.boolean.union([post,slab],engine='manifold'))
        self.assertEqual(r['checks'][2]['status'],'risk')
        self.assertGreater(r['checks'][2]['sum_mm2'],10)

    def test_input_is_unchanged(self):
        m=box(); before=mesh_digest(m)
        inspect_layers(m,build_direction=(1,0,0))
        self.assertEqual(before,mesh_digest(m))

    def test_isolated_contour_below_precision_is_never_silently_lost(self):
        tiny=box((1e-12,1e-12,1)); tiny.apply_translation([3,0,0])
        m=trimesh.util.concatenate([box(),tiny])
        s=section_mesh(m,[0,0,0],[0,0,1])
        self.assertFalse(s.diagnostics['complete'])
        self.assertGreater(s.diagnostics['collapsed_segments'],0)

    def test_one_reversed_wall_face_is_unresolved(self):
        m=box(); m.faces[0]=m.faces[0,::-1]
        s=section_mesh(m,[0,0,.123],[0,0,1])
        self.assertFalse(s.diagnostics['complete'])
        self.assertGreater(s.diagnostics['orientation_imbalances'],0)

    def test_curved_thin_and_thick_walls_at_two_tessellations(self):
        for count in (32,96):
            for thickness,expected in ((.3,'risk'),(1.0,'clear_in_layers')):
                m=trimesh.creation.annulus(r_min=2,r_max=2+thickness,height=2,sections=count)
                r=inspect_layers(m)
                self.assertEqual(r['status'],'complete')
                self.assertEqual(r['checks'][1]['status'],expected)
                volume=count*((2+thickness)**2-4)*np.sin(2*np.pi/count)
                self.assertAlmostEqual(r['volume_estimate_mm3'],volume,places=6)

    def test_small_detached_feature_and_real_gap_are_preserved(self):
        small=box((.2,.2,2)); small.apply_translation([2.12,0,0])
        m=trimesh.util.concatenate([box(),small])
        s=section_mesh(m,[0,0,0],[0,0,1])
        self.assertTrue(s.diagnostics['complete'])
        self.assertEqual(s.diagnostics['material_components'],2)
        self.assertAlmostEqual(s.material.area,12.04,places=7)
        self.assertEqual(inspect_layers(m)['checks'][1]['status'],'risk')

    def test_rotation_and_translation_keep_section_volume(self):
        m=box(); m.apply_translation([80,-52,25])
        r=inspect_layers(m,build_direction=(1,0,0))
        self.assertEqual(r['status'],'complete')
        self.assertAlmostEqual(r['volume_estimate_mm3'],24,places=7)

    def test_subdivision_does_not_change_a_box_review(self):
        m=box(); dense=m.subdivide().subdivide()
        a,b=inspect_layers(m),inspect_layers(dense)
        self.assertEqual(b['status'],'complete')
        self.assertAlmostEqual(a['volume_estimate_mm3'],b['volume_estimate_mm3'],places=7)
        self.assertEqual([c['status'] for c in a['checks']],[c['status'] for c in b['checks']])

    def test_layer_budget_does_not_silently_coarsen(self):
        r=inspect_layers(box((4,3,10)),layer_height=.1,max_layers=10)
        self.assertEqual(r['status'],'unavailable')
        self.assertEqual(r['layers'],[])
        self.assertEqual(r['layer_height_mm'],.1)

    def test_segment_budget_does_not_report_complete_review(self):
        r=inspect_layers(box(),max_total_segments=1)
        self.assertEqual(r['status'],'unavailable')
        self.assertIsNone(r['volume_estimate_mm3'])

    def test_internal_seam_winding_budget_is_cumulative(self):
        # Opposite coincident internal sheets are irrelevant to material, but
        # certifying every seam must still obey the stated computation limit.
        sheets=[]
        for y in (-.6,.6):
            vertices=[[-.5,y,-1],[.5,y,-1],[.5,y,1],[-.5,y,1]]
            faces=[[0,1,2],[0,2,3],[2,1,0],[3,2,0]]
            sheets.append(trimesh.Trimesh(vertices=vertices,faces=faces,process=False))
        m=trimesh.util.concatenate([box(),*sheets])
        full=section_mesh(m,[0,0,.123],[0,0,1])
        self.assertTrue(full.diagnostics['complete'])
        self.assertGreater(full.diagnostics['internal_seam_length_mm'],0)
        # v2.5 budgets actual spatial candidates, including all seam probes.
        budget=full.diagnostics['winding_tests']-1
        limited=section_mesh(m,[0,0,.123],[0,0,1],max_winding_tests=budget)
        self.assertFalse(limited.diagnostics['complete'])
        self.assertLessEqual(limited.diagnostics['winding_tests'],budget)

    def test_failure_of_offsets_is_not_reported_as_clear(self):
        with patch('src.core.layer_review.opening_residual',side_effect=RuntimeError('injected')):
            r=inspect_layers(box())
        self.assertNotEqual(r['status'],'complete')
        self.assertEqual(r['checks'][1]['status'],'unresolved')

    def test_invalid_settings_are_rejected(self):
        for kw in ({'layer_height':0},{'line_width':-1},{'critical_angle':0},{'critical_angle':91},{'layer_height':float('nan')}):
            with self.assertRaises(ValueError): inspect_layers(box(),**kw)

    def test_non_fdm_does_not_claim_fdm_layer_review(self):
        r=AMRuleEngine().evaluate(box(),'SLS')
        self.assertEqual(r.layer_review['status'],'not_applicable')

    def test_legacy_score_is_unchanged_by_layer_review(self):
        e=AMRuleEngine(); a=e.evaluate(box(),layer_review_enabled=False); b=e.evaluate(box())
        self.assertEqual(a.total_score,b.total_score)
        self.assertEqual(a.evaluation_status,b.evaluation_status)
        self.assertEqual(a.layer_review['status'],'not_requested')

    def test_layer_settings_change_inspection_without_changing_legacy_profile(self):
        e=AMRuleEngine(); m=box((4,.5,2))
        a=e.evaluate(m)
        b=e.evaluate(m,layer_settings={'line_width':.8,'layer_height':.1})
        self.assertEqual(a.layer_review['checks'][1]['status'],'clear_in_layers')
        self.assertEqual(b.layer_review['checks'][1]['status'],'risk')
        self.assertEqual(b.layer_review['expected_layers'],20)
        self.assertEqual(a.total_score,b.total_score)
        self.assertEqual(a.profile,b.profile)

    def test_invalid_layer_override_is_visible_without_destroying_legacy_score(self):
        r=AMRuleEngine().evaluate(box(),layer_settings={'unknown':3})
        self.assertEqual(r.total_score,100)
        self.assertEqual(r.layer_review['status'],'unavailable')

    def test_layer_failure_does_not_destroy_legacy_result(self):
        with patch('src.core.layer_review.inspect_layers',side_effect=RuntimeError('injected')):
            r=AMRuleEngine().evaluate(box())
        self.assertEqual(r.total_score,100)
        self.assertEqual(r.layer_review['status'],'unavailable')

    def test_json_contains_finite_traceable_results(self):
        r=json.loads(json_text(AMRuleEngine().evaluate(box())))
        self.assertEqual(r['layer_review']['status'],'complete')
        self.assertIn('grid_mm',r['layer_review']['layers'][0]['diagnostics'])
        self.assertEqual(r['engine_version'],'2.6')


if __name__=='__main__': unittest.main()
