"""Adversarial contracts for review changes, including small-feature counterexamples."""
import unittest
from unittest.mock import patch
import numpy as np
import trimesh
import shapely as sh
from src.core.sections import section_mesh,winding_at,opening_residual
from src.core.section_index import WindingIndex,WindingLimit,FaceZIndex
from src.core.layer_review import inspect_layers
from src.core.layer_regions import classify_thin_regions,comparison_scope
from src.core.mesh_diagnostics import mesh_digest


def box(size=(4,3,2),at=(0,0,0)):
    m=trimesh.creation.box(size);m.apply_translation(at);return m


def sliced(m,fast=True,**kw):
    return section_mesh(m,[0,0,.123],[0,0,1],axes=np.eye(3)[:2],use_fast_path=fast,**kw)


class Review25(unittest.TestCase):
    def test_index_matches_exhaustive_crossings_including_vertices(self):
        rng=np.random.default_rng(20260909)
        segments=rng.integers(-10,11,size=(200,2,2)).astype(float)
        points=np.r_[rng.uniform(-12,12,size=(200,2)),segments[:,0]]
        np.testing.assert_array_equal(WindingIndex(segments).values(points),winding_at(points,segments))

    def test_index_budget_is_cumulative_across_calls(self):
        seg=np.array([[[1.,-1],[1,1]],[[-1,1],[-1,-1]]])
        index=WindingIndex(seg,max_tests=1)
        self.assertEqual(index.values([[0,0]])[0],1)
        with self.assertRaises(WindingLimit):index.values([[0,0]])
        self.assertEqual(index.tests,1)

    def test_900_pins_preserve_analytic_area_with_index(self):
        pins=[]
        for i in range(900):
            m=trimesh.creation.cylinder(radius=.3,height=2,sections=16)
            m.apply_translation([(i%30)*1.5,(i//30)*1.5,0]);pins.append(m)
        s=sliced(trimesh.util.concatenate(pins))
        self.assertTrue(s.diagnostics['complete'],s.diagnostics)
        self.assertGreater(s.diagnostics['exhaustive_winding_tests'],8000000)
        self.assertLess(s.diagnostics['winding_tests'],8000000)
        self.assertEqual(s.diagnostics['material_components'],900)
        self.assertAlmostEqual(s.material.area,900*8*.3**2*np.sin(2*np.pi/16),places=6)

    def test_fast_and_noded_paths_preserve_nested_cavity(self):
        inner=box((2,1,2));inner.invert()
        m=trimesh.util.concatenate([box(),inner])
        a,b=sliced(m),sliced(m,False)
        self.assertEqual(a.diagnostics['contour_path'],'endpoint_loops')
        self.assertTrue(a.diagnostics['complete'] and b.diagnostics['complete'])
        self.assertLess(a.material.symmetric_difference(b.material).area,1e-8)
        self.assertAlmostEqual(a.material.area,10,places=7)

    def test_crossing_rings_fall_back_without_double_counting(self):
        m=trimesh.util.concatenate([box((4,4,2)),box((4,4,2),(2,1,0))])
        a=sliced(m)
        self.assertEqual(a.diagnostics['contour_path'],'noded')
        self.assertTrue(a.diagnostics['complete'])
        self.assertAlmostEqual(a.material.area,26,places=7)

    def test_touching_boxes_fall_back_and_keep_internal_seam_behavior(self):
        m=trimesh.util.concatenate([box((4,4,2)),box((4,4,2),(4,0,0))])
        a,b=sliced(m),sliced(m,False)
        self.assertEqual(a.diagnostics['contour_path'],'noded')
        self.assertTrue(a.diagnostics['complete'])
        self.assertLess(a.material.symmetric_difference(b.material).area,1e-8)
        self.assertAlmostEqual(a.material.area,32,places=7)

    def test_self_crossing_loop_is_not_trusted_as_simple_ring(self):
        from src.core.section_components import component_rings,fast_linework
        pts=np.array([[0,0],[2,2],[0,2],[2,0],[0,0.]])
        segments=np.stack([pts[:-1],pts[1:]],axis=1)
        groups,_=component_rings(segments)
        self.assertIsNone(fast_linework(groups))

    def test_z_index_matches_brute_force_at_events(self):
        m=trimesh.util.concatenate([box(),box((1,1,1),(3,0,3))])
        index=FaceZIndex(m)
        for z in sorted(set([-2,0,.1,8,*m.vertices[:,2]])):
            expected=np.flatnonzero((index.low<=z+1e-8)&(index.high>=z-1e-8))
            np.testing.assert_array_equal(index.sweep(z),expected)
            np.testing.assert_array_equal(index.query(z,1e-8),expected)
        with self.assertRaises(ValueError):index.sweep(-3)

    def test_projection_reuse_matches_general_planes_without_mutating_inputs(self):
        m=box();origin=np.array([0.,0.,.123]);normal=np.array([0.,0.,2.])
        before=mesh_digest(m);s=section_mesh(m,origin,normal)
        t=section_mesh(m,origin,normal,vertex_projection=m.vertices[:,2])
        self.assertLess(s.material.symmetric_difference(t.material).area,1e-9)
        np.testing.assert_array_equal(normal,[0,0,2]);self.assertEqual(before,mesh_digest(m))

    def test_sphere_small_residuals_remain_details_not_prominent_risk(self):
        r=inspect_layers(trimesh.creation.icosphere(subdivisions=4,radius=25))
        self.assertEqual(r['status'],'complete')
        self.assertEqual(r['checks'][1]['status'],'details_only')
        self.assertEqual(r['checks'][1]['sum_mm2'],0)
        self.assertGreater(r['thin_detail_sum_mm2'],0)
        self.assertTrue(any(x['thin_details'] for x in r['layers']))

    def test_entire_tiny_pin_is_never_erased_by_display_cutoff(self):
        r=inspect_layers(trimesh.creation.cylinder(radius=.015,height=2,sections=32))
        self.assertEqual(r['checks'][1]['status'],'risk')
        self.assertLess(r['layers'][0]['thin_area_mm2'],r['thin_display_floor_mm2'])
        self.assertTrue(r['layers'][0]['thin_details'][0]['whole_component_lost'])

    def test_real_wall_survives_priority_classification(self):
        r=inspect_layers(box((20,.3,2)))
        self.assertEqual(r['checks'][1]['status'],'risk')
        self.assertAlmostEqual(r['checks'][1]['sum_mm2'],60,places=7)

    def test_small_connected_tip_remains_visible_in_details(self):
        polygon=sh.Polygon([(0,0),(3,0),(3,3),(1.02,3),(1.01,3.01),(1,3),(0,3)])
        major,minor,data=classify_thin_regions(polygon,opening_residual(polygon,.4),.4,1e-10)
        self.assertGreater(data['thin_candidate_area_mm2'],0)
        self.assertEqual(data['thin_candidate_regions'],len(major)+len(minor))
        self.assertAlmostEqual(data['thin_candidate_area_mm2'],data['thin_area_mm2']+data['thin_detail_area_mm2'])

    def test_area_perimeter_scale_is_not_circle_diameter(self):
        circle=sh.Point(0,0).buffer(.015,quad_segs=128)
        _,_,data=classify_thin_regions(circle,circle,.4,1e-10)
        self.assertAlmostEqual(data['thin_details'][0]['area_perimeter_scale_mm'],.015,places=5)

    def test_detail_table_cap_does_not_truncate_aggregates(self):
        parts=[sh.box(i,0,i+.02,.02) for i in range(60)]
        material=sh.union_all(parts)
        _,_,data=classify_thin_regions(material,material,.4,1e-10)
        self.assertEqual(len(data['thin_details']),50)
        self.assertTrue(data['thin_details_truncated'])
        self.assertEqual(data['thin_candidate_regions'],60)
        self.assertAlmostEqual(data['thin_candidate_area_mm2'],60*.02**2)

    def test_far_closed_body_is_measured_without_inventing_total_area(self):
        broken=box();broken.update_faces(broken.face_normals[:,0]<.9)
        m=trimesh.util.concatenate([broken,box((20,20,2),(80,0,0))])
        r=inspect_layers(m)
        self.assertEqual(r['status'],'partial');self.assertEqual(r['complete_layers'],0)
        self.assertEqual(r['partial_component_layers'],10)
        self.assertIsNone(r['volume_estimate_mm3'])
        for row in r['layers']:
            self.assertIsNone(row['area_mm2']);self.assertAlmostEqual(row['known_area_mm2'],400)
            self.assertEqual(row['thin_area_mm2'],0)
        self.assertEqual(r['checks'][1]['status'],'unresolved')
        self.assertEqual(r['checks'][1]['fully_measured_layers'],0)
        self.assertEqual(r['checks'][1]['measured_layers'],10)

    def test_open_cavity_excludes_enclosing_ring_from_known_material(self):
        inner=box((2,1,2));inner.invert();inner.update_faces(inner.face_normals[:,0]<.9)
        s=sliced(trimesh.util.concatenate([box(),inner]))
        self.assertFalse(s.diagnostics['complete'])
        self.assertEqual(s.known_material.area,0)

    def test_unknown_neighbor_cannot_create_false_support_or_one_layer_findings(self):
        material=sh.box(0,0,2,2)
        partial=dict(complete=False,diagnostics={'unknown_bounds_mm':[[1,1,3,3]]})
        self.assertTrue(comparison_scope(material,[partial]).is_empty)
        self.assertTrue(comparison_scope(material,[None]).is_empty)
        far=sh.box(10,10,12,12)
        self.assertAlmostEqual(comparison_scope(sh.union_all([material,far]),[partial]).area,4)
        # The allowance must also expand the uncertainty mask.
        near=sh.box(3.1,1,4,2)
        self.assertTrue(comparison_scope(near,[partial],.2).is_empty)

    def test_empty_air_layers_remain_valid_and_floating_body_is_found(self):
        m=trimesh.util.concatenate([box((4,3,.4),(0,0,0)),box((4,3,.4),(0,0,2))])
        r=inspect_layers(m)
        self.assertEqual(r['status'],'complete')
        self.assertTrue(any(x['complete'] and x['area_mm2']==0 for x in r['layers']))
        self.assertEqual(r['checks'][2]['status'],'risk')
        self.assertGreater(r['checks'][2]['sum_mm2'],11.9)

    def test_cancelled_shells_do_not_report_clear_metrics(self):
        a=box();b=a.copy();b.invert();r=inspect_layers(trimesh.util.concatenate([a,b]))
        self.assertEqual(r['status'],'unavailable');self.assertTrue(r['reason'])
        self.assertTrue(all(c['status']=='unresolved' for c in r['checks']))
        self.assertTrue(all(c.get('sum_mm2') is None for c in r['checks'][1:]))

    def test_direct_mixed_winding_input_is_warned_without_repair(self):
        m=box();m.faces[0]=m.faces[0,::-1];before=mesh_digest(m);r=inspect_layers(m)
        self.assertTrue(any('방향의 연결' in s for s in r['warnings']))
        self.assertEqual(before,mesh_digest(m))

    def test_preview_cache_invalidates_geometry_direction_height_and_version(self):
        from src.ui.app import layer_preview_frame,layer_preview_section
        layer_preview_frame.clear();layer_preview_section.clear()
        m=box();digest=mesh_digest(m)
        with patch('src.core.sections.section_mesh',wraps=section_mesh) as call:
            a=layer_preview_section(digest,(0,0,1),0.,'test',m)
            b=layer_preview_section(digest,(0,0,1),0.,'test',m)
            self.assertEqual(call.call_count,1);self.assertAlmostEqual(a.material.area,b.material.area)
            layer_preview_section(digest,(0,0,1),.1,'test',m)
            layer_preview_section(digest,(1,0,0),0.,'test',m)
            layer_preview_section(digest,(0,0,1),0.,'next',m)
            n=box((5,3,2));layer_preview_section(mesh_digest(n),(0,0,1),0.,'test',n)
            self.assertEqual(call.call_count,5)
        layer_preview_frame.clear();layer_preview_section.clear()


if __name__=='__main__':unittest.main()
