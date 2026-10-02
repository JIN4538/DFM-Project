# 절삭 1차 확장 검증 자료

2026-09-19~20 개발 작업공간에서 실행했다. 폴더 날짜는 작업 시작일이며 배포 날짜가 아니다. 범위와 구현 이유는 [구현 기록](../../docs/project-knowledge/MACHINING_IMPLEMENTATION_2026-09-19.md), 사용자 설명은 [절삭 안내](../../docs/USER_GUIDE_MACHINING.md)에 있다.

## 최종 자료

| 자료 | 확인 범위 |
|---|---|
| [전체 회귀 출력](regression-complete.txt), [JUnit](regression-complete.xml) | 현재 소스의 tests_v3와 tests: **780 통과·경고 1건, 509.27초** |
| [레거시 검사](legacy.txt) | 별도 verify_legacy.py 55/55 통과 |
| [UI·결과 계약 검사](ui-contracts-selection-final.txt) | 선택 항목 유지 수정 후 25/25 통과 |
| [실제 브라우저 QA](ui/UI_QA.md) | 설치된 Edge의 별도 headless context에서 8개 흐름 통과, page error 0건. 화면·자동화 실패와 최종 결과를 구분한다. |
| [12개 형상 관측](observations-final/summary.json) | 자체 STEP의 생성 치수와 실제 관측을 함께 보존. 가상 공구 조건 D4/날10/도달15 mm이며 관측 저장 자체가 독립 시험을 대체하지 않는다. |
| [최종 엔진 식별](engine-source-final/manifest.json) | 실행에 사용한 Python 소스·requirements.txt 49개와 SHA. 데이터·실행환경은 상위 저장소를 사용한다. |
| [작업자 기동·종료 시험](process-timing/README.md) | 짧은 시험 준비 시간 가정의 실패, 실제 기동 시간, 보강한 독립 18/18 통과 기록. 생산 시간 제한 코드는 바꾸지 않았다. |

최종 엔진 코드 SHA: `2d668f2a637e9338356acae7f5fa3c7338faedb723a1200f0705d39003af6d86`.

전체 회귀의 경고 1건은 기존 `test_aabb_overlap_is_not_solid_overlap`에서 발생한 Trimesh 체적 기반 질량 중심 나눗셈 RuntimeWarning이다. 해당 시험은 통과했다.

## 이전 실패의 보존

- `regression.txt/xml`: 776 통과·3 실패. 새 패키지의 감사 스냅샷 누락 2건과 확장 전 형상 색인 기대값 1건이다.
- `regression-final.txt/xml`: 777 통과·2 실패. 작업자 시험의 준비 시간 가정 실패이며, 단독 재현과 후속 계측은 `process-timing/`에 있다.
- `process-isolated-retest.txt`: 보강 전 작업자 시험 14 통과·4 실패. 전체 회귀 부하만을 원인으로 단정하지 않는다.
- `observations/`: 최종 UI 변경 전 코드에서 얻은 관측이다. 최신 관측과 코드 SHA를 혼합하지 않는다.
- `ui/`: 초기 자동화 실패, 수정 전 실제 선택·본문 불일치, 수정 뒤 최종 브라우저 결과를 덮어쓰지 않고 보존한다.

검사 통과는 해당 조건에서 소프트웨어의 계산·상태·표시를 확인한 결과다. 실물 가공 실험, 유한 공구·홀더·고정구를 포함한 CAM 검증, 사람 대상 사용성 평가, 제조 성공 확률 검증은 수행하지 않았다. 바탕화면 앱과 기존 8507 서버도 이 검증으로 갱신되지 않았다.
