# AM-DFM 3.0 전달 확인

2026-09-14. 소스 커밋 `d8349ba1a4832a8f592d526b67c8135cb236bbc5`.

- 로컬: 225개 통합 검사 통과, 기존 기본검증 별도 55/55 통과.
- ZIP: 195개 개발 파일, ZIP CRC 및 각 파일 SHA-256 대조 통과.
- 별도 폴더 압축 해제 후 UI 3개 검사 통과(10.85초). 설치 의존성은 기존 검증된 환경 사용.
- [GitHub Windows CI](https://github.com/JIN4538/DFM-Project/actions/runs/34847814804): 완료, 성공. 깨끗한 환경에서 의존성 설치·pip check·전체 회귀·기본검증 실행.
- [검토 PR #1](https://github.com/JIN4538/DFM-Project/pull/1). 브랜치 `codex/am-dfm-evidence-review`; main에는 아직 병합하지 않았다.
- 원래 추적된 PDF/DOCX/ZIP/MD 24개: 변경 없음. 외부 STL 원본과 실제 치수 미확정 상태 유지.
- [실행 중인 로컬 앱](http://127.0.0.1:8507). 재실행은 저장소의 `START_REVIEW.cmd`.
- 원본 보관 문헌, 외부 STL 형상, Python 런타임과 의존성은 소스 ZIP에 포함하지 않았다. 새 설치는 `INSTALL.cmd`부터 실행한다.

ZIP SHA-256: `1a6e63eaaccf38ae382a844ce5068136f0d6e0ffc83b69e8f09951f6623b0335`.

장비·재료·슬라이서가 미확정이므로 실물 제작, 치수 공차, 강도·열변형 검증은 하지 않았다. 기하 검토의 검증과 제조 성공 보증을 구분한다. 문헌 조사·현재 기능의 목적·조건별 검증 범위는 ZIP 안 README와 docs를 따른다.
