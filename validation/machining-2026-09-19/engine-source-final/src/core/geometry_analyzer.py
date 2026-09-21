"""형상 분석기 (v2) — AM 제조성 평가를 위한 3D 형상 분석

v1 대비 주요 변경
-----------------
1. 모든 방향 의존 분석을 '빌드 좌표계'로 회전시킨 뒤 수행한다.
   -> 종횡비 / 빌드볼륨 적합성이 빌드 방향에 자동으로 반응한다.
2. 오버행 판정을 다시 정의한다.
   - 하향면 각도 정보를 clip 으로 뭉개지 않는다.
   - 수직벽(법선이 빌드 방향과 수직)은 자립하므로 제외한다.
   - 빌드 플레이트에 접촉한 면은 제외한다.
   - 임계각을 공정별 값으로 외부에서 주입받는다.
3. 지지구조물 부피를 투영 면적 기준으로 계산하고,
   높이는 '바닥까지'가 아니라 '바로 아래 첫 표면까지'로 레이캐스팅한다.
4. 벽두께를 정점 법선이 아니라 면 중심 + 면 법선으로 측정한다.
   샘플링은 난수가 아니라 누적 면적 기반 결정론적 계통 샘플링이다(재현성).
   대표값은 최솟값이 아니라 백분위수(기본 5%)를 쓴다.
5. 최소 특징 크기는 모서리 길이(=테셀레이션 설정)를 쓰지 않는다.
   복셀 모폴로지 오프닝 기반 검사를 옵션으로 제공하고, 기본은 N/A 이다.
"""

import numpy as np
import trimesh

EPS = 1e-9


# ──────────────────────────────────────────────────────────────
# 빌드 좌표계
# ──────────────────────────────────────────────────────────────
def unit(v):
    v = np.asarray(v, dtype=float).ravel()
    if v.shape != (3,) or not np.isfinite(v).all():
        raise ValueError("빌드 방향은 유한한 숫자 3개여야 합니다.")
    n = np.linalg.norm(v)
    if n < EPS:
        raise ValueError("빌드 방향 벡터의 크기가 0입니다.")
    return v / n


def to_build_frame(mesh: trimesh.Trimesh, build_direction) -> trimesh.Trimesh:
    """빌드 방향이 +Z가 되도록 메시를 회전시킨 사본을 돌려준다.

    v1은 각 분석 함수가 제각각 build_direction을 처리하거나 아예 무시했다.
    좌표계를 한 번만 맞추면 이후 모든 분석이 'Z가 위'라는 단일 가정으로
    끝나므로, 방향 의존 버그가 구조적으로 사라진다.
    """
    b = unit(build_direction)
    m = mesh.copy()
    if len(m.vertices) == 0:
        return m
    if np.allclose(b, [0, 0, 1]):
        return m
    m.apply_transform(trimesh.geometry.align_vectors(b, [0, 0, 1]))
    return m


# ──────────────────────────────────────────────────────────────
# 오버행
# ──────────────────────────────────────────────────────────────
def compute_overhang(mesh_bf: trimesh.Trimesh, critical_angle: float,
                     plate_tol_ratio: float = 1e-3,
                     bridge_limit: float = 0.0) -> dict:
    """오버행(지지구조 필요 면) 판정. 입력은 빌드 좌표계 메시.

    정의
    ----
    theta       : 면 법선과 +Z 사이 각 (0~180도)
    inclination : 수평면 기준 하향면의 경사각 = 180 - theta
                  90도 = 수직벽, 45도 = 45도 경사, 0도 = 수평 하향면
    지지 필요    : 아래를 향하고(dot < 0) AND inclination < critical_angle
                  AND 빌드 플레이트 접촉면이 아님
    """
    n = mesh_bf.face_normals
    areas = mesh_bf.area_faces
    if len(n) == 0:
        return {'bridges': [], 'bridged_area': 0.0, 'overhang_face_indices': [],
                'overhang_mask': np.zeros(0, dtype=bool),
                'inclination_deg': np.zeros(0), 'critical_angle': float(critical_angle),
                'overhang_area': 0.0, 'total_area': 0.0, 'overhang_area_ratio': 0.0,
                'overhang_face_count': 0, 'plate_face_count': 0}
    dots = np.clip(n[:, 2], -1.0, 1.0)

    theta = np.degrees(np.arccos(dots))
    inclination = 180.0 - theta          # 하향면의 수평면 기준 경사각

    # 수직벽(dots == 0)은 자립하므로 제외한다. v1은 여기를 ~(dots>0)로 써서 포함시켰다.
    is_down = dots < -EPS

    if critical_angle <= 0:
        # 분말 지지 공정(SLS 등): 기하학적 지지구조가 필요 없다.
        needs = np.zeros(len(n), dtype=bool)
    else:
        needs = is_down & (inclination < critical_angle - EPS)

    # 빌드 플레이트 접촉면 제외 (v1은 바닥면을 오버행으로 잡았다)
    z = mesh_bf.triangles_center[:, 2]
    zmin = float(mesh_bf.vertices[:, 2].min())
    height = float(mesh_bf.extents[2])
    tol = max(1e-6, plate_tol_ratio * max(height, 1.0))
    # Every vertex must contact the plate; object height is not a contact tolerance.
    tol = max(1e-7, 1e-8 * max(height, 1.0))
    on_plate = np.max(mesh_bf.triangles[:, :, 2], axis=1) <= zmin + tol
    needs = needs & ~on_plate

    # 짧은 수평 구간은 지지 없이 건너뛸 수 있다(브리징). 표준 6.6.9 는
    # 지지 구조 없이 제작 가능한 최대 크기를 고려사항으로 든다.
    bridges = []
    if bridge_limit > 0 and needs.any():
        mask2 = np.zeros(len(n), dtype=bool); mask2[needs] = True
        adj2 = mesh_bf.face_adjacency
        sel2 = adj2[mask2[adj2[:, 0]] & mask2[adj2[:, 1]]] if len(adj2) else np.empty((0, 2), int)
        try:
            comps2 = trimesh.graph.connected_components(
                sel2, nodes=np.where(needs)[0], min_len=1)
        except Exception:
            comps2 = []
        for comp in comps2:
            comp = np.asarray(comp, dtype=int)
            ok, span, frac = _is_bridgeable(mesh_bf, comp, bridge_limit)
            if ok:
                needs[comp] = False
                bridges.append({'span': span, 'anchor_frac': frac,
                                'area': float(areas[comp].sum()),
                                'n_faces': int(len(comp))})

    total_area = float(areas.sum())
    oh_area = float(areas[needs].sum())
    return {
        'bridges': bridges,
        'bridged_area': float(sum(b['area'] for b in bridges)),
        'overhang_face_indices': np.where(needs)[0].tolist(),
        'overhang_mask': needs,
        'inclination_deg': inclination,
        'critical_angle': float(critical_angle),
        'overhang_area': oh_area,
        'total_area': total_area,
        'overhang_area_ratio': oh_area / total_area if total_area > EPS else 0.0,
        'overhang_face_count': int(needs.sum()),
        'plate_face_count': int(on_plate.sum()),
    }


