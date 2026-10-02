"""적층제조(AM) 제조성 평가 규칙 엔진 (v2)

v1 대비 주요 변경
-----------------
1. 평가를 두 단계로 나눈다.
   - 하드 게이트 (feasibility): 입력 유효성 및 현재 프로필의 제약 조건.
     미충족이나 판정 불확실성이 있으면 점수를 매기지 않는다.
     v1은 빌드볼륨 초과 부품도 가중평균에 섞어서, 나머지가 만점이면
     90점 A등급 '바로 인쇄 가능'이 나올 수 있었다.
   - 소프트 규칙 (quality): 게이트를 통과한 부품의 제조 난이도 점수.
2. 측정 불가 규칙은 100점이 아니라 N/A 이고, 가중치를 다른 규칙에
   재분배한다. v1은 동작하지 않는 구멍 규칙이 모든 부품에 만점을 줬다.
3. 점수 곡선을 연속 함수로 만들었다. v1은 임계값 경계에서 최대 30점이
   불연속으로 튀어서 삼각형 하나 차이로 등급이 바뀔 수 있었다.
4. 공정별 임계각/밀도를 형상 분석 계층까지 실제로 전달한다.
   v1은 45도가 하드코딩되어 SLA의 30도가 적용되지 않았다.
5. SLS 처럼 임계값이 0인 규칙은 나눗셈이 아니라 N/A로 처리한다.
   v1은 ZeroDivisionError로 앱이 죽었다.

기반 표준
---------
- KS D ISO/ASTM 52910(2024 확인), 적층제조 - 설계 - 요구사항, 지침 및 권고사항,
  국가기술표준원. (ISO/ASTM 52910:2018 IDT, 일치 채택)

  이 표준은 '무엇을 평가해야 하는가'의 근거이다.
    · 5장 설계 기회 및 제약
    · 6장 설계 고려사항  -> 소프트 규칙 목록의 근거
    · 7장 red flag 이슈  -> 하드 게이트의 근거

  이 표준은 '얼마여야 하는가'의 근거가 될 수 없다.
  적용범위 1.3에 "일반적 지침과 이슈 식별은 다루지만, 구체적 설계 해법이나
  공정별·재료별 데이터는 다루지 않는다"고 명시되어 있다.
  따라서 아래 PROCESS_PARAMS 의 모든 수치는 별도 출처를 가지며,
  각 항목의 'source' 필드에 그 출처를 명시한다.

- Oh, Y., Ko, H., Sprock, T., Bernstein, W. Z., & Kwon, S. (2021).
  Additive Manufacturing, 37, 101702.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

import numpy as np
import trimesh

from src.core import geometry_analyzer as ga
from src.core.mesh_diagnostics import inspect_mesh
from src.core.reproducibility import APP_VERSION


class ProcessType(Enum):
    FDM = "FDM"
    SLA = "SLA"
    SLS = "SLS"
    DMLS = "DMLS"


# 공정 명칭 정리
#   FDM / SLA / SLS 등은 특정 기업의 상표에서 유래한 통칭이며 표준 문서에는 등장하지
#   않는다. KS D ISO/ASTM 52910:2018 3.1절은 적층제조 공정을 7가지로 분류하고
#   각각에 표준 용어를 부여한다. 실무 통용성을 위해 통칭을 유지하되 표준 용어를 병기한다.
PROCESS_TERMS = {
    ProcessType.FDM:  dict(std_ko='재료 압출',     std_en='material extrusion',
                           clause='3.1.3'),
    ProcessType.SLA:  dict(std_ko='액조 광경화',   std_en='vat photopolymerization',
                           clause='3.1.7'),
    ProcessType.SLS:  dict(std_ko='분말 베드 융해', std_en='powder bed fusion',
                           clause='3.1.5'),
    ProcessType.DMLS: dict(std_ko='분말 베드 융해', std_en='powder bed fusion',
                           clause='3.1.5'),
}


def process_label(ptype, short=False) -> str:
    """UI/보고서용 공정 표기. 통칭 + 표준 용어 병기."""
    if isinstance(ptype, str):
        ptype = ProcessType[ptype.upper()]
    t = PROCESS_TERMS[ptype]
    if short:
        return f"{ptype.value} ({t['std_ko']})"
    return f"{ptype.value} ({t['std_ko']}, {t['std_en']}) — 52910 {t['clause']}"


# ──────────────────────────────────────────────────────────────
# 공정별 파라미터
#   hard_*  : 보수적 프로필 제약. 위반은 모든 장비의 제조 불가능을 뜻하지 않음
#   thr_*   : 소프트 규칙 권장 기준
#   source  : 출처 명시 (교수님 질문 대비)
# ──────────────────────────────────────────────────────────────
PROCESS_PARAMS = {
    ProcessType.FDM: dict(
        hard_wall=0.4,          # 보수적 프로필 하한; 노즐 직경은 보편적 물리 한계가 아님
        thr_wall=1.0,
        # FDM 방향 검토용 잠정 임계각. 실제 장비·재료·슬라이서 조건에서 별도 검증이 필요하다.
        critical_angle=45.0,
        thr_overhang_area=0.30,
        thr_support_ratio=0.5,
        support_density=0.165,  # Cura 24건 회귀값 (설정 15% 와 근접)
        support_wall=0.2715,    # 둘레 항 계수 [mm]. 벽+인터페이스 실효 두께
        thr_aspect=10.0,
        thr_min_feature=0.8,
        layer_height=0.2,        # [사양] 장비 설정값
        line_width=0.4,          # 단면 검토의 기본 선폭. hard_wall과 독립적인 설정
        thr_cusp_ratio=0.5,      # [판단] 평균 계단높이 / 층두께
        # [실측] Jiang, Xu & Stringer (2018), CIE48. 노즐 0.4mm, PLA, 층 0.2mm,
        #   190도, 20mm/s 조건에서 변형 허용 0.15mm 기준 LPBL = 2.0mm 로 실측됨.
        #   노즐과 층 두께만 같고 재료·온도·속도·냉각 조건은 별도 확인해야 한다.
        #   이전에는 근거 없이 10mm 를 썼는데, 브리지 한계를 크게 잡을수록 지지가
        #   필요한 구간을 불필요하다고 판정하므로 오차 방향이 위험한 쪽이었다.
        bridge_limit=2.0,
        thr_gap=0.5,             # [관행] 노즐 폭 이상이어야 두 형상이 분리됨
        thr_thickness_ratio=3.0, # [관행] 급격한 두께 변화 설계 지침
        trapped_blocks=False,   # 재료 압출: 서포트가 갇히는 정도라 경고
        source="노즐 0.4mm를 가정한 잠정 프로필. 서포트 계수는 보고서의 Cura 회귀값이며 원자료 재검증 필요. 재료 압출 관련 표준은 ISO/ASTM 52903-1/-2에 존재함.",
    ),
    ProcessType.SLA: dict(
        hard_wall=0.2,
        thr_wall=0.5,
        critical_angle=30.0,
        thr_overhang_area=0.25,
        thr_support_ratio=0.3,
        support_density=0.10, support_wall=0.20,   # 미검증 추정값
        thr_aspect=8.0,
        thr_min_feature=0.3,
        layer_height=0.05, thr_cusp_ratio=0.5,
        bridge_limit=0.0,        # 액조 광경화는 브리징 불가
        thr_gap=0.3, thr_thickness_ratio=3.0,
        trapped_blocks=True,    # 액조 광경화: 레진이 경화되어 영구 잔류
        source="장비 제조사 설계 가이드 기반 잠정값. 문헌 출처 확정 필요",
    ),
    ProcessType.SLS: dict(
        hard_wall=0.4,
        thr_wall=0.8,
        critical_angle=0.0,     # 분말이 지지 역할 -> 기하학적 지지구조 불필요
        thr_overhang_area=None, # N/A
        thr_support_ratio=None, # N/A
        support_density=0.0, support_wall=0.0,
        thr_aspect=12.0,
        thr_min_feature=0.5,
        layer_height=0.1, thr_cusp_ratio=0.5,
        bridge_limit=0.0,        # 분말이 지지하므로 브리징 개념 없음
        thr_gap=0.5, thr_thickness_ratio=3.0,
        trapped_blocks=True,    # 분말 베드 융해: 갇힌 분말 배출 불가
        source="장비 제조사 설계 가이드 기반 잠정값. 문헌 출처 확정 필요",
    ),
    ProcessType.DMLS: dict(
        hard_wall=0.15,
        thr_wall=0.3,
        # [관행] Jiang, Xu & Stringer (2018) 은 대부분의 프린터에서 PTOA 가
        #   45도로 설정된다고 서술한다. 같은 논문의 실측값은 그 조건에서 40도이며,
        #   45도를 쓰면 40~45도 구간을 지지 필요로 과대 판정한다(안전한 방향).
        critical_angle=45.0,
        thr_overhang_area=0.30,
        thr_support_ratio=0.4,
        support_density=0.20, support_wall=0.35,   # 미검증 추정값 (금속은 열전달 목적)
        thr_aspect=8.0,
        thr_min_feature=0.2,
        layer_height=0.03, thr_cusp_ratio=0.5,
        # 금속 PBF 의 브리지 한계는 실측 자료를 확보하지 못했다. 근거 없이 값을
        # 주면 지지 필요 구간을 놓치므로, 실측 전까지 0(브리징 없음)으로 둔다.
        bridge_limit=0.0,
        thr_gap=0.3, thr_thickness_ratio=2.5,
        trapped_blocks=True,    # 분말 베드 융해: 갇힌 분말 배출 불가
        source="장비 제조사 설계 가이드 기반 잠정값. 문헌 출처 확정 필요",
    ),
}

# ──────────────────────────────────────────────────────────────
# 임계값 근거 등급 (provenance)
#
#   모든 수치가 똑같이 임의인 것은 아니다. 근거의 성격에 따라 네 단계로
#   나뉘며, 단계마다 개선 방법과 필요한 비용이 다르다. 이 표를 코드에 두는
#   이유는, 어떤 값이 취약한지 사용자와 개발자가 항상 볼 수 있게 하기
#   위해서다. 근거가 약한 값을 약하다고 표시하지 않으면 모든 값이
#   똑같이 믿을 만한 것처럼 보인다.
#
#   [사양]  장비·재료 사양에서 직접 온 값. 논쟁의 여지가 없다.
#   [유도]  물리 법칙이나 기하 항등식에서 유도된다. 임계값이라기보다 계산식이다.
#   [실측]  실험·계측으로 회귀한 값. 재현 가능하고 갱신 가능하다.
#   [관행]  업계 통용값. 출처는 있으나 물리적 필연은 아니다.
#   [판단]  근거 없음. 개발자가 정했다.
# ──────────────────────────────────────────────────────────────
THRESHOLD_PROVENANCE = {
    'hard_wall':          ('판단', 'FDM 노즐 0.4mm를 보수적 하한으로 채택. 제조 불가능을 증명하는 값은 아님'),
    'thr_wall':           ('관행', '압출선 2~3줄 확보. 제조 서비스 설계 가이드 0.8~1.2mm'),
    'critical_angle':     ('관행', '슬라이서 기본값 45°. Jiang 등(2018) 도 45°가 통용됨을 서술'),
    'support_density':    ('실측', 'Cura 24건 회귀. 2항 모델 R²=0.978, 기울기 1.0005'),
    'support_wall':       ('실측', 'Cura 24건 회귀. 벽·인터페이스 실효 두께'),
    'thr_min_feature':    ('관행', '노즐/빔 직경에서 유도한 통용값'),
    'thr_overhang_area':  ('판단', '근거 없음. 어느 비율부터 문제인지 실측되지 않음'),
    'thr_support_ratio':  ('판단', '근거 없음. 비용 관점의 허용선이 정해지지 않음'),
    'thr_aspect':         ('판단', '근거 없음. 넘어짐·변형 한계가 실측되지 않음'),
    'layer_height':       ('사양', '장비 설정값. 계단 높이는 이 값에서 유도된다'),
    'line_width':         ('사양', '단면 검토용 기본 선폭 0.4mm. 실제 슬라이서의 선폭 설정에 맞춰 변경'),
    'bridge_limit':       ('실측', 'Jiang 등(2018) CIE48 실측 LPBL 2.0mm. 문헌의 특정 PLA 조건이며 실제 장비 조건은 별도 검증 필요'),
    'thr_gap':            ('관행', '두 형상이 분리되려면 압출선/빔 폭 이상 필요'),
    'thr_thickness_ratio': ('관행', '급격한 두께 변화 설계 지침 (2~3배)'),
    'thr_cusp_ratio':     ('판단', '근거 없음. 허용 계단 높이가 용도에 따라 다름'),
}

GRADE_BOUNDARY_PROVENANCE = ('판단', '90/80/70/60 경계에 근거 없음')
WEIGHT_PROVENANCE = ('판단', '실패 심각도에 대한 개발자 판단. AHP·회귀로 대체 예정')


def provenance_report(process_type='FDM') -> list:
    """임계값별 근거 등급을 표로 돌려준다. UI 와 보고서에서 함께 쓴다."""
    ptype = process_type if isinstance(process_type, ProcessType) else ProcessType[process_type.upper()]
    order = {'사양': 0, '유도': 1, '실측': 2, '관행': 3, '판단': 4}
    rows = []
    for key, (lvl, src) in THRESHOLD_PROVENANCE.items():
        if ptype != ProcessType.FDM:
            lvl, src = '판단', '공정별 미검증 잠정값. FDM 근거를 전용하지 않음'
        vals = {}
        for pt, P in PROCESS_PARAMS.items():
            v = P.get(key)
            vals[pt.value] = '—' if v is None else v
        rows.append({'항목': key, '등급': lvl, '근거': src, '공정': ptype.value, '값': vals[ptype.value]})
    rows.sort(key=lambda r: (order.get(r['등급'], 9), r['항목']))
    return rows


# 소프트 규칙 기본 가중치. N/A 규칙의 몫은 나머지에 비례 재분배된다.
BASE_WEIGHTS = {
    'wall_thickness':     0.20,
    'overhang_area':      0.20,
    'support_volume':     0.15,
    'staircase':          0.10,
    'thickness_gradient': 0.08,
    'feature_gap':        0.07,
    'aspect_ratio':       0.08,
    'build_margin':       0.04,
    'min_feature_size':   0.05,
    'horizontal_hole':    0.03,
}

RULE_LABELS = {
    'wall_thickness':   '최소 벽두께 (Min Wall Thickness)',
    'overhang_area':    '오버행 면적 비율 (Overhang Area Ratio)',
    'support_volume':   '지지구조물 부피 비율 (Support Volume Ratio)',
    'aspect_ratio':     '종횡비 (Aspect Ratio)',
    'build_margin':     '빌드 볼륨 여유 (Build Volume Margin)',
    'min_feature_size': '최소 특징 크기 (Min Feature Size)',
    'horizontal_hole':  '수평 구멍 직경 (Horizontal Hole Dia.)',
    'staircase':          '계단 효과 (Staircase / Surface Roughness)',
    'thickness_gradient': '갑작스런 두께 변화 (Abrupt Thickness Change)',
    'feature_gap':        '형상 간 최소 간격 (Min Feature Spacing)',
}

# 각 규칙이 대응하는 KS D ISO/ASTM 52910:2018 조항.
# 표준은 '무엇을 고려해야 하는가'까지만 규정하고 수치는 규정하지 않으므로,
# 조항은 규칙의 존재 근거이지 임계값의 근거가 아니다.
RULE_CLAUSES = {
    'wall_thickness':
        '6.6.10 물리적 고려사항 (최소 두께) · 7.3 갑작스런 두께 변화 · 5.3.5 형상 이산화',
    'overhang_area':
        '7.2 오버행 (red flag) · 6.6.9 지지 구조 없이 제작 가능한 최대 형상',
    'support_volume':
        '7.2 오버행 · 6.6.10 물리적 고려사항 · 6.8.3.1 후공정 고려사항',
    'aspect_ratio':
        '6.6.5 최대 종횡비',
    'build_margin':
        '6.6.8 최대 제작 가능 크기',
    'min_feature_size':
        '6.6.4 최소 형상 크기 · 7.7 미세 부품의 세부사항 · 7.9 테셀레이션',
    'horizontal_hole':
        '7.4 갇힌 체적 · 6.6.6 최소 형상 공간',
    'staircase':
        '6.6.3 표면 거칠기 · 7.5 계단화',
    'thickness_gradient':
        '7.3 갑작스런 두께 변화 (적색깃발)',
    'feature_gap':
        '6.6.6 최소 형상 공간',
}

GATE_CLAUSES = {
    '갇힌 체적':   '7.4 갇힌 체적 (적색깃발)',
    '메시 무결성': '6.6.11.2 빈틈 없는 양의 부피 · 6.6.11.3 법선 방향 · 6.6.11.4 내부 면 제거',
    '빌드 볼륨':   '6.6.8 최대 제작 가능 크기',
    '최소 벽두께': '6.6.10 물리적 고려사항 (장비 요구 최소 두께)',
}

# 입력 메시 진단이 근거하는 조항
MESH_CLAUSES = {
    'watertight': '6.6.11.2 메시는 빈틈 없이 양의 부피를 둘러싸야 함',
    'normals':    '6.6.11.3 삼각형 법선은 바깥쪽을 향해야 함',
    'internal':   '6.6.11.4 내부 면은 제거되어야 함',
    'units':      '7.10 STL은 단위가 없어 크기 오류가 자주 발생함',
    'tessellation': '7.9 테셀레이션 품질은 공정 분해능과 맞춰야 함',
}


# ──────────────────────────────────────────────────────────────
# 연속 점수 함수
# ──────────────────────────────────────────────────────────────
def score_at_least(value, threshold, good_factor=2.0):
    """클수록 좋은 지표. value=threshold -> 50, value>=threshold*good -> 100, value=0 -> 0.
    모든 분기 경계에서 연속이다."""
    if threshold <= 0:
        return 100.0
    if value >= threshold * good_factor:
        return 100.0
    if value >= threshold:
        return 50.0 + 50.0 * (value - threshold) / (threshold * (good_factor - 1.0))
    return max(0.0, 50.0 * value / threshold)


def score_at_most(value, threshold, good_factor=0.5, fail_factor=2.0):
    """작을수록 좋은 지표. value<=threshold*good -> 100, value=threshold -> 50,
    value>=threshold*fail -> 0. 모든 분기 경계에서 연속이다."""
    if threshold <= 0:
        return 0.0 if value > 0 else 100.0
    if value <= threshold * good_factor:
        return 100.0
    if value <= threshold:
        return 50.0 + 50.0 * (threshold - value) / (threshold * (1.0 - good_factor))
    if value >= threshold * fail_factor:
        return 0.0
    return 50.0 * (threshold * fail_factor - value) / (threshold * (fail_factor - 1.0))


# ──────────────────────────────────────────────────────────────
# 결과 자료구조
# ──────────────────────────────────────────────────────────────
@dataclass
class GateResult:
    name: str
    passed: bool
    detail: str
    clause: str = ""
    status: str = field(default="", kw_only=True)

    def __post_init__(self):
        if not self.status:
            self.status = 'pass' if self.passed else 'fail'


@dataclass
class RuleResult:
    rule_name: str
    label: str
    status: str                    # 'pass' | 'warn' | 'fail' | 'na'
    value: Optional[float]
    threshold: Optional[float]
    unit: str
    score: Optional[float]         # None 이면 N/A (가중치 재분배 대상)
    weight: float                  # 재정규화 후 실제 가중치
    # 아래 세 필드는 키워드로만 받는다.
    #   clause 를 중간에 추가했을 때 위치 인자가 한 칸씩 밀려, 면 인덱스가
    #   clause 로 들어갔다가 덮어써지면서 3D 하이라이트가 조용히 사라진
    #   적이 있다. 필드 추가만으로 호출부가 깨지지 않도록 막는다.
    detail: str = field(default="", kw_only=True)
    clause: str = field(default="", kw_only=True)
    problem_face_indices: list = field(default_factory=list, kw_only=True)


@dataclass
class EvaluationResult:
    feasible: bool
    gates: List[GateResult] = field(default_factory=list)
    rule_results: List[RuleResult] = field(default_factory=list)
    total_score: Optional[float] = None
    grade: str = "N/A"
    process_type: str = "FDM"
    build_direction: list = field(default_factory=lambda: [0, 0, 1])
    warnings: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    summary: str = ""
    evaluation_status: str = "eligible"
    coverage: float = 0.0
    profile: dict = field(default_factory=dict)
    engine_version: str = APP_VERSION
    in_plane_rotation_deg: int = 0
    analysis_scope: str = 'full'
    mesh_diagnostics: dict = field(default_factory=dict)
    partial_metrics: dict = field(default_factory=dict)
    measurement_evidence: dict = field(default_factory=dict)
    preprocessing: dict = field(default_factory=dict)
    layer_review: dict = field(default_factory=dict)


class AMRuleEngine:
    """AM 제조성 평가 엔진 (하드 게이트 + 소프트 점수)."""

    def evaluate(self, mesh: trimesh.Trimesh, process_type='FDM',
                 build_direction=(0, 0, 1), printer_dims=(250, 250, 250),
                 min_feature_enabled=False, thickness_gradient_enabled=False,
                 wall_samples=2000, weights=None, layer_review_enabled=True,
                 layer_settings=None) -> EvaluationResult:
        """Keep calibrated solid metrics separate from FDM section-based checks.

        A mesh gate or unresolved 3D wall measurement cannot prevent planar FDM
        review. Conversely, planar review can never change the legacy gates,
        overall grade or calibrated support-volume prediction into a pass.
        """
        result = self._evaluate_geometry(mesh, process_type, build_direction, printer_dims,
                                         min_feature_enabled, thickness_gradient_enabled,
                                         wall_samples, weights)
        if result.process_type == 'FDM' and layer_review_enabled:
            from src.core.layer_review import inspect_layers
            try:
                settings = dict(layer_height=result.profile['layer_height'],
                                line_width=result.profile['line_width'],
                                critical_angle=result.profile['critical_angle'])
                overrides = dict(layer_settings or {})
                if set(overrides)-set(settings):
                    raise ValueError('단면 설정은 layer_height, line_width, critical_angle만 지원합니다.')
                settings.update(overrides)
                result.layer_review = inspect_layers(mesh, result.build_direction,
                                                     **settings)
            except Exception as exc:
                result.layer_review = dict(status='unavailable', checks=[], layers=[],
                    reason=f'단면 검토 실패: {exc}')
        else:
            result.layer_review = dict(status='not_requested' if not layer_review_enabled else 'not_applicable',
                                      checks=[], layers=[])
        return result

    def _evaluate_geometry(self, mesh: trimesh.Trimesh, process_type='FDM',
                 build_direction=(0, 0, 1), printer_dims=(250, 250, 250),
                 min_feature_enabled=False, thickness_gradient_enabled=False,
                 wall_samples=2000, weights=None) -> EvaluationResult:
        """weights 를 주면 그 가중치로 평가한다(전역 상태를 건드리지 않는다).

        이전 구현은 민감도 분석이 전역 BASE_WEIGHTS 를 직접 수정했다가
        복원하는 방식이라, 동시 실행이나 예외 발생 시 값이 오염될 수 있었다."""
        try:
            ptype = process_type if isinstance(process_type, ProcessType) else ProcessType[str(process_type).upper()]
        except KeyError:
            raise ValueError(f"알 수 없는 공정: {process_type}. "
                             f"{[p.value for p in ProcessType]} 중 하나여야 합니다.")
        P = PROCESS_PARAMS[ptype]

        pd = [float(v) for v in printer_dims]
        if len(pd) != 3 or not np.isfinite(pd).all() or min(pd) <= 0:
            raise ValueError(f"프린터 빌드 볼륨은 3축 모두 양수여야 합니다: {printer_dims}")
        build_direction = ga.unit(build_direction).tolist()
        if not isinstance(wall_samples, (int, np.integer)) or wall_samples < 1:
            raise ValueError("벽두께 표본 수는 양의 정수여야 합니다.")
        W = dict(BASE_WEIGHTS if weights is None else weights)
        if set(W) != set(BASE_WEIGHTS):
            raise ValueError("가중치는 모든 규칙 키를 정확히 포함해야 합니다.")
        if not all(np.isfinite(v) and v >= 0 for v in W.values()) or sum(W.values()) <= 0:
            raise ValueError("가중치는 유한한 음이 아닌 값이고 합이 양수여야 합니다.")

        # Validate before any ray casting. Invalid input is not a manufacturing failure.
        diagnostics = inspect_mesh(mesh)
        mesh_gate = self._mesh_gate(mesh, diagnostics)
        diagnostics['solid_check_passed'] = mesh_gate.passed
        mesh_gate.clause = GATE_CLAUSES['메시 무결성']
        if not mesh_gate.passed:
            state = 'indeterminate' if mesh_gate.status == 'unknown' else 'invalid_input'
            gates, partial = [mesh_gate], {}
            scope = 'none'
            if diagnostics['geometry_available']:
                # These use coordinates only, never volume, surface ownership,
                # normals, containment or ray casting on an invalid solid.
                mbf = ga.to_build_frame(mesh, build_direction)
                fit = ga.compute_build_volume_fit(mbf, printer_dims)
                partial = dict(build_volume_fit=fit, aspect_ratio=ga.compute_aspect_ratio(mbf),
                               withheld=['부피', '벽두께', '서포트량', '공동', '종합 점수'])
                scope = 'partial'
                gates.append(GateResult('빌드 볼륨', fit['fits'],
                    f"부품 {np.round(fit['part_size'], 2).tolist()}mm / 장비 {pd}mm. "
                    '0/90° XY 배치의 외곽 치수 검사이며 서포트·래프트·여유 공간을 제외합니다.',
                    clause=GATE_CLAUSES['빌드 볼륨']))
            return EvaluationResult(
                feasible=False, gates=gates, grade='판정 보류',
                process_type=ptype.value, build_direction=build_direction,
                evaluation_status=state, profile=dict(P),
                summary=('부분 분석 완료 · 입력 메시 검토 필요 — ' if partial else '입력 형상 검토 필요 — ') + mesh_gate.detail,
                suggestions=[mesh_gate.detail], analysis_scope=scope,
                mesh_diagnostics=diagnostics, partial_metrics=partial,
                preprocessing=mesh.metadata.get('preprocessing', {}),
                in_plane_rotation_deg=partial.get('build_volume_fit', {}).get('placement_rotation_deg', 0))

        analysis = ga.run_full_analysis(
            mesh, build_direction=build_direction,
            critical_angle=P['critical_angle'],
            support_density=P['support_density'],
            support_wall=P['support_wall'],
            bridge_limit=P['bridge_limit'],
            printer_dims=printer_dims,
            min_feature_threshold=P['thr_min_feature'],
            min_feature_enabled=min_feature_enabled,
            wall_samples=wall_samples,
        )
        analysis['trapped_volume'] = ga.compute_trapped_volume(mesh)
        mbf = analysis['build_frame_mesh']
        analysis['staircase'] = ga.compute_staircase(mbf, P['layer_height'])
        analysis['feature_gap'] = ga.compute_feature_gap(mesh)
        analysis['thickness_gradient'] = ga.compute_thickness_gradient(
            mesh, enabled=thickness_gradient_enabled)
        wt = analysis['wall_thickness']
        wt['verification'] = ga.verify_thin_regions(mesh, wt, P['hard_wall'])
        if wt.get('available') and 'sample_face_indices' in wt:
            wt['thin_face_indices'] = np.asarray(wt['sample_face_indices'])[
                np.asarray(wt['thicknesses']) < P['thr_wall']].tolist()

        warnings = self._mesh_warnings(mesh)
        warnings.append('점수는 구현된 형상 규칙의 선별 지표이며 출력 성공률이나 품질 보증이 아닙니다.')
        if analysis['trapped_volume'].get('has_trapped') and ptype == ProcessType.FDM:
            warnings.append('밀폐 공동 내부에 필요한 서포트의 제거 가능성은 검증하지 않았습니다.')
        if ptype != ProcessType.FDM:
            warnings.append('이 공정 프로필은 미검증 잠정값입니다. FDM 회귀 근거를 적용할 수 없습니다.')
        gates = [mesh_gate] + self._run_gates(analysis, P, printer_dims)
        for g in gates:
            g.clause = GATE_CLAUSES.get(g.name, '')
        feasible = all(g.passed for g in gates)

        result = EvaluationResult(
            feasible=feasible, gates=gates,
            process_type=ptype.value, build_direction=list(build_direction),
            warnings=warnings,
            profile=dict(P),
            in_plane_rotation_deg=analysis['build_volume_fit']['placement_rotation_deg'],
            mesh_diagnostics=diagnostics,
            preprocessing=mesh.metadata.get('preprocessing', {}),
            measurement_evidence={'wall_thickness': ga.wall_evidence(analysis['wall_thickness'], P['hard_wall'])},
        )

        rules = self._run_rules(analysis, P, W)
        for r in rules:
            r.clause = RULE_CLAUSES.get(r.rule_name, '')
        rules = self._normalize_weights(rules)
        result.rule_results = rules
        result.coverage = sum(W[r.rule_name] for r in rules if r.score is not None) / sum(W.values())

        if not feasible:
            result.total_score = None
            unknown = any(g.status == 'unknown' for g in gates)
            result.evaluation_status = 'indeterminate' if unknown else 'blocked'
            result.grade = '판정 보류' if unknown else "프로필 미충족"
            bad = [g.name for g in gates if not g.passed]
            result.summary = f"{'판정 보류' if unknown else '현재 프로필 기준 미충족'}: {', '.join(bad)}"
            result.suggestions = [g.detail for g in gates if not g.passed]
            return result

        scored = [r for r in rules if r.score is not None]
        if not scored or sum(r.weight for r in scored) <= 0:
            result.feasible = False
            result.evaluation_status = 'indeterminate'
            result.grade = '판정 보류'
            result.summary = '평가 가능한 규칙에 양의 가중치가 없습니다.'
            return result
        total = sum(r.score * r.weight for r in scored)
        result.total_score = round(total, 1)
        result.grade = self._grade(result.total_score)
        na = [r.label for r in rules if r.score is None]
        result.summary = (f"{result.total_score}점 ({result.grade}등급) | "
                          f"평가 규칙 {len(scored)}개"
                          + (f" | N/A {len(na)}개" if na else ""))
        result.suggestions = self._suggestions(rules, ptype)
        return result

    # ── 하드 게이트 ─────────────────────────────────────────
    @staticmethod
    def _mesh_gate(mesh, diagnostics=None) -> GateResult:
        """입력 메시가 평가 가능한 솔리드인지 판정한다.

        표준 6.6.11.2 는 메시가 빈틈 없이 양의 부피를 둘러싸야 함을,
        6.6.11.3 은 삼각형 법선이 바깥을 향해야 함을 요구한다.
        이전 구현은 이를 경고로만 표시하고 평가를 그대로 진행했다.
        그 결과 열린 메시, 법선이 반전된 메시, 삼각형 한 개짜리 입력이
        모두 A 등급을 받았다. 잘못된 입력에 그럴듯한 점수를 주는 것은
        점수를 주지 않는 것보다 나쁘므로 게이트로 승격한다.
        """
        diagnostics = inspect_mesh(mesh) if diagnostics is None else diagnostics
        if not diagnostics['topology_ready']:
            return GateResult("메시 무결성", False,
                              " / ".join(diagnostics['issues']) + '. 입력 표면을 검토하세요. 제조 불가능을 확정한 결과가 아닙니다.')
        vol = float(mesh.volume)
        # 자기교차 검사.
        #   is_watertight 는 '모든 엣지가 정확히 2개 면과 공유되는가' 만 본다.
        #   서로 관통하는 여러 개의 닫힌 껍질도 이 검사를 통과하므로,
        #   concatenate 로 합쳐 내부 면이 남은 메시를 잡아내지 못한다(6.6.11.4 위반).
        #   분리 바디는 AABB로 후보를 좁힌 뒤 불리언 교차 부피를 확인한다.
        #   단일 셸 내부의 모든 자기교차를 검증하는 알고리즘은 아니다.
        n_bodies = int(getattr(mesh, 'body_count', 1))
        if n_bodies > 1:
            overlap = AMRuleEngine._bodies_overlap(mesh)
            if overlap:
                return GateResult(
                    "메시 무결성", False,
                    overlap, status='unknown' if overlap.startswith('확인 필요') else 'fail')

        note = f"닫힌 솔리드 · 면 {len(mesh.faces):,}개 · 부피 {vol:,.1f}mm³"
        if n_bodies > 1:
            note += f" · 분리 바디 {n_bodies}개(겹치지 않음)"
        return GateResult("메시 무결성", True, note)

    @staticmethod
    def _bodies_overlap(mesh, tol=1e-6):
        """AABB가 겹치는 양의 셸 쌍의 실제 교차 부피를 계산한다.

        불리언 연산 실패는 확인 필요로 반환한다. 음의 셸은 별도로 양의
        셸에 포함되는지 확인한다. 단일 셸 내부 자기교차의 전수 검사는 아니다.
        """
        try:
            parts = mesh.split(only_watertight=False, repair=False)
        except Exception:
            return '확인 필요: 분리 껍질 계산에 실패했습니다.'
        if any(not p.is_watertight or not np.isfinite(p.volume) or p.volume == 0 for p in parts):
            return '확인 필요: 분리 껍질에 열린 표면 또는 부피가 0인 표면이 있습니다.'
        # 부호 있는 부피가 음수인 껍질은 '겹친 바디' 가 아니라 내부 공동이다.
        # 공동은 정의상 솔리드 안에 있으므로 바운딩박스가 항상 겹치며,
        # 이를 제외하지 않으면 속이 빈 정상 부품이 전부 오탐된다.
        # 공동 자체는 별도의 '갇힌 체적' 게이트가 판정한다(표준 7.4).
        solids = [p for p in parts if float(p.volume) > 0]
        for cavity in [p for p in parts if float(p.volume) < 0]:
            try:
                if not any(np.all(s.contains(cavity.vertices)) for s in solids):
                    return '확인 필요: 음의 껍질이 외부 솔리드 내부에 완전히 포함되지 않습니다. 법선 또는 교차를 검토하세요.'
            except Exception:
                return '확인 필요: 공동 껍질의 포함 관계를 판정하지 못했습니다.'
        if len(solids) < 2:
            return None
        parts = solids
        boxes = [p.bounds for p in parts]
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                lo = np.maximum(boxes[i][0], boxes[j][0])
                hi = np.minimum(boxes[i][1], boxes[j][1])
                d = hi - lo
                if np.all(d > tol):
                    try:
                        intersection = trimesh.boolean.intersection([parts[i], parts[j]], engine='manifold')
                        v = abs(float(intersection.volume))
                    except Exception:
                        return '확인 필요: 바운딩박스가 겹치지만 실제 교차 계산에 실패했습니다.'
                    if v > tol:
                        return f"바디 {i+1}·{j+1} 실제 교차 부피 {v:,.3f}mm³. 내부 면을 제거한 솔리드가 필요합니다."
        return None

    @staticmethod
    def _run_gates(analysis, P, printer_dims, mesh=None) -> List[GateResult]:
        gates = []
        if mesh is not None:
            gates.append(AMRuleEngine._mesh_gate(mesh))

        # 갇힌 체적 (표준 7.4)
        #   분말 베드 융해에서는 갇힌 분말을 빼낼 수 없고, 액조 광경화에서는
        #   레진이 그대로 남는다. '갇혔는가' 는 이진 사실이므로 임의 임계값이
        #   필요하지 않다. 재료 압출은 서포트가 갇히는 정도라 경고로 처리한다.
        tv = analysis.get('trapped_volume', {})
        if tv.get('available'):
            if tv['has_trapped']:
                sizes = ', '.join(f"{c['volume']:,.0f}mm³" for c in tv['cavity_sizes'][:3])
                msg = (f"밀폐된 내부 공동 {tv['n_cavities']}개, 총 {tv['trapped_volume']:,.1f}mm³ "
                       f"(부품 부피의 {tv['trapped_ratio']*100:.1f}%). 크기: {sizes}. "
                       f"재료 배출이 요구되는 설계라면 외부로의 배출 경로가 필요합니다.")
                gates.append(GateResult("갇힌 체적", not P['trapped_blocks'], msg))
            else:
                gates.append(GateResult("갇힌 체적", True, "밀폐된 내부 공동 없음"))
        else:
            gates.append(GateResult('갇힌 체적', False, tv.get('reason', '공동 분석 실패'), status='unknown'))

        sv = analysis['support_volume']
        if P['thr_support_ratio'] is not None and sv.get('available') is False:
            gates.append(GateResult('지지구조 분석', False, sv['reason'], status='unknown'))

        fit = analysis['build_volume_fit']
        if fit['fits']:
            gates.append(GateResult(
                "빌드 볼륨", True,
                f"부품 {np.round(fit['part_size'], 1).tolist()} / 프린터 {list(printer_dims)} · XY 배치 회전 {fit['placement_rotation_deg']}°"))
        else:
            gates.append(GateResult(
                "빌드 볼륨", False,
                f"부품 {np.round(fit['part_size'],1).tolist()}mm 가 프린터 "
                f"{list(printer_dims)}mm 를 초과합니다. 부품 분할 또는 장비 변경이 필요합니다."))

        # A count of two rays is not independent evidence. Corroborate suspected
        # patches; keep unconfirmed candidates visible and withhold the total.
        wt = analysis['wall_thickness']
        HARD = P['hard_wall']
        if not wt.get('available'):
            gates.append(GateResult("최소 벽두께", False,
                                    f"벽두께를 측정할 수 없어 조형 가능성을 판정할 수 없습니다 "
                                    f"({wt.get('reason','')}).", status='unknown'))
            return gates

        t = wt.get('thicknesses')
        n_below = int(np.sum(np.asarray(t) < HARD)) if t is not None else (
            1 if wt['min_thickness'] < HARD else 0)
        n_tot = int(wt['samples'])
        area_frac = None
        sa = wt.get('sample_face_areas')
        if sa is not None and t is not None and len(sa) == len(t):
            below = np.asarray(t) < HARD
            area_frac = float(np.asarray(sa)[below].sum() / max(wt.get('total_area', 1.0), 1e-9))

        detail_num = (f"최솟값 {wt['min_thickness']:.3f}mm · 5퍼센타일 {wt['p_thickness']:.2f}mm · "
                      f"하한 미만 샘플 {n_below}/{n_tot}"
                      + (f" · 표면 근처 제외 교차 {wt['discarded_near_hits']}개" if wt.get('discarded_near_hits') else "")
                      + (f" · 검출된 표본 면의 전체 면적 대비 비율 {area_frac*100:.3f}%" if area_frac is not None else ""))

        evidence = ga.wall_evidence(wt, HARD)
        if evidence['classification'] == 'corroborated_thin_region':
            gates.append(GateResult(
                "최소 벽두께", False,
                f"프로필 하한 {HARD}mm 미만인 영역을 국소 재측정에서도 검출했습니다. "
                f"맞은편 표면과 내부 3점 관통 거리가 근거이며, 실제 출력 불가능의 증명은 아닙니다. ({detail_num})"))
        elif evidence['classification'] in ('suspect_thin_region', 'unknown'):
            gates.append(GateResult(
                "최소 벽두께", False,
                f"얇은 특징 또는 모서리·측정 이상치인지 확인이 필요합니다. "
                f"국소 재측정에서 충분한 근거를 확보하지 못해 종합 판정을 보류합니다. ({detail_num})",
                status='unknown'))
        else:
            gates.append(GateResult(
                "최소 벽두께", True, f"검사 표본에서 프로필 하한 {HARD}mm 미만을 발견하지 못했습니다. ({detail_num})"))
        return gates

    @staticmethod
    def _mesh_warnings(mesh) -> List[str]:
        """입력 메시 진단. 각 항목은 표준 6.6.11 메시 고려사항에 근거한다."""
        w = []
        if not mesh.is_watertight:
            w.append("메시가 닫혀 있지 않습니다(non-watertight). 부피·두께 결과가 부정확할 수 있습니다. "
                     f"[{MESH_CLAUSES['watertight']}]")
        if not mesh.is_winding_consistent:
            w.append("면 법선 방향이 일관되지 않습니다. 오버행 판정이 반전될 수 있습니다. "
                     f"[{MESH_CLAUSES['normals']}]")
        if mesh.volume <= 0:
            w.append("부피가 0 이하입니다. 법선이 뒤집혔거나 열린 메시입니다. "
                     f"[{MESH_CLAUSES['normals']}]")
        if getattr(mesh, 'body_count', 1) > 1:
            w.append(f"분리된 바디가 {mesh.body_count}개입니다. 겹쳐 있으면 내부 면이 남아 "
                     f"부피가 중복 계산됩니다(불리언 합집합 권장). [{MESH_CLAUSES['internal']}]")
        return w

    # ── 소프트 규칙 ─────────────────────────────────────────
    def _run_rules(self, analysis, P, W=None) -> List[RuleResult]:
        W = W or BASE_WEIGHTS
        R = []

        # 1. 벽두께
        wt = analysis['wall_thickness']
        if wt.get('available'):
            v = wt['p_thickness']
            s = score_at_least(v, P['thr_wall'])
            R.append(RuleResult(
                'wall_thickness', RULE_LABELS['wall_thickness'],
                'pass' if v >= P['thr_wall'] else 'warn', round(v, 3), P['thr_wall'],
                'mm', s, W['wall_thickness'],
                detail=f"{wt['percentile']:.0f}퍼센타일 {v:.2f}mm / 최솟값 {wt['min_thickness']:.2f}mm "
                f"/ 중앙값 {wt['median_thickness']:.2f}mm (샘플 {wt['samples']}개)", problem_face_indices=wt.get('thin_face_indices', [])))
        else:
            R.append(RuleResult('wall_thickness', RULE_LABELS['wall_thickness'], 'na',
                                None, P['thr_wall'], 'mm', None,
                                W['wall_thickness'], detail=wt.get('reason', '')))

        # 2. 오버행 면적 비율
        oh = analysis['overhang']
        thr = P['thr_overhang_area']
        if thr is None:
            R.append(RuleResult('overhang_area', RULE_LABELS['overhang_area'], 'na',
                                None, None, '%', None, W['overhang_area'],
                                detail="분말 지지 공정이라 기하학적 지지구조가 불필요합니다. "
                                "가중치를 다른 규칙에 재분배합니다."))
        else:
            v = oh['overhang_area_ratio']
            s = score_at_most(v, thr)
            R.append(RuleResult(
                'overhang_area', RULE_LABELS['overhang_area'],
                'pass' if v <= thr else 'warn', round(v * 100, 2), thr * 100, '%', s,
                W['overhang_area'],
                detail=f"임계각 {oh['critical_angle']:.0f}° 기준 지지 필요 면 "
                f"{oh['overhang_face_count']}개 · 플레이트 접촉 {oh['plate_face_count']}개 제외"
                + (f" · 브리지로 제외 {len(oh.get('bridges', []))}개 영역"
                   f"({oh.get('bridged_area', 0):.0f}mm²)" if oh.get('bridges') else ""), problem_face_indices=oh['overhang_face_indices'][:2000]))

        # 3. 지지구조물 부피 비율
        sv = analysis['support_volume']
        thr = P['thr_support_ratio']
        if thr is None or sv.get('available') is False:
            R.append(RuleResult('support_volume', RULE_LABELS['support_volume'], 'na',
                                None, None, 'ratio', None, W['support_volume'],
                                detail=sv.get("reason", "분말 지지 공정 — 해당 없음")))
        else:
            v = sv['support_volume_ratio']
            s = score_at_most(v, thr)
            R.append(RuleResult(
                'support_volume', RULE_LABELS['support_volume'],
                'pass' if v <= thr else 'warn', round(v, 4), thr, 'ratio', s,
                W['support_volume'],
                detail=f"서포트 {sv['support_volume']:.1f}mm³ / 부품 {sv['part_volume']:.1f}mm³ "
                f"(2항 모델: 밀도 {sv.get('density',0):.3f}x부피항 {sv.get('vol_term',0):.0f} "
                f"+ 벽 {sv.get('wall',0):.3f}x둘레항 {sv.get('perim_term',0):.0f}, "
                f"지지 영역 {sv.get('n_regions',0)}개)"))

        # 4. 종횡비
        ar = analysis['aspect_ratio']
        v = ar['aspect_ratio']
        s = score_at_most(v, P['thr_aspect'], good_factor=0.3, fail_factor=2.0)
        R.append(RuleResult(
            'aspect_ratio', RULE_LABELS['aspect_ratio'],
            'pass' if v <= P['thr_aspect'] else 'warn', round(v, 2), P['thr_aspect'],
            'ratio', s, W['aspect_ratio'],
            detail=f"빌드 방향 높이 {ar['height']:.1f}mm / 최소 수평 폭 {ar['width']:.1f}mm"))

        # 5. 빌드 볼륨 여유 (게이트 통과 후의 여유율)
        bf = analysis['build_volume_fit']
        u = bf['utilization']
        s = score_at_most(u, 0.8, good_factor=0.5, fail_factor=1.25)
        R.append(RuleResult(
            'build_margin', RULE_LABELS['build_margin'],
            'pass' if u <= 0.8 else 'warn', round(u * 100, 1), 80.0, '%', s,
            W['build_margin'],
            detail=f"최대 축 점유율 {u*100:.1f}% (부품 {np.round(bf['part_size'],1).tolist()})"))

        # 6. 최소 특징 크기
        mf = analysis['min_feature_size']
        if mf.get('available'):
            v = mf['lost_volume_ratio']
            s = score_at_most(v, 0.01, good_factor=0.1, fail_factor=5.0)
            R.append(RuleResult(
                'min_feature_size', RULE_LABELS['min_feature_size'],
                'pass' if v <= 0.01 else 'warn', round(v * 100, 3), 1.0, '%', s,
                W['min_feature_size'],
                detail=f"지름 {mf['probe_diameter']:.2f}mm 구로 오프닝 시 소실 부피 비율 "
                f"(복셀 {mf['pitch']:.2f}mm)"))
        else:
            R.append(RuleResult('min_feature_size', RULE_LABELS['min_feature_size'], 'na',
                                None, P['thr_min_feature'], 'mm', None,
                                W['min_feature_size'], detail=mf.get('reason', '')))

        # 7. 계단 효과 (표준 6.6.3 / 7.5)
        sc = analysis.get('staircase', {})
        if sc.get('available'):
            v = sc['cusp_ratio']
            thr = P['thr_cusp_ratio']
            score = score_at_most(v, thr, good_factor=0.4, fail_factor=2.0)
            R.append(RuleResult(
                'staircase', RULE_LABELS['staircase'],
                'pass' if v <= thr else 'warn', round(v, 4), thr, 'ratio', score,
                W['staircase'],
                detail=f"평균 계단 높이 {sc['mean_cusp']*1000:.0f}µm / 층 두께 "
                f"{sc['layer_height']*1000:.0f}µm · 최대 {sc['max_cusp']*1000:.0f}µm · "
                f"경사면 비율 {sc['sloped_area_ratio']*100:.1f}%", problem_face_indices=sc.get('worst_face_indices', [])[:500]))
        else:
            R.append(RuleResult('staircase', RULE_LABELS['staircase'], 'na',
                                None, None, 'ratio', None, W['staircase'],
                                detail=sc.get('reason', '')))

        # 8. 갑작스런 두께 변화 (표준 7.3)
        tg = analysis.get('thickness_gradient', {})
        if tg.get('available'):
            v = tg['p95_ratio']
            thr = P['thr_thickness_ratio']
            score = score_at_most(v, thr, good_factor=0.4, fail_factor=3.0)
            R.append(RuleResult(
                'thickness_gradient', RULE_LABELS['thickness_gradient'],
                'pass' if v <= thr else 'warn', round(v, 2), thr, 'ratio', score,
                W['thickness_gradient'],
                detail=f"95퍼센타일 두께비 {v:.2f} · 중앙값 {tg['median_ratio']:.2f} · "
                f"비교 반경 {tg['radius']:.2f}mm (배율은 근사값이며 급변 유무 판별용)"))
        else:
            R.append(RuleResult('thickness_gradient', RULE_LABELS['thickness_gradient'],
                                'na', None, None, 'ratio', None,
                                W['thickness_gradient'], detail=tg.get('reason', '')))

        # 9. 형상 간 최소 간격 (표준 6.6.6)
        fg = analysis.get('feature_gap', {})
        if fg.get('available'):
            if not fg.get('has_gap'):
                R.append(RuleResult(
                    'feature_gap', RULE_LABELS['feature_gap'], 'pass',
                    None, P['thr_gap'], 'mm', 100.0, W['feature_gap'],
                    detail="검사한 법선 방향 표본에서 마주 보는 면을 찾지 못했습니다. 미검출 간격이 없다는 보장은 아닙니다."))
            else:
                v = fg['p_gap']
                thr = P['thr_gap']
                score = score_at_least(v, thr)
                R.append(RuleResult(
                    'feature_gap', RULE_LABELS['feature_gap'],
                    'pass' if v >= thr else 'warn', round(v, 3), thr, 'mm', score,
                    W['feature_gap'],
                    detail=f"5퍼센타일 간격 {v:.3f}mm · 최소 {fg['min_gap']:.3f}mm · "
                    f"중앙값 {fg['median_gap']:.2f}mm (표본 {fg['gap_count']}개)"))
        else:
            R.append(RuleResult('feature_gap', RULE_LABELS['feature_gap'], 'na',
                                None, P['thr_gap'], 'mm', None, W['feature_gap'],
                                detail=fg.get('reason', '')))

        # 10. 수평 구멍 직경
        ho = analysis['hole_analysis']
        R.append(RuleResult('horizontal_hole', RULE_LABELS['horizontal_hole'], 'na',
                            None, None, 'mm', None, W['horizontal_hole'],
                            detail=ho.get('reason', '')))
        return R

    @staticmethod
    def _normalize_weights(rules: List[RuleResult]) -> List[RuleResult]:
        """N/A 규칙의 가중치를 점수가 있는 규칙에 비례 재분배한다."""
        active = sum(r.weight for r in rules if r.score is not None)
        for r in rules:
            r.weight = r.weight / active if (r.score is not None and active > 0) else 0.0
        return rules

    @staticmethod
    def _grade(score) -> str:
        if score >= 90: return 'A'
        if score >= 80: return 'B'
        if score >= 70: return 'C'
        if score >= 60: return 'D'
        return 'F'

    @staticmethod
    def _suggestions(rules, ptype) -> List[str]:
        tips = {
            'wall_thickness': "벽두께를 기준 이상으로 키우거나 리브(rib)로 보강하세요.",
            'overhang_area': "빌드 방향을 바꾸거나, 하향면에 챔퍼를 적용해 자립각 이상으로 만드세요.",
            'support_volume': "빌드 방향 최적화 또는 자립 형상(self-supporting)으로 재설계하세요.",
            'aspect_ratio': "눕혀서 배치하거나 바닥 면적을 넓히세요.",
            'build_margin': "부품이 빌드 볼륨을 거의 채웁니다. 수축·휨 여유를 확인하세요.",
            'min_feature_size': "임계값보다 얇은 미세 특징을 제거하거나 키우세요.",
            'staircase': "빌드 방향을 바꿔 중요 면을 수직에 가깝게 두거나 층 두께를 낮추세요.",
            'thickness_gradient': "두꺼운 부위와 얇은 부위 사이에 점진적 전이를 주세요.",
            'feature_gap': "형상 사이 간격을 공정 한계 이상으로 벌리세요.",
        }
        out = [f"[{r.label}] {tips[r.rule_name]}"
               for r in rules if r.status == 'warn' and r.rule_name in tips]
        return out or ["계산된 소프트 규칙에서 권장 기준 미달이 검출되지 않았습니다. N/A 항목과 미모델링 현상은 별도 확인하세요."]


# 하위 호환용 별칭
AMRuleBase = AMRuleEngine
