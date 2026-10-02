"""Explicit, source-visible condition selection shared by AM and CNC views.

Browsing a record does not apply it. Only the apply callback may replace input
values or register evidence, so an unrelated preview cannot label a result.
"""
from __future__ import annotations

from urllib.parse import urlsplit

import pandas as pd
import streamlit as st

from .conditions import load_library, load_literature
from .defaults import wall_default_value, wall_default_basis


FIELD_LABELS = {
    "machine": "장비", "material": "재료", "slicer": "슬라이서",
    "layer_height_mm": "층 높이", "line_width_mm": "MEX 명목 선폭",
    "overhang_angle_deg": "수평 기준 하향면 탐색 각도",
    "minimum_wall_mm": "최소 벽 검토 기준", "minimum_hole_mm": "최소 홀 검토 기준",
    "build_volume_mm": "장비 공간 X × Y × Z", "clearance_mm": "각 경계의 여유",
    "tool_diameter_mm": "엔드밀 지름", "flute_length_mm": "날 길이",
    "reach_mm": "장착 후 돌출 길이", "hole_depth_ratio_limit": "원통 구간 길이/지름 기준",
    "threshold_basis": "기준 출처", "basis": "공구·기준 출처", "process_notes": "공정 조건·설계 요구",
    "nozzle_diameter_mm": "노즐 지름", "nozzle_temperature_c": "노즐 온도",
    "first_layer_nozzle_temperature_c": "첫 층 노즐 온도", "bed_temperature_c": "베드 온도",
    "slicer_density_g_cm3": "슬라이서에 기록된 재료 밀도",
    "supported_wall_guidance_mm": "연결된 벽의 제조사 두께 권고",
    "unsupported_wall_guidance_mm": "연결이 적은 벽의 제조사 두께 권고",
    "minimum_drain_hole_mm": "배출구 지름 권고", "minimum_clearance_mm": "틈새 권고",
    "overhang_angle_reference_deg": "시험 형상의 하향면 각도 참고값",
    "horizontal_span_reference_mm": "수평 보의 지지 간격 참고값",
    "exposure_time_s": "일반 층 노광 시간", "initial_exposure_time_s": "초기 노광 시간",
    "nominal_build_volume_mm": "명목 빌드 공간", "build_chamber_corner_radius_mm": "빌드 공간 모서리 반경",
    "material_part_size_reference_mm": "해당 재료의 부품 크기 참고값",
    "vertical_wall_guidance_mm": "수직 벽 두께 권고", "horizontal_wall_guidance_mm": "수평 벽 두께 권고",
    "integrated_assembly_clearance_mm": "일체형 조립체 간격 권고",
    "tensile_strength_mpa": "인장강도", "tensile_modulus_mpa": "인장 탄성계수",
    "elongation_xy_percent": "XY 방향 파단 연신율", "elongation_z_percent": "Z 방향 파단 연신율",
    "parameter_set": "제조사 설정 세트", "tensile_strength_vertical_mpa": "수직 방향 인장강도",
    "tensile_strength_horizontal_mpa": "수평 방향 인장강도",
    "minimum_wall_reference_range_mm": "최소 벽 두께 참고 범위", "minimum_wall_reference_mm": "최소 벽 두께 참고값",
    "build_platform_temperature_c": "빌드 플랫폼 온도", "shank_diameter_mm": "생크 지름",
    "overall_length_mm": "공구 전체 길이", "flute_count": "날 수",
    "catalog_material_application": "카탈로그의 대상 재료", "catalog_l3_mm": "카탈로그 L3 길이",
    "neck_diameter_mm": "목부 지름", "coating": "코팅", "catalog_overall_reach_mm": "카탈로그 도달 길이",
    "axis_travel_mm": "장비 X × Y × Z 축 이동량", "maximum_spindle_rpm": "최대 주축 회전수",
    "tensile_strength_min_mpa": "인장강도 최소값", "yield_strength_02_min_mpa": "0.2% 항복강도 최소값",
    "thermal_conductivity_w_mk": "열전도율", "density_kg_dm3": "밀도", "elastic_modulus_gpa": "탄성계수",
    "thermal_expansion_per_k": "선팽창계수", "density_g_cm3": "밀도",
    "finishing_cutter_diameter_to_corner_radius_max": "정삭 공구 지름/코너 반경 권고 상한",
}
AM_KEYS = {
    "machine": "machine", "material": "material", "slicer": "slicer",
    "layer_height_mm": "layer", "overhang_angle_deg": "angle",
    "minimum_wall_mm": "wall_limit", "minimum_hole_mm": "hole_limit",
    "clearance_mm": "clearance", "threshold_basis": "basis", "process_notes": "notes",
}
CNC_KEYS = {
    "machine": "cnc_machine", "material": "cnc_material", "tool_diameter_mm": "cnc_diameter",
    "flute_length_mm": "cnc_flute", "reach_mm": "cnc_reach",
    "hole_depth_ratio_limit": "cnc_ratio", "basis": "cnc_basis",
}


