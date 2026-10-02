"""User intent enters real review inputs; AI never supplies machining limits."""
from __future__ import annotations

import hashlib
import os

import streamlit as st
from amdfm.profiles import PROCESS_LABELS

from .advisor import PRIORITY_LABELS, review_context, profile_candidates
from .ai_client import parse_intent, AIClientError
from .conditions_view import apply_library_condition, clear_library_condition, _parameter_display, FIELD_LABELS, _source_link


def _keys(process):
    return ("cnc_machine", "cnc_material") if process == "CNC" else (f"machine_{process}", f"material_{process}")


def _name_options(library, process, field, current):
    """One searchable input, retaining custom names without inventing matches."""
    values = {"미확정"}
    if library is not None:
        values.update(str(record[field]).strip() for record in library.profiles_for(process)
                      if record.get(field) and str(record[field]).strip())
    if current:
        values.add(str(current))
    return ["미확정", *sorted(values - {"미확정"}, key=str.casefold)]


def _key():
    key = st.session_state.get("advisor_api_key", "").strip() or os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        try:
            key = str(st.secrets.get("OPENAI_API_KEY", "")).strip()
        except (FileNotFoundError, KeyError):
            pass
    return key


def _text_digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _names_edited(process, library=None):
    # A new machine/material cannot inherit source-backed limits for the old one.
    if process == 'CNC':
        return
    machine_key,material_key=_keys(process)
    machine,material=st.session_state[machine_key],st.session_state[material_key]
    if st.session_state.get(f'applied_condition_{process}'):
        clear_library_condition(process)
        st.session_state[machine_key],st.session_state[material_key]=machine,material
        st.session_state[f'advisor_reset_notice_{process}']='장비·재료 변경 · 이전 조건을 초기화했습니다.'
    previous=st.session_state.pop(f'equipment_defaults_{process}',{})
    # A custom/new machine cannot keep another machine's build dimensions.
    if previous.get('build_volume_mm'):
        for axis in 'XYZ':st.session_state[f'build_{axis}_{process}']=250.
        st.session_state[f'use_build_{process}']=False
    if previous.get('layer_height_mm') == st.session_state.get(f'layer_{process}'):
        st.session_state[f'layer_{process}']={'MEX':.2,'VPP':.05,'PBF_POLYMER':.1,'PBF_METAL':.03}[process]
    if library is None:return
    matches=[r for r in library.profiles_for(process) if str(r.get('machine','')).strip().casefold()==machine.strip().casefold() and machine!='미확정']
    if not matches:return
    resolved=[(r,library.resolve(r['id'],process)['values']) for r in matches]
    builds=[(r,v['build_volume_mm']) for r,v in resolved if v.get('build_volume_mm')]
    defaults=dict(profile_ids=[],digest=library.digest)
    if builds and len({tuple(v) for _,v in builds})==1:
        dims=builds[0][1]
        for axis,value in zip('XYZ',dims):st.session_state[f'build_{axis}_{process}']=float(value)
        defaults.update(profile_ids=[r['id'] for r,_ in builds],build_volume_mm=list(dims))
    material_matches=[v for r,v in resolved if str(r.get('material','')).strip().casefold()==material.strip().casefold() and material!='미확정']
    layers=[v['layer_height_mm'] for v in material_matches if v.get('layer_height_mm')]
    if layers and len(set(layers))==1:
        st.session_state[f'layer_{process}']=float(layers[0])
        defaults['layer_height_mm']=float(layers[0])
    if len(defaults)>2:st.session_state[f'equipment_defaults_{process}']=defaults


def _interpret():
    # Explicit click only: changing a widget or rerunning geometry never bills an API call.
    st.session_state.pop("advisor_draft", None)
    st.session_state.pop("advisor_error", None)
    text = st.session_state.get("advisor_request", "")
    try:
        with st.spinner("입력 문장에서 장비·재료·우선순위를 읽는 중…"):
            result = parse_intent(text, api_key=_key(), model=st.session_state.get("advisor_model", "gpt-4.1-mini"))
        st.session_state["advisor_draft"] = {**result, "input_digest": _text_digest(text)}
    except AIClientError as exc:
        st.session_state["advisor_error"] = str(exc)


