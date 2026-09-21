# 절삭 화면 QA — 최종 실제 브라우저 검증

**최종 결과: 독립 Edge 브라우저의 8단계 흐름을 통과했다.** 아래의 최초 실패를 수정한 뒤 `final-browser-v3/`에서 새 임시 context로 재검증했다. 이 폴더의 실제 PNG를 열어 수치, 강조 위치, 범례와 좁은 화면을 확인했다. 기하 검토의 UI 검증이며 실제 가공 성공이나 모든 기기에서의 사용성을 검증한 것은 아니다.

검토 대상은 저장소 `app.py`의 독립 서버 `http://127.0.0.1:8510/`이다. 기존 사용자 서버 8507과 바탕화면 앱은 조작하지 않았다.

## 실행 환경과 실제 화면 여부

- `server.json`에 숨김 실행한 venv Python PID 6336을 기록했다. 실제 리스너 PID 1912는 PID 6336의 자식이며 `server_processes.json`으로 확인했다.
- CUA `getState()`는 `apps=[]`, `browsers=[]`를 반환했다. `iab`과 `chrome` 탭 생성은 모두 `Browser is not available`로 실패했다.
- 요청된 대안으로 번들 Playwright와 이미 설치된 Microsoft Edge 153.0.4234.32를 사용했다. 각 실행은 **새 임시 headless context**이며 사용자 브라우저 프로필에 연결하지 않았다. 설치·다운로드는 없었다.
- `*.png`는 실제 Edge 렌더링 캡처다. 별도 `apptest_*`와 `*.plotly.json`은 Streamlit 상태·차트 명세 검증이며 스크린샷으로 간주하지 않는다.
- Python 3.12.14, Streamlit 1.63.0, Node 24.19.0을 사용했다. 최종 검증의 `dfm/machining_view.py` SHA256은 `54A7A42EE703628F884B3F0C65A303CFACF68B9465EE4368BB95D47CF6704FF1`이다.

## 최초 검증과 발견한 문제

1. `apptest_workflow.py`: 직사각 포켓 Ø8/날10/도달15 → 둥근 포켓 R3/Ø8 충돌4개 → Ø4 충돌해소 → 블록 표본분류 → 적층 복귀 5단계를 통과했다. `apptest_result.json`, `apptest_snapshots.json` 및 Plotly 명세에 기록했다.
2. 최초 브라우저 대기는 적층 버튼의 accessible name에 `play_arrow` 아이콘이 포함되는 것을 테스트가 빠뜨려 실패했다. 제품 오류가 아니다. `browser_initial_selector_timeout.*`에 보존했다.
3. 최초 직사각 화면은 rerun 중에 캡처되어 Stop과 표의 skeleton이 보인다. 이 화면으로 최종 가독성을 판단하지 않는다.
4. 각 조작 뒤 Stop이 사라지고 추가 렌더링이 끝날 때까지 기다린 `settled-browser/10_rectangle_tool8_wide.png`에서는 폭12/길이20/벽높이8 표와 다음 행동, 주황 바닥을 실제로 확인했다.
5. **항목 선택과 본문의 불일치가 두 번 재현됐다.** 직사각 포켓에서 둥근 포켓으로 변경·검토한 뒤 오목 원통면을 선택하면 dropdown에는 새 항목이 보이지만 본문은 직사각 포켓 미검출로 남았다. Stop이 없는 상태에서 90초 기다린 후에도 같았다. `settled-browser/browser_failure.png`, DOM, JSON이 근거다.
6. `browser_selection_diagnosis.cjs`는 같은 불일치를 새 context에서 재현했다. 제목 클릭으로 포커스를 옮겨도 바뀌지 않았으며, **절삭 설계 검토 버튼을 다시 누르면** R3/공구Ø8 초과4개로 갱신됐다. `selection-diagnosis/events.json` 및 PNG 5장이 근거다. 해당 selectbox는 실제 DOM의 `stForm` 밖이었다.
7. `selection-diagnosis/console.json`에는 Canvas2D readback 성능 권고 1개만 있었다. JS pageerror나 서버 예외는 없었다.
8. 직각 블록·벽이 둥글게 보이는 smooth shading이 확인됐다. 실제 형상과 음영을 혼동하지 않도록 CNC 뷰에 한정해 flat shading을 사용하는 것을 루트에 제안했다.

## 수정 뒤 최종 확인

루트는 항목 목록의 순서와 표시명을 고정하고, 새 형상에서만 최우선 항목을 자동 선택하도록 수정했다. 같은 형상의 공구 조건 변경에서는 사용자가 보던 항목을 유지한다. CNC 그림만 flat shading을 적용했다.

최종 증거는 [browser_result.json](final-browser-v3/browser_result.json), [시간·URL·viewport 기록](final-browser-v3/browser_steps.json), [실행 스크립트](browser_workflow.cjs)이다. 각 캡처 시점에 Stop과 결과 로딩 상태가 사라진 것을 확인했다.

