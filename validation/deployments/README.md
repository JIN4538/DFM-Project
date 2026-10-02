# 배포·실행 확인 기록 보관

보관일: 2026-09-15. 저장소 밖 `deliverables/`의 AM-DFM 배포 폴더 7곳에서 배포 manifest, 검증 JSON, QA·인수 기록과 ZIP 체크섬을 복사했다. 원래 파일명과 내용을 유지했으며 [archive_manifest.json](archive_manifest.json)에 24개 파일의 원래 위치, 크기, SHA-256을 기록했다.

| 원래 배포 폴더 | 변경 범위 |
|---|---|
| [am-dfm-v3-release](am-dfm-v3-release/) | AM-DFM 3.0 초기 개선판 |
| [am-dfm-v3-installer-fix](am-dfm-v3-installer-fix/) | Windows 설치 흐름 수정 |
| [am-dfm-v3-orientations](am-dfm-v3-orientations/) | 26방향과 직접 각도 입력 |
| [am-dfm-corpus-review](am-dfm-corpus-review/) | 실제 형상 전수 검토 반영 |
| [am-dfm-startup-fix-20260915](am-dfm-startup-fix-20260915/) | 동일 앱 중복 실행 처리 |
| [am-dfm-section-ux-20260915](am-dfm-section-ux-20260915/) | 단면 결과 안내 개선 |
| [am-dfm-workflow-ux-20260915](am-dfm-workflow-ux-20260915/) | 프로그램 전반 판단·위치·다음 행동 안내 |

각 폴더의 `release_manifest.json`과 검증 기록은 **그 배포 당시의 파일·커밋·실행 환경**에 대한 기록이다. 현재 Git HEAD의 파일 SHA나 새로운 시험 결과로 대신 사용하지 않는다. `SHA256SUMS.txt`는 원래 배포 ZIP의 체크섬이며 ZIP 자체는 이 보관 폴더에 중복 추가하지 않았다. 배포 폴더별로 작성된 검증 파일의 이름과 형식이 다르다는 점도 그대로 보존했다.

로그 전체, 실행 환경, 캐시와 반복 포장한 프로그램 ZIP은 제외했다. 원래 작업공간의 배포본과 검증 로그는 삭제하거나 수정하지 않았다. 로컬 경로·포트·프로세스 ID는 당시 배포의 출처 정보이며 다른 환경에서 재사용할 설정이 아니다.
