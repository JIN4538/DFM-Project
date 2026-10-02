# Windows 작업자 시간 제한 수정 검증

이 폴더는 작업 기록의 공개 가능한 로그 사본이다. 아래에 기술한 원래 `../final-code-review-02/`·`../final-code-review-03/`는 저장소 옆 `study/random-shape-audit/` 기준이다. 핵심 전후 값은 이 폴더의 [before-probe.json](before-probe.json)과 [after-probe.json](after-probe.json)에 복사했다. `venv313` 실행환경 자체는 배포하지 않으며 로그와 원래 실행 경로만 보존한다.

직접 부모가 자식을 생성한 뒤 먼저 종료하면 기존 PID 기반 taskkill은 남은 자식을 찾지 못했다. 0.75초 제한 반례에서 실제 대기는 4.228174초였고 자식이 뒤늦게 파일을 작성했다. 수정 후 같은 반례는 **0.755950초**, `TimeoutExpired`, 자식 파일 없음으로 바뀌었다. 이전과 이후 원기록은 각각 `../final-code-review-02/`, `../final-code-review-03/`에 보존했다.

## 실제 구현

작업마다 이름 없는 Job Object를 만든다. 핸들은 자식에게 상속하지 않으며 `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`만 설정하고 breakaway를 허용하지 않는다. CPython의 `_winapi.CreateProcess`로 작업자를 `CREATE_NO_WINDOW | CREATE_SUSPENDED` 상태에서 생성한다. 반환받은 프로세스 핸들을 Job에 할당한 다음 보존한 주 스레드 핸들로 `ResumeThread`를 호출한다. 할당 전에 작업자가 자식을 생성할 수 없다.

직접 부모의 종료와 Job 내 모든 후손의 종료를 구분한다. Job의 active process 수를 확인하고 직접 프로세스의 종료 신호도 별도로 기다린다. 제한 시간이 지나면 해당 Job만 종료하며, 처리 오류가 있어도 마지막 Job 핸들을 닫아 종료를 재시도한다. 직접 생성한 프로세스 핸들 외에 시스템 PID 목록·다른 사용자 프로세스·서비스를 조회하거나 종료하지 않는다.

stdout/stderr는 비공개 임시 파일에 받는다. 모든 소유 작업이 종료된 뒤 bytes로 읽어 기존 `CompletedProcess(args, returncode, stdout, stderr)`와 `TimeoutExpired`의 output/stderr API를 유지한다. 자식이 출력 pipe를 붙잡아 무제한 `communicate()` 대기가 생기는 경로를 제거했다. 종료 확인에 5초씩 제한을 두며, Job 할당·재개·정리 오류는 `OSError`로 명시한다. 정상 측정값으로 돌려주지 않는다.

Unix는 기존 `start_new_session`과 `killpg` 처리를 유지하고 timeout 뒤 출력 배수에도 제한을 둔다. 이번 새 실행 검증은 Windows 11에 한정되며 Linux 실행 통과를 주장하지 않는다. Windows Job의 출력과 무관한 후손 완료 대기는 Unix에서 새로 구현했다고 주장하지 않는다.

## 실행 결과

| 환경 | 실제 실행 파일 | 결과 |
|---|---|---|
| Python 3.12.14 | 프로젝트 `.venv/Scripts/python.exe` | 프로세스 계약 **18/18 통과, 13.72초** |
| Python 3.13.15 | 이 폴더의 `venv313/Scripts/python.exe` | 프로세스 계약 **18/18 통과, 14.04초** |
| Python 3.12.14 | 프로젝트 `.venv/Scripts/python.exe` | CAD·상세 계약 통합 **44/44 통과, 43.03초** |

3.13 검증은 별도로 생성한 실제 3.13 가상환경에서 pytest 8.4.2만 설치해 실행했다. 3.12용 바이너리 확장 패키지를 끌어와 검증한 것이 아니다. 버전·실행 경로·프로덕션 및 검사 파일 SHA-256은 `manifest.json`에, 콘솔 결과와 JUnit은 `pytest312.*`, `pytest313.*`에 있다.

검사는 다음 동작을 포함한다.

- 직접 부모 생존 및 선종료, 자식 stdout 상속 및 DEVNULL에서도 시간 초과 시 자식 정리.
- 정상 부모 선종료 뒤 자식 출력 수집과 부모 종료 코드 보존.
- 550 KB의 binary stdout/stderr 및 시간 초과 전 flush한 출력 보존.
- Job assign/resume 실패를 주입했을 때 작업 코드가 실행되지 않음.
- TerminateJobObject 실패를 주입해도 kill-on-close가 자식을 중단하며 OSError 보고.
- 핸들 종료 실패를 측정 성공으로 감추지 않음.
- 별도 제어 프로세스의 생존, 반복 생성·종료에서 핸들 누수 없음.
- 유효하지 않은 시간 제한과 존재하지 않는 실행 파일의 명시적 실패.

첫 구현의 15개 검사에서는 12개 통과·3개 실패가 있었다. Job 종료 직후 직접 프로세스 핸들이 아직 signal 상태가 되지 않아 중복 `TerminateProcess`가 WinError 5를 반환하는 경합이었다. Job accounting과 직접 종료 신호를 별도로 확인하고, 이미 종료 중인 경우 bounded wait로 정리한 뒤 재시험했다. 이 실패 이력을 지우지 않으며 최초 상태를 최종 통과로 설명하지 않는다.

프로세스 수정 이후의 독립 기하 probe도 4/4 통과했다. 중첩 3MF 변환·inch 단위, 테이퍼 단면의 독립 면적/둘레 공식, partial에서 null 체적 보존, 상세 timeout 이후 오래된 측정 제거를 다시 확인했다. CAD·상세 계약 통합 검사 44개는 `integration312.*`에 보존했으며 전수 형상 계산 데이터와 구분한다.

## 공식 원문 근거

- [Microsoft Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects): 자식의 기본 Job 상속, kill-on-close, nested job 및 breakaway 조건.
- [AssignProcessToJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject): 프로세스 할당 권한·중첩 제약·실패의 GetLastError.
- [Process Creation Flags](https://learn.microsoft.com/en-us/windows/win32/procthread/process-creation-flags): CREATE_SUSPENDED는 ResumeThread 이전에 주 스레드가 실행되지 않으며 CREATE_NO_WINDOW는 콘솔 창을 만들지 않음.
- [ResumeThread](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-resumethread): 반환되는 이전 suspend count 1에서 실행 재개, 실패는 DWORD -1.
- [Extended Limit Information](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information), [Basic Accounting Information](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_basic_accounting_information): 실제 ctypes 구조체 필드와 active process 수 정의.
- [TerminateJobObject](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-terminatejobobject): 해당 Job 및 하위 Job의 소유 프로세스 종료와 오류 반환.

Python 3.12/3.13 설치본의 `subprocess.Popen._execute_child`와 `_winapi.CreateProcess` API를 함께 확인했다. Popen이 반환 전에 주 스레드 핸들을 닫기 때문에 이 좁은 Windows 실행 경로에서는 CPython wrapper를 직접 사용한다. 다른 Python 구현·미시험 Windows 버전의 호환성을 보증하지 않는다. 실물 제조 성능·새 기하 수치의 검증 근거로 이 시간 제한 검사를 사용하지 않는다.
