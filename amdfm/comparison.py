"""Paired design review. Comparability conditions precede numeric differences."""
import numpy as np


def compare_designs(before,after):
    reasons=[]
    if before["profile"]!=after["profile"]:
        reasons.append("공정·검토 프로필이 다릅니다.")
    if not np.allclose(before["current_orientation"]["direction"],after["current_orientation"]["direction"]):
        reasons.append("모델 좌표에서의 적층 방향이 다릅니다.")
    if before["provenance"]["code_sha256"]!=after["provenance"]["code_sha256"]:
        reasons.append("측정 코드 버전이 다릅니다.")
    if any(r["model"]["unit_status"]=="assumed" for r in (before,after)):
        reasons.append("한쪽 이상의 실제 배율이 미확정입니다.")
    if any(r["summary"]["review_status"]!="geometry_review" for r in (before,after)):
        reasons.append("한쪽 이상의 입력 형상에 결함이 있습니다.")
    def values(r):
        wall=next(f for f in r["findings"] if f["id"]=="wall")
        return {"하향면 투영 합 (mm²)":r["current_orientation"]["overhang_projected_area_sum_mm2"],
            "높이 (mm)":r["current_orientation"]["height_mm"],
            "CAD 체적 (mm³)":r["geometry"]["exact_cad_volume_mm3"],
            "관측 최소 관통거리 (mm)":wall["measurements"].get("minimum_mm")}
    a,b=values(before),values(after)
    return {"comparable":not reasons,"reasons":reasons,"before":before["model"]["filename"],
        "after":after["model"]["filename"],"before_fingerprint":before["model_fingerprint"],
        "after_fingerprint":after["model_fingerprint"],
        "metrics":[{"항목":k,"변경 전":a[k],"변경 후":b[k],
                    "차이":b[k]-a[k] if not reasons and a[k] is not None and b[k] is not None else None} for k in a],
        "scope":"동일 좌표계로 설계된 두 형상을 가정합니다. 형상 차이가 기능·강도·출력 성공의 개선을 보증하지 않습니다."}