# ──────────────────────────────────────────────────────────────
# 지지구조물 부피
# ──────────────────────────────────────────────────────────────
def compute_support_volume(mesh_bf: trimesh.Trimesh, critical_angle: float,
                           density: float = 0.165, wall: float = 0.2715,
                           bridge_limit: float = 0.0) -> dict:
    """지지구조물 부피 추정 (2항 모델).

        V = density · Σ(A · h)  +  wall · Σ(P · h)

    A 는 연결된 지지 영역의 수평 투영 면적, P 는 그 영역의 수평 투영 둘레,
    h 는 아래 첫 표면까지의 높이다.

    항이 두 개인 이유
    ----------------
    지지 기둥은 내부 격자만으로 이루어지지 않는다. 바깥 벽과 인터페이스가
    함께 만들어지며, 이 성분은 부피가 아니라 둘레에 비례한다. 기둥이 가늘수록
    벽의 비중이 커지므로, 부피 항만 쓰면 작은 지지구조가 많은 형상에서
    계통적으로 과소추정한다.

    실제로 상용 슬라이서(Cura) 24건과 대조했을 때 부피 항만 쓴 모델은
    R² = 0.715 였고, 특히 미세 형상이 많은 시험 아티팩트를 옆으로 세운
    방향에서 4배까지 과소추정했다. 둘레 항을 더하자 R² = 0.978 로 올랐다.
    면적 항을 추가로 넣어도 계수가 사실상 0(-0.004)이어서 채택하지 않았다.

    계수의 의미
    ----------
    density = 0.165 : 기존 Cura 대조에서 적합한 부피 항 계수. 설정값 15%와
                      가깝지만 실제 내부 채움 비율과 같은 물리량임을 증명하지 않는다.
    wall    = 0.2715 mm : 둘레 1mm, 높이 1mm 당 추가되는 재료 두께.
                      노즐 0.4mm 의 압출선 폭보다 작은 값으로, 벽과 인터페이스를
                      합친 실효 두께에 해당한다.

    두 계수는 FDM / 노즐 0.4mm / 서포트 밀도 15% / Everywhere 배치 조건에서
    회귀한 값이다. R²=0.978은 기존 24조건의 적합도이며, 수정된 브리지·형상
    분석과 다른 공정·설정에 그대로 적용되는 검증 결과는 아니다.
    """
    if len(mesh_bf.faces) == 0:
        return {'support_volume': 0.0, 'part_volume': 0.0, 'support_volume_ratio': 0.0,
                'mean_support_height': 0.0, 'n_regions': 0,
                'vol_term': 0.0, 'perim_term': 0.0, 'density': density, 'wall': wall}
    try:
        regs = support_regions(mesh_bf, critical_angle, bridge_limit)
    except Exception as exc:
        return {'available': False, 'reason': f'서포트 분석 실패: {exc}'}
    part_volume = float(abs(mesh_bf.volume))
    if not regs:
        return {'support_volume': 0.0, 'part_volume': part_volume,
                'support_volume_ratio': 0.0, 'mean_support_height': 0.0,
                'n_regions': 0, 'vol_term': 0.0, 'perim_term': 0.0,
                'density': density, 'wall': wall}

    vol_term = float(sum(r['proj_area'] * r['mean_height'] for r in regs))
    perim_term = float(sum(r['perimeter'] * r['mean_height'] for r in regs))
    support_volume = density * vol_term + wall * perim_term
    heights = [r['mean_height'] for r in regs]
    return {
        'available': True,
        'support_volume': support_volume,
        'part_volume': part_volume,
        'support_volume_ratio': support_volume / part_volume if part_volume > EPS else 0.0,
        'mean_support_height': float(np.mean(heights)) if heights else 0.0,
        'n_regions': len(regs),
        'vol_term': vol_term, 'perim_term': perim_term,
        'density': density, 'wall': wall,
    }


# ──────────────────────────────────────────────────────────────
# 벽두께
# ──────────────────────────────────────────────────────────────
def adaptive_samples(mesh, requested: int, floor: int = 300, cap: int = 4000) -> int:
    """메시 크기에 따라 레이캐스팅 샘플 수를 조정한다.

    레이캐스팅이 전체 평가 시간의 대부분을 차지하므로, 면 수가 많을수록
    샘플 밀도를 낮춰 응답 시간을 제한한다. 면 수의 제곱근에 비례시키면
    큰 메시에서도 공간적 대표성을 유지하면서 비용이 완만하게 증가한다.
    """
    n_faces = len(mesh.faces)
    if n_faces <= requested:
        return n_faces
    scaled = int(requested * (requested / max(n_faces, 1)) ** 0.5 * 2.0)
    upper = min(requested, cap, n_faces)      # 요청치를 넘겨서는 안 된다
    return int(np.clip(max(scaled, floor), min(floor, upper), upper))


