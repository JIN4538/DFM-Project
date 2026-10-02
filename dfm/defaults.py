"""Editable UI starting criteria, with the exact basis retained for inspection.

These are application review defaults drawn from named manufacturer guidance.
They are not universal material limits, nor are they added to Profile's backend
defaults: a caller that explicitly supplies None must retain an unknown criterion.
"""
from copy import deepcopy


_WALL_DEFAULTS = {
    "MEX": {
        "value_mm": 1.2,
        "title": "Formlabs — Minimum Wall Thickness for 3D Printing",
        "url": "https://formlabs.com/blog/minimum-wall-thickness-3d-printing/",
        "locator": "Minimum Wall Thickness by 3D Printing Process; 0.4 mm nozzle example",
        "source_condition": "FDM: 일반 안내 1 mm와 0.4 mm 노즐 예시의 1.2 mm 권고",
        "selection_reason": "0.4 mm 노즐 예시의 1.2 mm를 초기 비교값으로 채택",
    },
    "VPP": {
        "value_mm": 0.4,
        "title": "Formlabs — Design specifications for 3D models (Form 2)",
        "url": "https://formlabs.com/support/Design-Specs/",
        "locator": "Minimum supported/unsupported wall thickness",
        "source_condition": "Form 2 · Clear Resin · 층 높이 0.1 mm; 두 연결 조건 모두 0.4 mm 권고",
        "selection_reason": "Form 4의 0.2 mm보다 큰 Form 2 참고값을 초기 비교값으로 채택",
    },
    "PBF_POLYMER": {
        "value_mm": 0.6,
        "title": "Formlabs — Design specifications for 3D models (Fuse 1 generation)",
        "url": "https://formlabs.com/support/Design-specifications-for-3D-models-Fuse-1/",
        "locator": "Minimum supported/unsupported wall thickness",
        "source_condition": "Fuse 1 · Nylon 12; 수직 벽 0.6 mm, 수평 벽 0.3 mm",
        "selection_reason": "방향별 참고값 중 큰 0.6 mm를 초기 비교값으로 채택",
    },
    "PBF_METAL": {
        "value_mm": 0.4,
        "title": "EOS — StainlessSteel 316L Material Data Sheet (07/2022)",
        "url": "https://www.eos.info/03_system-related-assets/material-related-contents/metal-materials-and-examples/metal-material-datasheet/stainlesssteel/material_datasheet_eos_stainlesssteel_316l_en_web.pdf",
        "locator": "PDF p.5 (zero-based page 4); Min. wall thickness",
        "source_condition": "EOS M 290 · EOS StainlessSteel 316L · 316L_Surface_1.X · 층 높이 0.02 mm; 0.3–0.4 mm",
        "selection_reason": "참고 범위의 상단 0.4 mm를 초기 비교값으로 채택",
    },
}


def wall_default(process):
    """Return a fresh provenance record for a supported AM process."""
    return {**deepcopy(_WALL_DEFAULTS[process]), "kind": "application_review_default", "accessed": "2026-09-29"}


def wall_default_value(process):
    return _WALL_DEFAULTS[process]["value_mm"]


def wall_default_basis(process):
    row = wall_default(process)
    return f"앱 기본 벽 비교값 {row['value_mm']:g} mm · {row['title']} · {row['source_condition']} · {row['url']}"


def wall_default_context(process, actual_value):
    """Describe a default/override without claiming source-backed equipment fit."""
    row = wall_default(process)
    return {**row, "effective_mm": actual_value,
            "status": "disabled" if actual_value is None else
                      "default_value" if actual_value == row["value_mm"] else "user_override"}
