# 절삭 재감사 실행 증거

현재 범위는 적층·절삭이다. 이번에 추가했던 사출·프레스 구현·시험·예제·생성 결과는 사용자의 지시에 따라 제거했다. 원본 문헌과 이전 적층·절삭 기록은 보존했다.

## 최종 실행

| 기록 | 결과와 해석 |
|---|---|
| `regression-complete.txt/xml` | **818 통과, 1 경고, 483.46초**, 종료 코드 0. 최종 소수 각도 표시 수정까지 포함한다. |
| `legacy.txt` | 기존 별도 검증 55/55 통과, 종료 코드 0. |
| `geometry/final-subset.txt/xml` | 새 독립 계산 22개를 포함한 131개 통과. 회전·이동·인치·수치/축 경계·교차/분할 원통·포켓 오인식 반례. |
| `ux-color-final.txt/xml` | 새 UX 15개+기존 UI5개, 20 통과. 이후 추가 소수 각도 시험은 전체818에 포함했다. |
| `observations-complete/summary.json` | 최종 코드의 자체 절삭 예제 12개 관측. 가상 공구 조건 D4/날10/돌출15이며 물리 검증 조건이 아니다. |
| `engine-source-complete/manifest.json` | 최종 엔진·앱 Python 소스 43개와 개별 SHA·환경 보관. |
| `removal-verification.json` | 새 사출·프레스 코드·화면·예제·시험·문서·생성 결과와 관련 바이트코드 부재 확인. |
| `ui/BROWSER_QA.md` | 실제 내장 브라우저의 반경 수정 전후, 위치·색, 각도, 가림 필터, 적층 복귀 확인. |
| `corpus-observations/` | 기존 무작위 26개 입력의 처리·지원 범위 관측. 초기 45초에서는 24개 처리·2개 시간 초과, 해당 2개만 실제 앱의 180초 한도로 재시도하여 처리 완료. 제한 CAD 9개·부품 선택/입력 범위 등에 따른 정량 보류 17개. 독립 치수 정확도 검사가 아니다. |

최종 코드 SHA는 `9b8fda0296c7bccb9fa320a9ffa15638f11a738ca497bc11b6925dfbdf674fe5`. 전체 회귀 후에도 소스 보관본과 현재 생산 파일의 해시가 같음을 확인했다. 경고는 기존 Trimesh의 체적 기반 질량중심 계산에서 발생했으며 해당 시험은 통과했다.

## 초기·중간 실행을 보존한 이유

- `regression.txt`, `regression-final.txt`는 각각 실제 화면에서 색/스크롤 개선과 소수 각도 표시 문제를 찾아 중단한 부분 실행이다. 최종 통과 검사로 세지 않는다.
- `observations-final/`은 소수 각도 UI 표시 수정 전의 동일 계산 엔진 관측이며, 최종 전체 코드 식별자가 있는 `observations-complete/`와 구분한다.
- `geometry/first.*`의 테두리 후보 오인식과 문구 계약 실패, `ux-first.*`의 기대값 문제를 삭제하지 않았다. [계산 기록](geometry/README.md)과 [UX 기록](../../docs/project-knowledge/MACHINING_UX_AUDIT_2026-09-20.md)에 원인과 수정 근거가 있다.

전체 보고서는 [절삭 재감사](../../docs/project-knowledge/MACHINING_REAUDIT_2026-09-20.md), 문헌의 역할과 조건은 [문헌 재감사](../../docs/research/MACHINING_EVIDENCE_REAUDIT_2026-09-20.md)를 따른다. 이 기록은 실제 가공 시험·CAM 공구 충돌·제조 성공 확률 검증이 아니다.
