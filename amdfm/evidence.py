"""Primary-source registry. Numeric screening settings are separate from sources."""
SOURCES = {
    "NIST_GAUSS": dict(title="NIST DLMF §3.5(v) — Gauss Quadrature",
        url="https://dlmf.nist.gov/3.5.v",kind="numerical_reference",locator="Equations 3.5.19 and 3.5.21: Gaussian error and Gauss–Legendre rule",
        use="형상 변화 구간의 2점 Gauss 적분 수학 근거. 고정 다면체의 구간별 단면적이 2차식이라는 별도 유도와 수치 검사를 전제로 함. CAD 곡면·실물·표본 최대의 정확성 보증이 아님.",
        access="공식 공개 수학 참조; 2026-09-15 확인"),
    "ISO52910": dict(title="KS D ISO/ASTM 52910:2018 — 적층제조 설계 요구사항·지침·권고",
        url="https://www.iso.org/standard/67289.html", kind="standard_fulltext_capture", locator="국내 2019 제정판; §§6.6, 6.9, 7; 제공 PDF 33쪽",
        local_path="KS D ISO.ASTM 52910.pdf",
        use="검토 항목과 설계 정보 전달의 근거. 공통 수치 임계값의 근거가 아님.",
        access="2026-09-21 사용자 제공 KS 전페이지 캡처 본문·참고문헌·해설 확인. 일부 워터마크·흐림이 남아 정확한 인용은 원페이지 대조 필요; 링크는 대응 ISO 판의 공식 안내"),
    "ISO52902": dict(title="ISO/ASTM 52902:2023 — Test artefacts; geometric capability assessment",
        url="https://www.iso.org/standard/79683.html", kind="standard_scope", locator="Scope",
        use="장비별 시험물과 측정에 의한 검증. 자체 CAD 예제는 표준 인증 시험물이 아님.", access="공식 범위·판 정보; 2023 전문 미확보"),
    "KS52902_2019": dict(title="KS D ISO/ASTM 52902:2019 — 적층제조 시스템의 기하학적 성능 평가용 시험물",
        url=None, kind="standard_fulltext_capture", locator="국내 2021 제정판; 본문 §§1–7·부속서 A–D; 제공 PDF 45쪽",
        local_path="KS D ISO,ASTM 52902.pdf",
        use="별도 제조 조건에서 시험물을 제작·측정하여 장비 성능을 평가할 근거. 자체 CAD의 계산 검산은 이 실물 평가나 인증을 대체하지 않음.",
        access="2026-09-21 KS 2019 기반판 전페이지 캡처 확인. PDF 44쪽 해설 하단 일부 잘림·워터마크 있음. ISO 2023 전문 확보로 간주하지 않음"),
    "KS52901_2017": dict(title="KS D ISO/ASTM 52901:2017 — 적층제조 부품 구매 요구사항",
        url=None, kind="standard_fulltext_capture", locator="국내 2021 제정판; 구매 정보·요구사항·검사·부속서 A; 제공 PDF 17쪽",
        local_path="KS D ISO ASTM 52901.pdf",
        use="사용 목적·재료·치수·품질·검사와 수락 조건을 고객과 공급자가 합의할 근거. 형상 계산만으로 납품 적합·제조 성공을 판정할 수 없음.",
        access="2026-09-21 KS 전페이지 캡처 본문·부속서·참고문헌·해설 확인; 워터마크가 겹친 문자는 원페이지 재확인 필요"),
    "KS52903_1_2020": dict(title="KS D ISO/ASTM 52903-1:2020 — 플라스틱 재료의 압출 기반 적층제조 — 제1부: 공급재료",
        url=None, kind="standard_fulltext_capture", locator="국내 2023 제정판; 원재료 식별·특성·문서화; 제공 PDF 12쪽",
        local_path="KS D ISO,ASTM 52903-1.pdf",
        use="플라스틱 MEX의 재료 조건과 추적성을 별도로 관리할 근거. 메시만으로 원재료 적합성이나 실제 접합 강도를 확인하지 않음.",
        access="2026-09-21 KS 전페이지 캡처 확인; 타 AM 공정의 재료 합격 기준으로 사용하지 않음"),
    "KS52903_2_2020": dict(title="KS D ISO/ASTM 52903-2:2020 — 플라스틱 재료의 압출 기반 적층제조 — 제2부: 공정 장치",
        url=None, kind="standard_fulltext_capture", locator="국내 2023 제정판; 공정 장비·관리·적격성; 제공 PDF 12쪽",
        local_path="KS D ISO,ASTM 52903-2.pdf",
        use="플라스틱 MEX의 장비·공정 조건을 기록하고 검증할 근거. 기하 검토 완료는 장비 적격성·생산 품질 검증이 아님.",
        access="2026-09-21 KS 전페이지 캡처 확인; 표·주석은 워터마크를 고려해 원페이지와 대조하며 보편 수치 기준으로 전환하지 않음"),
    "ISO52911M": dict(title="ISO/ASTM 52911-1:2019 — Laser-based powder bed fusion of metals",
        url="https://www.iso.org/standard/72951.html", kind="standard_scope", locator="Scope",
        use="금속 PBF 공정 고유의 설계 검토 필요성.", access="공식 공개 범위; 전문 미확보"),
    "ISO52911P": dict(title="ISO/ASTM 52911-2:2019 — Laser-based powder bed fusion of polymers",
        url="https://www.iso.org/standard/72952.html", kind="standard_scope", locator="Scope",
        use="고분자 PBF와 금속 PBF의 설계 조건 분리.", access="공식 공개 범위; 전문 미확보"),
    "MOYLAN2014": dict(title="Moylan et al. (2014), An Additive Manufacturing Test Artifact",
        url="https://nvlpubs.nist.gov/nistpubs/jres/119/jres.119.017.pdf", kind="original_research", locator="Test artifact design and measurement",
        use="알려진 형상과 독립 측정을 이용해 장비의 능력을 확인.", access="공개 논문"),
    "KUIPERS2020": dict(title="Kuipers et al. (2020), Adaptive width control of dense contour-parallel toolpaths",
        url="https://arxiv.org/abs/2004.13497", kind="original_research", locator="Abstract; adaptive bead width framework",
        use="고정 선폭 형태학 검토를 실제 슬라이서 출력 누락 판정과 구분.", access="공개 저자 원고"),
    "PRUSA_ARACHNE": dict(title="PrusaSlicer — Arachne perimeter generator",
        url="https://help.prusa3d.com/article/arachne-perimeter-generator_352769", kind="vendor_documentation", locator="Minimum feature size; minimum perimeter width",
        use="얇은 특징의 생략·확대는 가변 선폭과 슬라이서 설정에 의존.", access="공식 문서"),
    "JIANG2018": dict(title="Jiang, Xu & Stringer (2018), A new support strategy for reducing waste in AM",
        url=None, kind="original_research", locator="저장소 PDF p.5; LITERATURE.md R06",
        use="오버행/브리지 임계값은 장비·재료·냉각·처짐 허용 조건과 함께 정함. 2 mm를 기본 한계로 차용하지 않음.", access="저장소 원문"),
    "STAV2022": dict(title="Stavropoulos et al. (2022), Knowledge-based manufacturability assessment for optimization of AM",
        url="https://doi.org/10.1007/s00170-022-09948-w", kind="original_research", locator="저장소 R07; STEP B-rep method; Table 2",
        use="CAD 특징·공정 지식 연결. 원통면 탐지가 관통홀/제조 성공 보증은 아님.", access="저장소 원문"),
    "KIM2019": dict(title="Kim et al. (2019), A Design for Additive Manufacturing Ontology to Support Manufacturability Analysis",
        url="https://tsapps.nist.gov/publication/get_pdf.cfm?pub_id=925693", kind="original_research", locator="Design features and design/process/material parameters",
        use="특징·재료·공정·설계 규칙의 근거를 구조화.", access="NIST 공개 저널 원고; 2018 학회판과 구분"),
    "FORM4": dict(title="Formlabs — Design specifications for 3D models (Form 4 generation)",
        url="https://formlabs.com/support/Design-specifications-for-3D-models-Form-4-generation/", kind="vendor_experiment", locator="Grey Resin V5, Form 4, 50 µm; drain holes",
        use="장비·수지·층 높이별 가이드. 일반 홀과 배출 홀의 기준을 구분하며 보편 VPP 임계값으로 쓰지 않음.",
        access="공개 제조사 문서; 설계값은 Grey Resin V5·50 µm, 같은 페이지의 공차 시험은 100 µm·별도 후경화 조건"),
    "FORM_ORIENTATION": dict(title="Formlabs — Model orientation best practices for SLA printing",
        url="https://formlabs.com/support/Model-Orientation/", kind="vendor_documentation",
        locator="Tilting a flat surface; Preserving integrity at intersections; Reducing minima; Preventing suction cups",
        use="VPP 방향·신생 성분·컵 형태의 검토 필요성. Form 계열의 탱크 분리 동작을 모든 VPP 장비에 일반화하지 않음.",
        access="공개 제조사 본문; Form 2 와이퍼·Form 3 계열 LFS 기구 설명을 구분"),
    "PAN2017": dict(title="Pan, He, Xu & Feinerman (2017), Study of separation force in constrained surface projection stereolithography",
        url="https://yayuepan.lab.uic.edu/wp-content/uploads/sites/779/2021/01/8edafea83b2e3d9d65896da53bcf9ab108dc.pdf",
        kind="original_research", locator="PDF pp.4–8 (printed pp.355–359), §§2.2–5.2; Eq.(6)",
        use="Bottom-up 층 분리에서 면적·경계 길이·공극의 관련성. A/P는 mm 단위 기하량이며 박리력·성공률이 아님. 점도·속도·간극·필름 조건이 필요함.",
        access="저자 대학 공개 PDF; 자체 bottom-up 투영 장비·PDMS·LS600M/G+ 수지 실험. 원통·강체·일정 점도 가정의 힘 식을 임의 형상에 이식하지 않음"),
    "FUSE_DESIGN": dict(title="Formlabs — Fuse Series SLS Design Guide",
        url="https://formlabs.com/eu/white-papers/fuse-series-sls-design-guide/", kind="vendor_documentation",
        locator="Reference Dimensions; Minimum Drain Hole Diameter; Reducing Stress Concentrations; Part Orientation and Build Chamber Packing",
        use="고분자 SLS의 분말 지지·방향별 벽·배출·청소 고려. MEX의 무지지 규칙이나 보편 최소 치수로 사용하지 않음.",
        access="공개 본문; Fuse Series·Nylon 12 기준, 재료별 지침 별도. Maintaining Uniform Thickness 절의 배출홀 중복 문단은 균일두께 근거로 채택하지 않음"),
    "LI2020": dict(title="Li et al. (2020), Numerical Model and Experimental Validation for Laser Sinterable Semi-Crystalline Polymer: Shrinkage and Warping",
        url="https://doi.org/10.3390/polym12061373", kind="original_research",
        locator="§§2.1–2.3, 3.3, 4; original full-text XML PMC7361694",
        use="SLS 수축·휨은 물성·스캔·냉각 등 조건에 의존. 단면이나 종횡비 하나를 수축·열변형 예측값으로 바꾸지 않음.",
        access="공개 원문 XML; EP-P3850·Farsoon FS3300PA(PA12)·50×10×1 mm 시험편, 층 높이 0.10–0.19 mm. layer-layer angle은 스캔각 차이이며 빌드 기울기가 아님"),
    "MOHR2024": dict(title="Mohr et al. (online 2024; issue 2025), Thermal history transfer from complex components to representative test specimens in laser powder bed fusion",
        url="https://link.springer.com/article/10.1007/s40964-024-00689-8", kind="original_research",
        locator="§§2.1–2.3, 3.1.1; experimental thermal history and macroscale FEM",
        use="LPBF 단면 변화·층간 시간·열전달 경로를 함께 고려. 단면이 감소해도 온도가 상승한 구간이 있어 면적을 단조로운 열위험 점수로 사용하지 않음.",
        access="공개 원문; SLM280HL·316L·275 W·700 mm/s·해치 0.12 mm·층 0.05 mm·베이스 100°C 조건"),
    "CHENG2019": dict(title="Cheng et al. (2019), On utilizing topology optimization to design support structure to prevent residual stress induced build failure in laser powder bed metal additive manufacturing",
        url="https://www.sciencedirect.com/science/article/pii/S2214860418309035", kind="original_research",
        locator="Public abstract and introduction; DOI 10.1016/j.addma.2019.03.001",
        use="금속 PBF 서포트의 기계적 고정·열 방출 역할. 면 각도나 지지량만으로 잔류응력 억제·출력 성공을 판정하지 않음.",
        access="출판사 공개 초록·서론 확인; 상세 전문 재현·수치 모델 검증을 완료한 것으로 사용하지 않음"),
    "HUNTER2020": dict(title="Hunter et al. (2020), Assessment of trapped powder removal and inspection strategies for powder bed fusion techniques",
        url="https://link.springer.com/article/10.1007/s00170-020-04930-w", kind="original_research",
        locator="§§2.1–2.2, 3.1.2–3.1.3, 4; channel challenge devices, XCT and weighing",
        use="금속 분말 제거는 채널 직경·길이·굴곡·세척법·분말 상태에 의존. 열린 통로나 원통면 탐지가 제거 성공을 보장하지 않음.",
        access="공개 원문; Ti-6Al-4V·M2 Cusing L-PBF 및 A2XX EBSM 실험과 XCT·질량 대조. EBSM 소결 분말과 L-PBF 느슨한 분말의 결과를 구분"),
    "ASTMF3530": dict(title="ASTM F3530-22 — Design; post-processing for metal PBF-LB",
        url="https://store.astm.org/f3530-22.html", kind="standard_scope", locator="Scope §1.1.1",
        use="분말 제거 등 후처리 검토의 필요성. 형상만으로 제거 성공을 판정하지 않음.", access="공개 범위; 전문 미확보"),
    "OCCT": dict(title="Open CASCADE Technology — STEP translator",
        url="https://dev.opencascade.org/doc/overview/html/occt_user_guides__step.html", kind="software_documentation", locator="STEP reader; units; shape transfer",
        use="STEP 단위 변환·솔리드·곡면 입력 처리. CAD가 원래 설계 의도를 모두 복원하지는 않음.", access="공식 API 문서 및 설치된 7.9.3 API"),
    "3MF_CORE": dict(title="3MF Consortium — Core Specification v1.4.0",
        url="https://github.com/3MFConsortium/spec_core/blob/master/3MF%20Core%20Specification.md",
        kind="format_specification", locator="Published 2025-02-06; §§2.1, 2.3, 3.3–3.4, 4.1–4.2",
        use="패키지 시작 모델·선언 단위·빌드 객체·성분 변환의 입력 근거. 3MF 메시가 CAD 설계 이력이나 실제 출력 공차를 제공한다는 뜻은 아님.",
        access="공식 저장소 원문; 검토한 판은 v1.4.0. 지원하는 기하 입력 범위를 설명하며 전체 규격 적합 인증을 주장하지 않음"),
    "3MF_PRODUCTION": dict(title="3MF Consortium — Production Extension v1.2",
        url="https://github.com/3MFConsortium/spec_production/blob/master/3MF%20Production%20Extension.md",
        kind="format_specification", locator="Published v1.2; §§2, 3.1–3.3",
        use="패키지 내부 모델 참조·객체 식별·변환의 의미. 루트의 빌드 목록만 사용하며 비루트 모델에서 다른 파일을 다시 참조하는 구성은 허용되지 않음.",
        access="공식 저장소 원문; Production 확장 전체 구현·대체 객체·제조 지시 해석 완료를 뜻하지 않음"),
    "STL_FORMAT": dict(title="Library of Congress — STL (STereoLithography) File Format Family",
        url="https://wwws.loc.gov/preservation/digital/formats/fdd/fdd000504.shtml",
        kind="format_documentation", locator="Description; Identification and description; Format specifications",
        use="STL 삼각형·정점·법선 구조와 표면 근사의 근거. 원통면의 설계 지름·설계 의도를 복원하는 CAD 입력으로 간주하지 않음.",
        access="미국 의회도서관 공식 형식 해설. 원 1988 규격 전문 자체가 아니며, 해설도 해당 원문 미확보를 명시"),
}


