from dataclasses import asdict, dataclass
import math

PROCESS_LABELS = {
    "MEX": "재료 압출 · FFF/FDM",
    "VPP": "액조 광경화 · SLA/DLP",
    "PBF_POLYMER": "고분자 분말 베드 융해 · SLS",
    "PBF_METAL": "금속 분말 베드 융해 · LPBF",
}

@dataclass(frozen=True)
class Profile:
    process: str = "MEX"
    name: str = "장비 미정 · 탐색용 조건"
    machine: str = "미확정"
    material: str = "미확정"
    slicer: str = "미확정"
    layer_height_mm: float = 0.2
    line_width_mm: float = 0.4
    overhang_angle_deg: float = 45.0  # measured from horizontal XY plane
    minimum_wall_mm: float | None = None
    minimum_hole_mm: float | None = None
    build_volume_mm: tuple[float, float, float] | None = None
    clearance_mm: float = 0.0
    threshold_basis: str = "사용자 탐색 조건; 실물 시편으로 보정하지 않음"
    process_notes: str = ""

    def validate(self):
        if self.process not in PROCESS_LABELS:
            raise ValueError("지원하는 AM 공정이 아닙니다.")
        for key in ("layer_height_mm", "line_width_mm"):
            value = getattr(self, key)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{key}: 유한한 양수가 필요합니다.")
        if not math.isfinite(self.overhang_angle_deg) or not 0 < self.overhang_angle_deg <= 90:
            raise ValueError("오버행 각도는 수평면 기준 0° 초과 90° 이하여야 합니다.")
        for key in ("minimum_wall_mm", "minimum_hole_mm"):
            value = getattr(self, key)
            if value is not None and (not math.isfinite(value) or value <= 0):
                raise ValueError(f"{key}: 미지정 또는 유한한 양수가 필요합니다.")
        if not math.isfinite(self.clearance_mm) or self.clearance_mm < 0:
            raise ValueError("배치 여유는 유한한 0 이상 값이 필요합니다.")
        if self.build_volume_mm is not None:
            if len(self.build_volume_mm) != 3 or any(not math.isfinite(x) or x <= 0 for x in self.build_volume_mm):
                raise ValueError("빌드 공간의 세 치수는 유한한 양수여야 합니다.")
            if min(self.build_volume_mm) <= 2 * self.clearance_mm:
                raise ValueError("장비 여유가 사용 가능한 빌드 공간보다 큽니다.")
        return self

    def to_dict(self):
        return asdict(self)


UNASSESSED = {
    "MEX": ["하중·층간 접합강도", "열변형·수축", "가변 선폭의 실제 압출경로", "브리지 처짐", "접착·서포트 제거 접근성"],
    "VPP": ["수지 배출 경로와 세척", "박리력·흡착 컵", "서포트 접점·후경화 변형", "실제 표면·공차·강도"],
    "PBF_POLYMER": ["분말 배출 통로", "열수축·뒤틀림", "패킹·열 이력", "실제 표면·공차·강도"],
    "PBF_METAL": ["열전달·잔류응력·변형", "서포트 및 분말 제거 접근성", "스캔 전략·기공·금속 조직", "후가공 여유·검사·강도"],
}

