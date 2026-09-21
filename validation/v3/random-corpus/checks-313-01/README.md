# Python 3.13 전체 회귀검사

2026-09-15, Windows 11에서 바탕화면 배포본의 기존 Python 3.13.15 가상환경으로
현재 저장소의 `tests`와 `tests_v3`를 실행했다. 작업 디렉터리와 실제 `amdfm` import 경로는
현재 저장소다. 바탕화면의 애플리케이션 소스를 검사 대상으로 바꾸거나 편집하지 않았다.

- 실행 파일: `C:/Users/JIN/Desktop/AM-DFM_v3_0/.venv/Scripts/python.exe`
- 엔진 코드 SHA-256: `dfa1f3f44c96a19ee5ffd3dd11fc8b882034b5dfdf51783bf0bc29fc01ea45fa`
- 전체 결과: **458 passed, 1 warning in 203.84s**. 실패·오류·건너뜀은 모두 0개다.
- `pip check`: **No broken requirements found.**
- 시작과 종료 시 기록한 애플리케이션 및 검사 파일 SHA가 모두 동일하다.
- 비교용으로 전달받은 Python 3.12 결과는 458개 통과·기존 경고 1개, 210.33초다.
  실행시간 차이는 이 두 번의 관측이며 Python 버전별 성능 우열의 근거로 삼지 않는다.

유일한 경고는 `tests/test_review.py::ReviewRegression::test_aabb_overlap_is_not_solid_overlap`에서
Trimesh의 질량중심 계산 `center_mass = integrated[1:4] / volume`이 발생시킨
`RuntimeWarning: invalid value encountered in divide`다. 경고를 필터링하거나 코드를 수정하여 숨기지 않았다.

주요 환경은 Streamlit 1.63.0, NumPy 2.3.5, SciPy 1.17.0, Shapely 2.1.2,
Trimesh 5.1.0, pytest 8.4.2다. 전체 의존성 버전, 실행 경로, Git HEAD와 개별 소스·검사 SHA는
`environment.json`에 기록했다. 콘솔은 `pytest.txt`, JUnit은 `pytest.xml`, 의존성 검사는
`pip-check.txt`, 완료 상태·경고·출력 SHA 및 전후 소스 동일성은 `result.json`에 있다.

실행 명령:

```powershell
& 'C:/Users/JIN/Desktop/AM-DFM_v3_0/.venv/Scripts/python.exe' -X utf8 -m pytest tests tests_v3 -q --junitxml=validation/v3/random-corpus/checks-313-01/pytest.xml
& 'C:/Users/JIN/Desktop/AM-DFM_v3_0/.venv/Scripts/python.exe' -X utf8 -m pip check
```

이 결과는 위 Windows·Python·의존성 조합에서 현재 저장소 코드의 회귀검사가 통과했다는 기록이다.
다른 Python 구현·모든 운영체제·실물 적층제조 성공을 보증하지 않는다.
