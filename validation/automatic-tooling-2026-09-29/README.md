# 빈 공구 치수 자동 제안 검증

- [최종 요약](summary.json): 동일한 실행 코드에서 고유1,445검사의 최종 통과 상태, 바탕화면54검사, 실제 브라우저 확인.
- [V3 첫 실행](full-001.xml):1,277통과/1실패. 옛 미입력 기본 동작을 기대한 시험을 새 opt-out 흐름에 맞췄다.
- [재검사+기존 검사](base-and-missing-input-recheck.xml):177통과(기존167+해당 화면10). 초기 실패를 삭제하거나 처음부터 통과한 것으로 바꾸지 않았다.
- [STEP 합산](cad-combined.json):33파일297조건.31파일279조건은 [첫 실행](cad-run-001/records.jsonl), 마지막2파일18조건은 [재실행](cad-run-002/records.jsonl). 최초75초 로더 제한은 [중단 기록](cad-run-001/interrupted.json)에 있다. 재실행에만180초를 허용했다.
- 297조건 중44조건에서110개 자동 입력을 생성했다. unavailable210개와 not_applicable21개를 정상 추천으로 세지 않는다. 같은 기하 엔진으로 재검산한 통합 계약 검사이며 독립 특징 인식 정확도는 아니다.
- [가중치 SHA](unchanged-models.json): 이번 작업에서 새 모델을 훈련하지 않았다.

단차홀·멀리 떨어진 돌출부·짧은 날·미지원 면·입력 불변의 독립 반례는 `tests_v3/test_tool_recommendation.py`, UI는 `test_automatic_tooling_ui.py`에 있다. 공개 데이터 샘플/분할 감사는 [연구 기록](../../docs/research/public-cad-data-2026-09-29/MFCAD.md)으로 분리했다.
