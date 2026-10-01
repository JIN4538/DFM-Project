"""Machine defaults must drive the same editable inputs used for review."""
from types import SimpleNamespace
import pytest
from dfm import advisor_view

class Library:
    digest='fixture-identity'
    def profiles_for(self,process):
        return [dict(id='machine-a',machine='Printer A',material='PLA')]
    def resolve(self,identifier,process):
        return dict(values=dict(build_volume_mm=[220.,210.,250.],layer_height_mm=.12))

def test_equipment_choice_fills_one_settings_state_and_unknown_resets(monkeypatch):
    state={'machine_MEX':'Printer A','material_MEX':'PLA','layer_MEX':.2}
    monkeypatch.setattr(advisor_view,'st',SimpleNamespace(session_state=state))
    advisor_view._names_edited('MEX',Library())
    assert [state[f'build_{a}_MEX'] for a in 'XYZ']==[220.,210.,250.]
    assert state['layer_MEX']==.12
    assert state['equipment_defaults_MEX']['digest']=='fixture-identity'
    state['machine_MEX']='Unknown printer'
    advisor_view._names_edited('MEX',Library())
    assert [state[f'build_{a}_MEX'] for a in 'XYZ']==[250.]*3
    assert state['layer_MEX']==.2
    assert state['use_build_MEX'] is False
    assert 'equipment_defaults_MEX' not in state

def test_custom_layer_override_survives_unrecognized_material(monkeypatch):
    state={'machine_MEX':'Printer A','material_MEX':'PLA','layer_MEX':.2}
    monkeypatch.setattr(advisor_view,'st',SimpleNamespace(session_state=state))
    advisor_view._names_edited('MEX',Library())
    state['layer_MEX']=.16;state['material_MEX']='User material'
    advisor_view._names_edited('MEX',Library())
    assert state['layer_MEX']==.16
