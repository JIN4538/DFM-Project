"""One-shot navigation to app-owned result anchors after a location is opened."""
from __future__ import annotations

import streamlit as st


def request_problem_location(scope: str) -> None:
    if scope not in ('am', 'cnc'):
        raise ValueError('Unknown result scope')
    key = scope + '_location_jump'
    st.session_state[key] = int(st.session_state.get(key, 0)) + 1
    st.session_state[scope + '_location_jump_pending'] = True


def location_heading(scope: str) -> None:
    if scope not in ('am', 'cnc'):
        raise ValueError('Unknown result scope')
    st.subheader('문제 위치', anchor='dfm-' + scope + '-problem-location')


def finish_location_navigation(scope: str) -> None:
    """Run once, after the chart has been emitted; ordinary reruns stay put."""
    if scope not in ('am', 'cnc'):
        raise ValueError('Unknown result scope')
    if not st.session_state.pop(scope + '_location_jump_pending', False):
        return
    sequence = int(st.session_state.get(scope + '_location_jump', 0))
    # Only an allow-listed scope and an integer enter this fixed script. No CAD
    # names, report values, selectors supplied by a user, or remote code enter it.
    # The sequence changes the element on a repeated click of the same button.
    st.html('''<script>
    (() => {
      const request = SEQUENCE;
      let frames = 0;
      const move = () => {
        const heading = document.getElementById('dfm-SCOPE-problem-location');
        if (!heading && frames++ < 30) { requestAnimationFrame(move); return; }
        if (!heading) return;
        heading.style.scrollMarginTop = '6rem';
        heading.setAttribute('tabindex', '-1');
        heading.focus({preventScroll: true});
        heading.scrollIntoView({block: 'start', behavior: 'instant'});
      };
      requestAnimationFrame(() => requestAnimationFrame(move));
    })();
    </script>'''.replace('SCOPE', scope).replace('SEQUENCE', str(sequence)),
            unsafe_allow_javascript=True)
