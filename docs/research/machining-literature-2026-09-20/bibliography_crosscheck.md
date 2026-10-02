# 문헌 목록 중복·기존 인용·핵심 서지 교차검토

검토일: 2026-09-20. 대상: `current_citations.json`, `foundations.json`, `geometry.json`, `process.json`, `standards.json`. 앱 코드·기존 원문은 변경하지 않았다.

이번 작업은 **서지 목록과 실제 조사 범위를 정리하는 독립 점검**이다. 현재 AM 등록 문헌 전부의 원문을 다시 읽거나 모든 AM 표준의 최신성을 보증하는 검토가 아니다. URL 일치, DOI, 문헌명·저자, 기존 문서의 인용 위치를 비교했으며 핵심 몇 건만 공식 페이지에서 추가 교차 확인했다.

## 1. 집계 단위를 먼저 구분

검토한 JSON 스냅샷의 구성은 다음과 같다.

| 구분 | 레코드 수 | 의미 |
|---|---:|---|
| 현재 적층·공통 런타임 출처 |24|앱 근거 등록소의 항목 수|
| 현재 절삭 런타임 출처 |5|앱 근거 등록소의 항목 수|
| 기존 원문 목록 R01–R14 |14|과거 확보 자료의 목록. 등록소29항목과 일부 겹침|
| 이번 심층 조사 F/G/P/S |57|F7+G16+P16+S18. 기존 인용 재검토와 신규 조사를 함께 포함|
| 조사 중복을 묶은 주제별 자료군 |55|F01/G08과G12/P05를 각1회 집계한 값|

55는 “새 논문55편”이나 “단일 문서55권”이 아니다. F01/G08에는 같은 연구의 보고서판·학술지판이 있고, S07·S10에는 여러 부의 표준이 묶여 있다. 현재 등록29개와 기존 원문14개도 합쳐43종이라고 단순 계산하면 안 된다.

기존 문서의 `documentation_url_occurrences`는 **URL 등장 위치 색인**이다. 같은 링크의 반복, 라이브러리 릴리스 문서, 로컬 서버 주소도 포함하므로 독립 참고문헌 수로 세지 않는다.

## 2. 확정 중복 및 관련 자료의 구별

| 레코드 관계 | 판정 | 문서 처리 |
|---|---|---|
| F01 ↔ G08 | 같은 연구계열. F01은1997학술지판을 대표하며 실제 읽은 공개본은1995NISTIR5713 계열 | 주제별 신규 조사 집계는1회.1997 DOI와1995보고서의 판·쪽 체계를 별도로 표기 |
| G12 ↔ P05 | 제목과 Autodesk URL이 완전히 같은 도움말 | 한 문헌으로 집계하고 두 조사 분야에서 교차참조 |
| G13 ↔ P목록 | 일치 항목 없음 | 드릴링 충돌 문서는 별도 유지 |
| F03 ↔ S02 | F03은 NIST 도구 웹페이지, S02는2021년 NIST AMS200-12 정식 보고서 | 별개 자료로 유지. 웹페이지가 보고서의 접근 경로인 관계만 표시 |
| G05 ↔ G07 | Hierarchical CADNet 논문과 MFCAD++ 데이터셋 | 별개 유지. DOI와 자료 유형이 다름 |
| F07 ↔ 현재 OCCT | BRepTools API와 STEP translator 사용자 안내 | 같은 소프트웨어의 서로 다른 문서. 합치지 않음 |
| P01 ↔ 현재 CNC_CORNER | Sandvik Milling inside corners와 Protolabs Network Sharp corners | 주제만 비슷한 다른 자료. 합치지 않음 |

