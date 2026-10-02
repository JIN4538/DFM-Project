"""AM-DFM 규칙 엔진 검증 하네스 (v2)

정답을 해석적으로 아는 형상만 넣어서, 엔진이 그 정답을 내는지 확인한다.
코드를 수정할 때마다 실행해서 FAIL 이 늘지 않는지 본다.

    python verify.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import trimesh

from src.core import geometry_analyzer as ga
from src.processes.additive import AMRuleEngine, score_at_least, score_at_most
from src.core.scoring import AXIS_ORIENTATIONS

engine = AMRuleEngine()
Z = (0, 0, 1)
LOG = []


def check(name, ok, got, want, note=""):
    LOG.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}")
    print(f"         기대: {want}")
    print(f"         실제: {got}" + (f"   {note}" if note else ""))


def rule(mesh, rname, process='FDM', bdir=Z):
    r = engine.evaluate(mesh, process, bdir)
    return [x for x in r.rule_results if x.rule_name == rname][0]


def wedge(alpha_deg, W=40.0, D=20.0):
    """하향 경사면이 수평면 기준 alpha_deg 인 삼각기둥."""
    H = W * np.tan(np.radians(alpha_deg))
    v = np.array([[0, -D/2, H], [W, -D/2, H], [W, -D/2, 0],
                  [0,  D/2, H], [W,  D/2, H], [W,  D/2, 0]], float)
    f = np.array([[0,1,2],[3,5,4],[0,3,4],[0,4,1],[1,4,5],[1,5,2],[0,2,5],[0,5,3]])
    m = trimesh.Trimesh(vertices=v, faces=f, process=True); m.fix_normals()
    return m


BOX = trimesh.creation.box(extents=[40, 30, 20])

print("=" * 78)
print("L1. 해석해 대조")
print("=" * 78)

# T1/T2 직육면체
bf = ga.to_build_frame(BOX, Z)
oh = ga.compute_overhang(bf, 45.0)
sv = ga.compute_support_volume(bf, 45.0, 0.15)
check("T1 직육면체 오버행 면적비", oh['overhang_area_ratio'] < 1e-9,
      f"{oh['overhang_area_ratio']*100:.2f}% ({oh['overhang_face_count']}면)", "0.00% (0면)")
check("T2 직육면체 서포트 부피", sv['support_volume'] < 1e-9,
      f"{sv['support_volume']:.2f} mm3", "0.00 mm3")

# T3 경사각 스윕
print("\n  T3 경사각 스윕 (FDM 임계각 45°)")
print(f"       {'경사각':>7s} {'오버행면적비':>12s} {'규칙점수':>9s}   기대")
sw = {}
for a in [10, 30, 40, 44, 46, 60, 80]:
    m = wedge(a)
    o = ga.compute_overhang(ga.to_build_frame(m, Z), 45.0)
    sw[a] = o['overhang_area_ratio']
    r = rule(m, 'overhang_area')
    print(f"       {a:5d}°  {o['overhang_area_ratio']*100:10.2f}%  {r.score:8.1f}점   "
          f"{'서포트 필요' if a < 45 else '자립'}")
check("T3 45° 임계각 작동", sw[44] > 0 and sw[46] < 1e-9 and sw[60] < 1e-9 and sw[80] < 1e-9,
      f"44°={sw[44]*100:.1f}%, 46°={sw[46]*100:.1f}%, 60°={sw[60]*100:.1f}%, 80°={sw[80]*100:.1f}%",
      "44°>0, 46°/60°/80°=0")

# T4 공정별 임계각
print("\n  T4 공정별 임계각 (SLA 30°)")
sla = {}
for a in [25, 29, 35, 40]:
    o = ga.compute_overhang(ga.to_build_frame(wedge(a), Z), 30.0)
    sla[a] = o['overhang_area_ratio']
    print(f"       {a:5d}°  {o['overhang_area_ratio']*100:10.2f}%")
check("T4 SLA 30° 임계각 적용", sla[29] > 0 and sla[35] < 1e-9 and sla[40] < 1e-9,
      f"29°={sla[29]*100:.1f}%, 35°={sla[35]*100:.1f}%, 40°={sla[40]*100:.1f}%",
      "29°>0, 35°/40°=0")

# T5 벽두께 정확도
print("\n  T5 두께를 아는 평판")
print(f"       {'실제':>7s} {'측정':>9s} {'오차':>8s}")
errs = []
for t in [0.5, 1.0, 2.0, 5.0]:
    w = ga.compute_wall_thickness(trimesh.creation.box(extents=[60, 40, t]))
    e = (w['p_thickness'] - t) / t * 100
    errs.append(abs(e))
    print(f"       {t:5.1f}mm {w['p_thickness']:8.3f}mm {e:+7.2f}%")
check("T5 벽두께 오차 2% 이내", max(errs) < 2.0, f"최대 {max(errs):.2f}%", "2% 미만")

# T6 서포트 부피 2항 모델 해석해 대조
print("\n  T6 서포트 부피 해석해 대조 (2항 모델)")
plate = trimesh.creation.box(extents=[40, 30, 4]); plate.apply_translation([0, 0, 20])
post = trimesh.creation.box(extents=[4, 4, 18]);   post.apply_translation([0, 0, 9])
tbl = trimesh.boolean.union([plate, post])
h = 18.0
A_exposed = 40 * 30 - 4 * 4            # 노출 하향면 투영 면적
P_exposed = 2 * (40 + 30) + 4 * 4      # 바깥 둘레 + 기둥 구멍 둘레
DENS, WALL = 0.165, 0.2715
V_expect = DENS * A_exposed * h + WALL * P_exposed * h
sv = ga.compute_support_volume(ga.to_build_frame(tbl, Z), 45.0, DENS, WALL)
err = abs(sv['support_volume'] - V_expect) / V_expect * 100
print(f"       부피항 {A_exposed}x{h:.0f}={A_exposed*h:.0f}  "
      f"둘레항 {P_exposed}x{h:.0f}={P_exposed*h:.0f}  지지 영역 {sv['n_regions']}개")
check("T6 서포트 부피 해석해 오차 1% 이내", err < 1.0,
      f"{sv['support_volume']:.1f} mm3 (오차 {err:.3f}%)",
      f"{V_expect:.1f} mm3 = {DENS}x{A_exposed*h:.0f} + {WALL}x{P_exposed*h:.0f}")

# T6b 투영 면적 보정 — 경사면이 있는 형상으로 검증
#   T6 의 형상은 수평 하향면뿐이라 |n·b| = 1 이고, 면 넓이를 그대로 써도
#   같은 값이 나온다. 즉 투영 보정의 유무를 구분하지 못한다.
#   경사면을 가진 쐐기로 다시 확인한다.
print("\n  T6b 투영 면적 보정 (경사면 형상)")
_w30 = wedge(30)
_bf30 = ga.to_build_frame(_w30, Z)
_oh30 = ga.compute_overhang(_bf30, 45.0)
_i30 = np.asarray(_oh30['overhang_face_indices'])
_a30 = _bf30.area_faces[_i30]
_nz30 = np.abs(_bf30.face_normals[_i30][:, 2])
_regs = ga.support_regions(_bf30, 45.0)
_proj_sum = sum(r['proj_area'] for r in _regs)
_raw_sum = float(_a30.sum())
print(f"       면 넓이 합 {_raw_sum:.1f}  투영 면적 합 {_proj_sum:.1f}  "
      f"|n_z| {_nz30.min():.4f}")
check("T6b 투영 면적이 면 넓이보다 작아야", _proj_sum < _raw_sum * 0.95,
      f"투영 {_proj_sum:.1f} / 면넓이 {_raw_sum:.1f} = {_proj_sum/_raw_sum:.4f}",
      f"cos(30°) = {np.cos(np.radians(30)):.4f} 배 (투영 보정 미적용이면 1.0)")

# T3b 임계각 경계 자체
#   T3 은 44/46 만 보므로 부등호를 <= 로 바꿔도 통과한다.
#   경계값 45.0 에서의 판정을 명시적으로 고정한다.
print("\n  T3b 임계각 경계값 판정")
_r45 = ga.compute_overhang(ga.to_build_frame(wedge(45.0), Z), 45.0)
_r449 = ga.compute_overhang(ga.to_build_frame(wedge(44.9), Z), 45.0)
_r451 = ga.compute_overhang(ga.to_build_frame(wedge(45.1), Z), 45.0)
print(f"       44.9° {_r449['overhang_area_ratio']*100:6.2f}%   "
      f"45.0° {_r45['overhang_area_ratio']*100:6.2f}%   "
      f"45.1° {_r451['overhang_area_ratio']*100:6.2f}%")
check("T3b 임계각 45.0°는 자립으로 판정", _r45['overhang_area_ratio'] < 1e-9
      and _r449['overhang_area_ratio'] > 0 and _r451['overhang_area_ratio'] < 1e-9,
      f"44.9°>0, 45.0°=0, 45.1°=0",
      "기준각과 같으면 지지 불필요 (부등호는 미만이어야)")

# T3c 수직벽은 어떤 임계각에서도 오버행이 아니어야
print("\n  T3c 수직벽 배제")
_wall = trimesh.creation.box(extents=[40, 2, 60])
_res = {}
for _ca in (30.0, 45.0, 89.0):
    _o = ga.compute_overhang(ga.to_build_frame(_wall, Z), _ca)
    _res[_ca] = _o['overhang_area_ratio']
    print(f"       임계각 {_ca:4.0f}° -> 오버행 {_o['overhang_area_ratio']*100:.2f}%")
check("T3c 수직벽은 임계각과 무관하게 자립", all(v < 1e-9 for v in _res.values()),
      ", ".join(f"{k:.0f}°={v*100:.2f}%" for k, v in _res.items()),
      "법선이 빌드 방향과 수직이면 지지 불필요")

# T5b 얇은 특징 탐지 — 면적 가중 표본만 쓰면 놓친다
print("\n  T5b 미세 특징 탐지 (면적 대비 0.05% 크기)")
_blk = trimesh.creation.box(extents=[80, 80, 20])
_pin = trimesh.creation.cylinder(radius=0.15, height=10, sections=24)
_pin.apply_translation([30, 30, 15])
_wp = trimesh.boolean.union([_blk, _pin])
_wt = ga.compute_wall_thickness(_wp)
_tt = np.asarray(_wt['thicknesses'])
_nb = int((_tt < 0.4).sum())
print(f"       최솟값 {_wt['min_thickness']:.4f}mm  하한 미만 표본 {_nb}/{len(_tt)}")
check("T5b 지름 0.3mm 핀 탐지", _wt['min_thickness'] < 0.4 and _nb >= 2,
      f"최솟값 {_wt['min_thickness']:.4f}mm, 하한 미만 {_nb}개",
      "0.3mm 근처. 면적 가중 표본만 쓰면 20mm 로 보고된다")

_rp = engine.evaluate(_wp, 'FDM', Z)
check("T5b2 미세 특징 부품은 게이트 차단", not _rp.feasible,
      f"feasible={_rp.feasible}, 등급={_rp.grade}",
      "노즐 직경 미만 특징이 있으므로 인쇄 불가")

# T7 하드 게이트
print("\n  T7 하드 게이트")
big = trimesh.creation.box(extents=[400, 400, 400])
rb = engine.evaluate(big, 'FDM', Z, (250, 250, 250))
thin = trimesh.creation.box(extents=[60, 40, 0.2])
rt = engine.evaluate(thin, 'FDM')
check("T7a 빌드볼륨 초과 -> 인쇄 불가", (not rb.feasible) and rb.total_score is None,
      f"feasible={rb.feasible}, 점수={rb.total_score}, 등급={rb.grade}",
      "feasible=False, 점수 없음")
check("T7b 노즐 직경 미만 벽 -> 인쇄 불가", not rt.feasible,
      f"feasible={rt.feasible}, 등급={rt.grade}", "feasible=False (0.2mm < 0.4mm)")

# T8 점수 곡선 연속성
print("\n  T8 점수 곡선 연속성 (경계에서 점프 없어야)")
jumps = []
for f, thr in [(score_at_least, 1.0), (score_at_most, 0.5)]:
    xs = np.linspace(0.001, thr * 3, 4000)
    ys = np.array([f(x, thr) for x in xs])
    jumps.append(float(np.max(np.abs(np.diff(ys)))))
print(f"       score_at_least 최대 점프 {jumps[0]:.4f}점 / score_at_most {jumps[1]:.4f}점")
check("T8 점수 불연속 1점 미만", max(jumps) < 1.0,
      f"최대 {max(jumps):.4f}점", "1점 미만 (v1은 최대 30점)")

print()
print("=" * 78)
print("L2. 불변성")
print("=" * 78)
r0 = engine.evaluate(BOX, 'FDM')

mv = BOX.copy(); mv.apply_translation([137.0, -92.0, 55.0])
check("T9 평행이동 불변", abs(r0.total_score - engine.evaluate(mv, 'FDM').total_score) < 1e-6,
      f"{r0.total_score} vs {engine.evaluate(mv,'FDM').total_score}", "동일")

rt_ = BOX.copy(); rt_.apply_transform(trimesh.transformations.rotation_matrix(np.pi/2, [0,0,1]))
check("T10 Z축 90° 회전 불변", abs(r0.total_score - engine.evaluate(rt_, 'FDM').total_score) < 1e-6,
      f"{r0.total_score} vs {engine.evaluate(rt_,'FDM').total_score}", "동일")

wg = wedge(30)
b1 = ga.to_build_frame(wg, Z); b2 = ga.to_build_frame(wg.copy().apply_scale(2.0), Z)
o1, o2 = ga.compute_overhang(b1, 45.0), ga.compute_overhang(b2, 45.0)
s1, s2 = ga.compute_support_volume(b1, 45.0, .15), ga.compute_support_volume(b2, 45.0, .15)
a1, a2 = ga.compute_aspect_ratio(b1), ga.compute_aspect_ratio(b2)
check("T11 2배 확대 시 순수 기하 비율은 불변",
      abs(o1['overhang_area_ratio']-o2['overhang_area_ratio']) < 1e-9
      and abs(a1['aspect_ratio']-a2['aspect_ratio']) < 1e-9,
      f"오버행 {o1['overhang_area_ratio']:.4f}->{o2['overhang_area_ratio']:.4f}, "
      f"종횡비 {a1['aspect_ratio']:.4f}->{a2['aspect_ratio']:.4f}",
      "오버행 면적비와 종횡비는 기하학적 비율이므로 불변")

# 서포트 부피 비율은 불변이 아니어야 한다.
#   V = a·Σ(A·h) + b·Σ(P·h) 에서 부피항은 L³, 둘레항은 L² 로 커진다.
#   벽 두께 b 는 부품 크기와 무관한 고정값이므로, 큰 부품일수록 벽의 비중이
#   줄어 서포트 비율이 감소한다. 이는 실제 조형에서도 성립하는 거동이다.
#   초기 구현(부피항 단독)은 L³ 로만 커져 비율이 불변이었고, 그것이 오히려
#   물리와 어긋난 것이었다.
_r1, _r2 = s1['support_volume_ratio'], s2['support_volume_ratio']
check("T11b 서포트 비율은 크기가 커지면 감소", _r2 < _r1 - 1e-6,
      f"1배 {_r1:.4f} -> 2배 {_r2:.4f} ({(_r2/_r1-1)*100:+.1f}%)",
      "벽 항이 L², 부피 항이 L³ 이므로 큰 부품일수록 벽 비중이 줄어야 한다")

cyl_c = trimesh.creation.cylinder(radius=6, height=40, sections=16)
cyl_f = trimesh.creation.cylinder(radius=6, height=40, sections=128)
rc, rf = engine.evaluate(cyl_c, 'FDM'), engine.evaluate(cyl_f, 'FDM')
print(f"       원통 분할 16 (면 {len(cyl_c.faces)}) vs 128 (면 {len(cyl_f.faces)})")
check("T12 테셀레이션 해상도 불변", abs(rc.total_score - rf.total_score) < 1.0,
      f"{rc.total_score} vs {rf.total_score}", "동일 (형상이 같으므로)")

sph = trimesh.creation.icosphere(subdivisions=4, radius=20)
x1, x2 = engine.evaluate(sph, 'FDM'), engine.evaluate(sph, 'FDM')
check("T13 재현성 (동일 입력 2회)", abs(x1.total_score - x2.total_score) < 1e-12,
      f"{x1.total_score} vs {x2.total_score}", "완전 동일 (결정론적 샘플링)")

print()
print("=" * 78)
print("L3. 단조성 / 방향 반응")
print("=" * 78)
print("  T14 벽두께 단조 증가")
prev, mono = -1, True
for t in [0.5, 0.8, 1.5, 3.0, 6.0]:
    r = rule(trimesh.creation.box(extents=[60, 40, t]), 'wall_thickness')
    print(f"       {t:4.1f}mm -> 측정 {r.value:6.3f}mm  {r.score:6.1f}점")
    mono &= (r.score >= prev - 1e-9); prev = r.score
check("T14 벽두께 단조성", mono, "위 표", "감소 없음")

print("\n  T15 종횡비 방향 반응 (10x10x100 기둥)")
pil = trimesh.creation.box(extents=[10, 10, 100])
vals = {}
for lb, d in [('+Z', (0,0,1)), ('+X', (1,0,0)), ('+Y', (0,1,0))]:
    r = rule(pil, 'aspect_ratio', bdir=d)
    vals[lb] = r.value
    print(f"       {lb}: 종횡비 {r.value:6.2f}  {r.score:6.1f}점")
check("T15 종횡비 방향 반응", abs(vals['+Z']-10.0) < .01 and abs(vals['+X']-1.0) < .01,
      f"+Z={vals['+Z']}, +X={vals['+X']}, +Y={vals['+Y']}",
      "세우면 100/10=10.0, 눕히면 10/min(10,100)=1.0")

print("\n  T15b 얇은 지느러미 (100x2x80) — max 폭을 쓰면 놓치는 사례")
fin = trimesh.creation.box(extents=[100, 2, 80])
rf_ = rule(fin, 'aspect_ratio')
check("T15b 얇은 판 종횡비 = 높이/최소폭", abs(rf_.value - 40.0) < 0.01,
      f"종횡비 {rf_.value} ({rf_.score:.1f}점)",
      "80/2 = 40.0 (v1은 max 폭을 써서 80/100=0.8 만점)")

print("\n  T16 빌드볼륨 적합성이 방향에 반응 (300x50x50 막대, 250 프린터)")
bar = trimesh.creation.box(extents=[300, 50, 50])
fz = engine.evaluate(bar, 'FDM', (0,0,1), (250,250,250)).feasible
fx = engine.evaluate(bar, 'FDM', (1,0,0), (250,250,250)).feasible
print(f"       +Z(눕힘, X=300mm): feasible={fz}   +X(세움, Z=300mm): feasible={fx}")
check("T16 빌드볼륨 방향 반응", (not fz) and (not fx),
      f"+Z={fz}, +X={fx}", "두 방향 모두 300mm 축이 남아 불가")

# T17/T18 지지 항 분해의 테셀레이션 불변성과 해석해 일치
print("\n  T17-18 지지 항 분해 (부피/둘레/면적)")
_pl = trimesh.creation.box(extents=[40, 30, 4]); _pl.apply_translation([0, 0, 20])
_po = trimesh.creation.box(extents=[4, 4, 18]); _po.apply_translation([0, 0, 9])
_tb = trimesh.boolean.union([_pl, _po])
_seq, _m = [], _tb
for _ in range(3):
    _t = ga.support_terms(ga.to_build_frame(_m, Z), 45.0)
    _seq.append((len(_m.faces), _t))
    print(f"       면 {len(_m.faces):5d} -> 부피항 {_t['vol_term']:9.1f}  "
          f"둘레항 {_t['perim_term']:8.1f}  면적항 {_t['area_term']:8.1f}  영역 {_t['n_regions']}")
    _m = _m.subdivide()
_pt = [x[1]['perim_term'] for x in _seq]
check("T17 둘레항 테셀레이션 불변", max(_pt) - min(_pt) < 1.0,
      f"{_pt[0]:.1f} / {_pt[1]:.1f} / {_pt[2]:.1f}",
      "메시를 4배로 쪼개도 동일 (삼각형 단위 Σ√A 는 2배씩 커진다)")

# 해석해: 40x30 판 둘레 140 + 4x4 기둥 구멍 둘레 16 = 156mm, 높이 18mm
check("T18 둘레항 해석해 일치", abs(_pt[0] - 156.0 * 18.0) < 1.0,
      f"{_pt[0]:.1f}", "156mm x 18mm = 2808.0")

print()
print("=" * 78)
print("L4. 비정상 입력 방어 — 잘못된 입력에 점수를 주면 안 된다")
print("=" * 78)
print("  (정상 형상만으로는 드러나지 않는 사각지대. 19개 검증이 이 영역을 못 덮었다.)")


def blocked(mesh, label, expect_gate=None):
    """평가가 차단되어야 하는 입력."""
    try:
        r = engine.evaluate(mesh, 'FDM', Z)
    except Exception as e:
        return False, f"예외 발생 {type(e).__name__}: {e}"
    if r.feasible or r.total_score is not None:
        return False, f"통과됨 — 점수 {r.total_score} 등급 {r.grade}"
    names = [g.name for g in r.gates if not g.passed]
    if expect_gate and expect_gate not in names:
        return False, f"차단은 됐으나 게이트가 다름: {names}"
    return True, f"차단됨 ({', '.join(names)})"


BOXV = trimesh.creation.box(extents=[40, 30, 20])

# T20 열린 메시
_open = trimesh.Trimesh(vertices=BOXV.vertices, faces=BOXV.faces[2:], process=False)
ok, got = blocked(_open, "열린 메시", "메시 무결성")
check("T20 열린 메시 차단", ok, got, "메시 무결성 게이트 위반")

# T21 법선 반전
_flip = trimesh.creation.box(extents=[40, 30, 20]); _flip.invert()
ok, got = blocked(_flip, "법선 반전", "메시 무결성")
check("T21 법선 반전 메시 차단", ok, got,
      "메시 무결성 위반 (반전 시 오버행 판정이 뒤집히므로 점수가 무의미)")

# T22 삼각형 1개
_tri = trimesh.Trimesh(vertices=[[0, 0, 0], [10, 0, 0], [0, 10, 0]],
                       faces=[[0, 1, 2]], process=False)
ok, got = blocked(_tri, "삼각형 1개", "메시 무결성")
check("T22 면 1개 입력 차단", ok, got, "솔리드가 아니므로 차단")

# T23 퇴화 삼각형(면적 0)
_deg = trimesh.Trimesh(vertices=[[0, 0, 0], [1, 0, 0], [2, 0, 0]],
                       faces=[[0, 1, 2]], process=False)
ok, got = blocked(_deg, "퇴화 삼각형")
check("T23 퇴화 형상 차단", ok, got, "면적/부피 0 이므로 차단")

# T24 부피 0
ok, got = blocked(trimesh.creation.box(extents=[40, 30, 0]), "두께 0 평판")
check("T24 부피 0 입력 차단", ok, got, "부피 0 이므로 차단")

# T25 자기교차 (겹치는 concatenate)
_a = trimesh.creation.box(extents=[20, 20, 20])
_b = trimesh.creation.box(extents=[20, 20, 20]); _b.apply_translation([5, 5, 5])
ok, got = blocked(trimesh.util.concatenate([_a, _b]), "자기교차", "메시 무결성")
check("T25 겹치는 다중 바디 차단", ok, got,
      "내부 면이 남아 부피 중복 (표준 6.6.11.4)")

# T26 겹치지 않는 다중 바디는 통과해야 (위양성 방지)
_c = trimesh.creation.box(extents=[20, 20, 20])
_d = trimesh.creation.box(extents=[20, 20, 20]); _d.apply_translation([60, 0, 0])
_r = engine.evaluate(trimesh.util.concatenate([_c, _d]), 'FDM', Z)
check("T26 떨어진 다중 바디는 통과", _r.feasible,
      f"feasible={_r.feasible}, 점수={_r.total_score}",
      "겹치지 않으면 정상 입력 (위양성이면 안 됨)")

# T27 두께 불균일 — 게이트가 최솟값을 쓰는지
_thick = trimesh.creation.box(extents=[40, 30, 20])
_thin = trimesh.creation.box(extents=[10, 10, 0.1]); _thin.apply_translation([25, 0, 0])
_mixed = trimesh.boolean.union([_thick, _thin])
_w = ga.compute_wall_thickness(_mixed)
_rm = engine.evaluate(_mixed, 'FDM', Z)
print(f"       최솟값 {_w['min_thickness']:.3f}mm / 5퍼센타일 {_w['p_thickness']:.2f}mm "
      f"/ 물리 하한 0.4mm")
check("T27 부분적 초박막 차단 (게이트=최솟값)",
      (not _rm.feasible) and _rm.total_score is None,
      f"feasible={_rm.feasible}, 점수={_rm.total_score}",
      "일부만 하한 미만이어도 차단 — 백분위수를 쓰면 놓친다")

# T28 하드 게이트 우선순위: 게이트 위반 시 점수를 산출하지 않는다
_over = trimesh.creation.box(extents=[400, 400, 400])
_ro = engine.evaluate(_over, 'FDM', Z, (250, 250, 250))
check("T28 게이트 위반 시 점수 미산출", _ro.total_score is None and _ro.grade == '프로필 미충족' and _ro.evaluation_status == 'blocked',
      f"점수={_ro.total_score}, 등급={_ro.grade}",
      "점수 None, 등급 '프로필 미충족', 상태 blocked")

# T29 정상 입력은 여전히 통과 (방어가 과하면 안 됨)
_rn = engine.evaluate(BOXV, 'FDM', Z)
check("T29 정상 입력 오차단 없음", _rn.feasible and _rn.total_score == 100.0,
      f"feasible={_rn.feasible}, 점수={_rn.total_score}", "정상 통과 100.0")

# ── 갇힌 체적 (표준 7.4) ──
print()
print("  T30-33 갇힌 체적 (표준 7.4)")
_o = trimesh.creation.box(extents=[40, 40, 40])
_i = trimesh.creation.box(extents=[20, 20, 20])
_sealed = trimesh.boolean.difference([_o, _i])
_d = trimesh.creation.box(extents=[5, 5, 60])
_vented = trimesh.boolean.difference([_o, trimesh.boolean.union([_i, _d])])

_tv = ga.compute_trapped_volume(_sealed)
print(f"       밀폐: 공동 {_tv.get('n_cavities')}개, {_tv.get('trapped_volume', 0):,.0f}mm³ "
      f"(이론 8,000)")
check("T30 밀폐 공동 검출 및 부피", _tv['has_trapped'] and _tv['n_cavities'] == 1
      and abs(_tv['trapped_volume'] - 8000.0) < 1.0,
      f"{_tv['n_cavities']}개 / {_tv['trapped_volume']:,.1f}mm³",
      "1개 / 8,000.0mm³ (20³)")

_tv2 = ga.compute_trapped_volume(_vented)
check("T31 배출 구멍이 있으면 갇히지 않음", not _tv2['has_trapped'],
      f"has_trapped={_tv2['has_trapped']}, 공동 {_tv2['n_cavities']}개",
      "공동이 외부와 이어지므로 0개")

_rs = engine.evaluate(_sealed, 'SLS', Z)
_rf = engine.evaluate(_sealed, 'FDM', Z)
print(f"       밀폐 부품 판정: SLS feasible={_rs.feasible} / FDM feasible={_rf.feasible}")
check("T32 분말 공정은 갇힌 체적을 차단", (not _rs.feasible)
      and any(g.name == '갇힌 체적' and not g.passed for g in _rs.gates),
      f"SLS feasible={_rs.feasible}", "분말을 빼낼 수 없으므로 인쇄 불가")
check("T33 재료 압출은 차단하지 않음 (오탐 방지)", _rf.feasible,
      f"FDM feasible={_rf.feasible}, 점수={_rf.total_score}",
      "속이 빈 부품은 재료 압출에서 정상 형상")

# ── 계단 효과 (6.6.3 / 7.5) ──
print()
print("  T34-36 계단 효과 — cusp = t · cos(a) 해석해")
print(f"       {'경사각':>7s} {'최대 cusp':>11s} {'이론값':>11s}")
_errs = []
for _a in (10, 30, 45, 60, 80):
    _sc = ga.compute_staircase(ga.to_build_frame(wedge(_a), Z), 0.2)
    _th = 0.2 * np.cos(np.radians(_a))
    _errs.append(abs(_sc['max_cusp'] - _th))
    print(f"       {_a:5d}°  {_sc['max_cusp']:11.5f} {_th:11.5f}")
check("T34 계단 높이 해석해 일치", max(_errs) < 1e-6,
      f"최대 오차 {max(_errs):.2e}", "t · cos(경사각)")

_v = ga.compute_staircase(ga.to_build_frame(
    trimesh.creation.box(extents=[40, 2, 60]), Z), 0.2)
_b = ga.compute_staircase(ga.to_build_frame(BOX, Z), 0.2)
check("T35 수직면·수평면은 계단 없음",
      _v['max_cusp'] < 1e-9 and _b['max_cusp'] < 1e-9,
      f"수직판 {_v['max_cusp']:.2e} / 직육면체 {_b['max_cusp']:.2e}",
      "둘 다 0 (수직벽은 계단이 없고, 수평면은 한 층으로 끝남)")

# 45도 쐐기는 90도 회전에 대칭이라 +Z 와 +X 가 같은 값을 준다(빗면이 회전
# 후에도 45도). 방향 반응을 보려면 비대칭 형상을 써야 한다. 30도 빗면은
# 회전하면 60도가 되므로 값이 달라진다.
_w30 = wedge(30)
_s1 = ga.compute_staircase(ga.to_build_frame(_w30, Z), 0.2)
_s2 = ga.compute_staircase(ga.to_build_frame(_w30, (1, 0, 0)), 0.2)
_s3 = ga.compute_staircase(ga.to_build_frame(_w30, (0, 1, 0)), 0.2)
print(f"       30° 쐐기: +Z {_s1['mean_cusp']:.5f} · +X {_s2['mean_cusp']:.5f} · "
      f"+Y {_s3['mean_cusp']:.5f}")
check("T36 계단 높이가 빌드 방향에 반응",
      abs(_s1['mean_cusp'] - _s2['mean_cusp']) > 1e-4 and _s3['mean_cusp'] < 1e-9,
      f"+Z {_s1['mean_cusp']:.5f} / +X {_s2['mean_cusp']:.5f} / +Y {_s3['mean_cusp']:.5f}",
      "+Z(30°)와 +X(60°)는 달라야 하고, +Y 는 모든 면이 수직·수평이라 0")

# 45도 쐐기는 대칭이므로 오히려 같아야 한다. 이것도 함께 고정한다.
_w45 = wedge(45)
_e1 = ga.compute_staircase(ga.to_build_frame(_w45, Z), 0.2)['mean_cusp']
_e2 = ga.compute_staircase(ga.to_build_frame(_w45, (1, 0, 0)), 0.2)['mean_cusp']
check("T36b 45° 쐐기는 90° 회전에 대칭", abs(_e1 - _e2) < 1e-9,
      f"+Z {_e1:.6f} = +X {_e2:.6f}",
      "빗면이 45°라 회전 후에도 45° (대칭성 확인)")

# ── 브리지 스팬 (6.6.9) ──
print("\n  T37-39 브리지 스팬")


def _bridge_part(span):
    _L = trimesh.creation.box(extents=[6, 20, 30]); _L.apply_translation([-(span/2+3), 0, 15])
    _R = trimesh.creation.box(extents=[6, 20, 30]); _R.apply_translation([(span/2+3), 0, 15])
    _D = trimesh.creation.box(extents=[span+12, 20, 4]); _D.apply_translation([0, 0, 32])
    return trimesh.boolean.union([_L, _R, _D])


print(f"       {'스팬':>6s} {'제한 없음':>11s} {'제한 10mm':>11s}")
_res_b = {}
for _sp in (4, 8, 12, 20):
    _bf = ga.to_build_frame(_bridge_part(_sp), Z)
    _o0 = ga.compute_overhang(_bf, 45.0, bridge_limit=0.0)
    _o1 = ga.compute_overhang(_bf, 45.0, bridge_limit=10.0)
    _res_b[_sp] = (_o0['overhang_area_ratio'], _o1['overhang_area_ratio'])
    print(f"       {_sp:4d}mm {_o0['overhang_area_ratio']*100:10.2f}% "
          f"{_o1['overhang_area_ratio']*100:10.2f}%")
check("T37 한계 이하 스팬은 지지 불필요",
      _res_b[4][1] < 1e-9 and _res_b[8][1] < 1e-9,
      f"4mm={_res_b[4][1]*100:.2f}%, 8mm={_res_b[8][1]*100:.2f}%", "둘 다 0%")
check("T38 한계 초과 스팬은 지지 필요",
      _res_b[12][1] > 0 and abs(_res_b[12][1] - _res_b[12][0]) < 1e-9,
      f"12mm={_res_b[12][1]*100:.2f}% (제한 없을 때 {_res_b[12][0]*100:.2f}%)",
      "제외되지 않고 그대로")

_post = trimesh.creation.box(extents=[10, 20, 30]); _post.apply_translation([0, 0, 15])
_arm = trimesh.creation.box(extents=[6, 20, 4]); _arm.apply_translation([8, 0, 28])
_canti = trimesh.boolean.union([_post, _arm])
_oc = ga.compute_overhang(ga.to_build_frame(_canti, Z), 45.0, bridge_limit=10.0)
check("T39 외팔보는 다리로 오인하지 않음",
      len(_oc['bridges']) == 0 and _oc['overhang_area_ratio'] > 0,
      f"다리 판정 {len(_oc['bridges'])}개, 오버행 {_oc['overhang_area_ratio']*100:.2f}%",
      "폭이 좁아도 한쪽만 고정이면 건너뛸 수 없음")

# ── 형상 간 최소 간격 (6.6.6) ──
print("\n  T40-41 형상 간 최소 간격")
print(f"       {'실제 간격':>10s} {'측정값':>10s}")
_gerr = []
for _g in (0.3, 0.8, 2.0, 5.0):
    _a1 = trimesh.creation.box(extents=[20, 20, 20])
    _a2 = trimesh.creation.box(extents=[20, 20, 20]); _a2.apply_translation([20 + _g, 0, 0])
    _fg = ga.compute_feature_gap(trimesh.boolean.union([_a1, _a2]))
    _gerr.append(abs(_fg['min_gap'] - _g))
    print(f"       {_g:8.1f}mm {_fg['min_gap']:9.4f}mm")
check("T40 간격 해석해 일치", max(_gerr) < 1e-3,
      f"최대 오차 {max(_gerr):.2e}mm", "슬롯 폭과 일치")

_fg2 = ga.compute_feature_gap(BOX)
check("T41 마주 보는 형상이 없으면 간격 없음", not _fg2.get('has_gap', True),
      f"has_gap={_fg2.get('has_gap')}", "볼록 형상은 바깥 레이가 아무것도 만나지 않음")

# ── 갑작스런 두께 변화 (7.3) ──
print("\n  T42-44 갑작스런 두께 변화")
_uni = [ga.compute_thickness_gradient(trimesh.creation.box(extents=[60, 40, _t]), enabled=True)['p95_ratio']
        for _t in (2.0, 6.0)]
_sph = ga.compute_thickness_gradient(
    trimesh.creation.icosphere(subdivisions=3, radius=20), enabled=True)['p95_ratio']
print(f"       균일 2mm {_uni[0]:.2f} · 균일 6mm {_uni[1]:.2f} · 구체 {_sph:.2f}")
check("T42 균일 두께 부품은 비 1.0", max(_uni + [_sph]) < 1.05,
      f"최대 {max(_uni + [_sph]):.3f}", "1.0 (두께가 변하지 않음)")


def _step_part(thin, thick):
    _p1 = trimesh.creation.box(extents=[40, 40, thin])
    _p2 = trimesh.creation.box(extents=[20, 40, thick])
    _p2.apply_translation([30, 0, thick / 2 - thin / 2])
    return trimesh.boolean.union([_p1, _p2])


_steps = [(2, 4), (2, 8), (1, 12)]
_sr = [ga.compute_thickness_gradient(_step_part(a, b), enabled=True)['p95_ratio']
       for a, b in _steps]
print(f"       단차 " + " · ".join(f"{a}->{b}mm {r:.1f}" for (a, b), r in zip(_steps, _sr)))
check("T43 두께 급변을 탐지", all(r > 1.5 for r in _sr),
      ", ".join(f"{r:.2f}" for r in _sr),
      "모두 1.5 초과 (배율의 크기는 근사값이며 급변 유무만 판별)")

_m = _step_part(2, 8)
_tseq = []
for _ in range(3):
    _tseq.append(ga.compute_thickness_gradient(_m, enabled=True)['p95_ratio'])
    _m = _m.subdivide()
_box_tg = ga.compute_thickness_gradient(BOX, enabled=True)['p95_ratio']
_off = ga.compute_thickness_gradient(BOX)
check("T44b 단순 솔리드 오탐을 인지하고 기본 비활성",
      _box_tg > 1.5 and (not _off.get('available')),
      f"40x30x20 직육면체 비 {_box_tg:.2f}, 기본 available={_off.get('available')}",
      "방향별 관통 거리가 20/30/40mm 라 오탐. 기본 꺼짐이어야 정상 부품이 감점되지 않음")

check("T44 두께 변화 지표 테셀레이션 불변",
      max(_tseq) - min(_tseq) < 0.01,
      " / ".join(f"{v:.2f}" for v in _tseq), "메시를 4배로 쪼개도 동일")

# ── 규칙 추가가 방향 선택에 미치는 영향 ──
print()
print("  T45 계단 효과 추가로 진짜 트레이드오프가 생기는가")
from src.core.scoring import evaluate_orientations as _eo, pareto_front as _pf
_cone = trimesh.creation.cone(radius=30, height=8, sections=64)
_res = _eo(_cone, 'FDM')
_p = _pf(_res)
print(f"       {'방향':12s} {'오버행%':>8s} {'계단µm':>8s} {'종합':>7s}")
for _lb, _r in _res.items():
    if not _r.feasible:
        continue
    _d = {x.rule_name: x for x in _r.rule_results}
    _st = _d['staircase'].value * 200 if _d['staircase'].value is not None else -1
    print(f"       {_lb:12s} {_d['overhang_area'].value:8.2f} {_st:8.1f} {_r.total_score:7.1f}")
check("T45 얕은 원뿔에서 파레토 지배가 깨짐",
      (not _p['weight_free']) and len(_p['front']) >= 3,
      f"프론트 {len(_p['front'])}개, 가중치 불필요={_p['weight_free']}",
      "계단 효과는 오버행과 반대로 움직이므로 트레이드오프가 생겨야 함")
print("       (규칙이 오버행 계열뿐일 때는 항상 지배가 성립해 가중치가 불필요했다.")
print("        서로 상충하는 축이 생기면 비로소 선호 정보가 필요해진다.)")

print()
print("=" * 78)
print("L0. 스모크 — 4공정 x 6방향 = 24조합")
print("=" * 78)
crash = 0
for p in ['FDM', 'SLA', 'SLS', 'DMLS']:
    line = f"  {p:5s} "
    for lb, d in AXIS_ORIENTATIONS.items():
        try:
            r = engine.evaluate(BOX, p, d)
            line += f"{lb.split()[0]}={str(r.total_score):>5s} "
        except Exception as e:
            line += f"{lb.split()[0]}=CRASH({type(e).__name__}) "; crash += 1
    print(line)
check("L0 24조합 무예외", crash == 0, f"{crash}건 크래시", "0건")

print()
print("=" * 78)
n = sum(1 for _, ok in LOG if ok)
print(f"결과: {n} / {len(LOG)} 통과")
print("=" * 78)
for name, ok in LOG:
    if not ok:
        print(f"  FAIL  {name}")
sys.exit(0 if n == len(LOG) else 1)