_COMMON_SOURCES = {
    "overhang": ("ISO52910",),
    "wall": ("ISO52910",),
    "cad_holes": ("ISO52910", "OCCT", "STAV2022", "KIM2019"),
    "cavities": ("ISO52910", "OCCT"),
    "sections": ("ISO52910", "MOYLAN2014", "NIST_GAUSS"),
}

# These links justify the interpretation of a measured feature. They neither
# select numeric profile values nor certify the geometry algorithm itself.
_PROCESS_SOURCES = {
    "MEX": {
        "overhang": ("JIANG2018", "KIM2019"),
        "wall": ("KUIPERS2020", "PRUSA_ARACHNE"),
        "cad_holes": (),
        "cavities": ("JIANG2018",),
        "sections": ("KUIPERS2020", "PRUSA_ARACHNE"),
    },
    "VPP": {
        "overhang": ("FORM_ORIENTATION", "FORM4"),
        "wall": ("FORM4",),
        "cad_holes": ("FORM4",),
        "cavities": ("FORM4", "FORM_ORIENTATION"),
        "sections": ("PAN2017", "FORM_ORIENTATION"),
    },
    "PBF_POLYMER": {
        "overhang": ("ISO52911P", "FUSE_DESIGN"),
        "wall": ("FUSE_DESIGN", "LI2020"),
        "cad_holes": ("FUSE_DESIGN",),
        "cavities": ("FUSE_DESIGN",),
        "sections": ("FUSE_DESIGN", "LI2020"),
    },
    "PBF_METAL": {
        "overhang": ("ISO52911M", "CHENG2019", "MOHR2024"),
        "wall": ("ISO52911M", "MOHR2024"),
        "cad_holes": ("HUNTER2020", "ASTMF3530"),
        "cavities": ("HUNTER2020", "ASTMF3530"),
        "sections": ("MOHR2024", "CHENG2019"),
    },
}


