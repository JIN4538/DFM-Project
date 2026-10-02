# 개발 작업 기록 보관본

`files/`는 저장소 옆 study의 2026-09-26·28·29·30 작업에서 보존한 스크립트, 학습/검증 요약, 실패·재시험, 배포 확인, 실제 UI 화면, 수정 전후 CAD다. 원본 바이트를 복사했으며 기존 study 자료를 삭제하거나 수정하지 않았다. 현재 실행할 코드와 재현 명령은 저장소의 `scripts/`와 `docs/project-knowledge/`를 따른다.

[manifest.json](manifest.json)은 원래 study 경로, 보관 경로, 바이트 수, SHA와 제외 사유를 연결한다. 새 복사 2,194개와 기존 저장소의 동일 바이트 참조 123개를 구분한다. 폴더별 백업·외부 원본 패키지는 디렉터리 제외 기록에 있다. 대용량 SQLite DB, 학습 배열, 개별 계산 캐시와 프로세스 상태는 로컬에 남긴다. 모델 가중치·데이터 카탈로그·수집 및 학습 스크립트는 저장소에 포함한다.

보관 STEP 299개도 [전체 형상 색인](../../examples/geometry_manifest.json)에 등록했다. 앱 시연 선택 목록과 연구용 수정 쌍을 구분하며 파일 수를 독립 설계 수로 부르지 않는다. 파일 읽기와 원래 SHA 확인은 `scripts/audit_repository_publication.py`와 `scripts/verify_geometry_inventory.py`에서 수행한다.

각 학습 단계의 숫자·채택 모델·반례와 최신 연구 방향은 [공개 범위 안내](../../docs/project-knowledge/REPOSITORY_PUBLICATION_2026-10-01.md)와 [연구 제안](../../docs/research/RESEARCH_AGENDA_2026-10-01.md)을 참고한다. 초기 실패 기록을 최신 성공 기록으로 덮어쓰지 않는다.
