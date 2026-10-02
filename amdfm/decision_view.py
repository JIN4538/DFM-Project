"""A single recommendation and its measured consequences, in user language."""
from __future__ import annotations

import pandas as pd
import streamlit as st


def render_recommendation(recommendation, *, on_apply, presets, key_prefix, compact=False):
    best = recommendation.get('recommended')
    with st.container(border=True):
        st.markdown('**추천 방향**')
        if recommendation['status'] == 'no_fit':
            st.warning('비교한 방향 중 입력한 빌드 공간에 들어가는 후보가 없습니다. '
                       '장비 공간 또는 부품 분할을 검토하세요.')
        else:
            st.info(recommendation['title'])
        if best:
            differences = recommendation.get('current_comparison', {}).get('differences', [])
            if differences and compact and not recommendation.get('keep_current'):
                changed=[d for d in differences if d['change']!='same']
                st.caption(' / '.join(
                    f"{d['label']} {d['current']:,.4g} → {d['recommended']:,.4g} {d['unit']} ({'유리' if d['change']=='improvement' else '불리'})"
                    for d in changed))
            if differences and not compact:
                st.dataframe(pd.DataFrame([
                    {'비교 항목': d['label'], '현재':f"{d['current']:,.4g} {d['unit']}",
                     '추천 후보':f"{d['recommended']:,.4g} {d['unit']}",
                     '변화':{'same':'같음','improvement':'유리','tradeoff':'불리'}[d['change']]}
                    for d in differences]),hide_index=True)
            if not recommendation.get('keep_current'):
                tradeoffs=[d['label'] for d in differences if d['change']=='tradeoff']
                if tradeoffs:
                    st.caption('함께 증가·감소하는 항목: '+', '.join(tradeoffs))
                st.button('추천 방향 적용·전체 다시 검토', key=key_prefix+'_apply_recommendation',
                          on_click=on_apply, args=(best['direction'],presets), type='primary')
        else:
            st.write('**다음 행동** · '+recommendation['next_action'])
        with st.expander('선택 근거·다른 후보'):
            if recommendation.get('keep_current'):
                st.caption(f"대표 후보 {best['name']}와 비교해 현재 방향이 같거나 더 유리합니다."
                           if best else '입력한 공간에 맞는 현재 방향을 유지합니다.')
            if compact:
                differences=recommendation.get('current_comparison',{}).get('differences',[])
                if differences:
                    st.dataframe(pd.DataFrame([
                        {'비교 항목':d['label'],'현재':f"{d['current']:,.4g} {d['unit']}",
                         '추천 후보':f"{d['recommended']:,.4g} {d['unit']}",
                         '변화':{'same':'같음','improvement':'유리','tradeoff':'불리'}[d['change']]}
                        for d in differences]),hide_index=True)
            if recommendation['criteria']:
                st.dataframe(pd.DataFrame([
                    {'비교 항목':c['label'], '우선 방향':'작을수록 유리' if c['direction']=='min' else '클수록 유리'}
                    for c in recommendation['criteria']]),hide_index=True)
            if recommendation.get('alternatives'):
                st.write('비교한 다른 후보: '+', '.join(r['name'] for r in recommendation['alternatives']))