def sources_for(check: str, process: str) -> list[str]:
    """Return relevant source IDs without transferring rules across processes."""
    if check not in _COMMON_SOURCES:
        raise ValueError(f"지원하는 근거 검토 항목이 아닙니다: {check}")
    if process not in _PROCESS_SOURCES:
        raise ValueError(f"지원하는 AM 공정이 아닙니다: {process}")
    return list(dict.fromkeys(_COMMON_SOURCES[check] + _PROCESS_SOURCES[process][check]))


_SECTION_GUIDANCE = {
    "MEX": {
        "title": "재료 압출의 단면·연결 검토",
        "reason": "단면 면적·경계·성분과 높이에 따른 변화를 관측해 얇은 특징·분기·천장 검토 위치를 찾습니다.",
        "action": "변화가 큰 높이의 형상을 확인하고, MEX 층간 정밀 검토와 실제 슬라이서의 가변 선폭 경로를 대조하세요.",
        "limitations": (
            "단면 차집합·직접 중첩 부재는 실제 무지지 면적·브리지 실패·압출 누락을 확정하지 않습니다.",
            "명목 선폭과 실제 가변 선폭·압출 경로는 다릅니다. 접착력·처짐·강도는 계산하지 않습니다.",
        ),
    },
    "VPP": {
        "title": "액조 광경화의 단면·분리 검토",
        "reason": "Bottom-up처럼 경화층을 탱크에서 분리하는 방식에 해당할 때, 단면 면적·경계 길이·A/P는 분리 과정의 검토에 참고할 기하량입니다.",
        "action": "관측 최대 단면·성분 수·단면 변화의 위치를 확인하고, 장비의 분리 방식·방향·서포트 접점·수지 배출 경로를 함께 검토하세요.",
        "limitations": (
            "A/P의 단위는 mm입니다. 수지 점도·인상 속도·필름·간극 조건 없이 박리력·성공률을 계산하지 않습니다.",
            "내부 루프는 흡착 컵 확정이 아닙니다. 각 인쇄 단계의 3D 공기·수지 연결성과 압력 평형은 미평가입니다.",
            "단면 성분 수·차집합은 신생 성분의 지지 실패 판정이 아닙니다. 실제 서포트·경화 거동은 포함하지 않습니다.",
            "분리 과정의 해석은 Bottom-up 등 경화층을 탱크에서 분리하는 방식에 한정합니다. Top-down 등 다른 VPP 방식에 같은 분리 해석을 적용하지 않습니다.",
        ),
    },
    "PBF_POLYMER": {
        "title": "고분자 PBF의 단면·재료 분포 검토",
        "reason": "단면 크기·성분·변화를 관측해 두께 변화와 분말 배출을 검토할 위치를 찾습니다. 분말 지지 공정의 해석은 MEX와 다릅니다.",
        "action": "얇은 특징·두꺼운 부위의 전환과 내부 경로를 확인하고, 재료별 냉각·패킹·분말 제거 조건을 공정 담당자와 검토하세요.",
        "limitations": (
            "새 성분이나 직접 중첩 부재만으로 지지 실패를 판정하지 않습니다. FDM 선폭·브리지 규칙을 적용하지 않습니다.",
            "단면 면적·A/P·변화량은 온도·열위험 점수·수축·휨 예측값이 아닙니다. 물성·스캔·냉각 이력은 미평가입니다.",
            "내부 루프나 열린 통로만으로 분말 제거 성공을 확정하지 않습니다. 채널 연결·좁은 목·청소 접근성은 별도 검토가 필요합니다.",
        ),
    },
    "PBF_METAL": {
        "title": "금속 LPBF의 단면 변화·열 검토 위치",
        "reason": "단면 증감·겹침 변화를 관측해 하향면과 열전달 경로를 검토할 높이를 찾습니다. 같은 면적에서도 층간 시간·열전달 조건에 따라 열이력이 달라집니다.",
        "action": "변화 구간의 하향면·열전달 및 고정용 서포트·제거 접근성을 확인하고, 장비의 스캔·층간 시간·예열 조건과 함께 검토하세요.",
        "limitations": (
            "단면이 작아져도 온도는 상승할 수 있습니다. 면적·A/P·변화량을 온도·열위험 점수·잔류응력·휨으로 환산하지 않습니다.",
            "새 성분·직접 중첩 부재만으로 지지 필요량이나 출력 실패를 확정하지 않습니다. 서포트의 열·기계적 해석은 미평가입니다.",
            "열린 통로나 원통면이 있어도 실제 분말·서포트 제거 성공은 미확정입니다.",
        ),
    },
}


def section_guidance(process: str) -> dict:
    """Explain section measurements with the selected process's evidence scope."""
    if process not in _SECTION_GUIDANCE:
        raise ValueError(f"지원하는 AM 공정이 아닙니다: {process}")
    guidance = _SECTION_GUIDANCE[process]
    return {
        "title": guidance["title"],
        "reason": guidance["reason"],
        "action": guidance["action"],
        "limitations": list(guidance["limitations"]) + [
            "표본 단면 사이의 미관측 형상은 포함하지 않습니다. 관측 최대값은 연속 높이의 전역 최대가 아닙니다.",
        ],
    }


def used_sources(findings):
    return {k:SOURCES[k] for k in dict.fromkeys(key for f in findings for key in f.evidence)}


def review_context_sources(process: str) -> dict:
    """Sources for unassessed production requirements, not geometry thresholds."""
    if process not in _PROCESS_SOURCES:
        raise ValueError(f"지원하는 AM 공정이 아닙니다: {process}")
    keys = ["KS52901_2017", "KS52902_2019"]
    if process == "MEX":
        keys += ["KS52903_1_2020", "KS52903_2_2020"]
    return {key: SOURCES[key] for key in keys}