def _display(value, unit=""):
    if value is None:
        return "미입력"
    if isinstance(value, (tuple, list)):
        text = " × ".join(_display(v) for v in value)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        text = f"{value:,.8g}"
    else:
        text = str(value)
    unit = {"degC": "°C", "deg": "°", "text": "", "count": "개", "ratio": "배",
            "dimensionless": "", "1": ""}.get(unit, unit)
    return f"{text} {unit}".strip()


def _parameter_display(field, parameter):
    value = parameter.get("value")
    if "range" in field and isinstance(value, (list, tuple)):
        return _display(" ~ ".join(_display(v) for v in value), parameter.get("unit", ""))
    return _display(value, parameter.get("unit", ""))


def _reset_values(process):
    if process == "CNC":
        return {"machine": "미확정", "material": "미확정", "tool_diameter_mm": None,
                "flute_length_mm": None, "reach_mm": None, "hole_depth_ratio_limit": None,
                "basis": "사용자 지정 공구·검토 조건"}
    return {"machine": "미확정", "material": "미확정", "slicer": "미확정",
            "layer_height_mm": {"MEX": .2, "VPP": .05, "PBF_POLYMER": .1, "PBF_METAL": .03}[process],
            "line_width_mm": .4, "overhang_angle_deg": 45., "minimum_wall_mm": wall_default_value(process),
            "minimum_hole_mm": None, "build_volume_mm": (250., 250., 250.), "clearance_mm": 0.,
            "threshold_basis": wall_default_basis(process), "process_notes": ""}


def _write_values(process, values):
    if process == "CNC":
        for field, key in CNC_KEYS.items():
            st.session_state[key] = values[field]
    else:
        for field, key in AM_KEYS.items():
            st.session_state[f"{key}_{process}"] = values[field]
        if process == "MEX":
            st.session_state["line_width"] = values["line_width_mm"]
        for axis, length in zip("XYZ", values["build_volume_mm"]):
            st.session_state[f"build_{axis}_{process}"] = float(length)
        # Knowing the machine size does not opt the user into a size constraint.
        st.session_state[f"use_build_{process}"] = False
    st.session_state.pop("auto_review", None)
    st.session_state.pop("queued_detail", None)


def clear_library_condition(process):
    """Return to the visible application defaults and clear imported evidence."""
    _write_values(process, _reset_values(process))
    st.session_state.pop(f"applied_condition_{process}", None)
    st.session_state.pop(f"equipment_defaults_{process}", None)
    st.session_state[f"condition_preview_{process}"] = None


def apply_library_condition(library, process, profile_id):
    """A fresh scenario cannot inherit unrelated tool or minimum-size limits."""
    record = library.profiles[profile_id]
    if not any(p.get("application") == "automatic" for p in record["parameters"].values()):
        return
    resolved = library.resolve(profile_id, process)
    values = {**_reset_values(process), **resolved["values"]}
    basis_key = "basis" if process == "CNC" else "threshold_basis"
    values[basis_key] = library.basis(profile_id)
    if process != "CNC" and "minimum_wall_mm" not in resolved["values"]:
        values[basis_key] += " | " + wall_default_basis(process)
    _write_values(process, values)
    st.session_state[f"applied_condition_{process}"] = {"profile_id": profile_id, "digest": library.digest}


