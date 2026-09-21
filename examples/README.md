# 테스트 형상 안내

저장소에 테스트 형상 **128개 파일, SHA-256 기준 122종**을 보관한다. 중복 배치·과거 버전의 같은 바이트는 Git의 동일 객체로 저장된다. SHA가 다르다는 것이 물리적으로 다른 설계라는 뜻은 아니며, 회귀용 3MF 3개는 압축 내부 모델이 같다. 절삭 재감사의 10개 STEP은 회전·이동 조건 5종을 수정 전후에 다시 내보낸 기록이다.

| 위치 | 형상 수 | 용도와 기록 |
|---|---:|---|
| [cad](cad/) | 14 | 직접 치수를 정의한 CAD 기준형상. [기대값·생성기](cad/manifest.json) |
| [machining](machining/) | 12 | 절삭 기하 검증용 자체 STEP. 포켓·원통면·오인식 반례와 [독립 기대값](machining/manifest.json) |
| [corpus](corpus/) | 26 | 사용자가 제공한 STEP 21·STL 4·3MF 1과 동반 TXT 5개. 실제 형상 전수 검토 입력 |
| [external](external/) | 3 | 초기에 전달받은 외부 STL 사례 |
| [historical](historical/) | 22 | 미팅 데모 2, 규칙 확인 18, v1 원본 시험 2. 생성기·당시 결과 함께 보관 |
| [regressions](regressions/) | 3 | 3MF 인치 단위·중첩 변환 검사에서 사용한 원본 압축 파일과 실패·성공 기록 |
| [validation/v3](../validation/v3/) | 11 | Cura 얇은 리브 실험의 입력 STL |
| [절삭 회전·이동 재감사](../validation/machining-reaudit-2026-09-20/geometry/) | 10 | 독립 포켓의 회전·좌표 이동 5조건을 수정 전후 보존. [생성 치수·변환](../validation/machining-reaudit-2026-09-20/geometry/probe_geometry.py) |
| [cura_run](../cura_run/) | 27 | 과거 방향별 슬라이서 실험과 오류 재현 입력 |

정확한 파일 경로·바이트 수·SHA는 [geometry_manifest.json](geometry_manifest.json)에 있다. 원본 출처는 각 그룹의 README·manifest에 기록했다. 외부 자료의 치수나 라이선스를 임의로 확정하지 않으며, 불량·미확정 형상도 시험 입력으로 보존한다.

## 사용하는 방법

- 현재 앱에서는 **CAD 기준형상**, **절삭 검증 형상**, **외부 STL 사례**, **검증용 예제**를 바로 선택할 수 있다. 다른 컴퓨터에 바탕화면 테스트 폴더가 없어도 저장소의 `corpus`를 사용한다.
- 다른 예제는 **내 파일**로 불러온다. 역사적 결과 파일에 적힌 점수와 실행환경은 해당 시점의 기록이다.
- `scripts/verify_geometry_inventory.py`를 실행하면 목록과 실제 파일의 바이트·SHA 및 누락을 확인한다. 이 확인은 파일 무결성 검증이며 제조 적합 검사가 아니다.
- [전수 검토 방법](../docs/VALIDATION_CORPUS.md)에 따라 항상 새 출력 폴더에서 재실행한다.
