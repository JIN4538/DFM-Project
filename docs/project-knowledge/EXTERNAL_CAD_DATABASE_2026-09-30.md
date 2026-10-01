# 외부 CAD 자료의 로컬 DB 반입

사용자 요청: “외부 데이터를 우리 데이터베이스로 가져올 수 있어?” 공개 자료의 반입 가능성을 확인하고 이미 확보한 두 저장소 샘플로 실제 반입·조회 경로를 검증했다. 전체 데이터 수집이나 모델 학습을 요청 완료로 확대하지 않는다.

## 완료 범위

- `scripts/import_external_cad_data.py`: 기존 출처 목록의 SHA-256·바이트 수·Git blob을 확인한 뒤 새 SQLite 파일에 원본을 복사한다. 기존 파일을 덮어쓰지 않는다. 의존성은 표준 라이브러리와 선택적 OCP이며 기존 읽기 전용 CAD 감사기를 재사용한다.
- 이 어댑터는 **MFCAD 원본 1개와 MFInstSeg 저장소 예제 1개를 위한 소규모 반입기**다. MFCAD++ 또는 임의 전체 데이터셋을 자동 수입하는 범용 도구가 아니다.
- STEP 2개·라벨 2개·저장소 라이선스 2개·공개 분할 목록 6개, 총 12개 원본을 BLOB으로 보관했다. 전체 출처 목록 원문도 보존했다. 공개 분할 목록의 행 수는 확보된 CAD 모델 수가 아니다.
- 정규화한 면 라벨은 11+27=38개다. MFInstSeg 인스턴스 관계와 바닥면의 원본 JSON을 보존하고 바닥면 라벨도 면 테이블에 저장했다.
- 기존 장비·재료 조건 DB, 제품 화면, 바탕화면 실행본, AI 가중치는 변경하지 않았다. **학습 실행 0, MFCAD++ 반입 0**이다.

DB 위치: `C:/Users/JIN/Documents/ChatGPT/DFM/study/external-cad-db-2026-09-30/external_cad.sqlite`.

## 보관 및 학습 준비 상태

`datasets`, `raw_files`, `samples`, `face_labels`, `split_audits`, `import_runs` 테이블에 데이터셋·버전·출처·원본·검사 결과를 연결한다. 표본은 이미 검사에 사용한 자료이므로 새로운 독립 평가 데이터로 취급하지 않는다.

- MFCAD는 STEP 면의 name을 라벨 인덱스로 사용한다. 원본 파일의 면 출현 순서와 라벨 번호는 다르다. 클래스 이름에 관한 원저자 자료 간 모순이 남아 있어 숫자 라벨을 그대로 보존했다.
- MFInstSeg는 원저자 pythonocc 순회와 현 OCP 순회를 전체 대조하지 않았다. OCP 면 번호의 대응을 `provisional_ocp_ordinal_not_upstream_verified`로 저장하며 STEP 텍스트 엔터티와 임의로 연결하지 않았다.
- MFInstSeg 분할의 중복 행 13개와 분할 간 공통 ID 5개를 그대로 기록했다. 원본 목록을 수정하지 않았으며 깨끗한 학습·평가 분할은 후속 작업이다.
- 두 샘플은 `training_ready=false`다. 보관·기하 검사·학습 준비·학습 실행은 별개 상태다.
- 저장소 샘플의 MIT LICENSE·저작권을 함께 보관했다. 이 정보를 외부 MFInstSeg 전체 배포본이나 별도 MFCAD_GNN 저장소의 이용 조건으로 자동 확대하지 않는다.
- 두 STEP 원문에는 mm가 명시되어 있다. 현재 감사기의 OCP 출력 단위 설정을 일반 단위 변환 수입기로 검증한 것은 아니다.

출처 및 선행 조사: [MFCAD 계열 검토](../research/public-cad-data-2026-09-29/MFCAD.md). 공식 [MFCAD 저장소](https://github.com/hducg/MFCAD), [AAGNet 저장소](https://github.com/whjdark/AAGNet), [QUB MFCAD++](https://pure.qub.ac.uk/en/datasets/mfcad-dataset-dataset-for-paper-hierarchical-cadnet-learning-from/). 이번에는 새 원본을 다운로드하지 않았다. QUB 페이지 직접 열기 제한과 이전 ZIP 403 기록을 구분하며, 전체 수신을 확인하지 않았다.

## 검증

[결과 JSON](../../validation/external-cad-intake-2026-09-30/summary.json): 반입 테스트 12개 통과, 실제 OCP 로드에서 두 샘플 모두 단일 유효 solid 확인. SQLite 무결성과 외래 키 검사 통과, 보관 원본 12개 및 출처 목록의 바이트 일치 확인, 기존 모델·manifest 파일 8개 SHA 불변 확인.

- MFCAD: 11면, 10×10×10 mm, 체적 850.464754671 mm³.
- MFInstSeg: 27면, 약 61.152895×41.809025×43.721100 mm, 체적 38541.370279030 mm³.
- DB SHA-256: `7a866c430ab922201240e6f27da568429ea1d478e69ad5a531fa105b71f4915c`.

재실행은 반드시 새 DB 경로를 사용한다.

```powershell
.venv/Scripts/python.exe scripts/import_external_cad_data.py --source-dir ../study/public-cad-data-2026-09-29/mfcad --database <새파일.sqlite> --ocp
.venv/Scripts/python.exe -m pytest tests_v3/test_external_cad_import.py -q
```

다음 단계는 전체 원본 확보, 데이터셋별 어댑터와 라벨 어휘 검증, 중복·유사 형상 단위 분할, 특징 텐서 추출, 학습·기존 규칙 대비 평가다. 공개 특징 라벨을 개선안의 정답이나 최적 공구 치수로 바꾸어 부르지 않는다.