def conditions_ready(library, process):
    applied = st.session_state.get(f"applied_condition_{process}", {})
    return (not applied or bool(library is not None and applied.get("digest") == library.digest
        and library.profiles.get(applied.get("profile_id"), {}).get("process") == process))


def _source_link(source):
    title = source.get("title", source.get("id", "근거 자료"))
    url = source.get("url", "")
    try:
        parsed = urlsplit(url)
    except (TypeError, ValueError):
        parsed = None
    if parsed and parsed.scheme in ("https", "http") and parsed.netloc:
        st.markdown(f"[{title}]({url})")
    else:
        st.write(title)
    for field, label in (("locator", "확인 항목"), ("revision", "판본"), ("accessed", "확인일")):
        if source.get(field):
            st.caption(f"{label}: {_display(source[field])}")


def render_condition_picker(process, *, compact=False):
    """Return the library for this run; optional lookup stays outside forms."""
    try:
        library = load_library()
    except (OSError, ValueError) as exc:
        st.warning("조건 라이브러리를 읽지 못했습니다. 직접 조건을 입력해 검토할 수 있습니다.")
        st.caption(str(exc))
        if st.session_state.get(f"applied_condition_{process}"):
            st.warning("이전에 가져온 조건의 출처를 확인할 수 없어 검토를 보류합니다. 라이브러리를 복구하거나 직접 입력으로 초기화하세요.")
            st.button("직접 입력으로 초기화", key=f"clear_condition_{process}",
                      on_click=clear_library_condition, args=(process,))
        return None
    records = library.profiles_for(process)
    applied = st.session_state.get(f"applied_condition_{process}", {})
    applied_id = applied.get("profile_id")
    active = library.profiles.get(applied_id)
    if compact:
        return library
    with st.expander("저장된 조건 가져오기", expanded=False):
        lookup = {r["id"]: r for r in records}
        preview_key = f"condition_preview_{process}"
        if st.session_state.get(preview_key) not in lookup:
            st.session_state[preview_key] = None
        selected = st.selectbox("조건 검색·선택", [None, *lookup], key=preview_key,
            format_func=lambda key: "조건을 선택하세요" if key is None else lookup[key]["label"],
            placeholder="장비·재료·공구 검색", persist_state="session")
        if selected:
            record = lookup[selected]
            automatic = any(p.get("application") == "automatic" for p in record["parameters"].values())
            st.markdown(f"**{record['label']}**")
            for field, label in (("machine", "장비"), ("material", "재료")):
                if record.get(field):
                    st.write(f"{label}: {record[field]}")
            rows = []
            for field, parameter in record.get("parameters", {}).items():
                rows.append({"항목": parameter.get("label", FIELD_LABELS.get(field, field)),
                    "값": _parameter_display(field, parameter),
                    "검토 연결": "입력값으로 가져옴" if parameter.get("application") == "automatic" else "참고만 · 계산 미연결"})
            if rows:
                st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
                parameter_key = f"condition_parameter_{process}"
                if st.session_state.get(parameter_key) not in record["parameters"]:
                    st.session_state[parameter_key] = next(iter(record["parameters"]))
                field = st.selectbox("값별 적용 조건·원문 위치", list(record["parameters"]), key=parameter_key,
                                     format_func=lambda k: record["parameters"][k].get("label", FIELD_LABELS.get(k, k)))
                parameter = record["parameters"][field]
                st.caption("원문 위치: " + parameter["locator"])
                for condition in parameter.get("conditions", []):
                    st.caption("이 값의 조건: " + condition)
            if automatic:
                st.button("이 조건을 입력에 적용", key=f"apply_condition_{process}", type="primary",
                          width="stretch", on_click=apply_library_condition, args=(library, process, selected))
            else:
                st.info("참고용 자료 · 적용할 수치 없음")
            with st.expander("조건의 출처"):
                for condition in record.get("conditions", []):
                    st.write(f"• {condition}")
                for source_id in record.get("source_ids", []):
                    if source_id in library.sources:
                        _source_link(library.sources[source_id])
        if applied_id:
            st.button("직접 입력으로 초기화", key=f"clear_condition_{process}",
                      on_click=clear_library_condition, args=(process,))
    if active and applied.get("digest") == library.digest:
        st.caption(f"적용 조건: {active['label']}")
    elif applied_id:
        st.warning("적용했던 조건 데이터가 변경되어 검토를 보류합니다. 조건을 재적용하거나 ‘직접 입력으로 초기화’를 누르세요.")
    return library


