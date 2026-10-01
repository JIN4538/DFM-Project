"""A location click must issue one real, repeatable browser navigation."""
import pytest
from streamlit.testing.v1 import AppTest


@pytest.mark.parametrize('scope', ['am', 'cnc'])
def test_location_jump_is_consumed_once_and_repeatable(scope):
    app = AppTest.from_string(f'''
import streamlit as st
from dfm.location_navigation import request_problem_location, location_heading, finish_location_navigation
st.button('위치 보기', on_click=request_problem_location, args=({scope!r},), key='open')
st.button('다른 동작', key='other')
location_heading({scope!r})
finish_location_navigation({scope!r})
''').run()
    assert not app.exception
    assert not app.get('html')
    for sequence in (1, 2):
        app.button(key='open').click().run()
        assert not app.exception
        assert app.session_state[scope + '_location_jump'] == sequence
        emitted = app.get('html')
        assert len(emitted) == 1
        body = emitted[0].proto.body
        assert f'dfm-{scope}-problem-location' in body
        assert 'scrollIntoView' in body and 'focus(' in body
        assert f'const request = {sequence}' in body
        app.button(key='other').click().run()
        assert not app.get('html')


def test_navigation_rejects_untrusted_scope():
    from dfm.location_navigation import request_problem_location
    with pytest.raises(ValueError):
        request_problem_location("am');alert(1)//")
