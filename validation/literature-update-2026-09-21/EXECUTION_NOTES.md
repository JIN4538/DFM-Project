# 실행 조건과 중단 기록

2026-09-21 첫 전체 명령은 `python -X utf8 -m pytest tests_v3 tests -q`였다. `regression.txt`에 8% 진행 표식만 남았으며 최종 JUnit/통과 수는 생성되지 않았다. Windows에서 PowerShell과 tasklist까지 메모리 부족으로 실패했다. 해당 실행은 중단했고 최종 통과로 합산하지 않는다. 별도 빠른 근거 검사 `evidence.txt`의 44개 통과와도 구분한다.

메모리 회복을 확인한 뒤 전체 명령을 다시 실행했다. 과도한 수치 라이브러리 스레드 생성을 줄이기 위해 재실행 프로세스에만 `OPENBLAS_NUM_THREADS=1`, `OMP_NUM_THREADS=1`, `MKL_NUM_THREADS=1`, `NUMEXPR_NUM_THREADS=1`을 지정했다. 알고리즘/수치 임계값이나 운영체제 설정은 변경하지 않았다.

두 번째 실행은 822개 통과·1개 실패·경고 1건(284.79초)이었다. `test_finding_evidence_matches_calculation_and_does_not_claim_cad_for_mesh_rays`가 기존 출처 1개를 기대했지만 새 Nelaturi 출처가 추가되어 실패했다. `regression-before-expectation-update.txt`와 `.xml`에 그대로 보존했다. 기대 목록을 새 출처와 맞추고, 해당 출처가 유한 공구 알고리즘의 구현을 주장하지 않는다는 검사도 유지·보강했다. 런타임 계산식은 바꾸지 않았다.

이후 같은 전체 명령으로 다시 실행한 결과가 `regression-final.txt`와 `regression-final.xml`이다. 문서의 최종 통과 수는 이 파일에서 읽으며 이전 실행을 합산하지 않는다. 별도 레거시 검사는 `legacy.txt`의 55/55다.
