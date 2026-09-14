# AM-DFM 3.0

적층제조 부품의 **문제 위치·이유·수정 방법·방향별 손익**을 확인하는 한국어 설계 검토 도구다. STEP/STL을 읽고 CAD 원통면, 하향면, 바닥 접촉, 빌드 공간, 밀폐 공동, 법선 거리 표본과 MEX 층간 관계를 검토한다. 출력 성공 점수나 A/B 등급을 만들지 않는다.

## 실행

현재 Windows 작업공간에는 `.venv`와 의존성이 설치되어 있다. `START_REVIEW.cmd`를 실행하거나 다음 명령을 사용한다.

```powershell
.\.venv\Scripts\python.exe -X utf8 -m streamlit run app.py --server.port 8507
```

[로컬 앱 열기](http://127.0.0.1:8507). 앱은 로컬 컴퓨터에서 동작한다. 파일은 외부 분석 서버로 전송하지 않는다.

다른 환경에서는 Python 3.12를 설치하고 `INSTALL.cmd`를 실행한다. 또는:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 사용 순서

1. **CAD 기준형상**, **내 파일**, **외부 STL 사례** 중에서 입력을 고른다. STEP은 선언 단위를 mm로 변환한다. STL은 단위·배율을 선택한다.
2. 공정과 위로 향할 모델 축을 고르고 **설계 검토**를 누른다. 먼저 문제 위치와 필요한 조치를 확인한다.
3. **방향 비교**에서 투영면적·높이·바닥 면적·빌드 공간을 비교하고 원하는 방향을 적용한다.
4. 필요하면 **정밀 검토**에서 벽 또는 MEX 층간 관계를 계산한다. G-code를 읽거나 Cura의 기준 실험 경로도 확인할 수 있다.
5. **수정 전후**에서 변경 전 결과를 저장하고 수정 파일을 같은 조건으로 검토한다. 코드·프로필·배율·방향이 다르면 개선량을 만들지 않는다.
6. **근거·내보내기**에서 HTML 보고서, 전체 JSON, 현재 방향 STL, 입력 원본을 내려받는다.

원본 STL에 단위가 없으면 실제 치수를 추정해 자동 수정하지 않는다. 예를 들어 포함된 외부 사례 `3DP_20546_S-0039.stl`의 좌표 범위는 150×142×25,000이다. mm 가정에서는 높이 25 m이며 이것이 실제 부품 치수라는 뜻은 아니다. 최장 길이 입력은 **전체 등방 배율**을 바꾸며 한 축의 오류를 복원하지 않는다.

## 공정별 범위

| 공정 | 제공하는 검토 | 별도 확인할 내용 |
|---|---|---|
| MEX / FFF / FDM | 공통 형상, 하향면·바닥·벽 표본, 층간·선폭 관계, G-code 경로 | 실제 비드·브리지 처짐·열변형·접착·강도 |
| VPP / SLA / DLP | 공통 형상, 하향면 후보, 원통면, CAD 밀폐 경계 | 박리력·흡착·서포트 접점·세척·후경화 |
| 고분자 PBF / SLS | 공통 형상, 원통면·CAD 밀폐 경계·공간·높이 | 분말 제거·수축·열 이력. MEX 오버행/층 규칙 미적용 |
| 금속 PBF / LPBF | 공통 형상, 하향면 후보, 원통면·CAD 밀폐 경계 | 열전달·잔류응력·변형·분말/지지 제거·후가공 |

기본값은 미확정 장비를 위한 탐색 조건이다. 최소 벽·홀 기준은 선택 입력이며 기준 출처를 함께 기록한다. 형상만으로 강도·인쇄 성공·표준 적합성을 판정하지 않는다. BJT·DED·MJT·SHL 등 다른 공정과 다축 적층의 자동 규칙은 이번 범위에 포함하지 않았다.

## 검증과 개발 근거

- [문헌 조사·기존 제품 비교·v2.6 평가·교수님 피드백 반영](docs/research/AM_DFM_RESEARCH_AND_DESIGN.md)
- [구조와 수치 계약](docs/ARCHITECTURE_V3.md)
- [실행한 검증 결과와 남은 한계](docs/VALIDATION_V3.md)
- [기존 인수기록과 참고문헌](docs/project-knowledge/README.md)
- [치수가 알려진 자체 CAD 14개](examples/cad/manifest.json)와 [생성 소스](scripts/generate_cad_examples.py)

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest tests_v3 tests -q
.\.venv\Scripts\python.exe -X utf8 verify_legacy.py
```

새 예제 생성은 기존 기준형상을 덮어쓰지 않도록 새 폴더에 한다.

```powershell
.\.venv\Scripts\python.exe scripts/generate_cad_examples.py examples/new-cad-run
```

설치된 CuraEngine으로 독립 리브 실험을 재실행하려면 새 출력 폴더를 지정한다. 실제 프린터로 G-code를 보내는 기능은 없다.

```powershell
.\.venv\Scripts\python.exe scripts/run_cura_experiment.py --out validation/v3/new-cura-run
```

## 원본과 개선 소스

루트 PDF·DOCX·ZIP은 기존 원자료이며 보존했다. 기존 실행 코드는 ZIP에서 `src/`로 복사했고 새 패키지는 `amdfm/`, 새 UI는 `app.py`다. `run_app.py`도 새 앱으로 연결된다. 과거 점수 UI를 재현하는 용도로만 `streamlit run run_legacy.py`를 사용한다. 새 앱은 과거 점수 엔진을 호출하지 않는다.

`cura_run/`은 기존 실험의 보존본이고 `validation/v3/`는 이번 실행 기록이다. 새 분석을 과거 측정값 위에 쓰지 않는다. 외부 STL 사례는 로컬 `examples/external/`에 있으며 Git 추적에서는 제외했다.

소스 배포 ZIP에는 앱·코드·테스트·자체 CAD·문헌 조사·검증 기록이 포함된다. 원래 보관한 PDF/DOCX/ZIP, 외부 STL 형상, Python 실행환경과 설치 의존성은 포함하지 않는다. 원자료 링크는 전체 GitHub 저장소를 기준으로 한다. 새 설치에서는 `INSTALL.cmd`부터 실행한다. GitHub Actions에는 Windows 회귀검사 절차를 추가했으며 실제 원격 실행 성공 여부는 해당 실행 기록으로 확인한다.

## 입력·계산 한도

STEP/STL 80 MiB, 삼각형 600,000개, CAD 면 20,000개와 솔리드 100개를 상한으로 둔다. STEP 변환 75초, 벽 검토 60초, UI 층간 검토 90초를 넘으면 이유를 기록하고 기존 빠른 결과를 유지한다. 층간 검토는 최대 1,500층·교차 선분 1,500,000개다. 한도를 맞추기 위해 몰래 층 간격을 늘리지 않는다. 큰 모델의 화면은 250,000개까지 삼각형을 표시하며 분석·방향 STL은 전체 형상을 사용한다.

STEP 변환 중 OCCT의 기본 shape processing이 적용될 수 있다. 원본 파일 바이트는 보존하고 변환된 B-rep의 유효성을 확인한다. 구 극점의 면적 0 계산용 삼각형은 CAD 경로에서만 제거하며 변경 수와 CAD 면 연결을 기록한다. STL은 기본 경로에서 자동 수리하지 않는다.
