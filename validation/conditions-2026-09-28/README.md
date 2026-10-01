# 조건 DB 검증 기록

2026-09-28. 실제 출력·가공 실험은 수행하지 않았다.

| 기록 | 결과 |
|---|---|
| `catalog-audit-final.json` | 62개 조건·270개 값 스키마/출처 연결 검사, 기존 문헌 43개 파일 해시 대조 통과 |
| `regression-final.txt/xml` | 저장소 Python 3.12.14, 전체 938개 통과·경고 1개, 370.57초 |
| `desktop-focused.txt/xml` | 바탕화면 Python 3.13.15, DB·통합·UI 115개 통과, 30.24초 |
| `am-source-verification.json` | 고정 Prusa INI 58개 값과 SHA, AM PDF 도표 검토 기록 |
| `cnc-source-verification.json` | 19개 공구 치수 및 카탈로그/소재 원문 대조 기록 |
| `browser-am.txt/png`, `browser-cnc.txt/png` | 바탕화면 서버에서 조건 선택→적용→실제 검토와 출처 확인 |

115개 집중검사는 전체 시험의 일부를 다른 Python 환경에서 재검사한 것이므로 938개와 합산하지 않는다. 전체 시험의 경고는 기존 Trimesh의 `test_aabb_overlap_is_not_solid_overlap` 체적 계산 경고다.

`regression-01`은 최초 931통과/3실패 기록이며 최종 판정에는 사용하지 않는다. 실패 수정 내용은 [인수 기록](../../docs/project-knowledge/CONDITION_DATABASE_2026-09-28.md)에 있다. `catalog-audit-01`도 초기 상태를 보존한 기록이며 최종 DB는 `catalog-audit-final`을 따른다.

테스트는 기하 계산, 단위/출처 보존, 입력 격리, 기준형상 대조, 화면 동작을 검증한다. 제조 성공률, 공구 안정성, 열변형, 강도 또는 표준 적합 인증을 검증한 것은 아니다.
