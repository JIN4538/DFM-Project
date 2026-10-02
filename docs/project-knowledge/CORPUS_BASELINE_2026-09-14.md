# 무작위 형상 26개: 변경 전 기준과 독립 공급사 수치 대조

이 문서는 **공통 단면·3MF·표면 STEP 개선 이전** 상태를 보존한다. 기준 커밋은 `7c5444a81b277e7b8af9bf9cba2408eab9024edc`, 분석 코드 SHA-256은 `da5022ec34e2560243a3dcec65a56a1d74f8aa82056519dfdcdc7e105e1310d9`다. 이 결과를 후속 엔진의 검증 결과로 바꾸어 설명하지 않는다.

## 범위와 결과

사용자의 바탕화면 `무작위 형상 테스트` 폴더를 재귀 조사했다. 파일31개는 **STEP21개(.stp19개·.step2개), STL4개, 3MF1개, 동반 TXT5개**다. 처음 구두 집계의 STEP20개/STL5개는 잘못 센 값이며 실제 파일별 manifest로 정정했다. 원본 파일은 변경하지 않았고 형상26개 모두 입력을 시도했다. 파일마다 별도 프로세스로 실행했으며, 4공정의 장비 공간은 `None`으로 지정해 공간 크기로 거절하지 않았다. STL 치수는 단위 없는 mm 가정이며 재조정하지 않았다. 기본 방향은 +Z, 비교 후보26개다.

입력21개 성공,5개 거절. 조립체 전체와 개별 솔리드를 구분한50대상×4공정=200개 검토 보고서를 만들었다. 법선 거리148개 measured,4개 partial,48개 unknown. MEX 층 검토는32개 complete,1개 partial,9개 unknown,8개 unavailable였다. 다른3공정의150개 층 검토는 모두 N/A였다. 이 수치는 제조 성공률이 아니다.

독립 좌표투영·삼각형 외적 계산으로 비교한200개 보고서의26방향 높이/하향면 투영합/강체변환/공간 무제한 계약에서 불일치는 없었다. CAD 대 메시 체적의 최대 상대 차이는0.093224%였다. 같은 메시를 사용한 산술 검증과 전체 체적 대조는 CAD의 모든 국소 면이나 열·강도·프린트 결과를 검증하지 않는다.

거절 파일과 이유는 그대로 보존했다.

- `12.1 Bracket.stp`: 폐솔리드 없음.
- `3.1 Gear_Set_2D.stp`: 폐솔리드 없음.
- `3.4 Valve_RM_20130113.stp`: CAD 면124의 삼각형 없음.
- `Raspberry Pi 4 Model B.step`: 솔리드100개/면20,000개 제한.
- `the-over-engineered-backpack-wall-mount-v2.3mf`: 당시 입력 형식 미지원.

집계는 [baseline-statistics.json](../../validation/v3/random-corpus/baseline-statistics.json)에 있다. 전체 원본별 JSON·HTML·배율·프로필·실행 환경·SHA·메시 캐시는 저장소 옆 `study/random-shape-audit/baseline-01/`에 보존한다. 원형상은 저장소에 재배포하지 않았다. 당시 엔진은 `baseline-source/`, 당시 배치 스크립트는 `baseline-audit-script.py`에 별도 동결했다.

## 900-602 공급사 값의 독립 대조

공급사 동반 TXT는 단면30×30, 길이6m 공급, 단면2차모멘트 Ix=Iy=2.85cm⁴를 표시한다. STEP 외곽30×30×6000mm는 일치했다. 그러나 CAD 체적 관성에서 일정 단면 압출로 역산한 Ix=26650.25, Iy=26670.65mm⁴는 TXT의28500mm⁴와 약6.4~6.5% 차이가 났다.

다른 계산으로도 재확인했다. 모델 높이 중앙에서 메시와 평면의 교선을 추출하고, 닫힌 루프6개의 포함관계와 shoelace 적분으로 구한 단면적은301.459835mm², Ix=26654.525, Iy=26674.983mm⁴였다. 메시 체적·관성에서 역산한 결과와 일치하며 CAD 적분값과 약0.02% 차이다. 다운로드된 CAD와 공급사 단면 명세를 같은 정답으로 취급할 수 없다는 반례다. 카탈로그 수치에 맞추기 위해 형상을 수정하지 않았다.

- STEP SHA-256: `a82f75d019b5e4b2f30a2f856413c10d4a0b260bae2329e43d56518c330e5797`
- TXT SHA-256: `8f07f64b043e74e9d193fcccd2836ca73be8290080d7bc7aed4a693bfd0f8ee9`
- [재현 스크립트](../../scripts/check_catalog_section.py), [측정 결과](../../validation/v3/random-corpus/supplier-section-900-602.json)

재현 예: `python scripts/check_catalog_section.py --audit <감사폴더> --source /900-602.stp --catalog-inertia-mm4 28500 --out <새결과.json>`. 교선 끝점 결합은0.0000001mm 반올림, 관성의 체적/길이 역산은 일정 단면 압출이라는 가정이다. 실제 소재 밀도·출력성·강도는 이 비교에서 도출하지 않는다.
