"""Streamlit session-state integration tests; no browser or external server required."""
import unittest
from unittest.mock import patch
from pathlib import Path
from streamlit.testing.v1 import AppTest

class UIRegression(unittest.TestCase):
    def app(self):
        at=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'run_legacy.py'),default_timeout=30).run()
        self.assertEqual(len(at.exception),0)
        return at

    def button(self,at,label):
        return next(b for b in at.button if label in b.label)

    def test_evaluate_and_changed_model_requires_reevaluation(self):
        at=self.app(); self.button(at,'제조성 평가').click().run()
        self.assertEqual(len(at.exception),0)
        self.assertEqual(at.session_state.result.total_score,100)
        sample=next(x for x in at.selectbox if x.label=='샘플 선택')
        sample.set_value('moderate').run()
        self.assertTrue(any('사이드바 설정' in w.value for w in at.warning))
        self.assertFalse(any('결과 —' in h.value for h in at.subheader))
        self.button(at,'제조성 평가').click().run()
        self.assertEqual(len(at.exception),0)
        self.assertIn('Moderate',at.session_state.ctx['model'])

    def test_blocked_current_direction_still_allows_comparison(self):
        at=self.app()
        next(x for x in at.number_input if x.label=='Z').set_value(10).run()
        self.button(at,'제조성 평가').click().run()
        self.assertFalse(at.session_state.result.feasible)
        self.button(at,'6방향 비교 실행').click().run()
        self.assertEqual(len(at.exception),0)
        self.assertEqual(len(at.session_state.orient),6)

    def test_toggles_propagate_to_comparison_and_sensitivity(self):
        at=self.app()
        next(x for x in at.checkbox if '두께 변화' in x.label).check().run()
        self.button(at,'제조성 평가').click().run()
        self.button(at,'6방향 비교 실행').click().run()
        self.assertEqual(len(at.exception),0)
        for r in at.session_state.orient.values():
            self.assertIsNotNone(next(x for x in r.rule_results if x.rule_name=='thickness_gradient').score)
        self.button(at,'민감도 분석 실행').click().run()
        self.assertEqual(len(at.exception),0)
        self.assertEqual(at.session_state.sens['base_score'],at.session_state.result.total_score)

    def test_failed_sample_generation_shows_error_without_traceback(self):
        from src.ui import app
        with patch.object(app,'generate_sample_models',side_effect=RuntimeError('샘플 합집합 생성 실패')):
            at=self.app()
        self.assertTrue(any('샘플 합집합 생성 실패' in e.value for e in at.error))

    def test_failed_direction_comparison_does_not_keep_previous_result(self):
        from src.ui import app
        at=self.app(); self.button(at,'제조성 평가').click().run()
        self.button(at,'6방향 비교 실행').click().run()
        self.assertEqual(len(at.session_state.orient),6)
        with patch.object(app,'evaluate_orientations',side_effect=RuntimeError('injected')):
            self.button(at,'6방향 비교 실행').click().run()
        self.assertEqual(len(at.exception),0)
        self.assertIsNone(at.session_state.orient)
        self.assertTrue(any('방향 비교를 완료하지' in e.value for e in at.error))

    def test_partial_result_keeps_mesh_view_and_safe_dimensions(self):
        import trimesh
        from src.ui import app
        mesh = trimesh.creation.box([40, 30, 20])
        mesh.update_faces(list(range(11)))
        samples = {'good': {'mesh': mesh, 'name': 'Open fixture', 'description': 'test'}}
        with patch.object(app, 'generate_sample_models', return_value=samples):
            at = self.app(); self.button(at, '제조성 평가').click().run()
        self.assertEqual(len(at.exception), 0)
        self.assertEqual(at.session_state.result.analysis_scope, 'partial')
        self.assertIsNone(at.session_state.result.total_score)
        self.assertTrue(at.get('plotly_chart'))
        self.assertTrue(any('외곽 치수' in h.value for h in at.subheader))
        self.assertEqual(next(m for m in at.metric if m.label == '부피 (mm³)').value, '검토 필요')

    def test_cleanup_mode_change_requires_new_evaluation_even_if_shape_identical(self):
        at = self.app(); self.button(at, '제조성 평가').click().run()
        next(r for r in at.radio if r.label == '분석에 사용할 메시').set_value('보수적 정리본').run()
        self.assertEqual(len(at.exception), 0)
        self.assertTrue(any('사이드바 설정' in w.value for w in at.warning))
        self.button(at, '제조성 평가').click().run()
        self.assertEqual(len(at.exception), 0)
        self.assertEqual(at.session_state.result.total_score, 100)
        self.assertEqual(at.session_state.result.preprocessing['mode'], 'conservative_cleanup')

    def test_blocked_result_keeps_rules_and_geometry_visible(self):
        at = self.app()
        next(x for x in at.number_input if x.label == 'Z').set_value(10).run()
        self.button(at, '제조성 평가').click().run()
        self.assertEqual(len(at.exception), 0)
        self.assertTrue(any('규칙별 상세' in h.value for h in at.subheader))
        self.assertGreaterEqual(len(at.get('plotly_chart')), 1)
        self.assertIsNone(at.session_state.result.total_score)

    def test_fdm_layer_results_are_visible_when_mesh_gate_fails(self):
        import trimesh
        from src.ui import app
        m=trimesh.creation.box([4,3,2]); m.update_faces(m.face_normals[:,2]<.9)
        with patch.object(app,'generate_sample_models',return_value={'good':{'mesh':m,'name':'Open top','description':'fixture'}}):
            at=self.app(); self.button(at,'제조성 평가').click().run()
            self.assertEqual(len(at.exception),0)
            self.assertEqual(at.session_state.result.layer_review['status'],'complete')
            self.assertIsNone(at.session_state.result.total_score)
            self.assertTrue(any('FDM 단면 검토 완료' in s.value for s in at.success))
            self.assertGreaterEqual(len(at.get('plotly_chart')),2)
            next(s for s in at.slider if s.label=='확인할 단면 층').set_value(5).run()
            self.assertEqual(len(at.exception),0)
            self.assertIsNone(at.session_state.result.total_score)

    def test_layer_display_cannot_hide_open_vertical_contours(self):
        import trimesh
        from src.ui import app
        m=trimesh.creation.box([4,3,2]); m.update_faces(m.face_normals[:,0]<.9)
        with patch.object(app,'generate_sample_models',return_value={'good':{'mesh':m,'name':'Open wall','description':'fixture'}}):
            at=self.app(); self.button(at,'제조성 평가').click().run()
        self.assertEqual(len(at.exception),0)
        self.assertNotEqual(at.session_state.result.layer_review['status'],'complete')
        self.assertFalse(any('FDM 단면 검토 완료' in s.value for s in at.success))

    def test_non_fdm_does_not_show_fdm_layer_success(self):
        at=self.app()
        next(s for s in at.selectbox if s.label=='공정').set_value('SLS').run()
        self.button(at,'제조성 평가').click().run()
        self.assertEqual(len(at.exception),0)
        self.assertFalse(any('FDM 단면 검토 완료' in s.value for s in at.success))

    def test_layer_settings_require_reevaluation_and_propagate_to_directions(self):
        at=self.app(); self.button(at,'제조성 평가').click().run()
        next(n for n in at.number_input if n.label=='단면 층 높이 (mm)').set_value(.4).run()
        self.assertTrue(any('사이드바 설정' in w.value for w in at.warning))
        self.assertFalse(any('FDM 단면 검토 완료' in s.value for s in at.success))
        self.button(at,'제조성 평가').click().run()
        self.button(at,'6방향 비교 실행').click().run()
        self.assertEqual(len(at.exception),0)
        self.assertEqual(at.session_state.result.total_score,100)
        for result in at.session_state.orient.values():
            self.assertEqual(result.layer_review['layer_height_mm'],.4)

    def test_partial_components_render_without_claiming_full_area(self):
        import trimesh
        from src.ui import app
        broken=trimesh.creation.box([4,3,2]);broken.update_faces(broken.face_normals[:,0]<.9)
        good=trimesh.creation.box([4,3,2]);good.apply_translation([20,0,0])
        m=trimesh.util.concatenate([broken,good])
        with patch.object(app,'generate_sample_models',return_value={'good':{'mesh':m,'name':'Partial','description':'fixture'}}):
            at=self.app();self.button(at,'제조성 평가').click().run()
            self.assertEqual(at.session_state.result.layer_review['status'],'partial')
            self.assertEqual(next(v for v in at.metric if v.label=='층단면 부피 (근사 mm³)').value,'미확정')
            for label in ('작은 선폭 세부','지지·브리지 검토 영역','한 층에만 나타나는 영역'):
                next(s for s in at.selectbox if s.label=='단면 표시 항목').set_value(label).run()
                self.assertEqual(len(at.exception),0)
                self.assertFalse(any('단면 표시를 완료하지' in w.value for w in at.warning))
            self.assertTrue(any('분리된 닫힌 성분' in i.value for i in at.info))

    def test_sphere_details_are_visible_without_prominent_risk(self):
        import trimesh
        from src.ui import app
        m=trimesh.creation.icosphere(subdivisions=4,radius=25)
        with patch.object(app,'generate_sample_models',return_value={'good':{'mesh':m,'name':'Sphere','description':'fixture'}}):
            at=self.app();self.button(at,'제조성 평가').click().run()
            self.assertEqual(at.session_state.result.layer_review['checks'][1]['status'],'details_only')
            rows=at.session_state.result.layer_review['layers']
            i=next(r['index'] for r in rows if r['thin_detail_area_mm2']>0)
            next(s for s in at.slider if s.label=='확인할 단면 층').set_value(i).run()
            next(s for s in at.selectbox if s.label=='단면 표시 항목').set_value('작은 선폭 세부').run()
            self.assertEqual(len(at.exception),0)
            self.assertTrue(any('선택 층의 선폭 세부 기록' in e.label for e in at.expander))
            self.assertFalse(any('단면 표시를 완료하지' in w.value for w in at.warning))

    def test_previous_engine_result_requires_new_evaluation(self):
        at=self.app();self.button(at,'제조성 평가').click().run()
        context=dict(at.session_state.ctx)
        context['runtime']={**context['runtime'],'app_version':'2.5'}
        at.session_state.ctx=context;at.run()
        self.assertEqual(len(at.exception),0)
        self.assertTrue(any('프로그램 버전이 변경' in w.value for w in at.warning))
        self.assertFalse(any('FDM 단면 검토 완료' in x.value for x in at.success))
        self.button(at,'제조성 평가').click().run()
        self.assertEqual(len(at.exception),0)
        self.assertEqual(at.session_state.ctx['runtime']['app_version'],'2.6')

    def test_nist_support_and_single_layer_minor_overlays_match_records(self):
        from src.ui import app
        from src.core.model_loader import load_model
        import json
        path=Path(__file__).resolve().parents[1]/'cura_run/NIST_Test_Artifact_online__posZ.stl'
        m=load_model(str(path))['mesh']
        with patch.object(app,'generate_sample_models',return_value={'good':{'mesh':m,'name':'NIST','description':'fixture'}}):
            at=self.app();self.button(at,'제조성 평가').click().run()
            self.assertEqual(len(at.exception),0)
            review=at.session_state.result.layer_review
            self.assertEqual(review['checks'][3]['status'],'details_only')
            for prefix,label in (('unsupported','작은 지지·브리지 세부'),('single_layer','작은 한 층 세부')):
                row=max(review['layers'],key=lambda r:r[prefix+'_detail_area_mm2'] or 0)
                self.assertGreater(row[prefix+'_detail_area_mm2'],0)
                next(x for x in at.slider if x.label=='확인할 단면 층').set_value(row['index']).run()
                next(x for x in at.selectbox if x.label=='단면 표시 항목').set_value(label).run()
                self.assertEqual(len(at.exception),0)
                self.assertFalse(any('단면 표시를 완료하지' in w.value for w in at.warning))
                figures=[json.loads(x.proto.spec) for x in at.get('plotly_chart')]
                self.assertTrue(any(t.get('name')==label for f in figures for t in f['data']))

if __name__=='__main__': unittest.main()