def compute_wall_thickness(mesh: trimesh.Trimesh, n_samples: int = 2000,
                           percentile: float = 5.0) -> dict:
    """레이캐스팅 기반 국소 두께 분포.

    v1 대비
    -------
    - 정점 법선 대신 '면 중심 + 면 법선'. 정점 법선은 모서리에서 평균되어
      레이가 대각으로 빠져나가고, 박스형 부품에서 두께를 sqrt(3)배로 재는
      계통 오차를 만든다.
    - 난수 샘플링 대신 누적 면적 기반 결정론적 계통 샘플링.
      같은 입력이면 항상 같은 결과가 나오고, 면적 가중이라
      테셀레이션이 조밀한 곡면이 과대표집되지 않는다.
    - 대표값을 최솟값이 아니라 백분위수로. 최솟값은 이상치 하나에
      결과 전체가 끌려간다.
    빌드 방향과 무관하므로 원본 메시를 그대로 쓴다.
    """
    areas = mesh.area_faces
    if len(areas) == 0 or areas.sum() <= EPS:
        return {'available': False, 'reason': '면이 없습니다.'}

    # 샘플링 전략을 두 가지로 나눈다.
    #
    #   면적 가중  : 두께 '분포'를 대표한다. 백분위수 산출에 쓴다.
    #   면 균등    : 작은 면을 놓치지 않는다. 최솟값 탐지에 쓴다.
    #
    # 면적 가중만 쓰면 얇은 특징을 구조적으로 놓친다. 얇을수록 면적이 작아
    # 뽑힐 확률이 낮기 때문이다. 실측 예: 80x80x20 블록에 지름 0.3mm 핀을
    # 붙이면 핀은 전체 면적의 0.05% 라서 한 번도 뽑히지 않았고, 최솟값이
    # 20mm 로 보고되었다. 제조성 검토 도구가 얇은 특징을 놓치는 것은
    # 존재 이유를 부정하는 오류이므로 면 균등 샘플링을 함께 쓴다.
    n = adaptive_samples(mesh, int(n_samples))
    nf = len(areas)
    if nf <= n:
        idx = np.arange(nf)
        distribution_mass = areas.copy()
    else:
        cum = np.cumsum(areas)
        n_area = max(1, n // 2)
        tgt = (np.arange(n_area) + 0.5) * (cum[-1] / n_area)
        idx_area = np.clip(np.searchsorted(cum, tgt), 0, nf - 1)

        n_rest = max(1, n - n_area)
        idx_uni = np.linspace(0, nf - 1, n_rest // 2 + 1).astype(int)
        idx_small = np.argsort(areas)[:max(1, n_rest - len(idx_uni))]

        idx = np.unique(np.concatenate([idx_area, idx_uni, idx_small]))
        # Only area samples represent the distribution. Detection-only samples
        # must not bias the percentile toward tiny, densely tessellated faces.
        counts = np.bincount(idx_area, minlength=nf)
        distribution_mass = counts[idx].astype(float) * areas.sum() / n_area

    centers = mesh.triangles_center[idx]
    normals = mesh.face_normals[idx]
    eps = max(1e-5, 1e-5 * float(np.max(mesh.extents)))

    # 면 법선의 반대 방향으로 한 번 쏜다. 이 값은 엄밀히 말해 '법선 방향
    # 관통 거리' 이며, 마주보는 면이 평행할 때 두께와 일치한다.
    #
    # 원뿔 안의 여러 방향으로 쏘아 최솟값을 취하는 방법도 시도했으나, 비스듬한
    # 레이는 두께보다 짧은 거리를 주어 오히려 과소측정을 만들었다(5mm 균일
    # 판에서 2.03mm). 두께의 정의가 법선 방향에 묶여 있기 때문이다.
    # 따라서 단일 방향을 유지하고, 서로 다른 법선의 표본을 섞어 비교하는
    # 문제는 두께 구배 계산 쪽에서 법선 유사도로 걸러 해결한다.
    origins = centers - normals * eps
    dirs = -normals
    try:
        locs, ray_idx, target_faces = mesh.ray.intersects_location(
            ray_origins=origins, ray_directions=dirs, multiple_hits=False)
    except Exception as e:
        return {'available': False, 'reason': f'레이캐스팅 실패: {e}'}
    if len(ray_idx) == 0:
        return {'available': False, 'reason': '유효한 두께 측정값이 없습니다.'}
    dist = np.linalg.norm(locs - centers[ray_idx], axis=1)
    keep = dist > eps * 10
    t = dist[keep]
    target_faces = target_faces[keep]
    ray_idx = ray_idx[keep]
    if len(t) == 0:
        return {'available': False, 'reason': '유효한 두께 측정값이 없습니다.'}

    hit_faces = idx[ray_idx]
    order = np.argsort(t)
    masses = distribution_mass[ray_idx]
    def area_quantile(q):
        ranked = np.argsort(t)
        cdf = np.cumsum(masses[ranked])
        if cdf[-1] <= 0:
            return float('nan')
        pos = min(int(np.searchsorted(cdf, q / 100 * cdf[-1], side='left')), len(t)-1)
        return float(t[ranked[pos]])
    if masses.sum() <= 0:
        return {'available': False, 'reason': '면적 대표 표본의 두께 측정 실패'}
    return {
        'available': True,
        'min_thickness': float(np.min(t)),
        'p_thickness': area_quantile(percentile),
        'percentile': percentile,
        'median_thickness': area_quantile(50),
        'max_thickness': float(np.max(t)),
        'samples': int(len(t)),
        'distribution_method': 'area_weighted_inverse_cdf',
        'sample_area_coverage': float(mesh.area_faces[hit_faces].sum() / areas.sum()),
        'thicknesses': t,                        # 진단용 원자료
        'sample_centers': centers[ray_idx],
        'sample_normals': normals[ray_idx],
        'sample_face_areas': mesh.area_faces[hit_faces],
        'sample_face_indices': hit_faces,
        'target_face_indices': target_faces,
        'discarded_near_hits': int(np.count_nonzero(~keep)),
        'ray_epsilon': eps,
        'total_area': float(areas.sum()),
        'thin_face_indices': hit_faces[order[:200]].tolist(),
    }


def verify_thin_regions(mesh, wt, threshold, max_faces=128):
    """Bounded confirmation probes on initially suspect faces.

    Three interior probes must all find nonadjacent, approximately opposing
    surfaces below the profile threshold, with a measurable spatial span.
    This is corroborating geometric evidence, NOT proof of print failure.
    Unconfirmed candidates (including budget limits) always remain review items.
    The cosine/span settings are engineering heuristics, not standard limits.
    """
    out = dict(method='three_interior_probes_v1', threshold_mm=float(threshold),
               opposition_cosine=0.85, min_span_mm=float(threshold / 4),
               verified_regions=0, checked_faces=0, candidate_faces=0,
               confirmed_face_indices=[], budget_limited=False)
    if not wt.get('available'):
        return out
    t = np.asarray(wt.get('thicknesses', []))
    indices = np.asarray(wt.get('sample_face_indices', []), dtype=int)
    if len(indices) != len(t):
        out['reason'] = '재측정할 표본 면 인덱스가 없습니다.'
        return out
    candidates = np.unique(indices[t < threshold])
    out['candidate_faces'] = len(candidates)
    if not len(candidates):
        return out
    selected = candidates[np.linspace(0, len(candidates)-1, min(len(candidates), max_faces)).astype(int)]
    out.update(checked_faces=len(selected), budget_limited=len(selected) < len(candidates))
    bary = np.array([[0.6, 0.2, 0.2], [0.2, 0.6, 0.2], [0.2, 0.2, 0.6]])
    points = np.einsum('ij,njk->nik', bary, mesh.triangles[selected]).reshape((-1, 3))
    source = np.repeat(selected, 3)
    normals = mesh.face_normals[source]
    eps = wt.get('ray_epsilon', max(1e-5, 1e-5 * float(max(mesh.extents))))
    valid = np.zeros(len(points), dtype=bool)
    try:
        loc, rays, targets = mesh.ray.intersects_location(points - normals*eps, -normals, multiple_hits=False)
        distances = np.linalg.norm(loc - points[rays], axis=1)
        opposing = -np.einsum('ij,ij->i', normals[rays], mesh.face_normals[targets]) >= 0.85
        shared_vertex = np.any(mesh.faces[source[rays]][:, :, None] == mesh.faces[targets][:, None, :], axis=(1, 2))
        valid[rays] = (distances > eps*10) & (distances < threshold) & opposing & ~shared_vertex
    except Exception as exc:
        out['reason'] = f'국소 재측정 실패: {exc}'
        return out
    grouped = points.reshape((-1, 3, 3))
    span = np.maximum.reduce([np.linalg.norm(grouped[:, i]-grouped[:, j], axis=1)
                              for i, j in ((0, 1), (0, 2), (1, 2))])
    confirmed = valid.reshape((-1, 3)).all(axis=1) & (span >= max(threshold/4, eps*10))
    out['confirmed_face_indices'] = selected[confirmed].tolist()
    out['verified_regions'] = int(confirmed.sum())
    return out


def wall_evidence(wt, threshold):
    """No suspect measurement can silently turn into a passing wall gate."""
    out = dict(available=bool(wt.get('available')), threshold_mm=float(threshold),
               classification='unknown', below_count=0,
               minimum_mm=wt.get('min_thickness'), percentile_5_mm=wt.get('p_thickness'),
               sampled_face_indices=[])
    if not wt.get('available'):
        out['reason'] = wt.get('reason', '측정 불가')
        return out
    t = np.asarray(wt.get('thicknesses', [wt['min_thickness']]))
    out['below_count'] = int(np.count_nonzero(t < threshold))
    indices = np.asarray(wt.get('sample_face_indices', []), dtype=int)
    if len(indices) == len(t):
        out['sampled_face_indices'] = indices[t < threshold].tolist()
    verification = wt.get('verification', {})
    out['verification'] = verification
    out['discarded_near_hits'] = wt.get('discarded_near_hits', 0)
    if verification.get('verified_regions', 0) > 0 and out['below_count']:
        out['classification'] = 'corroborated_thin_region'
    elif out['below_count'] or out['discarded_near_hits']:
        out['classification'] = 'suspect_thin_region'
    else:
        out['classification'] = 'not_detected_in_samples'
    return out


# ──────────────────────────────────────────────────────────────
# 종횡비 / 빌드 볼륨
# ──────────────────────────────────────────────────────────────
def compute_aspect_ratio(mesh_bf: trimesh.Trimesh) -> dict:
    """빌드 좌표계 기준 높이 / 최소 수평 폭.

    v1은 build_direction 인자를 아예 받지 않아 방향을 바꿔도 값이 고정이었고,
    폭으로 max(x, y)를 써서 얇은 판이 오히려 좋은 점수를 받았다.
    넘어짐/휨 위험이 목적이면 최소 수평 치수를 봐야 한다.
    """
    ex = mesh_bf.extents
    if ex is None or len(ex) < 3 or len(mesh_bf.faces) == 0:
        return {'aspect_ratio': 0.0, 'height': 0.0, 'width': 0.0, 'footprint': (0.0, 0.0)}
    height = float(ex[2])
    width = float(min(ex[0], ex[1]))
    return {'aspect_ratio': height / width if width > EPS else float('inf'),
            'height': height, 'width': width,
            'footprint': (float(ex[0]), float(ex[1]))}


def compute_build_volume_fit(mesh_bf: trimesh.Trimesh, printer_dims) -> dict:
    """빌드 좌표계 기준 바운딩박스와 프린터 볼륨 비교.

    v1은 방향을 무시하고 원본 바운딩박스만 봤다. 세우면 들어가고 눕히면
    안 들어가는 경우를 구분하지 못한다.
    수평 두 축은 90도 회전 배치를 허용한다.
    """
    dims = np.asarray(printer_dims, dtype=float)
    if dims.shape != (3,) or not np.isfinite(dims).all() or np.any(dims <= 0):
        raise ValueError("프린터 크기는 유한한 양수 3개여야 합니다.")
    size = np.asarray(mesh_bf.extents if len(mesh_bf.faces) else [0, 0, 0], dtype=float)
    candidates = [(0, size), (90, size[[1, 0, 2]])]
    rotation, placed = min(candidates, key=lambda x: float(np.max(x[1] / dims)))
    margins = dims - placed
    fits = bool(len(mesh_bf.faces) and np.all(margins >= -1e-9))
    return {'fits': fits, 'part_size': placed.tolist(),
            'unrotated_part_size': size.tolist(), 'placement_rotation_deg': rotation,
            'printer_size': dims.tolist(), 'margin': margins.tolist(),
            'min_margin_ratio': float(np.min(margins / dims)),
            'utilization': float(np.max(placed / dims)),
            'scope': '0/90 degree in-plane AABB; excludes supports, raft and clearances'}


# ──────────────────────────────────────────────────────────────
# 최소 특징 크기 (옵션)
# ──────────────────────────────────────────────────────────────
def compute_min_feature_size(mesh: trimesh.Trimesh, threshold: float,
                             enabled: bool = False,
                             max_voxels: int = 3_000_000) -> dict:
    """복셀 모폴로지 오프닝 기반 미세 특징 검사.

    v1은 '메시 최단 모서리 길이'를 최소 특징 크기로 썼다. 그 값은 부품 설계가
    아니라 CAD 내보내기 시 코드 공차(테셀레이션 해상도)를 측정한다.
    같은 원통을 분할 수만 바꿔 내보내면 값이 한 자릿수씩 달라진다.

    여기서는 지름 threshold 인 구로 오프닝했을 때 사라지는 부피 비율을 잰다.
    사라진 비율이 클수록 임계값보다 얇은 특징이 많다는 뜻이고,
    테셀레이션 해상도와 무관하다.

    비용이 커서 기본은 비활성(N/A)이다. 활성화하면 규칙에 가중치가 배분된다.
    """
    if not enabled:
        return {'available': False,
                'reason': '기본 비활성 (복셀 검사 비용). UI에서 켤 수 있습니다.'}
    try:
        from scipy import ndimage
    except ImportError:
        return {'available': False, 'reason': 'scipy 미설치'}

    if not np.isfinite(threshold) or threshold <= 0:
        return {'available': False, 'reason': '양수 특징 크기 기준이 필요합니다.'}
    pitch = threshold / 3.0
    est = np.prod(np.asarray(mesh.extents) / pitch + 3)
    if est > max_voxels:
        return {'available': False,
                'reason': '요청 특징 크기를 분해할 복셀 해상도가 메모리 한도를 초과합니다. 값을 조악하게 바꾸어 평가하지 않습니다.'}

    try:
        grid = mesh.voxelized(pitch=pitch).fill().matrix
    except Exception as e:
        return {'available': False, 'reason': f'복셀화 실패: {e}'}

    total = int(grid.sum())
    if total == 0:
        return {'available': False, 'reason': '복셀 격자가 비었습니다.'}

    r = max(1, int(round(threshold / 2.0 / pitch)))
    zz, yy, xx = np.mgrid[-r:r + 1, -r:r + 1, -r:r + 1]
    ball = (zz ** 2 + yy ** 2 + xx ** 2) <= r ** 2
    opened = ndimage.binary_opening(grid, structure=ball)
    lost = 1.0 - opened.sum() / total
    return {'available': True, 'lost_volume_ratio': float(lost),
            'pitch': float(pitch), 'probe_diameter': float(2 * r * pitch),
            'voxels': total}


def compute_hole_analysis(mesh: trimesh.Trimesh) -> dict:
    """수평 구멍 분석.

    v1은 항상 빈 리스트를 돌려주면서도 규칙 점수는 100점을 줬다.
    즉 모든 부품이 가중치만큼 공짜 점수를 받았다.
    현재 구현에는 메시 구멍 특징 인식기가 없어 N/A로 명시하고,
    가중치를 다른 규칙에 재분배한다. STEP/B-rep 도입 시 복구한다.
    """
    return {'available': False,
            'reason': '현재 버전에는 STL 구멍 특징 인식기가 구현되어 있지 않습니다. '
                      'STEP/B-rep 도입 시 활성화됩니다.'}


# ──────────────────────────────────────────────────────────────
# 통합
# ──────────────────────────────────────────────────────────────
def run_full_analysis(mesh, build_direction=(0, 0, 1), critical_angle=45.0,
                      support_density=0.165, support_wall=0.2715,
                      bridge_limit=0.0, printer_dims=(250, 250, 250),
                      min_feature_threshold=0.8, min_feature_enabled=False,
                      thickness_gradient_enabled=False,
                      wall_samples=2000) -> dict:
    mbf = to_build_frame(mesh, build_direction)
    return {
        'build_frame_mesh': mbf,
        'overhang': compute_overhang(mbf, critical_angle, bridge_limit=bridge_limit),
        'support_volume': compute_support_volume(mbf, critical_angle,
                                                support_density, support_wall,
                                                bridge_limit),
        'wall_thickness': compute_wall_thickness(mesh, n_samples=wall_samples),
        'aspect_ratio': compute_aspect_ratio(mbf),
        'build_volume_fit': compute_build_volume_fit(mbf, printer_dims),
        'min_feature_size': compute_min_feature_size(mesh, min_feature_threshold,
                                                     enabled=min_feature_enabled),
        'hole_analysis': compute_hole_analysis(mesh),
    }


def support_regions(mesh_bf: trimesh.Trimesh, critical_angle: float,
                    bridge_limit: float = 0.0) -> list:
    """오버행 면을 '연결된 지지 영역' 단위로 묶는다.

    지지구조는 삼각형 하나마다 세우는 것이 아니라 이어진 영역마다 기둥 하나로
    세워진다. 따라서 기둥의 벽 면적은 삼각형 개수가 아니라 영역의 둘레로
    결정된다. 삼각형 단위로 Σ√A 를 쓰면 같은 형상이라도 메시를 잘게 쪼갤수록
    값이 커진다(4분할마다 2배). 이는 테셀레이션 해상도를 측정하는 것이지
    형상을 측정하는 것이 아니다.
    """
    oh = compute_overhang(mesh_bf, critical_angle, bridge_limit=bridge_limit)
    idx = np.asarray(oh['overhang_face_indices'], dtype=int)
    if len(idx) == 0:
        return []

    # 오버행 면들끼리만 인접 그래프를 만들어 연결 성분을 찾는다
    mask = np.zeros(len(mesh_bf.faces), dtype=bool)
    mask[idx] = True
    adj = mesh_bf.face_adjacency
    sel = adj[mask[adj[:, 0]] & mask[adj[:, 1]]] if len(adj) else np.empty((0, 2), int)
    try:
        comps = trimesh.graph.connected_components(sel, nodes=idx, min_len=1)
    except Exception as exc:
        raise RuntimeError('지지 영역 연결 성분 분리에 실패했습니다.') from exc

    zmin = float(mesh_bf.vertices[:, 2].min())
    eps = max(1e-4, 1e-4 * float(mesh_bf.extents[2]))
    fue = mesh_bf.faces_unique_edges          # (F, 3) -> edges_unique 인덱스
    ev = mesh_bf.vertices[mesh_bf.edges_unique]

    out = []
    for comp in comps:
        comp = np.asarray(comp, dtype=int)
        if len(comp) == 0:
            continue
        areas = mesh_bf.area_faces[comp]
        normals = mesh_bf.face_normals[comp]
        proj = areas * np.abs(normals[:, 2])
        centers = mesh_bf.triangles_center[comp]

        # 영역별 높이: 아래 교차면이 없으면 플레이트까지. 계산 실패는 위로 전달한다.
        origins = centers.copy(); origins[:, 2] -= eps
        dirs = np.tile([0.0, 0.0, -1.0], (len(comp), 1))
        heights = centers[:, 2] - zmin
        try:
            locs, ray_idx, _ = mesh_bf.ray.intersects_location(
                ray_origins=origins, ray_directions=dirs, multiple_hits=False)
            for r_, h_ in zip(ray_idx, centers[ray_idx, 2] - np.asarray(locs).reshape(-1, 3)[:, 2]):
                if h_ > eps:
                    heights[r_] = min(heights[r_], h_)
        except Exception as exc:
            raise RuntimeError("지지 높이 레이캐스팅 실패") from exc
        heights = np.maximum(heights, 0.0)

        A = float(proj.sum())
        h_mean = float(np.average(heights, weights=proj) if A > EPS else heights.mean())

        # 영역 경계 둘레: 이 영역 안에서 한 번만 등장하는 엣지
        e = fue[comp].ravel()
        uniq, cnt = np.unique(e, return_counts=True)
        bnd = uniq[cnt == 1]
        if len(bnd):
            seg = ev[bnd]
            d = seg[:, 1, :] - seg[:, 0, :]
            perim = float(np.linalg.norm(d[:, :2], axis=1).sum())   # 수평 투영 둘레
        else:
            perim = 0.0

        out.append({'proj_area': A, 'mean_height': h_mean, 'perimeter': perim,
                    'n_faces': int(len(comp))})
    return out


def support_terms(mesh_bf: trimesh.Trimesh, critical_angle: float,
                  bridge_limit: float = 0.0) -> dict:
    """지지구조물 부피를 물리적으로 분해한 항들을 돌려준다.

    실제 지지 기둥은 세 성분으로 나뉜다.

        부피 항   Σ (A · h)        내부 격자 채움
        둘레 항   Σ (P · h)        기둥 바깥 벽. P 는 '연결된 지지 영역'의 둘레
        면적 항   Σ A              모델과 닿는 인터페이스 층

    연결 성분 단위로 경계를 계산한다. 면 중심 높이의 근사, 임계각과 STL
    정밀도 때문에 테셀레이션 영향이 완전히 제거되는 것은 아니다.
    """
    if len(mesh_bf.faces) == 0:
        return {'vol_term': 0.0, 'perim_term': 0.0, 'area_term': 0.0,
                'n_regions': 0, 'n_faces': 0, 'part_volume': 0.0}
    regs = support_regions(mesh_bf, critical_angle, bridge_limit)
    if not regs:
        return {'vol_term': 0.0, 'perim_term': 0.0, 'area_term': 0.0,
                'n_regions': 0, 'n_faces': 0,
                'part_volume': float(abs(mesh_bf.volume))}
    return {
        'vol_term':   float(sum(r['proj_area'] * r['mean_height'] for r in regs)),
        'perim_term': float(sum(r['perimeter'] * r['mean_height'] for r in regs)),
        'area_term':  float(sum(r['proj_area'] for r in regs)),
        'n_regions':  len(regs),
        'n_faces':    int(sum(r['n_faces'] for r in regs)),
        'part_volume': float(abs(mesh_bf.volume)),
    }


# ──────────────────────────────────────────────────────────────
# 갇힌 체적 (trapped volume) — 표준 7.4
# ──────────────────────────────────────────────────────────────
def compute_trapped_volume(mesh: trimesh.Trimesh) -> dict:
    """부품 내부에 밀폐된 공동이 있는지 판정한다.

    표준 7.4 는 미사용 적층재료가 구성 요소 안에 갇히면 제품이 과도한 무게를
    갖게 되고, 분말이나 액체 재료의 경우 새어 나올 수 있다는 점을 설계자
    주의사항으로 든다. 분말 베드 융해에서는 갇힌 분말을 빼낼 수 없고,
    액조 광경화에서는 레진이 그대로 경화되어 남는다.

    판정 방법
    --------
    닫힌 메시를 껍질 단위로 분리하면, 부호 있는 부피가 음수인 껍질이
    내부 공동이다. 법선이 바깥을 향하도록 정렬된 메시에서 공동의 껍질은
    솔리드 기준으로 안쪽을 향하기 때문이다.
    배출 구멍이 있으면 공동이 외부와 이어져 껍질이 하나로 합쳐지므로
    자동으로 구분된다.

    임계값에 대하여
    --------------
    이 규칙은 '갇혔는가' 라는 이진 사실을 묻는다. 따라서 '몇 mm³ 이상이면
    문제인가' 같은 임의 임계값이 필요하지 않다. 갇혀 있으면 재료를 뺄 수
    없고, 그것으로 판정이 끝난다. 다른 규칙들과 달리 근거를 개발자가
    정하지 않아도 되는 몇 안 되는 항목이다.
    """
    if not mesh.is_watertight:
        return {'available': False,
                'reason': '닫힌 메시가 아니어서 내부 공동을 판정할 수 없습니다.'}
    try:
        parts = mesh.split(only_watertight=False, repair=False)
    except Exception as e:
        return {'available': False, 'reason': f'껍질 분리 실패: {e}'}

    if len(parts) <= 1:
        return {'available': True, 'has_trapped': False, 'trapped_volume': 0.0,
                'n_cavities': 0, 'solid_volume': float(abs(mesh.volume)),
                'trapped_ratio': 0.0, 'cavity_sizes': []}

    vols = [float(p.volume) for p in parts]
    cavities = [(-v, p) for v, p in zip(vols, parts) if v < 0]
    solid = float(sum(vols))  # net material volume, excluding cavities
    trapped = float(sum(v for v, _ in cavities))
    sizes = [{'volume': v,
              'extents': [round(float(x), 2) for x in p.extents]}
             for v, p in sorted(cavities, key=lambda x: -x[0])[:10]]
    return {
        'available': True,
        'has_trapped': bool(cavities),
        'trapped_volume': trapped,
        'n_cavities': len(cavities),
        'solid_volume': solid,
        'trapped_ratio': trapped / solid if solid > EPS else 0.0,
        'cavity_sizes': sizes,
    }


# ──────────────────────────────────────────────────────────────
# 계단 효과 (staircase) — 표준 6.6.3 표면 거칠기, 7.5 계단화
# ──────────────────────────────────────────────────────────────
def compute_staircase(mesh_bf: trimesh.Trimesh, layer_height: float,
                      horiz_tol: float = 1e-6) -> dict:
    """층 적층으로 생기는 계단 높이를 계산한다. 입력은 빌드 좌표계 메시.

    유도
    ----
    수평면에서 각도 a 로 기울어진 면을 두께 t 인 층으로 쌓으면, 한 층마다
    수직으로 t, 수평으로 t/tan(a) 만큼 계단이 생긴다. 이 계단의 직각 꼭짓점에서
    이상적인 면까지의 수직 거리가 계단 높이이며, 직각삼각형의 빗변에 대한
    높이이므로

        cusp = (t · t/tan a) / sqrt(t² + (t/tan a)²) = t · cos(a)

    이다. 면 법선과 빌드 방향의 내적이 cos(a) 이므로 cusp = t · |n·b| 가 된다.

    경계 조건
    --------
    a = 90도(수직벽)  -> cusp = 0. 계단이 생기지 않는다.
    a = 0도(수평면)   -> 식의 극한은 t 이지만 실제로는 계단이 없다. 한 층이
                        그대로 면을 이루기 때문이다. 따라서 별도로 0 처리한다.
    완만한 경사면일수록 계단 하나가 커진다. 얕은 돔에서 계단이 두드러지는
    현상과 일치한다.

    이 값은 임의 상수 없이 층 두께와 형상만으로 정해진다. 층 두께는 장비
    설정값이므로, 계단 높이 자체는 판단이 개입하지 않는 물리량이다.
    """
    if layer_height <= 0:
        return {'available': False, 'reason': '층 두께가 지정되지 않았습니다.'}
    n = mesh_bf.face_normals
    areas = mesh_bf.area_faces
    total = float(areas.sum())
    if total <= EPS:
        return {'available': False, 'reason': '표면적이 0입니다.'}

    c = np.abs(np.clip(n[:, 2], -1.0, 1.0))       # |n·b| = cos(경사각)
    cusp = layer_height * c
    is_horizontal = c >= 1.0 - horiz_tol           # 수평면: 계단 없음
    cusp[is_horizontal] = 0.0

    w = areas / total
    mean_cusp = float(np.sum(cusp * w))
    return {
        'available': True,
        'mean_cusp': mean_cusp,                    # 면적 가중 평균 계단 높이 [mm]
        'max_cusp': float(cusp.max()),
        'cusp_ratio': mean_cusp / layer_height,    # 층 두께 대비 (0~1)
        'layer_height': float(layer_height),
        'sloped_area_ratio': float(areas[(~is_horizontal) & (c > horiz_tol)].sum() / total),
        'worst_face_indices': np.argsort(-cusp)[:200].tolist(),
    }


# ──────────────────────────────────────────────────────────────
# 형상 간 최소 간격 — 표준 6.6.6
# ──────────────────────────────────────────────────────────────
def compute_feature_gap(mesh: trimesh.Trimesh, n_samples: int = 2000) -> dict:
    """형상 사이의 좁은 틈을 찾는다.

    벽두께는 면에서 '안쪽'으로 레이를 쏴 반대쪽 벽까지를 재지만, 형상 간격은
    같은 레이를 '바깥쪽'으로 쏴서 마주 보는 다른 면까지의 거리를 잰다.
    볼록한 면에서 나간 레이는 아무것도 만나지 않으므로 간격이 없다고 판정되고,
    슬롯이나 두 형상 사이에서 나간 레이는 맞은편 면을 맞히므로 그 거리가
    간격이 된다.

    간격이 공정 한계보다 좁으면 두 형상이 조형 중에 붙어버린다. 표준 6.6.6 은
    이를 최소 형상 공간으로 다룬다.

    표본 추출은 벽두께와 같은 이유로 면적 가중과 면 균등을 병행한다.
    """
    areas = mesh.area_faces
    if len(areas) == 0 or areas.sum() <= EPS:
        return {'available': False, 'reason': '면이 없습니다.'}

    n = adaptive_samples(mesh, int(n_samples))
    nf = len(areas)
    if nf <= n:
        idx = np.arange(nf)
    else:
        cum = np.cumsum(areas)
        n_area = max(1, n // 2)
        tgt = (np.arange(n_area) + 0.5) * (cum[-1] / n_area)
        idx_area = np.clip(np.searchsorted(cum, tgt), 0, nf - 1)
        n_rest = max(1, n - n_area)
        idx_uni = np.linspace(0, nf - 1, n_rest // 2 + 1).astype(int)
        idx_small = np.argsort(areas)[:max(1, n_rest - len(idx_uni))]
        idx = np.unique(np.concatenate([idx_area, idx_uni, idx_small]))

    centers = mesh.triangles_center[idx]
    normals = mesh.face_normals[idx]
    eps = max(1e-5, 1e-5 * float(np.max(mesh.extents)))
    origins = centers + normals * eps            # 바깥으로 밀어낸 뒤
    dirs = normals                               # 바깥 방향으로 발사

    try:
        locs, ray_idx, _ = mesh.ray.intersects_location(
            ray_origins=origins, ray_directions=dirs, multiple_hits=False)
    except Exception as e:
        return {'available': False, 'reason': f'레이캐스팅 실패: {e}'}

    if len(ray_idx) == 0:
        return {'available': True, 'has_gap': False, 'min_gap': float('inf'),
                'samples': int(len(idx)), 'gap_count': 0, 'gaps': np.array([])}

    g = np.linalg.norm(locs - centers[ray_idx], axis=1)
    g = g[g > eps * 10]
    if len(g) == 0:
        return {'available': True, 'has_gap': False, 'min_gap': float('inf'),
                'samples': int(len(idx)), 'gap_count': 0, 'gaps': np.array([])}
    return {
        'available': True, 'has_gap': True,
        'min_gap': float(np.min(g)),
        'p_gap': float(np.percentile(g, 5.0)),
        'median_gap': float(np.median(g)),
        'gap_count': int(len(g)),
        'samples': int(len(idx)),
        'gaps': g,
    }


# ──────────────────────────────────────────────────────────────
# 브리지 스팬 — 표준 6.6.9
# ──────────────────────────────────────────────────────────────
def _region_span(mesh_bf, faces):
    """연결 영역의 수평 최소 폭을 구한다.

    영역 정점들을 수평면에 투영한 뒤 주성분 분석으로 주축을 찾고,
    두 주축 방향 폭 중 작은 값을 폭으로 본다. 축 정렬 바운딩박스만 쓰면
    비스듬히 놓인 다리의 폭이 과대평가된다.
    """
    v = mesh_bf.vertices[np.unique(mesh_bf.faces[faces].ravel())][:, :2]
    if len(v) < 3:
        return 0.0
    c = v - v.mean(axis=0)
    try:
        _, _, vt = np.linalg.svd(c, full_matrices=False)
        proj = c @ vt.T
    except np.linalg.LinAlgError:
        proj = c
    ext = proj.max(axis=0) - proj.min(axis=0)
    return float(np.min(ext))


def _is_bridgeable(mesh_bf, faces, bridge_limit, flat_tol=0.95, anchor_frac=0.5):
    """이 오버행 영역이 지지 없이 건너뛸 수 있는 다리인지 판정한다.

    세 조건을 모두 만족해야 한다.

      1. 거의 수평일 것. 경사면은 다리가 아니라 오버행이다.
      2. 최소 폭이 공정별 브리지 한계 이하일 것.
      3. 양쪽이 고정되어 있을 것. 경계 바깥에 재료가 있어야 다리가 성립한다.
         외팔보는 폭이 좁아도 건너뛸 수 없다.

    3번은 영역 경계 바깥쪽 점이 솔리드 안에 있는지로 확인한다. 이 판정이
    없으면 좁은 외팔보를 다리로 오인해 지지가 필요한데도 불필요하다고
    보고하게 된다.
    """
    # Conservative recognition: a flat rectangular underside with support
    # immediately BELOW both ends along the SAME candidate span direction.
    # Irregular outlines remain support-requiring until a chord tracer exists.
    if bridge_limit <= 0 or len(faces) == 0:
        return False, 0.0, 0.0
    from scipy.spatial import ConvexHull
    verts = mesh_bf.vertices[np.unique(mesh_bf.faces[faces].ravel())]
    if np.ptp(verts[:, 2]) > 1e-6:
        return False, 0.0, 0.0
    try:
        hull = ConvexHull(verts[:, :2])
        poly = verts[hull.vertices, :2]
    except Exception:
        return False, 0.0, 0.0
    if len(poly) != 4:
        return False, 0.0, 0.0
    area = float(mesh_bf.area_faces[faces].sum())
    if not np.isclose(area, hull.volume, rtol=1e-5):
        return False, 0.0, 0.0
    edge = np.roll(poly, -1, axis=0) - poly
    lens = np.linalg.norm(edge, axis=1)
    axes = edge / lens[:, None]
    if not np.all(np.abs(np.sum(axes * np.roll(axes, 1, axis=0), axis=1)) < 1e-6):
        return False, 0.0, 0.0
    center = poly.mean(axis=0)
    for j in (0, 1):
        direction = axes[j]
        across = axes[1-j]
        span, width = lens[j], lens[1-j]
        if span > bridge_limit + 1e-9:
            continue
        step = min(0.02, span * 0.01)
        probes = []
        for fraction in np.linspace(-0.4, 0.4, 5):
            for sign in (-1, 1):
                xy = center + fraction * width * across + sign * (span/2 + step) * direction
                probes.append([xy[0], xy[1], verts[0, 2] - step])
        try:
            paired = mesh_bf.contains(np.asarray(probes)).reshape(-1, 2).all(axis=1)
        except Exception:
            return False, float(span), 0.0
        if paired.all():
            return True, float(span), 1.0
    return False, float(min(lens)), 0.0


# ──────────────────────────────────────────────────────────────
# 갑작스런 두께 변화 — 표준 7.3
# ──────────────────────────────────────────────────────────────
def compute_thickness_gradient(mesh: trimesh.Trimesh, n_samples: int = 3000,
                               radius_factor: float = 3.0,
                               enabled: bool = False) -> dict:
    """이웃한 부위 사이의 국소 두께 비를 구한다. 표준 7.3.

    표준 7.3 은 열을 쓰는 공정에서 갑작스런 두께 변화가 형상을 왜곡하고
    정확도를 낮춘다고 지적한다. 두꺼운 부위가 열을 더 오래 머금기 때문이며,
    사출 성형이나 다이캐스팅의 문제와 같은 원리다.

    측정 방법
    --------
    면적에 비례해 표면 위 점을 균등 추출하고(면 중심을 쓰면 표본 밀도가
    테셀레이션에 좌우된다), 각 점에서 법선 반대 방향으로 레이를 쏴 관통
    거리를 잰다. 그 값을 작은 반경 안의 최솟값으로 평활화해 국소 두께로
    삼은 뒤, 더 넓은 반경 안에서의 최대·최소 비를 구한다.

    이 지표의 한계 — 반드시 함께 읽을 것
    ----------------------------------
    레이캐스팅 값은 발사 방향에 의존한다. 두께 2mm 판의 옆면에서 쏜 레이는
    판을 가로질러 40mm 를 잰다. 평활화가 이런 값을 상당 부분 걷어내지만
    완전하지는 않다. 따라서 이 지표는

        · 균일한 부품에서 1.0 이 나오는지          -> 검증됨
        · 두께가 급변하는 부품에서 1.0 을 넘는지    -> 검증됨
        · 메시 해상도에 의존하지 않는지            -> 검증됨
        · 비의 '크기' 가 실제 두께 비와 일치하는지  -> 검증되지 않음

    즉 '급변이 있는가' 를 가리는 탐지기로는 쓸 수 있으나, '몇 배인가' 를
    재는 계측기로는 쓸 수 없다.

    더구나 단순 솔리드에서 오탐이 난다. 40x30x20 직육면체는 두께가 급변하지
    않지만, 세 방향의 관통 거리가 20/30/40mm 라서 비 2.0 이 보고된다. 이는
    형상의 문제가 아니라 측정 방식의 한계다. 이런 오탐이 정상 부품의 점수를
    깎는 것은 받아들일 수 없으므로 기본 비활성으로 두고, 사용자가 명시적으로
    켤 때만 점수에 반영한다. 정확한 국소 두께장은 내접구 전파 알고리즘이
    필요하며 계산 비용이 크다. B-rep 도입 시 정확히 구할 수 있다.
    """
    if not enabled:
        return {'available': False,
                'reason': ('기본 비활성. 단순 솔리드에서 오탐이 나온다. '
                           '40x30x20 직육면체는 두께 급변이 없으나 측정 방향에 따라 '
                           '20/30/40mm 가 나와 비 2.0 으로 보고된다. '
                           'UI 에서 켤 수 있으며, 켜면 가중치가 배분된다.')}
    if len(mesh.faces) == 0 or float(mesh.area) <= EPS:
        return {'available': False, 'reason': '면이 없습니다.'}
    try:
        from scipy.spatial import cKDTree
    except ImportError:
        return {'available': False, 'reason': 'scipy 미설치'}

    # 표본 수는 줄이지 않는다. 이 지표는 공간 밀도가 낮아지면 국소 두께
    # 평활화가 실패해 균일한 부품에서도 큰 값이 나온다(2mm 판에서 30배).
    # 대신 면이 많은 메시는 레이캐스팅 비용을 줄이기 위해 단순화한 대리
    # 메시에서 거리를 잰다. 두께는 저해상도 근사로도 충분히 보존된다.
    #   비용 상한: 면 수가 매우 많으면 레이캐스팅이 급격히 느려지고 메모리도
    #   커진다. 이 지표는 급변 유무를 가리는 보조 지표이므로, 상한을 넘으면
    #   계산을 포기하고 N/A 로 돌려준다. 값을 못 내는 것이 오래 붙잡고 있거나
    #   메모리로 죽는 것보다 낫다.
    MAX_FACES = 60000
    if len(mesh.faces) > MAX_FACES:
        return {'available': False,
                'reason': (f'면이 {len(mesh.faces):,}개로 상한 {MAX_FACES:,}개를 넘어 '
                           f'두께 변화 분석을 건너뜁니다. 이 규칙은 N/A 로 처리되고 '
                           f'가중치는 다른 규칙에 재분배됩니다.')}
    n = int(min(max(n_samples, 500), 6000))
    ray_mesh = mesh
    try:
        pts, fidx = trimesh.sample.sample_surface(mesh, n, seed=0)
    except TypeError:
        pts, fidx = trimesh.sample.sample_surface(mesh, n)
    except Exception as e:
        return {'available': False, 'reason': f'표면 표본 추출 실패: {e}'}

    normals = mesh.face_normals[fidx]
    eps = max(1e-5, 1e-5 * float(np.max(mesh.extents)))
    try:
        locs, ray_idx, _ = ray_mesh.ray.intersects_location(
            ray_origins=pts - normals * eps, ray_directions=-normals,
            multiple_hits=False)
    except Exception as e:
        return {'available': False, 'reason': f'레이캐스팅 실패: {e}'}
    if len(ray_idx) < 20:
        return {'available': False, 'reason': f'유효 표본이 {len(ray_idx)}개뿐입니다.'}

    t = np.linalg.norm(locs - pts[ray_idx], axis=1)
    keep = t > eps * 10
    t, P = t[keep], pts[ray_idx][keep]
    if len(t) < 20:
        return {'available': False, 'reason': f'유효 표본이 {len(t)}개뿐입니다.'}

    # 이웃 탐색은 반경이 아니라 '거리 상한이 있는 k-최근접' 으로 한다.
    #   반경만 쓰면 두꺼운 부품에서 반경이 부품 크기만 해져 모든 점이 서로
    #   이웃이 되고, 표본 3000개면 900만 쌍을 돌게 된다. 실제로 반지름 30mm
    #   구체에서 이 함수 하나가 11초를 썼다. k 를 고정하면 비용이 O(n log n)
    #   으로 묶이면서도 국소성은 유지된다.
    K = 24
    tree = cKDTree(P)
    r_local = max(float(np.percentile(t, 25)), 1e-6)
    k1 = min(K, len(t))
    d1, i1 = tree.query(P, k=k1, distance_upper_bound=r_local)
    d1 = np.atleast_2d(d1); i1 = np.atleast_2d(i1)
    valid1 = np.isfinite(d1) & (i1 < len(t))
    tn = np.where(valid1, t[np.clip(i1, 0, len(t) - 1)], np.inf)
    t_local = np.minimum(tn.min(axis=1), t)

    radius = float(radius_factor * r_local)
    k2 = min(K, len(t))
    d2, i2 = tree.query(P, k=k2, distance_upper_bound=radius)
    d2 = np.atleast_2d(d2); i2 = np.atleast_2d(i2)
    valid2 = np.isfinite(d2) & (i2 < len(t))
    tl = t_local[np.clip(i2, 0, len(t) - 1)]
    hi = np.where(valid2, tl, -np.inf).max(axis=1)
    lo = np.where(valid2, tl, np.inf).min(axis=1)
    enough = valid2.sum(axis=1) >= 3
    ratios = np.where(enough & np.isfinite(hi) & np.isfinite(lo),
                      hi / np.maximum(lo, 1e-9), 1.0)

    order = np.argsort(-ratios)
    return {
        'available': True,
        'max_ratio': float(ratios.max()),
        'p95_ratio': float(np.percentile(ratios, 95)),
        'median_ratio': float(np.median(ratios)),
        'radius': radius, 'local_radius': r_local,
        'samples': int(len(t)),
        'magnitude_is_approximate': True,
        'worst_points': P[order[:50]].tolist(),
    }
