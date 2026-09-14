# 설치 창 즉시 종료 수정

사용자가 배포본의 INSTALL을 실행하면 창이 즉시 닫힌다고 보고했다. 바탕화면 `AM-DFM_v3_0`의 설치 파일과 최초 배포 manifest가 일치하는 것을 확인한 뒤 해당 복사본도 수정했다. 기존 설치/시작 파일은 같은 폴더의 `installer-backup-20260914/`에 보존했다.

## 원인

`py --list-paths`에는 Python 3.13만 등록되어 있었다. 기존 `INSTALL.cmd`는 무조건 `py -3.12 -m venv .venv`를 호출했으므로 `No suitable Python runtime found`로 실패했다. 이어지는 `if errorlevel 1 exit /b 1` 때문에 마지막 `pause`에 도달하지 못했다. 기존 앱 회귀검사는 INSTALL의 Explorer 실행 경로를 검증하지 않아 이 결함을 놓쳤다.

## 수정

- 정상 기존 `.venv`를 먼저 탐색하고 재사용한다. Python 3.12/3.13의 64-bit 실행환경을 지원한다.
- 명시 경로 `AM_DFM_PYTHON`, py 런처, PATH의 실제 Python을 탐색한다. WindowsApps 별칭을 설치된 Python으로 오인하지 않는다.
- 설치 본체는 표준 라이브러리만 사용하는 `scripts/install_environment.py`로 옮겼다. 프로젝트 안에만 가상환경을 만들고, pip 설치·일관성·앱/STEP import를 확인한다.
- 성공과 실패 모두 공통 종료 경로에서 창을 유지한다. 자동검사에만 `--no-pause`를 사용한다.
- Python 탐색 로그와 매 실행의 상세 로그를 `logs/`에 남긴다. `--diagnose`는 의존성을 변경하지 않는다.
- 불량 기존 `.venv`는 자동 삭제/덮어쓰기하지 않으며 새 폴더 설치를 안내한다.
- START_REVIEW와 VERIFY의 오류도 창에 남도록 수정했다. GitHub Windows 검증을 Python 3.12/3.13 행렬로 확장했다.

## 검증

실제 CMD 반례 5개가 통과했다: 한글·공백·괄호 경로, 명시 Python과 빈 PATH, 앱 파일 누락 로그, 실패 후 pause 대기와 Enter 종료, Python 누락 및 불량 `.venv` 보존. Python 3.13 의존성 dry-run은 바이너리 wheel만 허용한 상태에서 성공했다. 실제 설치·런타임 시험의 후속 결과는 배포 폴더의 설치 로그와 전달 확인 기록을 따른다. wheel 해결만으로 전체 런타임 호환이 검증됐다고 표현하지 않는다.

분석 엔진과 CAD 기준형상은 변경하지 않았다. 기존 3.0 수치 검증 기록은 해당 코드 SHA와 함께 그대로 보존한다.
