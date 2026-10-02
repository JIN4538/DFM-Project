"""Automated novice tasks; this is not a human usability study."""
import argparse
import json
from pathlib import Path
import sys
import time
from streamlit.testing.v1 import AppTest

ROOT=Path(__file__).resolve().parents[1]


def run(output):
    output.mkdir(parents=True,exist_ok=False)
    cases=[]
    for family,title,edit in [('적층제조','얇은 판 · 두께 0.3 mm',False),
        ('절삭가공','3개 포켓 · 수정 전',True),
        ('절삭가공','관통 구멍 3개 · 지름 6 mm',False)]:
        started=time.perf_counter();actions=[]
        app=AppTest.from_file(str(ROOT/'app.py'),default_timeout=100).run()
        if family=='절삭가공':
            app.selectbox(key='source').select('절삭 시연용 형상').run();actions.append('시연 목적 선택')
        app.selectbox(key='demo_example').select(title).run();actions.append('형상 선택')
        assert app.selectbox(key='manufacturing_family').value==family
        key='start_from_model' if family=='적층제조' else 'cnc_start_from_model'
        app.button(key=key).click().run();actions.append('검토 시작')
        assert not app.exception and not app.error
        report=app.session_state['report' if family=='적층제조' else 'cnc_report']
        assert any('종합 결론' in item.value for item in app.subheader)
        app.button(key='am_conclusion_location' if family=='적층제조' else 'cnc_conclusion_location').click().run()
        actions.append('문제 위치 보기')
        assert not app.exception and not app.error
        assert app.get('plotly_chart')
        item=dict(family=family,shape=title,actions=actions,manual_numeric_entries=0,
            conclusion=True,direct_problem_location=True)
        if family=='절삭가공':
            item['automatic_tool']=report['tool_recommendation']['values']
            assert all(v is not None for v in item['automatic_tool'].values())
        if edit:
            app.button(key='cnc_create_edit_preview').click().run();actions.append('추천 수정 적용·재검토')
            assert not app.exception and not app.error
            data,audit=app.session_state['cnc_edit_preview_result']
            assert data.startswith(b'ISO-10303-21;')
            assert app.get('download_button') and app.selectbox(key='cnc_edit_focus')
            assert audit['dimensional_reinspection']['after_conflicts']==0
            item['actual_step_reinspection']=audit['dimensional_reinspection']
            item['edited_pockets']=audit['edited_pocket_count']
        item['seconds']=time.perf_counter()-started;cases.append(item)
    result=dict(scope='automated visible app task paths; zero recruited users, no human completion-time claim',
        users=0,cases=cases,all_completed=True,source_script='scripts/run_user_flow_audit.py')
    (output/'result.json').write_bytes((json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode('utf8'))
    print(json.dumps(dict(tasks=len(cases),all_completed=True),ensure_ascii=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);a=p.parse_args();run(a.output)