def _apply_intent(current_process):
    draft = st.session_state.get("advisor_draft")
    if not draft or draft["input_digest"] != _text_digest(st.session_state.get("advisor_request", "")):
        return
    intent = dict(draft["intent"])
    process = intent["process"] if intent["process"] != "unknown" else current_process
    st.session_state["manufacturing_family"] = "절삭가공" if process == "CNC" else "적층제조"
    if process != "CNC":
        st.session_state["process"] = process
    machine_key, material_key = _keys(process)
    changes_names=any(intent[field] and intent[field].strip().casefold()!=str(st.session_state.get(key,'미확정')).strip().casefold()
                      for field,key in (('equipment',machine_key),('material',material_key)))
    previous_names={key:st.session_state.get(key,'미확정') for key in (machine_key,material_key)}
    if process != 'CNC' and changes_names:
        clear_library_condition(process)
        for key,value in previous_names.items():
            st.session_state[key]=value
        st.session_state[f'advisor_reset_notice_{process}']='장비·재료 변경 · 이전 조건을 초기화했습니다.'
    # Missing fields stay missing; a statement that only asks for supports must
    # not erase already selected equipment/material or inject numeric settings.
    for field, key in (("equipment", machine_key), ("material", material_key)):
        if intent[field]:
            st.session_state[key] = intent[field]
    st.session_state[f"advisor_priority_{process}"] = intent["priority"]
    st.session_state['cnc_visibility' if process=='CNC' else 'initial_wall']=True
    st.session_state[f"advisor_origin_{process}"] = {
        "equipment": st.session_state.get(machine_key, "미확정"),
        "material": st.session_state.get(material_key, "미확정"),
        "priority": intent["priority"], "process": process,
        "notes": intent["notes"], "provenance": draft["provenance"],
    }
    st.session_state.pop("advisor_draft", None)
    st.session_state.pop("auto_review", None)


def _forget_key():
    st.session_state["advisor_api_key"] = ""


