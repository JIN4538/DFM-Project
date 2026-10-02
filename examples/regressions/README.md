# 3MF 좌표 변환의 독립 반례

`final-code-review-01`, `final-code-review-02`, `final-code-review-03`은 2026-09-14 실제 형상 재감사 중 별도 실행에서 생성한 `nested_shear_inches.3mf`와 원본 검사 코드·기록입니다. 중첩된 부품 변환, 반사, 전단, 축별 배율, 이동, inch→mm 변환을 함께 적용한 2×3×4 상자를 사용해 가져오기 결과를 독립 좌표 계산과 대조했습니다.

3개 3MF의 압축파일 SHA-256은 다르지만, 압축을 푼 두 항목의 바이트는 모두 같습니다. 같은 기하 반례의 실행별 원자료이며 **서로 다른 형상 3개로 집계하지 않습니다.** 압축 컨테이너의 차이를 제거하거나 다시 저장하지 않고 원본을 보존했습니다.

| 내부 항목 | 세 파일에 공통인 SHA-256 |
| --- | --- |
| `_rels/.rels` | `ad804e6c604693c5abbab3fddd7f0e1c40bb0b9c1106cb535222ef9ac6b479f9` |
| `3D/model.model` | `53080f43ac7a0db308fac5ab057cf03d7d4d7434279ecf7fb2184b8f0dec55a2` |

첫 실행의 `first_attempt_error.txt`, 두 번째 실행의 `orphan-after-timeout.txt`도 지우지 않았습니다. `results.json`과 `REVIEW.md`는 당시 코드에 대한 기록이며 현재 버전의 새 실행 결과가 아닙니다. 현재 검증 범위는 [검증 기록](../../docs/VALIDATION_V3.md)과 [독립 CAD 감사](../../docs/project-knowledge/INDEPENDENT_CAD_AUDIT_2026-09-14.md)를 참고합니다.

`probe.py`는 각 실행의 원본 생성·검사 코드입니다. 원래 `study/random-shape-audit/final-code-review-*/` 배치를 기준으로 저장소 위치와 출력 위치를 계산하므로, **이 복사본을 그대로 실행하지 않습니다.** 새 검사는 별도 빈 폴더에서 저장소 경로를 명시한 사본으로 수행하고, 이 원자료를 덮어쓰지 않습니다. 형상 자체는 현재 앱에서 3MF 파일로 바로 열 수 있습니다.

[SOURCE_MANIFEST.json](SOURCE_MANIFEST.json)에 원본 작업공간 상대 경로, 저장소 경로, 파일 크기와 SHA-256을 기록했습니다. 모든 복사본을 원본 바이트와 대조했습니다.
