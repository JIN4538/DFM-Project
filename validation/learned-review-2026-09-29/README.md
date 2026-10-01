# 내장 규칙 학습 AI·결론 화면 검증

구현·바탕화면 배치와 아래 검증을 완료했다. 원본 파일의 실행 단위와 버전을 구분한다.

- [모델 학습 기록](MODEL_REPORT.md): 55,000개 수치 시나리오, 11개 결정트리, 원시 예측과 규칙 재확인의 구분.
- [최종 독립 수치 평가](training-final-006/training-evaluation.json): 개발 후 새 시드로 평가한 일반·무작위 경계·크기 변화 27,500건.
- [어댑터 수정 후 재실행](adapter-recheck-provenance.json): 007은 006과 같은 데이터·트리·범위·지표다. 새 독립 시험으로 더하지 않는다.
- [인접 부동소수점 스트레스](numeric-nextafter-stress.json): 36건 중 원시 예측 13건 불일치. 규칙 확인 후 알려진 문제를 잘못 해제한 경우는 0건.
- [실제 CAD 계산](cad-integration-001/summary.json): STEP 26개에서 AM 4공정·CNC 공구/방향 조건 122건. 알려진 치수 대조 409건, 결론·범위 검사 608건, 미입력 보존 84건 통과. 수치 입력 5,198건의 원시 모델 조치와 교사 조치 일치.
- [최종 어댑터로 재평가](cad-replay-001/summary.json): 위 측정값을 재사용한 122건이다. 기하 계산을 새로 122번 한 것이 아니다. 원본 보고서 SHA와 변경되지 않은 기하 교사 소스를 대조했다. 빌드 제한 미적용 80건을 추가로 확인했다.

## 회귀 검사 기록

`legacy.txt/xml`은 기존 엔진 167개 통과다. `regression-initial.txt/xml`의 14개 실패는 이전 문구·버튼·표 순서를 기대한 화면 검사였으며, 최초 실패를 보존했다. 새 UI에서 동일 치수·위치·출처·미완료 상태가 유지되는지를 확인하도록 갱신하고 관련 검사들을 재실행했다. 최종 전체 실행은 `regression-final.txt/xml`에 기록한다.

`compact-*.txt/xml`, `cnc-related-final.txt/xml`, `model-tests-*.txt/xml`은 각 실행의 관련 검사다. 같은 검사를 여러 번 실행한 수를 독립 검사 수로 합산하지 않는다.

## 범위

학습 모델의 대상은 측정값에 따른 문제·조치 종류다. STEP 특징 인식 자체를 AI가 학습한 것으로 설명하지 않는다. 알려진 치수 대조, 기존 규칙과의 일치, 화면 연결 검사는 서로 다른 검증이다. 문헌 규칙 밖의 결론을 추가하거나 미측정 값을 정상으로 바꾸지 않는다.

## 최종 상태

- 전체 v3 재실행: **1,103개 통과** (`regression-final.txt/xml`).
- 마지막 입력 구조 수정 뒤 관련 검사: **41개 통과** (`final-input-ui.log/xml`).
- 바탕화면 Python 3.13.15 실제 실행 환경: **82개 통과** (`desktop-final.txt/xml`). scikit-learn 설치 없이 실행했다.
- 마지막 코드의 보존 CAD 재평가: **122건 통과** (`cad-replay-final/summary.json`).
- 실제 브라우저: `browser-desktop-wall-final.png/txt`. 최소 벽 1 mm를 입력한 뒤 본문 버튼을 사용하여 0.3 mm 판의 벽 보강 결론을 확인했다.
- 절삭 브라우저: `browser-desktop-cnc-final.png/txt`. 포켓 3 mm / 공구 4 mm, 벽 높이 20 mm / 날 8 mm / 돌출 10 mm의 적용과 개선 조치를 확인했다.

최종 코드 SHA: `b8ca7cc8a86d8a79a1c80f9564f003e427a4432c24b5e0f16e36e996f3ae7de8`. 모델 SHA: `07cc7514fe4276a9f967a77bcc9970c13a922f3695853b8f63eb8e84250693a7`.
