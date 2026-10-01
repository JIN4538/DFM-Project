"""Source-backed, offline conditions; explicit scenarios, never fuzzy inference.

Catalog specifications, slicer settings and physical validation are distinct.
Only an allowlisted field with a checked source can feed the geometry engines.
Everything else remains inspectable reference information.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import date
import hashlib
import json
import math
from pathlib import Path
from urllib.parse import urlparse


DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "conditions"
PROCESSES = {"MEX", "VPP", "PBF_POLYMER", "PBF_METAL", "CNC"}
AM_FIELDS = {"build_volume_mm", "minimum_wall_mm", "minimum_hole_mm", "layer_height_mm", "line_width_mm"}
CNC_FIELDS = {"tool_diameter_mm", "flute_length_mm", "reach_mm", "hole_depth_ratio_limit"}
KINDS = {"machine_specification", "tool_specification", "manufacturer_guidance", "slicer_setting",
         "material_property", "experimental_result"}
LENGTH_UNITS = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "inch": 25.4, "in": 25.4,
                "um": .001, "µm": .001, "μm": .001}
FIELD_LABELS = {
    "machine": "장비", "material": "재료", "slicer": "슬라이서",
    "build_volume_mm": "빌드 공간", "minimum_wall_mm": "최소 벽 비교 기준",
    "minimum_hole_mm": "최소 홀 기록 기준", "layer_height_mm": "층 높이",
    "line_width_mm": "MEX 명목 선폭", "tool_diameter_mm": "엔드밀 지름",
    "flute_length_mm": "날 길이", "reach_mm": "장착 후 돌출 길이",
    "hole_depth_ratio_limit": "원통 구간 길이/지름 비교 기준",
}


class ConditionError(ValueError):
    """Invalid or incompatible evidence must not silently become a preset."""


def _require(condition, message):
    if not condition:
        raise ConditionError(message)


def _strings(value, label, *, nonempty=False):
    _require(isinstance(value, list) and all(isinstance(x, str) and x.strip() for x in value)
             and (bool(value) or not nonempty), f"{label}: 문자열 목록이 필요합니다.")


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _same(left, right):
    # Canonical numeric settings are compared exactly; deliberate small edits
    # must remain visible rather than swallowed by a broad tolerance.
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return len(left) == len(right) and all(_same(a, b) for a, b in zip(left, right))
    return left == right


def _canonical(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def _input_fields(process):
    fields = ((CNC_FIELDS | {"machine", "material"}) if process == "CNC" else
              AM_FIELDS | {"machine", "material", "slicer", "overhang_angle_deg", "clearance_mm"})
    if process != "MEX":
        fields = fields - {"line_width_mm"}
    if process == "PBF_POLYMER":
        fields = fields - {"overhang_angle_deg"}
    return fields


def normalize_parameter(field, parameter):
    """Normalize allowed engine inputs only. Reference values stay in source units."""
    value, unit = parameter["value"], parameter["unit"]
    if field == "hole_depth_ratio_limit":
        _require(unit in {"1", "ratio", "dimensionless"}, f"{field}: 무차원 단위가 필요합니다.")
        factor = 1.0
    else:
        _require(unit in LENGTH_UNITS, f"{field}: 지원하지 않는 길이 단위 {unit}")
        factor = LENGTH_UNITS[unit]
    if field == "build_volume_mm":
        _require(isinstance(value, list) and len(value) == 3, "빌드 공간은 X·Y·Z 세 치수여야 합니다.")
        values = value
    else:
        values = [value]
    _require(all(_finite(x) and x > 0 for x in values), f"{field}: 유한한 양수만 적용할 수 있습니다.")
    normalized = [float(x) * factor for x in values]
    _require(all(math.isfinite(x) and x > 0 for x in normalized), f"{field}: 단위 변환 범위를 벗어났습니다.")
    return normalized if field == "build_volume_mm" else normalized[0]


class ConditionLibrary:
    def __init__(self, bundles):
        self.sources = {}
        self.profiles = {}
        bundles = deepcopy(list(bundles))
        for bundle in bundles:
            _require(isinstance(bundle, dict), "조건 DB 최상위는 객체여야 합니다.")
            _require(bundle.get("schema_version") == 1, "조건 DB의 지원하지 않는 스키마 버전입니다.")
            _require(isinstance(bundle.get("sources"), list) and isinstance(bundle.get("profiles"), list), "출처와 조건 목록이 필요합니다.")
            for source in bundle["sources"]:
                _require(isinstance(source, dict), "출처 레코드가 객체가 아닙니다.")
                for field in ("id", "title", "publisher", "url", "accessed", "locator", "revision"):
                    _require(isinstance(source.get(field), str) and source[field].strip(), f"출처 {field} 누락")
                _require(source["id"] not in self.sources, f"중복 출처 ID: {source['id']}")
                parsed = urlparse(source["url"])
                _require(parsed.scheme in {"https", "http"} and bool(parsed.netloc), "출처에는 HTTP(S) 원문 주소가 필요합니다.")
                try:
                    date.fromisoformat(source["accessed"])
                except ValueError as exc:
                    raise ConditionError("출처 확인 날짜가 잘못되었습니다.") from exc
                _require(source.get("verification") == "primary_source_checked", "자동 조건 DB에는 대조된 1차 출처만 등록합니다.")
                _strings(source.get("limitations"), "출처 한계")
                self.sources[source["id"]] = source
        for bundle in bundles:
            for profile in bundle["profiles"]:
                self._validate_profile(profile)
                self.profiles[profile["id"]] = profile
        self.digest = hashlib.sha256(_canonical(bundles)).hexdigest()

    def _source_ids(self, value, label):
        _strings(value, label, nonempty=True)
        _require(len(set(value)) == len(value), f"{label}: 중복 출처")
        _require(set(value) <= self.sources.keys(), f"{label}: 존재하지 않는 출처")

    def _validate_profile(self, profile):
        _require(isinstance(profile, dict), "조건 레코드가 객체가 아닙니다.")
        for key in ("id", "label"):
            _require(isinstance(profile.get(key), str) and profile[key].strip(), f"조건 {key} 누락")
        _require(profile["id"] not in self.profiles, f"중복 조건 ID: {profile['id']}")
        process = profile.get("process")
        _require(process in PROCESSES, f"지원 범위 밖 공정: {process}")
        _require(profile.get("category") in {"machine", "material", "process", "tool"}, "조건 분류 오류")
        for key in ("machine", "material", "slicer"):
            _require(key not in profile or isinstance(profile[key], str), f"{key}: 이름은 문자열이어야 합니다.")
        _require(process != "CNC" or "slicer" not in profile, "CNC 조건에는 슬라이서 필드를 사용할 수 없습니다.")
        _require(profile.get("physical_validation") == "not_validated_by_project", "이 DB는 프로젝트의 실물 검증 자료가 아닙니다.")
        _strings(profile.get("conditions"), "조건 적용 범위", nonempty=True)
        _strings(profile.get("limitations"), "조건 한계", nonempty=True)
        self._source_ids(profile.get("source_ids"), profile["id"])
        params = profile.get("parameters")
        _require(isinstance(params, dict), "조건 parameters가 필요합니다.")
        for field, parameter in params.items():
            _require(isinstance(parameter, dict), f"{field}: 조건 레코드가 필요합니다.")
            self._source_ids(parameter.get("source_ids"), field)
            _require(set(parameter["source_ids"]) <= set(profile["source_ids"]), f"{field}: 조건 출처 목록에 없는 출처")
            for key in ("unit", "locator"):
                _require(isinstance(parameter.get(key), str) and parameter[key].strip(), f"{field}: {key} 누락")
            _strings(parameter.get("conditions"), f"{field} 적용 조건")
            _require(parameter.get("kind") in KINDS, f"{field}: 값의 성격 누락")
            application = parameter.get("application")
            _require(application in {"automatic", "reference_only"}, f"{field}: 연결 범위 오류")
            value = parameter.get("value")
            _require(value is not None and not isinstance(value, (bool, dict)), f"{field}: 미확정 값을 숫자 또는 거짓으로 대체할 수 없습니다.")
            numbers = value if isinstance(value, list) else [value]
            _require(bool(numbers) and all((isinstance(x, str) and bool(x.strip())) or _finite(x) for x in numbers), f"{field}: 비정상 값")
            if application == "automatic":
                allowed = CNC_FIELDS if process == "CNC" else AM_FIELDS
                _require(field in allowed, f"{field}: 계산에 연결할 수 없는 항목입니다.")
                _require(field != "line_width_mm" or process == "MEX", "선폭은 MEX에만 적용합니다.")
                _require(parameter["kind"] not in {"experimental_result", "material_property"}, "물성·실험값을 범용 판정값으로 자동 적용할 수 없습니다.")
                normalize_parameter(field, parameter)
        # Test coherent dimensions through the existing engine validators too.
        numeric = {key: normalize_parameter(key, p) for key, p in params.items() if p["application"] == "automatic"}
        if process == "CNC":
            from .machining import MachiningProfile
            MachiningProfile(**numeric).validate()
        else:
            from amdfm.profiles import Profile
            Profile(process=process, **numeric).validate()

    def profiles_for(self, process):
        _require(process in PROCESSES, f"지원 범위 밖 공정: {process}")
        return deepcopy(sorted((p for p in self.profiles.values() if p["process"] == process), key=lambda p: p["label"]))

    def resolve(self, profile_id, process):
        _require(profile_id in self.profiles, "등록되지 않은 조건입니다. 목록에서 정확한 조건을 선택하세요.")
        profile = self.profiles[profile_id]
        _require(profile["process"] == process, "선택한 조건과 검토 공정이 다릅니다.")
        values = {key: normalize_parameter(key, p) for key, p in profile["parameters"].items() if p["application"] == "automatic"}
        for key in ("machine", "material", "slicer"):
            if profile.get(key) and profile[key] not in {"미확정", "unspecified", "unknown"}:
                values[key] = profile[key]
        evidence = {
            "profile_id": profile_id, "label": profile["label"], "process": process,
            "database_sha256": self.digest, "schema_version": 1,
            "selection_method": "explicit_scenario_selection",
            "physical_validation": profile["physical_validation"],
            "conditions": profile["conditions"], "limitations": profile["limitations"],
            "parameters": profile["parameters"],
            "sources": {key: self.sources[key] for key in profile["source_ids"]},
            "expected_values": values,
        }
        return deepcopy({"values": values, "evidence": evidence})

    def context(self, profile_id, process, actual):
        if not profile_id:
            return {}
        resolved = self.resolve(profile_id, process)
        evidence = resolved["evidence"]
        evidence["fields"] = {
            key: {"expected": value, "effective": deepcopy(actual.get(key)),
                  "overridden": not _same(value, actual.get(key)),
                  "status": "disabled" if key == "build_volume_mm" and actual.get(key) is None else
                            "user_override" if not _same(value, actual.get(key)) else "source_value"}
            for key, value in resolved["values"].items()
        }
        evidence["overridden_fields"] = [k for k, v in evidence["fields"].items() if v["overridden"]]
        # A user can add a wall limit after selecting a machine-only record.
        # Such new criteria have no authority from that machine's source.
        candidates = _input_fields(process)
        # Include None: adding a formerly unknown limit must invalidate a stale
        # snapshot just as changing an already-populated limit does.
        evidence["input_snapshot"] = {key: deepcopy(actual.get(key)) for key in sorted(candidates)}
        evidence["user_inputs"] = {
            key: {"effective": deepcopy(actual[key]), "status": "user_input_or_exploration_default"}
            for key in sorted(candidates - resolved["values"].keys())
            if key in actual and actual[key] is not None and actual[key] != "미확정"
        }
        return evidence

    def am_profile(self, profile_id, *, enforce_build_volume=False, overrides=None):
        from amdfm.profiles import Profile
        _require(profile_id in self.profiles, "등록되지 않은 조건입니다.")
        process = self.profiles[profile_id]["process"]
        _require(process != "CNC", "AM 조건이 아닙니다.")
        resolved = self.resolve(profile_id, process)
        values = resolved["values"]
        if not enforce_build_volume:
            values.pop("build_volume_mm", None)
        values.update(overrides or {})
        _require(not {"condition_evidence", "process"}.intersection(values), "조건의 공정·출처를 수동으로 덮어쓸 수 없습니다.")
        values.setdefault("threshold_basis", self.basis(profile_id))
        default_layer = {"MEX": .2, "VPP": .05, "PBF_POLYMER": .1, "PBF_METAL": .03}[process]
        profile = replace(Profile(process=process, name=self.profiles[profile_id]["label"], layer_height_mm=default_layer), **values)
        profile = replace(profile, condition_evidence=self.context(profile_id, process, profile.to_dict()))
        profile.validate()
        return profile

    def machining_profile(self, profile_id, *, overrides=None):
        from .machining import MachiningProfile
        resolved = self.resolve(profile_id, "CNC")
        values = resolved["values"]
        values.update(overrides or {})
        _require("condition_evidence" not in values, "조건의 출처를 수동으로 덮어쓸 수 없습니다.")
        values.setdefault("basis", self.basis(profile_id))
        profile = MachiningProfile(**values, condition_evidence={})
        profile = replace(profile, condition_evidence=self.context(profile_id, "CNC", profile.to_dict()))
        profile.validate()
        return profile

    def basis(self, profile_id):
        profile = self.profiles[profile_id]
        titles = "; ".join(self.sources[s]["title"] for s in profile["source_ids"])
        return (f"조건 DB: {profile['label']} · {titles} · 원자료에 없는 값은 사용자 입력·탐색 기본값; "
                "적용 조건 확인 필요; 프로젝트 실물 검증 전")


def _unique_keys(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, f"JSON 키가 중복되어 값이 모호합니다: {key}")
        result[key] = value
    return result


def load_library(directory=None):
    directory = Path(directory) if directory is not None else DATA_DIR
    paths = sorted(directory.glob("*.json"))
    paths = [p for p in paths if p.name not in {"literature.json", "schema.json"}]
    _require(bool(paths), "조건 DB 파일이 없습니다. data/conditions 폴더를 함께 배포하세요.")
    try:
        bundles = [json.loads(p.read_text(encoding="utf-8"), object_pairs_hook=_unique_keys) for p in paths]
        return ConditionLibrary(bundles)
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ConditionError(f"조건 DB를 읽을 수 없습니다: {exc}") from exc


def load_literature(directory=None):
    """Discovery index only; it cannot provide automatic thresholds."""
    directory = Path(directory) if directory is not None else DATA_DIR
    path = directory / "literature.json"
    if not path.exists():
        return []
    try:
        catalog = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_keys)
        _require(catalog.get("schema_version") == 1, "문헌 색인 버전 오류")
        records = catalog["records"]
        _require(isinstance(records, list), "문헌 색인 형식 오류")
        _require(all(r.get("application") == "background_only" and not r.get("automatic_parameters") for r in records),
                 "문헌 색인을 수치 기준으로 승격할 수 없습니다.")
        return records
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise ConditionError(f"문헌 색인을 읽을 수 없습니다: {exc}") from exc


def validate_context(evidence, process, actual):
    if not evidence:
        return
    _require(isinstance(evidence, dict) and evidence.get("process") == process, "조건 출처와 검토 공정이 일치하지 않습니다.")
    _require(evidence.get("physical_validation") == "not_validated_by_project", "조건 DB를 실물 검증으로 표시할 수 없습니다.")
    snapshot = evidence.get("input_snapshot")
    _require(isinstance(snapshot, dict) and set(snapshot) == _input_fields(process), "계산 조건의 전체 출처 스냅샷이 필요합니다.")
    for key, value in snapshot.items():
        _require(_same(value, actual.get(key)), f"{key}: 입력 변경 후 출처 기록을 다시 생성해야 합니다.")
    _require(isinstance(evidence.get("fields"), dict), "조건의 적용 값 기록이 없습니다.")
    for key, field in evidence["fields"].items():
        _require(isinstance(field, dict) and _same(actual.get(key), field.get("effective")), f"{key}: 수치 변경 후 조건 출처 기록도 갱신해야 합니다.")
    for key, field in evidence.get("user_inputs", {}).items():
        _require(isinstance(field, dict) and _same(actual.get(key), field.get("effective")), f"{key}: 사용자 입력 변경 후 출처 기록도 갱신해야 합니다.")


def condition_html(evidence):
    """Readable, escaped provenance in both standalone report families."""
    from html import escape
    if not evidence:
        return ""
    esc = lambda x: escape(str(x), quote=True)
    def fmt(value):
        if value is None:
            return "미적용 / 미입력"
        if isinstance(value, (tuple, list)):
            return " × ".join(fmt(x) for x in value)
        return f"{value:g}" if isinstance(value, (int, float)) else str(value)
    rows = "".join(
        f"<tr><td>{esc(FIELD_LABELS.get(key, key))}</td><td>{esc(fmt(field['expected']))}</td>"
        f"<td>{esc(fmt(field['effective']))}</td><td>{esc({'source_value':'출처 값','user_override':'사용자 변경','disabled':'사용 안 함','geometry_proposal':'형상에서 자동 제안'}.get(field['status'], '확인 필요'))}</td></tr>"
        for key, field in evidence.get("fields", {}).items())
    links = "".join(f"<li><a href='{esc(s['url'])}'>{esc(s['title'])}</a> · {esc(s['locator'])} · 확인 {esc(s['accessed'])}</li>"
                    for s in evidence.get("sources", {}).values())
    unsourced = "".join(f"<li>{esc(FIELD_LABELS.get(k, k))}: {esc(fmt(v['effective']))}</li>"
                        for k, v in evidence.get("user_inputs", {}).items())
    generated = "".join(f"<li>{esc(FIELD_LABELS.get(k, k))}: {esc(fmt(v['effective']))}</li>"
                        for k, v in evidence.get("generated_inputs", {}).items())
    return (f"<details><summary>적용한 조건 DB · {esc(evidence['label'])}</summary>"
            "<p>선택한 시나리오의 출처 값과 실제 계산에 사용한 값을 구분합니다. 실물 제조 검증은 수행하지 않았습니다.</p>"
            "<table><tr><th>항목 (길이 mm)</th><th>출처 값</th><th>실제 적용</th><th>구분</th></tr>" + rows + "</table>"
            + "<p><b>원자료에 없는 직접 입력·탐색 기본값</b> · 아래 값은 선택한 출처가 정한 값이 아닙니다.</p><ul>" + unsourced + "</ul>"
            + ("<p><b>형상에서 자동 제안</b></p><ul>" + generated + "</ul>" if generated else "")
            + "<p>" + esc(" · ".join(evidence.get("conditions", []))) + "</p>"
            + "<p>" + esc(" · ".join(evidence.get("limitations", []))) + "</p><ul>" + links + "</ul>"
            + f"<p>DB SHA-256: {esc(evidence['database_sha256'])}</p></details>")
