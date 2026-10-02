# 바탕화면 실행본 갱신 — 2026-09-26

## 확인 및 반영

- 실행본: `C:\Users\JIN\Desktop\AM-DFM_v3_0`
- 기준 저장소: `C:\Users\JIN\Documents\ChatGPT\DFM\DFM-Project`
- 기준 커밋: `d8d1ab010f24111f8f2835157ccd4b93de667a00`
- 갱신 전에는 `dfm/` 모듈과 절삭 검증 STEP 12개가 없었고, `app.py`가 최신 코드와 달랐다. 절삭가공 화면이 반영되지 않은 구버전이었다.
- 추적된 실행 코드·설치/실행 스크립트·예제·테스트·텍스트 설명서 329개를 대조했다. 60개 추가, 21개 교체, 248개 동일이었다. 동기화 후 329개 모두 저장소 SHA-256과 일치한다.
- `release_manifest.json`은 이전본을 백업한 후 현재 동기화 범위와 기준 커밋·파일 SHA를 기록한 매니페스트로 갱신했다. 81개 소스/자료 변경 외에 생성 매니페스트 1개가 교체된다.
- `.venv`·사용자가 추가한 형상·검토 결과·기존 로그·과거 검증 자료는 삭제하거나 덮어쓰지 않았다. 기존 참고문헌 원본 PDF나 과거 ZIP은 실행 배포본으로 재복사하지 않았다.
- 본 작업은 최신 개발 코드의 배치이며, 저장소 런타임 소스 수정이나 Git 커밋은 하지 않았다.

## 복구 자료

교체 전 파일 백업: `backup-20260926-120354/`

`backup-20260926-120354/before-and-plan.json`에 작업 전/후 SHA와 변경 종류가 있다. 각 교체 파일은 같은 상대 경로에 보존했다. `sync-result.json`은 완료 상태이며 `sync_desktop.py`는 이번 작업 스크립트다. 추가된 파일을 포함하여 어떠한 삭제도 수행하지 않았다.

## 실행 및 환경

- 일반 실행: 바탕화면 `AM-DFM_v3_0/START_REVIEW.cmd`
- 기본 주소: `http://127.0.0.1:8507/`
- 화면의 `제조 공정`에서 `절삭가공` 선택 후 `입력 → 절삭 검증 형상`으로 내장 예제를 사용할 수 있다.
- Python 3.13.15, Streamlit 1.63.0, OCP 7.9.3.1, trimesh 5.1.0 import 확인.
- `python -m pip check`: `No broken requirements found.`
- `scripts/start_review.py --help`: 정상. `START_REVIEW.cmd`와 이 스크립트는 이전 실행본도 저장소와 동일했다.
- 갱신 착수 시 기존 Streamlit 서버 및 8507 수신 프로세스가 없었다. 무관한 프로세스를 종료하지 않았다.

## 검사

실제 바탕화면 `.venv`와 바탕화면 소스로 아래 기존 회귀검사를 실행한다. 이 기록은 전체 823개 재실행을 뜻하지 않는다.

```
python -X utf8 -m pytest tests_v3/test_machining_ui.py tests_v3/test_machining_review.py tests_v3/test_start_review.py -q --junitxml=desktop-focused.xml
```

`desktop-focused.log`, `desktop-focused.xml` 참조. **68개 통과, 86.55초**, 실패·생략 없음. 절삭 화면 진입, 공구 미입력 상태, 공구 치수 변경과 조건 충돌, 표면 가림 표본 표시, 적층·절삭 전환과 이전 결과 분리, 12개 CAD 예제의 독립 치수·반례, Windows 중복 실행/포트 충돌 처리 계약을 검증했다.
