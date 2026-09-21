# 무작위 형상 26개 독립 기하 감사

검토일: 2026-09-14. 환경: Windows / Python 3.12.14 / cadquery-ocp-novtk 7.9.3.1.1.

**요청한 바탕화면 폴더의 형상 파일 26개를 모두 조사했다.** STEP/STP 21개, STL 4개, 3MF 1개다. STEP 중 19개 파일에 솔리드가 총 169개 있고, 나머지 두 STEP은 곡면만 있다. 빌드 공간으로 형상을 탈락시키거나 크기를 맞추기 위한 배율 변경을 하지 않았다. 전후 SHA-256 대조에서 원본 26개가 모두 보존됐다.

검토 스크립트는 AM-DFM 분석 모듈을 사용하지 않는다. OCCT로 원 STEP을 직접 읽어 단위·루트 전송·유효성·솔리드·면·외곽을 조사하고, B-rep 적분과 삼각형 발산정리 체적합을 서로 대조했다. 두 B-rep 적분법과 메시 생성은 같은 OCCT 커널을 사용하므로 완전히 다른 CAD 커널의 검증이라고 부르지 않는다. 실제 출력물의 치수·강도·품질은 측정하지 않았다. STL의 mm 값은 명시적인 단위 가정이다.

## 발견과 구현 수정

| 발견 | 확인 근거 | 수정 또는 남긴 판단 |
|---|---|---|
| 복잡 곡면의 기본 CAD 적분 편차 | Submodelv150 체적 81,865.099246 → 정밀 적분 81,876.551263 mm³. Valve 첫 솔리드 447,753.386685 → 447,666.599829 mm³ | 적응형 Gauss 적분으로 변경. 요청 상대오차 1e-9와 반환 오차 추정치를 기록. CAD 체적을 제조 공차 보증으로 확대하지 않음 |
| Valve 면 124에서 메시가 없음 | 원통면의 UV 범위 `[1.5115310203843606, 1.6300616332054325, -4, -4]`. 축방향 구간이 정확히 0이고 면적도 정확히 0 | 원 B-rep는 보존. 별도 적분 형상에서 영면적 기여만 제외하고 CAD 면 번호·사유 기록. 실제 작은 면을 임계값으로 삭제하지 않음 |
| assembly_solid의 유효한 첫 솔리드가 0.05 mm 메시에서 열림 | 경계 변 4개. 0.01 mm 재메시는 122,604개 삼각형, 경계·비다양체·중복 0개, 일관된 면 방향 | 별도 B-rep 복사에서 더 세밀한 메시를 만들고 위상 검사와 자원 한도를 모두 통과할 때 채택. 이전·새 설정 및 검사값 기록 |
| Pump_assy 두 번째 솔리드의 메시 결함 | 0.05 mm에서 비다양체 변·중복 삼각형 각각 8개. 0.01 mm에서는 각각 16개 | 재메시 후보를 거부하고 원래 결과와 미확정 사유 보존. 임의 봉합·좌표 허용오차 병합·중복 삭제를 수행하지 않음 |
| Raspberry STEP이 솔리드 수 제한에 걸림 | 유효한 109솔리드·10,316면. 0.05 mm에서 241,342개 삼각형 | 솔리드 수 상한을 100에서 1,000으로 조정. 면 20,000개·삼각형 600,000개 및 작업 시간 제한 유지 |
| Bracket와 Gear_Set_2D에 닫힌 솔리드가 없음 | 각각 4개 곡면, 2개 평면. Gear의 두께 방향 범위는 수치 허용오차 수준 | 모든 면과 면 번호를 보존하여 곡면 입력으로 검토. 체적·재료 내외측·벽두께·공동을 임의 확정하지 않음 |