| 단계 | 실제 화면에서 확인한 결과 | 캡처 |
| --- | --- | --- |
| 직사각 포켓, Ø8/날10/도달15 | 폭12, 길이20, 벽높이8 mm와 다음 행동. 바닥만 주황 강조. 직각 벽이 곡면처럼 보이던 음영이 사라짐 | [전체](final-browser-v3/10_rectangle_tool8_wide.png), [형상](final-browser-v3/10_rectangle_tool8_wide.graph.png) |
| 둥근 포켓 R3, Ø8 | 오목 원통면 항목을 선택하면 추가 검토 버튼 없이 본문도 갱신. CAD 면7/9/11/13에서 반경3 mm, 공구반경4 mm 초과4개. 작은 공구 또는 형상 수정 안내 | [전체](final-browser-v3/11_rounded_tool8_wide.png), [강조](final-browser-v3/11_rounded_tool8_wide.graph.png) |
| 같은 형상, Ø4 | 선택한 오목 원통면 항목 유지. 초과0개, 네 행 모두 '아니오', 주황 강조 해제. 입구·경로 검토 등 적용 한계 유지 | [전체](final-browser-v3/12_rounded_tool4_wide.png), [형상](final-browser-v3/12_rounded_tool4_wide.graph.png) |
| 둥근 포켓, 폭780 px | 문장 줄바꿈, 표와 결과 구획을 읽을 수 있음. 전체 문서가 viewport보다 넓어지지 않음 | [전체](final-browser-v3/13_rounded_tool4_narrow.png) |
| 단순 블록 가림 표본 | 12개 중 직선 가림0, 반대 방향2, 접선8, 미확정0, 직선 통과2. 파란 원2·보라 사각2·회색 십자8과 범례 구분. 실제 공구 접근 보장이 아니라는 설명 유지 | [전체](final-browser-v3/14_block_visibility_wide.png), [점과 범례](final-browser-v3/14_block_visibility_wide.graph.png) |
| 블록, 폭780 px | 점·범례를 읽을 수 있고 범례는 두 줄로 배치. 전체 문서 가로 넘침 없음 | [전체](final-browser-v3/15_block_visibility_narrow.png), [그림](final-browser-v3/15_block_visibility_narrow.graph.png) |
| 반대 방향 표본만 표시 | 별도 검토 실행 없이 보라 사각형2개로 즉시 갱신. 선택한 분류와 그림 trace 일치 | [전체](final-browser-v3/15b_block_back_facing_only.png), [필터된 그림](final-browser-v3/15b_block_back_facing_only.graph.png) |
| 적층제조 복귀 | MEX의 기존 설계 조치·방향·정밀 검토 화면 표시. 높이15 mm, 부피18 cm³, 벽 표본12개 최소15 mm. CNC 결과가 섞이지 않음 | [전체](final-browser-v3/16_additive_return_wide.png), [형상](final-browser-v3/16_additive_return_wide.graph.png) |

최종 browser pageerror는 0개다. [console.json](final-browser-v3/console.json)의 유일한 경고는 Canvas2D readback 성능 권고이며 기능 예외는 아니다. 서버 로그에도 실행 예외는 없었다.

## 남은 작은 UX 개선 후보와 범위

- Ø4에서 초과가 없는 경우 다음 행동은 여전히 '공구반경보다 작은 면은…'이라는 조건부 안내다. 잘못된 판정은 아니지만 '현재 반경 비교 초과 없음 → 입구·경로 확인'처럼 상태에 맞춘 문장이 더 직접적이다.
- 폭780 px에서 긴 행동 설명이 있는 표는 내부 가로 스크롤이 필요하다. 좁은 3D 그림의 Z축 제목도 왼쪽 가장자리에서 일부 잘린다. 판정 본문·점·범례는 읽을 수 있으며 전체 페이지의 가로 넘침은 없다.
- 실제 Edge headless 렌더링을 확인한 결과다. 사용자 브라우저에 접속하거나 사람이 수행하는 사용성 시험을 한 것은 아니다. 다른 화면 폭, 모바일 브라우저, 보조공학, 실물 가공은 이 검증에 포함하지 않았다.

## 실패 기록의 구분과 보존

- `settled-browser/`, `selection-diagnosis/`는 수정 전 제품의 선택·본문 불일치를 담고 있다.
- `post-fix-browser/`는 Streamlit의 모듈 재사용으로 구버전 화면과 파일 변경 Rerun 배너가 남은 상태다. 소유 서버를 종료하고 새로 실행해 최종 검증했다.
- `final-browser/`의 최초 연결 실패는 서버 준비 전에 접근한 자동화 오류다. `final-browser-verified/`는 체크박스 input을 덮는 label 때문에 자동화 클릭이 막혔고, `final-browser-v2/`는 사이드바 스크롤 직후 dropdown 자동화가 닫혀 적층 복귀에 실패했다. 스크립트에 실제 label 클릭, 스크롤 후 대기·옵션 열림 확인을 반영한 `final-browser-v3/`에서 전체 흐름이 통과했다.
- 이전 증거는 덮어쓰거나 삭제하지 않았다. 최종 판정은 `final-browser-v3/`를 따른다.

## 실행 자원 정리

초기 소유 PID6336/1912를 확인 후 종료하고, 새 소유 PID4692와 자식5764로 8510을 재실행했다. [server-restart.json](server-restart.json)에 새 서버 출처가 있다. 최종 검증 뒤 두 PID의 실행 경로·8510 인수·부모 관계를 다시 확인하고 해당 두 프로세스만 종료했다. [확인한 소유 프로세스](server-cleanup-owned.json), [종료 결과](server-cleanup.json)에서 소유 PID 잔여0개, 8510 리스너0개를 확인할 수 있다. 모든 임시 브라우저 context도 종료했다. 8507과 바탕화면 앱에는 조작을 수행하지 않았다.
