# AM-DFM 빌드 방향 확장 배포

소스 커밋: 7c5444a81b277e7b8af9bf9cba2408eab9024edc. GitHub PR: https://github.com/JIN4538/DFM-Project/pull/1

바탕화면 `C:/Users/JIN/Desktop/AM-DFM_v3_0`의 소스 206개를 새 배포 manifest와 대조했다. 사용자 수정 파일이 없는 것을 먼저 확인했고, 바뀐 이전 파일은 폴더 내부 `backups/orientation-update-20260914-231143`에 보존했다. 기존 Python 실행환경은 유지했다.

저장소 Python 3.12.14: 전체 회귀 283개 통과, 기존 기본검증 55/55. 바탕화면 Python 3.13: 방향·층간·UI 관련 56개 통과(21.03초, desktop_python313.txt).

바탕화면 소스를 로컬 127.0.0.1:8507에 실행했다. 브라우저에서 자체 CAD 브래킷, 기울기 30°·방위각 60° 입력, 높이 48.63 mm, 현재 방향 포함 27개 비교 표시를 확인했다. 이 예시 방향이 권장 출력 방향이라는 뜻은 아니다.

별도 source ZIP은 release_manifest.json 및 SHA256SUMS.txt로 검증했다. GitHub Actions 실행 34853912718의 Windows 3.12 및 3.13 두 작업 모두 설치·의존성·전체 회귀·기존 기본검증을 성공했다(github_ci.json). 검증 수치와 곡면 근사·층 표본·공정 물리 한계는 배포본의 docs/project-knowledge/ORIENTATION_EXTENSION_2026-09-14.md에 있다.
