# 사용자 결정 흐름 검증 — 2026-09-28

구현·범위·문헌·배치 기록: [최종 인수 기록](../../docs/project-knowledge/USER_DECISION_IMPLEMENTATION_2026-09-28.md).

| 실행 | 환경 | 결과 | 로그 |
|---|---|---|---|
| 초기 관련 검사 | 저장소 Python 3.12.14 | 108 통과·1 실패, 245.71초 | focused.txt / focused.xml |
| 주요 구현 전체 회귀 | 저장소 Python 3.12.14 | 1009 통과·기존 경고 1개, 774.56초 | regression-final.txt / regression-final.xml |
| 주요 구현 바탕화면 | 바탕화면 Python 3.13.15 | 10 통과, 56.52초 | desktop.txt / desktop.xml |
| 마지막 안내 보완 — AM | 저장소 Python 3.12.14 | 71 통과, 25.69초 | final-am.txt / final-am.xml |
| 마지막 안내 보완 — CNC | 저장소 Python 3.12.14 | 32 통과, 50.04초 | final-cnc.txt / final-cnc.xml |
| 최종 바탕화면 | 바탕화면 Python 3.13.15 | 14 통과, 32.78초 | desktop-final.txt / desktop-final.xml |

초기 실패는 현재와 같은 방향의 재적용을 막은 뒤 기존 UI 검사가 비활성 버튼을 누르려 한 것이다. 불필요한 재실행 방지 및 원래 각도 보존을 확인하도록 갱신했다. 위 기록보다 앞선 32 통과·6 실패 실행은 해당 원본 로그 파일이 없으며 인수 기록에 경과만 적었다.

전체 회귀 SHA: `394aa2d100fda6bb31df58918516ce220a80af2010059050b98c3d5d9d987203`.

이후 AM 안내 2문구와 CNC 기존 비교값 기반 조치를 구체화했다. 최종 SHA: `184e37b2ef5180e077bedb9af2917b6e795e86fe2c2393e3268c6df774809c5f`. 해당 최종 변경은 관련 검사와 바탕화면 검사로 검증했다. 전체 회귀를 최종 SHA에서 다시 실행한 것으로 혼동하지 않는다.

## 실제 브라우저 확인

- `browser-wall-action.png`, `browser-wall-location.png`, `browser-thin-wall-dom.txt`: 0.3 mm 판과 검증용 1 mm 기준. 한 번 실행으로 기준 미만 판단·보강 제안·실제 측정점 제공. 제조사 기준/실물 검증이 아니다.
- `browser-direction-before.txt`, `browser-direction-after.txt`: 10×20×30 mm 박스에서 +X 추천, 높이 30→10 mm, 적용 후 같은 추천·현재 유지 및 설계 조치 화면 복귀.
- `browser-cnc-result.txt`, `browser-cnc-location.txt`, `browser-cnc-location.png`: 포켓 폭 3/깊이 20 mm, 공구 지름 4/날 길이 8/돌출 길이 10 mm. 치수 비교와 CAD 면 11 선택.
- `browser-cnc-final.txt`, `browser-cnc-final.png`: 최종 재시작 후 작은 공구/폭 확대 등 구체 조치 표시.
- `browser-thin-wall.png`는 첫 촬영 시 사이드바가 결과를 가린 중간 기록이다. 최종 판단 화면 증거로 사용하지 않는다.

실제 앱의 기존 작은 뷰포트에서 확인했으며 스크린샷을 위해 화면 크기를 변경하지 않았다. 앱 계산과 UI 동작의 검증이며 실제 제조 성공·강도·품질 또는 모든 연속 방향의 물리 최적을 검증한 결과가 아니다.