F01의 학술지 서지는 **Gupta, Regli, Das, Nau; Research in Engineering Design9,168–190(1997)**이며 DOI는10.1007/BF01596601이다. NIST 공식 페이지는1995년·NISTIR5713으로 기록한다. 두 연도가 다르다고 한쪽을 오타로 바꾸지 않는다. NIST 메타데이터의 저자1명 표기를 그대로 전체 저자로 확정하지 않고, 기존 조사에서 확인한 공개 PDF 표지의4명을 유지하는 것이 타당하다. [학술지 공식 서지](https://link.springer.com/article/10.1007/BF01596601), [NIST 보고서 공식 서지](https://www.nist.gov/publications/automated-manufacturability-analysis-survey)

## 3. 현재 절삭 등록5개와 조사 문헌 매핑

| 현재 등록 ID | 조사 ID | 기존/신규 판단 |
|---|---|---|
| CNC_GEOMETRY | P04 | 같은 Protolabs Design for Machining Toolkit. 기존 문헌 재검토 |
| CNC_CORNER | 해당 없음 | Hubs/Protolabs Network Sharp corners 자료를 현재 목록에 유지. P01로 대체했다고 쓰지 않음 |
| CNC_TOOL_DIMENSIONS | P03 | 같은 Harvey End Mill Anatomy. 기존 문헌 재검토 |
| CNC_FACE_RECOGNITION | G02 | Nature와 PMC URL은 같은 Yeo et al.(2021) 논문. 기존 문헌 재검토 |
| CNC_ACCESS_SCOPE | G12/P05 | 같은 Autodesk Shaft and Holder 문서. 기존 문헌 재검토 |

G02의 연결은 DOI10.1038/s41598-021-01313-3, PMID34772966, PMCIDPMC8590007로 확인했다. Nature 직접 열기는 오류, PMC 직접 열기는 재확인 시 봇 확인 화면이었으나 PubMed/PMC 검색 서지에서 식별자 대응을 확인했다. 따라서 이번 교차검토가 새로운 본문 전권 열람인 것처럼 접근 수준을 올리지 않는다. [PubMed 서지](https://pubmed.ncbi.nlm.nih.gov/34772966/)

## 4. 등록소 밖에서 이미 인용했던 조사 항목

| 조사 ID | 기존 위치 | 해석 |
|---|---|---|
| F02 | 기존 원문 R01 | Kerbrat et al.(2011)의 재검토; 신규 문헌 수에서 제외 |
| F07 | MACHINING_EVIDENCE_REAUDIT E09 | OCCT BRepTools API를 기존부터 인용 |
| G01 | MACHINING_EVIDENCE_REAUDIT E07 | Mirzendehdel et al.(2020)의 접근성 연구를 기존부터 인용 |
| G13 | MACHINING_EVIDENCE 및 REAUDIT E06 | Autodesk 드릴링 충돌 문서의 재검토 |
| P01 | MACHINING_EVIDENCE 및 REAUDIT E01 | Sandvik 코너 밀링 문서의 재검토 |
| P02 | MACHINING_EVIDENCE 및 REAUDIT E02 | Sandvik 홀·공동·포켓 문서의 재검토 |

제3절4개의 기존 자료군과 이 표의6개를 합해 **조사 목록 중10개 자료군은 기존 인용과 대응됨을 확인**했다. 나머지를 모두 저장소 역사상 최초 인용이라고 보증하지 않는다. 이번 비교 대상 색인에서 직접 대응하지 않은 것이며, 원문 내부의 참고문헌까지 전수 추적한 결과가 아니다.

## 5. 적층·공통24개 및 기존 원문14개 관계

현재 적층·공통24개에는 F/G/P/S와 **동일 문서로 확정한 중복이 없다**. 공통 OCCT와 F07은 서로 다른 API/사용자 안내이며, 현재 적층 지식 문헌이 다른 분야에서 참고 가치가 있다는 사실을 문서 동일성으로 혼동하지 않았다.

현재 등록 ID24개는 NIST_GAUSS, ISO52910, ISO52902, ISO52911M, ISO52911P, MOYLAN2014, KUIPERS2020, PRUSA_ARACHNE, JIANG2018, STAV2022, KIM2019, FORM4, FORM_ORIENTATION, PAN2017, FUSE_DESIGN, LI2020, MOHR2024, CHENG2019, HUNTER2020, ASTMF3530, OCCT,3MF_CORE,3MF_PRODUCTION, STL_FORMAT이다.

다만 기존 원문 R목록과는 다음 관계가 있다.

| 기존 원문 | 현재 등록 또는 조사 | 판정 |
|---|---|---|
| R01 | F02 | 같은2011연구 |
| R06 | JIANG2018 | 같은 연구의 기존 원문과 등록 항목 |
| R07 | STAV2022 | 같은 DOI의 연구. 아래 정식 제목 보완 필요 |
| R08 KS52902:2019 캡처 | ISO52902 국제2023판 | 관련 표준의 다른 판·채택본. 동일 파일·동일 규정 내용으로 합치지 않음 |
| R11 KS52910:2018 캡처 | ISO52910 국제2018판 | 관련 국제표준 기반의 KS채택본. 실제 파일·채택정보·완전성은 별도 유지 |
| R12 | F03/S01/S02/S17/S18과 주제 관련 |3D주석이라는 주제만 겹침. 동일 문헌이라고 합치거나 불명확한 서지를 보충하지 않음 |

R02–R05, R09–R10, R13–R14는 현재 조사 목록과 직접 동일 문서로 매핑하지 않았다. 이 판단은 해당 문헌의 유용성이 낮다는 의미가 아니다. R09·R10의 ISO판2020과 KS제정2023 날짜를 같은 날짜 종류로 취급하지 않는다.

## 6. 문서 출력 전에 보완할 핵심 서지

### R08의 title 필드는 문헌 제목이 아니라 결손 메모

현재 `original_literature.R08.title` 값은 “PDF1이 본문5절(인쇄쪽2)에서 시작”이다. 이것을 논문·표준 제목으로 인쇄하면 안 된다. 목록에서는 확인된 식별자 **KS D ISO ASTM52902:2019(불완전 캡처)**를 사용하고 결손 메모는 접근 수준/제약 열에 둔다. 확인되지 않은 KS정식 한글 제목은 임의로 완성하지 않는다.

### STAV2022/R07는 약칭과 정식 제목을 구분

현재 등록 및 R07의 제목은 축약형이다. 최종 참고문헌에는 다음 출판사 정식 서지를 사용하면 검색이 쉬워진다.

Panagiotis Stavropoulos; Konstantinos Tzimanis; Thanassis Souflas; Harry Bikas(2022). **Knowledge-based manufacturability assessment for optimization of additive manufacturing processes based on automated feature recognition from CAD models.** The International Journal of Advanced Manufacturing Technology122,993–1007. DOI10.1007/s00170-022-09948-w. [출판사 공식 페이지](https://link.springer.com/article/10.1007/s00170-022-09948-w)

이 보완은 현재 앱의 표시 약칭이 다른 논문을 가리킨다는 뜻이 아니다. 원문 내용의 재검증이나 규칙 확대를 수행한 것도 아니다.

### F06의 서지는 유지하되 접근 수준을 올리지 않음

공식 출판사 검색 서지에서 제목 **Systematic approach to analysing the manufacturability of machined parts**, Gupta·Nau, Computer-Aided Design27(5),323–342, May1995, DOI10.1016/0010-4485(95)96797-P를 다시 확인했다. 따라서 현재 F06 레코드의 핵심 서지를 수정할 근거는 없다. 직접 원문 열람 실패는 그대로 남긴다. 다른 논문의 참고문헌에 적힌 비정상 쪽수343–342로 바꾸면 안 된다. [출판사 서지](https://www.sciencedirect.com/science/article/pii/001044859596797P)

### R12는 미확정 상태 보존

자료는5쪽 번역·편집본으로 기록되어 있고 연도·권호·DOI와 원본 그림이 확보되지 않았다. “Tatsuya Mochizuki로 표기된 번역·편집 자료; 정식 원문 서지 미확인” 수준을 유지한다. 새 표준이나 NIST의 정확한 서지를 이 자료에 붙여 확정 논문으로 바꾸지 않는다.

### 발행연도와 확인일

연도 미표시 웹페이지는 “발행연도 미표시,2026-09-20 확인”으로 표기한다. F03의 조회연도, F07의 API버전8.0.1을 논문 발행연도로 변환하지 않는다. S16의R2024는 재확인 연도이며2018본문 판을 대체하는 발행연도가 아니다.

## 7. 최종 문서에 필요한 표현

권장 표현:

> 현재 코드에 등록된 출처29항목과 기존 확보 자료14항목을 구분해 정리했다. 절삭 개발 관련 심층 조사57레코드를 구성했으며 중복 및 판 관계를 정리한55개 자료군에는 기존 인용 재검토, 논문, 표준 묶음, 데이터셋과 공식 기술문서가 함께 포함된다. 문헌별로 실제 읽은 범위와 미확인 내용을 표시했다.

피해야 할 표현:

- “새 논문57편을 전부 정독했다.”
- “등록된 AM표준 모두2026년 최신판임을 검증했다.”
- “유료 표준 본문을 읽고 규정 수치를 구현했다.”
- “URL이 다르므로 모두 다른 문헌이다.”
- “보고서판과 학술지판의 연도가 다르므로 한쪽이 오류다.”

원본 JSON은 이 교차검토에서 수정하지 않았다. 최종 집계에서 중복 ID를 삭제할 필요 없이 대표 항목과 별칭을 연결하면 조사 흔적을 보존할 수 있다.