OCCT의 적응형 적분은 반복 계산의 변화로 오차를 추정한다. 요청값은 수치 적분 조건이며, 입력 CAD의 정확도나 전역 오차를 인증하는 값이 아니다. 구현 옵션은 현재 8.0.1 문서 대신 사용 버전에 맞춘 [OCCT 7.9.3 BRepGProp 원문](https://github.com/Open-Cascade-SAS/OCCT/blob/V7_9_3/src/BRepGProp/BRepGProp.hxx)과 설치된 바인딩의 설명을 확인했다.

메시 재생성용 복사는 기하 복사 `copyGeom=True`, 기존 메시 미복사 `copyMesh=False`를 명시했다. 원본 캐시와 후보의 공유 가능성을 없애기 위한 설정이다. [OCCT 7.9.3 BRepBuilderAPI_Copy 원문](https://github.com/Open-Cascade-SAS/OCCT/blob/V7_9_3/src/BRepBuilderAPI/BRepBuilderAPI_Copy.hxx).

## 수치 정확성 대조의 범위

147개 솔리드에서 적응형 Gauss와 별도 Gauss–Kronrod 체적 계산을 완료했다. 두 값의 최대 상대차는 약 `6.286×10⁻⁸`, 백분율로 `0.000006286%`였다. 이 관측을 모든 모델의 오차 상한으로 사용하지 않는다.

Valve의 Gauss–Kronrod 검사는 오래 진행돼 진단을 중단했다. 최초 240초 시간 초과와 추가 중단 기록을 그대로 남겼다. 해당 22개 솔리드는 적응형 Gauss와 세 단계 메시 체적합으로 대조했다. Valve 첫 솔리드의 메시 체적 상대차는 다음과 같아, 세분화가 오차를 단조롭게 줄인다고 주장할 수 없다.

| 요청 선형 편차 | B-rep 적응형 적분 대비 메시 체적 상대차 |
|---:|---:|
| 0.1 mm | −0.031826% |
| 0.05 mm | −0.004535% |
| 0.01 mm | +0.017400% |

원통면 3,206개는 반지름 방향 양쪽의 재료 존재 여부를 독립적으로 확인했다. 비영면적 면에서 내측 1,551개, 외측 1,639개가 기존 분류와 일치했다. 기존 미확정 15개는 독립 표본에서 외측으로 나타났다. 나머지 한 면은 정확히 면적이 0인 Valve 면 124이며 재료 방향을 확정하지 않는다. 이를 구멍 개수·관통 여부·제거 경로의 검증으로 확대하지 않는다.

## 같은 이름의 STEP·STL·3MF가 같은 형상인가

파일명만으로 같은 형상이라고 가정하지 않았다. 정점과 삼각형 중심에서 방향당 4,000개 표본을 골라 상대 메시 표면의 실제 최근접점까지 거리를 계산했다. 유한 표본이므로 연속 표면 전체의 Hausdorff 오차 보증은 아니다.

| 쌍 | 관측된 양방향 최대 표면 거리 | 대조 조건과 주의할 점 |
|---|---:|---|
| Arduino STL / STEP 메시 | 0.003506 mm | 원 좌표 그대로. 배율·위치 맞춤 없음. STL 1성분, CAD 1솔리드 |
| SG90 STL / STEP 메시 | 0.007310 mm | 원 좌표 그대로. 배율·위치 맞춤 없음. STL 1성분, CAD 1솔리드 |
| Raspberry STL / STEP 메시 | 0.046302 mm | 원 좌표 그대로. STL 79성분과 CAD 109솔리드는 같은 위상으로 볼 수 없음. 성분·솔리드 체적합은 겹침을 제거한 합집합 체적이 아님 |
| Backpack STL / 3MF 리소스 메시 | 0.054178 mm | 외곽 중심을 이용한 평행이동만 적용. 회전·배율·표면 맞춤 없음. 서로 다른 삼각형 분할임을 보존 |

3MF는 mm를 선언하고 ZIP 내부 production 확장 경로 `/3D/Objects/object_1.model`을 참조한다. 리소스에는 71,943개 정점과 143,890개 삼각형이 있다. 원 모델 외곽은 약 `38.10 × 42.0702 × 82.55 mm`다. 별도 build 변환은 X축 +90° 회전과 `(128, 128, 21.0350876)` 평행이동으로, 배치 후 외곽은 `38.10 × 82.55 × 42.0702 mm`가 된다. 리소스 좌표와 출력 배치 좌표를 구분해 검사했다.

## 회귀검사와 재현 자료

정밀 CAD 검사와 기존 CAD 기하 검사를 합쳐 **43개가 56.87초에 통과**했다. 이후 복사 옵션을 명시적으로 강화한 코드에서 정밀 검사 **11개가 3.69초에 다시 통과**했다. 전체 앱·공정별 검사는 별도 통합 실행 기록을 따른다.

새 반례는 Bezier 프리즘의 다항식 체적 적분, 구의 해석 체적·면적, 역방향 솔리드, 평면·원통 곡면 STEP, 솔리드와 독립 곡면의 묵시적 누락 방지, 실제 작은 면과 정확히 면적 0인 면 구분, 109개 바디 번호 보존, 손상된 메시 캐시의 원본 보존과 후보 위상 복구, 후보가 삼각형 예산을 넘는 경우의 거부다.

- [26개 원본 SHA와 완료 결과 색인](../../validation/v3/random-corpus/independent/completion-manifest.json)
- [첫 실행 및 시간 초과 보존](../../validation/v3/random-corpus/independent/initial-manifest.json)
- [Valve 정밀 적분·세 단계 메시](../../validation/v3/random-corpus/independent/valve-summary.json)
- [Gauss–Kronrod 중단 기록](../../validation/v3/random-corpus/independent/failure-summary.json)
- [경계·중복 문제의 좌표 기록](../../validation/v3/random-corpus/independent/tessellation-retry-summary.json)
- [동명 형상의 양방향 표면 거리](../../validation/v3/random-corpus/independent/paired-surface-comparisons.json)
- [26개 외곽 치수와 상세 영문 기록](../../../study/random-shape-audit/independent-01/INDEPENDENT_AUDIT.md)

기하 계산 결과를 실제 적층제조의 성공·열변형·강도·재료 제거·치수 공차 보증으로 확대하지 않았다. 결함이 남은 모델, 곡면 입력, 비교 불가능한 체적을 완료율을 높이기 위해 정상값이나 0으로 바꾸지 않았다.

## 동결 코드와 최종 복사 옵션의 동일성

전체 공정 실행은 `final-01/engine-source`의 동결 코드를 사용했다. 이후 복사 옵션을 강화한 최신 코드로 assembly_solid와 Pump_assy를 각각 다시 변환했다. 두 모델 모두 정점·삼각형·CAD 면 번호·바디 번호 전 배열이 정확히 같고, 모든 CAD JSON 메타데이터도 동일했다. NPZ와 JSON 파일 바이트 SHA-256까지 일치했다. [동결/최신 코드 SHA와 배열·산출물 동일성 기록](../../validation/v3/random-corpus/independent/deepcopy-frozen-equivalence.json).

배포본에는 [원통면 독립 프로브 집계](../../validation/v3/random-corpus/independent/cylinder-probe-summary.json)를 포함해 집계·계산 조건·SHA만 넣었다. 원본 STEP/STL/3MF와 전체 메시·좌표 배열은 재배포하지 않았다. 자세한 로컬 자료는 저장소 옆 `study/random-shape-audit/independent-01/`에 있으며, 위 영문 기록 링크는 해당 로컬 작업공간에서만 열린다.

## 재실행

동일한 26개 입력 파일이 있는 작업공간에서 새 출력 경로를 사용한다. 첫 명령은 각 파일에 240초를 허용하고 실패 기록을 보존한다. Valve의 별도 Gauss–Kronrod 검증을 생략하는 두 번째 명령은 해당 사실을 null로 기록하면서 적응형 Gauss와 세 단계 메시 검사를 실행한다. 마지막 명령은 같은 입력 목록에 대해 동명 형상 표면 거리를 재계산한다.

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/independent_cad_audit.py --source "$env:USERPROFILE/Desktop/무작위 형상 테스트" --out ../study/random-shape-audit/independent-new --refine --timeout 240
.\.venv\Scripts\python.exe -X utf8 scripts/independent_cad_audit.py --worker --source "$env:USERPROFILE/Desktop/무작위 형상 테스트/3.4 Valve_RM_20130113.stp" --out ../study/random-shape-audit/independent-new/valve-adaptive-and-mesh.json --refine --skip-gk
.\.venv\Scripts\python.exe -X utf8 scripts/independent_cad_audit.py --pairs --source "$env:USERPROFILE/Desktop/무작위 형상 테스트" --out ../study/random-shape-audit/independent-new
```

## 후속: 높이 사건 단면 적분의 독립 검산 — 2026-09-15

냉각팬 솔리드 2에서 균등 64개 단면의 체적이 메시 사면체 적분보다 35.7254% 작아지는 표본 누락을 확인했다. 메시 정점 높이 사이마다 두 Gauss 내점을 배치하는 사건 단면 검산을 추가했다. 기존 균등 수치 경로는 유지했다. [수학적 유도와 측정 계약](../EVENT_SECTION_METHOD.md), [팬 반례](CROSS_SECTION_ALIASING_2026-09-15.md).

회전·이동 프리즘의 해석 체적, 0.001 mm 얇은 판을 놓치는 균등 표본, 다각 원뿔의 이차 단면적, 공동, 매우 가까운 사건 높이와 예산 초과를 시험했다. 사건 모듈 및 현재 단면 API 통합 검사 52개가 13.69초에 통과했다. 원뿔은 체적 적분이 맞아도 표본 최대가 전역 최대가 되지 않는 반례를 포함한다.

기존 동결 메시 캐시에 대해 최신 엔진을 다시 동결하고 `run_detail`로 +Z 방향의 사건 단면을 전수 실행했다. 빌드 공간은 제한하지 않았고, 8,192표본·예상 교차 150만 개·작업자 90초 한도를 적용했다. 이 검사는 공정과 무관한 단면 기하의 단일 실행이며 4개 공정의 중복 실험으로 세지 않는다. 네 공정의 동일 API 연결은 통합 검사에서 확인했다.

| 집계 | complete | partial | unknown | 합계 |
|---|---:|---:|---:|---:|
| 전체 형상 26개 + CAD 솔리드 169개 선택 | 124 | 32 | 39 | 195 |
| 단일 솔리드의 전체/본체 중복 9개 제외 | 123 | 29 | 34 | 186 |

미확정 39개는 사전 예산 초과 21개, 재료 없는 곡면 CAD 2개, 조립체·다중 껍질 관계 11개, 메시 위상 조건 5개다. 시간 초과와 작업자 실패는 이번 최종 실행에서 없었다. 부분 결과 32개 중 26개는 두 내점을 표현할 수 없는 거의 같은 사건 높이, 나머지 6개는 일부 단면을 확정할 수 없는 경우였다. 이번 데이터에서 두 원인이 겹치는 선택은 0개였다. 미확정 전체 체적은 모두 null로 유지했다.

complete 124개의 사건 적분과 독립 사면체 적분 사이 최대 상대차는 `2.5383×10⁻⁹`였다. 이는 이번 고정 메시에서 관측한 차이이며 전체 기하·자기교차·공정 오차의 보증 한계가 아니다. 팬 솔리드 2는 10개 단면으로 `497,842.7874248 mm³`, 독립 메시 적분은 `497,842.7871037 mm³`였다. 원 CAD 적분 `497,834.0592 mm³`와 구분한다.

Pi 솔리드 67은 370개 중 360개 단면만 확정됐다. 새 표본에서 솔리드 106은 3,098개 중 3,004개, 솔리드 109는 1,150개 중 1,134개가 확정되어 미검토 높이를 보존했다. 솔리드 108은 9,278개 표본이 필요해 사전 한도에서 보류했다. 이러한 단면 한계를 임의 봉합이나 사건 높이 병합으로 없애지 않았다.

솔리드 106의 첫 실패 높이 4.1551042874 mm에서 원 교선의 중첩 약 2.1433×10⁻⁷ mm, 솔리드 109의 첫 실패 높이 1.1601307234 mm에서 약 1.0007×10⁻⁵ mm를 별도 교선 계산으로 확인했다. 인접 교선과의 T접점도 있으며 제품의 미해결 교선 길이와 격자 정밀도 범위에서 일치했다. 두 메시 모두 watertight·방향 일관 조건을 충족해도 이 단면은 확정되지 않는다. 원 CAD와 테셀레이션 중 어디서 발생한 문제인지는 미확정으로 유지한다. [솔리드 106 독립 진단](../../validation/v3/random-corpus/pi-body106-event-section-diagnostic.json), [솔리드 109 독립 진단](../../validation/v3/random-corpus/pi-body109-event-section-diagnostic.json).

26개 원본과 캐시·동결 엔진의 SHA가 실행 전후 동일했고, 기존 보고서의 모든 모델 지문과 배치도 일치했다. [195개 선택의 집계·참조 체적·지문](../../validation/v3/random-corpus/events/event-quadrature-summary.json)에 좌표 배열 없이 저장했다. [프로토타입 반례·과학 그림·환경 기록](../../../study/random-shape-audit/event-section-01/EXPERIMENT_REPORT.md)과 [최종 전수 원자료](../../../study/random-shape-audit/event-final-02/)는 로컬 작업공간에 있다. 첫 감사 스크립트의 상대 경로 오류는 제품 계산 전 발생했고 별도 실패 기록으로 보존한 뒤 절대 경로를 사용해 전수를 다시 실행했다.

[독립 반례의 설정·수치](../../validation/v3/random-corpus/events/prototype-counterexamples.json)와 [사전 계산량 목록](../../validation/v3/random-corpus/events/preflight-cost-inventory.json)도 공개 집계에 포함했다. 계산량만 고려하면 예산 초과인 31개 중 일부는 실제 API에서 재료·위상 조건에 먼저 걸리므로, 최종 API의 예산 초과 21개와 분모·검사 순서가 다르다.

```powershell
.\.venv\Scripts\python.exe scripts/audit_event_sections.py --corpus ../study/random-shape-audit/final-01 --out ../study/random-shape-audit/event-new --jobs 2 --timeout 90
```