def condition_context(library, process, actual):
    applied = st.session_state.get(f"applied_condition_{process}", {})
    if library is None or applied.get("digest") != library.digest:
        return {}
    profile_id = applied.get("profile_id")
    if not profile_id or profile_id not in library.profiles:
        return {}
    return library.context(profile_id, process, actual)


def render_condition_evidence(evidence):
    if not evidence:
        return
    with st.expander("적용 조건·출처"):
        st.markdown(f"**{evidence['label']}**")
        rows = []
        for key, field in evidence.get("fields", {}).items():
            unit = "mm" if key.endswith("_mm") else ""
            rows.append({"항목": FIELD_LABELS.get(key, key),
                         "출처 값": _display(field.get("expected"), unit),
                         "실제 적용": "크기 제한 미적용" if field.get("status") == "disabled" else _display(field.get("effective"), unit),
                         "구분": {"source_value": "출처 값 사용", "disabled": "사용 안 함", "user_override": "사용자가 변경", "geometry_proposal": "형상에서 자동 제안"}.get(field.get("status"), "확인 필요")})
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        changed = [FIELD_LABELS.get(key, key) for key, value in evidence.get("fields", {}).items() if value.get("status") == "user_override"]
        if changed:
            st.info("직접 변경: " + ", ".join(changed))
        additional = evidence.get("user_inputs", {})
        generated = evidence.get("generated_inputs", {})
        if generated:
            st.markdown("**형상에서 자동 제안**")
            st.dataframe(pd.DataFrame([{"항목": FIELD_LABELS.get(key, key),
                "실제 적용": _display(value.get("effective"), "mm" if key.endswith("_mm") else "")}
                for key, value in generated.items()]), hide_index=True, width="stretch")
        if additional:
            st.markdown("**자료에 없는 직접 입력·탐색 기본값**")
            st.dataframe(pd.DataFrame([{"항목": FIELD_LABELS.get(key, key),
                "실제 적용": _display(value.get("effective"), "mm" if key.endswith("_mm") else ""),
                "구분": "직접 입력·탐색 기본값"} for key, value in additional.items()]),
                hide_index=True, width="stretch")
        for condition in evidence.get("conditions", []):
            st.write(f"• {condition}")
        for source in evidence.get("sources", {}).values():
            _source_link(source)
        st.json(evidence, expanded=False)


def render_literature_library(process):
    """Browse existing reading records without inventing numerical criteria."""
    with st.expander("표준·논문 근거 찾아보기"):
        try:
            records = [r for r in load_literature() if process in r.get("discovery_processes", [])]
        except (OSError, ValueError) as exc:
            st.warning(str(exc))
            return
        matches = {r["id"]: r for r in records}
        key = f"literature_choice_{process}"
        if st.session_state.get(key) not in matches:
            st.session_state[key] = None
        selected = st.selectbox("문헌 검색·선택", [None, *matches], key=key,
            format_func=lambda value: "문헌을 선택하세요" if value is None else matches[value]["title"])
        if selected:
            record = matches[selected]
            st.write(f"**{record['title']}**")
            st.caption(f"{record['pages']}쪽 · 전문 검토 기록 {record['reading_record_date']}")
            st.write("저장소 원문 위치: " + record["repository_path"])
            st.write("검토 기록 위치: " + record["audit_path"])
            if record.get("source_limit"):
                st.caption("원문 한계: " + str(record["source_limit"]))
            for source in record.get("current_code_references", []):
                _source_link(source)
                if source.get("use"):
                    st.write(source["use"])
            if not record.get("current_code_references"):
                st.caption("현재 규칙에 직접 인용된 항목은 없습니다. 배경·후속 연구 자료로 구분합니다.")