def render_advisor(process, library, settings_renderer=None):
    """Return the current review context, without doing hidden model requests."""
    machine_key, material_key = _keys(process)
    for key in (machine_key, material_key):
        st.session_state.setdefault(key, "미확정")
    priority_key = f"advisor_priority_{process}"
    st.session_state.setdefault(priority_key, "balanced")
    options = (['balanced','accuracy','tool_access'] if process=='CNC' else
               ['balanced','height','accuracy'] if process=='PBF_POLYMER' else
               ['balanced','support','height','accuracy'] if process in ('VPP','PBF_METAL') else
               ['balanced','support','height','contact','accuracy'])
    if st.session_state[priority_key] not in options:
        options.append(st.session_state[priority_key])  # Retain a previously explicit request in its report.
    has_result = bool(st.session_state.get("cnc_report" if process == "CNC" else "report"))
    label = "검토 조건"
    with st.expander(label, expanded=not has_result):
        if not has_result:
            st.caption('장비·재료를 몰라도 기본 설정으로 바로 검토할 수 있습니다.')
        c1, c2 = st.columns(2)
        machine = c1.selectbox("사용할 장비 (선택)", _name_options(library, process, "machine", st.session_state[machine_key]),
                               key=machine_key, accept_new_options=True, placeholder="검색 또는 직접 입력",
                               format_func=lambda value: '선택하지 않음' if value=='미확정' else value,
                               persist_state="session", on_change=_names_edited, args=(process,library)) or "미확정"
        material = c2.selectbox("사용할 재료 (선택)", _name_options(library, process, "material", st.session_state[material_key]),
                                key=material_key, accept_new_options=True, placeholder="검색 또는 직접 입력",
                                format_func=lambda value: '선택하지 않음' if value=='미확정' else value,
                                persist_state="session", on_change=_names_edited, args=(process,library)) or "미확정"
        if st.session_state.get(f'advisor_reset_notice_{process}'):
            st.info(st.session_state.pop(f'advisor_reset_notice_{process}'))
        priority = st.selectbox("검토 중점", options, key=priority_key,
                                format_func=PRIORITY_LABELS.get, persist_state="session")
        plan_preferences = None
        if process == 'CNC':
            allowance = st.selectbox('변경할 수 있는 항목', ['형상·공구 모두', '공구만 · 원래 형상 유지', '형상만 · 현재 공구 유지'],
                                     key='cnc_plan_allowance', persist_state='session')
            plan_preferences = dict(preserve_geometry=allowance == '공구만 · 원래 형상 유지',
                                    allow_tool_change=allowance != '형상만 · 현재 공구 유지')
        intent = dict(equipment=machine, material=material, priority=priority, process=process, notes=[])
        matches = profile_candidates(intent, library, process) if library is not None else []
        if matches and not settings_renderer:
            lookup = {m["identifier"]: m for m in matches}
            match_key = f"advisor_match_{process}"
            if st.session_state.get(match_key) not in lookup:
                st.session_state[match_key] = matches[0]["identifier"]
            selected = st.selectbox("관련 조건", list(lookup), key=match_key,
                                    format_func=lambda k: lookup[k]["title"])
            record = library.profiles[selected]
            with st.expander("조건값·출처 보기"):
                st.caption(lookup[selected]["explanation"])
                for condition in record.get("conditions", []):
                    st.write(condition)
                for field, parameter in record["parameters"].items():
                    if parameter.get("application") == "automatic":
                        st.write(f"{parameter.get('label', FIELD_LABELS.get(field, field))}: {_parameter_display(field, parameter)}")
                for source in record.get("source_ids", []):
                    _source_link(library.sources[source])
            if any(p.get("application") == "automatic" for p in record["parameters"].values()):
                st.button("이 자료의 조건 가져오기", key=f"advisor_apply_profile_{process}",
                          on_click=apply_library_condition, args=(library, process, selected))
            else:
                st.caption("참고 자료 · 적용할 수치 없음")
        elif not settings_renderer and any(v.strip() not in ("", "미확정") for v in (machine, material)):
            st.caption("등록된 조건 없음 · 수치 기준을 직접 입력할 수 있습니다.")
        settings = settings_renderer(process) if settings_renderer else None
        if settings_renderer and library is not None:
            from .conditions_view import render_condition_picker
            render_condition_picker(process)
        with st.expander("외부 문장 입력 도우미 (선택)"):
            st.text_area("어떤 장비로 만들고, 무엇을 개선하고 싶나요?", key="advisor_request", max_chars=4000,
                         placeholder="예: Prusa MK4S에서 PLA로 만들 예정이고, 서포트가 적게 필요한 방향을 우선하고 싶어.",
                         persist_state="session")
            st.caption("입력 문장만 OpenAI에 전송합니다. CAD 파일은 전송하지 않습니다.")
            with st.expander("AI 연결 설정"):
                st.text_input("OpenAI API 키", type="password", key="advisor_api_key",
                              help="현재 세션에서만 사용합니다. 파일·보고서에 저장하지 않습니다.", persist_state="session")
                st.session_state.setdefault("advisor_model", os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"))
                st.text_input("API 모델", key="advisor_model", max_chars=100, persist_state="session")
                st.button("입력한 키 지우기", on_click=_forget_key, key="advisor_forget_key")
                st.caption("환경변수 또는 .streamlit/secrets.toml의 OPENAI_API_KEY도 사용할 수 있습니다. API 사용료는 연결한 계정에 청구됩니다.")
            ready = bool(_key())
            st.caption("연결 준비됨" if ready else "API 연결 필요")
            st.button("AI로 입력 문장 해석", key="advisor_interpret", on_click=_interpret,
                      disabled=not ready or not st.session_state.get("advisor_request", "").strip())
            if st.session_state.get("advisor_error"):
                st.error(st.session_state["advisor_error"])
            draft = st.session_state.get("advisor_draft")
            if draft:
                parsed = draft["intent"]
                st.markdown("**입력 해석 결과**")
                st.write(f"장비: {parsed['equipment'] or '언급 없음'} / 재료: {parsed['material'] or '언급 없음'} / 중점: {PRIORITY_LABELS[parsed['priority']]}")
                process_labels={**PROCESS_LABELS,'CNC':'절삭가공 · 고정축 밀링'}
                process_text=process_labels.get(parsed['process'],f"입력에서 확정하지 못함 · 현재 {process_labels[process]} 유지")
                st.write(f"공정: {process_text}")
                st.caption('치수 기준은 아래 입력값을 사용합니다.')
                stale = draft["input_digest"] != _text_digest(st.session_state.get("advisor_request", ""))
                if stale:
                    st.warning("문장이 바뀌었습니다. 다시 해석한 뒤 반영하세요.")
                st.button("해석을 검토 조건에 반영", key="advisor_accept", on_click=_apply_intent,
                          args=(process,), disabled=stale)
    origin = st.session_state.get(f"advisor_origin_{process}", {})
    same = bool(origin) and all(intent[k] == origin.get(k) for k in ("equipment", "material", "priority", "process"))
    if same:
        intent["notes"] = origin.get("notes", [])
    context = review_context(intent, mode="ai" if same else "manual", provenance=origin.get("provenance") if same else None)
    if plan_preferences is not None:
        context['plan_preferences'] = plan_preferences
    if settings is not None:
        context['settings'] = settings
    return context


def render_applied_context(report, process):
    context = report.get("review_context")
    if not context:
        return
    filename=report.get('model',report.get('input',{})).get('filename','')
    parts = [filename]
    parts.extend(context.get(field) for field in ("equipment", "material")
                 if context.get(field) not in (None, "", "미확정"))
    if context.get("priority", "balanced") != "balanced":
        parts.append(PRIORITY_LABELS[context["priority"]])
    if any(parts):
        st.caption(" · ".join(part for part in parts if part))
    if context.get("notes"):
        with st.expander("추가 요청 메모"):
            for note in context["notes"]:
                st.write(note)
