# 독립 단면 진단 원본 보관

보관일: 2026-09-15. 저장소 밖 `study/random-shape-audit/`에서 실행했던 독립 진단 스크립트 5개와 추적 결과 JSON 6개를 **바이트 변경 없이** 보관했다. [archive_manifest.json](archive_manifest.json)의 SHA-256을 원본과 대조했다.

| 대상 | 실행 스크립트 | 보존 결과 |
|---|---|---|
| Raspberry Pi 솔리드 67 | `diagnose_pi_67.py` | `pi-body-67-crossing-diagnosis-01.json` |
| Raspberry Pi 솔리드 108 | `diagnose_pi_108.py` | `pi-body-108-crossing-diagnosis-01.json` |
| Raspberry Pi 솔리드 106 | `diagnose_pi_106_event.py` | `pi-body-106-event-crossing-diagnosis-01.json` |
| Raspberry Pi 솔리드 109 | `diagnose_pi_109_event.py` | `pi-body-109-event-crossing-diagnosis-01.json` |
| 공급사 형상 900-602 | `check_supplier_section.py` | `supplier-900-602-check-01.json`, `supplier-900-602-check-02.json` |

이 스크립트는 **이 폴더에서 바로 실행할 수 있도록 변경한 도구가 아니다.** 원래 위치를 기준으로 `baseline-01/`, `final-01/`의 저장 메시·검토 결과와 DFM-Project 경로를 참조한다. 실행하면 같은 위치의 결과 JSON에 기록하는 코드도 있으므로 보관본 폴더에서 실행하지 않는다. 재현할 때는 원래 작업공간 구조와 당시 기록된 코드·환경을 별도 작업 디렉터리에 마련하고 새 결과 경로를 지정한다. 원래 구조와 상세 데이터가 없는 Git 복제본만으로 이 과거 진단을 재실행할 수 있다고 주장하지 않는다.

전체 원본 추적값과 최초 시도·후속 결과를 구분하여 보존했다. 이번 추가는 과거 검사를 다시 실행하거나 과거 수치의 의미를 변경한 작업이 아니다. 원 STEP의 결함, 메시 근사 현상, 출력 품질을 동일시하지 않는다. 관련 해석은 [솔리드 67 기록](../../../../docs/project-knowledge/PI_BODY67_SECTION_LIMIT_2026-09-15.md)과 [솔리드 108 기록](../../../../docs/project-knowledge/PI_BODY108_SECTION_LIMIT_2026-09-15.md)을 따른다.
