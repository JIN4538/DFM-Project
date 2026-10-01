# 외부 형상 DB·실제 재학습·조건 입력 통합

2026-09-30 사용자 요청: MFCAD++를 포함한 외부 데이터 조사·반입·학습, 특징 인식 → CAD 재측정 → 개선안 선택 강화, 장비·재료와 빌드 공간·층 설정 통합. 아래 내용은 앞선 2개 샘플 반입 이후의 새 작업이다. 지원 범위는 적층·절삭이다.

## 확보와 이용 조건

로컬 DB 루트: `C:/Users/JIN/Documents/ChatGPT/DFM/study/external-training-2026-09-30/`. 이전 연구 원본·실패 로그는 덮어쓰지 않았다. 반입 총 87,981개는 학습에 사용한 수가 아니다.

| 자료·공식 출처 | 확보·DB | 현재 학습 상태 |
|---|---|---|
| [MFCAD](https://github.com/hducg/MFCAD), 고정 커밋 ef6d58a40164d5192666821ce98d0cc90e379fac | 15,488 STEP와 face_truth, 350,295면. `training.sqlite`에 원본 BLOB·SHA·그래프·실측 보관 | 전체 그래프 준비; 학습/검증/시험 10,840/2,339/2,309. MIT 원문 보관 |
| [Thingi10K 저자 저장소](https://github.com/Thingi10K/Thingi10K), 저자 HF v1.5.0 미러 | 9,998 NPZ와 개별 저작권·저자·품질 메타데이터, `thingi.sqlite` | 이용 조건과 품질을 통과한 1,051 메시. Thing 단위로 179/38/43개 그룹 분리 |
| [MFInstSeg 저자 AAGNet](https://github.com/whjdark/AAGNet) → 저자 Google Drive | 62,495 STEP·JSON, 1,697,766면 라벨. `mfinstseg-complete.sqlite` | 면 순서 대응 미검증: training_ready=0, 가중치 학습 사용 0 |
| [MFCAD++ 저자 QUB 레코드](https://pure.qub.ac.uk/en/datasets/mfcad-dataset-dataset-for-paper-hierarchical-cadnet-learning-from/) | 공식 ZIP HTTP 403·브라우저 보안 확인; 실제 데이터 0 | 반입·학습 0. GitLab 생성기 소스가 원본 데이터라고 설명하지 않음 |
| [CADSynth 저자 ScienceDB](https://www.scidb.cn/en/detail?dataSetId=931c088fd44f4d3e82891a5180f10d90) | STEP 100,000개 배포 레코드·CC BY 4.0·파일 메타데이터 확인. UI 다운로드 미응답·공개 API 403 | 데이터 반입·학습 0 |

UV-Net의 MFCAD 전처리 미러는 같은 자료라 독립 추가 데이터로 세지 않는다. ABC의 CAD 기하와 Fusion Gallery 설계 이력은 제조성 문제·개선안 정답 자료로 직접 간주할 수 없어 이번 검증된 지도학습 범위에 넣지 않았다. 조사 카드와 접근 로그는 `source-access.json` 및 이전 `docs/research/public-cad-data-2026-09-29/`를 따른다.

Thingi10K는 전체 형상에 하나의 라이선스를 적용하지 않았다. CC BY·CC0/공공영역·BSD만 선별하고, 폐쇄·일관된 법선·단일 체적·자기교차 없음·CPU 예산 10,000면 이하 조건을 적용했다. 정확한 원본 SHA가 여러 분할에 존재하는 12개 그룹도 격리했다. 최종 실행 시 1개 메시가 추가로 체적 검사에 탈락했다. 원본의 길이 단위는 불명: 최대 크기 100으로 정규화한 **무차원 기하량 학습**이며 실물 mm 정답으로 사용하지 않았다. 사용한 각 원형의 저자·링크·이용 조건은 `data/training/thingi-attribution.json`이다.

MFInstSeg 저자 데이터 페이지 메타데이터에 CC0가 선언되어 있으나 ZIP 내부에는 별도 이용 조건 파일이 없다. 이전 공개 split 감사에서 중복 13행·분할 간 중복 5ID를 확인했고, 전체 반입에서 **라벨 내부 ID 불일치 18개**와 분할 간 동일 STEP 원본도 추가로 발견했다. 최종 격리 24개·미할당 18개를 보존한다. `mfinstseg.sqlite`는 최초 실패 시 남은 부분 DB, `mfinstseg-complete.sqlite`가 전체 반입 DB이다. 면 수가 맞는 것만으로 OCCT 버전 간 면 순서를 승인하지 않았다.

## 실제 모델 변경과 검증

### 1. 외부 라벨로 CAD 특징 인식

`dfm/cad_graph.py`는 실제 CAD 면의 기하·면 인접 관계로 22개 무차원 입력을 만든다. STEP 면 이름·파일명·라벨은 추론 입력에 넣지 않는다. MFCAD 라벨은 STEP face Name을 배열 인덱스로 사용해 연결한다. 원본 시각화 이름 목록의 오류를 [저자 저장소 issue #2](https://github.com/hducg/MFCAD/issues/2), 색 목록의 평면 부분 순서, 전체 기하와 대조해 16종 대응을 수정했다. 모든 모따기 면 4,849개는 경사면, stock 102,581개는 축 정렬 면임을 대조했다.

그래프 신경망은 64→64→48 은닉층의 세 차례 이웃 정보 집계와 16종 출력이다. 면별 MLP 비교 모델도 같은 분할에서 실제 학습했다. 새 모델은 `external_feature_gnn_v2.json`이고 실행은 NumPy로 하며 PyTorch를 요구하지 않는다. Torched 학습 모델과 JSON 내보내기를 별도로 대조했다.

MFCAD 보류 시험 2,309부품·52,248면:

| 모델 | 면 정확도 | Macro F1 | Mean IoU |
|---|---:|---:|---:|
| 면별 MLP 비교 | 91.8083% | 0.896588 | 0.825811 |
| 배포 GNN v2 | 99.9215% | 0.998824 | 0.997658 |

**이 수치는 합성 MFCAD의 보류 분할 결과**다. 전체 사용자 CAD의 정확도라고 확대하지 않는다. 최초 v1 모델은 독립적으로 만든 납작한 빈 직육면체를 높은 점수로 단차라고 잘못 인식했다. 이 실패 기록을 보존하고, 가공 특징이 없는 직육면체 비율을 넓힌 구성 정답 2,000개 학습·300개 검증·300개 별도 시험을 추가해 v2를 재학습했다. 외부 개수와 별도로 기록하며, 빈 직육면체 시험 면 정확도는 100%였다.

곡면을 포함한 부품은 이 평면 전용 분류기의 적용 범위 밖이다. 기존 CAD 원통/곡면 검토를 유지하며 전체 부품을 임의로 평면 특징에 끼워 넣지 않는다. 위 테스트 점수로 가중치 확신을 제조 판정으로 바꾸지 않는다. 얼굴 그룹은 우선 **특징 후보**이며 원본 인스턴스 정답을 학습한 것과 구분한다.

### 2. 후보 위치에서 CAD 치수 재측정

`dfm/external_features_review.py`는 삼각·직사각·육각 포켓의 바닥·벽·꼭짓점이 닫힌 동일 높이 직선 프리즘인지 확인한 경우에만 치수를 채운다. 전체 외부 자료에서 9,011형상의 14,042포켓을 재측정했다. 바닥 면적은 B-rep 적분, 폭은 바닥 다각형의 최소 캘리퍼 폭, 깊이는 바닥과 벽 윗점의 축방향 거리다. 폭을 엔드밀 진입 가능한 원의 지름으로 바꾸지 않는다.

회전·이동·배율, 다른 접근축, 빠진 벽, 곡면, 빈 직육면체를 독립 CAD 구성 치수에 대조했다. 삼각·육각 포켓은 기존 직사각 검토와 중복하지 않고, 새 코너·공구 치수 확인 항목을 종합 결론에 연결한다. 내측 직선 코너 반경 0은 공구 지름·날 길이가 맞더라도 수정 대상으로 남긴다. 인식 결과는 접힌 상세 안에서 사용자가 위치 버튼을 누를 때 그림을 표시한다.

후속으로 볼록 바닥의 모든 벽 평면까지 거리 ≥ 원 반경이라는 제약을 선형계획으로 풀어 최대 진입원도 재측정했다. 삼각 포켓 기준형상은 최소 폭 10.5 mm지만 진입원 지름은 7 mm이므로 폭만으로 공구를 비교하면 놓치는 충돌이 있다. 삼각·육각 포켓 공구 비교에는 진입원을 사용한다. 직사각은 두 값이 일치한다. 진입원은 공구 중심이 들어갈 공간이며 모든 내측 코너 가공까지 확인한 값으로 확대하지 않는다.

### 3. 외부 치수의 개선안 순위 학습

외부의 검증된 직사각 포켓 치수에 공구 변경·형상 변경·조합 변경 시나리오를 만들고, 기존 생성 학습 사례와 함께 순위 모델을 학습했다. 배포 파일 `plan_ranker_external_v2.json`. 절삭 기본 모델로 연결했고, 기존 순차 강화학습 제안은 같은 수치 재검산·충돌 비교를 통과해야 채택된다. 기존 사용자 선호는 유지한다.

시험 585개 외부 형상 그룹·3,510질의에서 프로젝트의 공개 비교 목적에 따른 최선 선택 비율은 **60.9117% → 84.2165%**, 평균 목적 후회값은 **0.00393828 → 0.000839765**였다. 일부 질의는 여전히 잘못 선택한다. 이 정답은 `train_plan_model.selection_objective`의 명시적 변경 비용·잔여 문제 정책이며, 외부 전문가가 검증한 개선 전후 쌍이 아니다. 자료에 없는 정답을 외부 라벨이라고 주장하지 않는다.

### 4. 외부 적층 형상으로 방향 예측 재학습

`neural_orientation_external_v2.json`은 외부 Thingi10K 형상에서 독립 계산한 방향별 높이/대각 길이, 하향 투영면적/전체 면적을 학습했다. Thing 단위 보류 시험 43그룹·47,520방향 조건에서 무차원 높이 MAE **0.0478237 → 0.0199682**, 하향면 MAE **0.0625070 → 0.0288909**였다. 실제 계산기와 독립 목표 계산의 최대 차이는 8.88e-16이다.

예측은 새로운 방향을 탐색할 때 사용하고 최종 표시는 메시에서 다시 계산한 값이다. 더 작은 예측 오차가 최종 추천 우위를 자동 보장하지는 않았다. 각 보류 Thing의 한 형상, 기존/새 12개 추가 후보, ‘정규화 높이+하향 투영면적’의 직접 계산 목적 비교에서는 **개선 0·동일 42·악화 1**이었다. 전체 경과와 해당 사례를 기록했다. 최종 방향의 일반 우위·연속 최적 방향을 확보했다고 설명하지 않는다.

## 사용자 입력과 화면

- 사용할 장비·재료의 검색 가능한 단일 선택창, 벽/홀 기준, 장비 크기 제한과 XYZ, 층 높이·선폭을 **검토 조건 한 패널**에 모았다. 별도 사이드바 ‘벽 기본값 출처’, ‘빌드 공간과 층 설정’ 블록은 제거했다.
- 정확히 일치하는 장비의 출처 있는 빌드 치수가 서로 모순되지 않을 때 동일 XYZ 입력을 자동 채운다. 장비·재료 조건에 층 높이가 있고 서로 일치하면 동일 층 높이 입력을 채운다. 값을 편집할 수 있으며, 크기 제한은 사용자가 적용했을 때만 검토한다.
- 장비·재료 변경 시 이전 조건의 값을 그대로 잘못 인용하지 않는다. 자동 층 높이를 새 미등록 재료에 붙이지 않으며 사용자가 직접 바꾼 층 높이는 유지한다.
- 출처·원본·근거는 내부 기록과 요청해서 펼치는 상세/내보내기에 남긴다. 첫 화면은 종합 결론과 조치이며 새 특징 그림도 요청할 때 계산한다.

## 재현 순서

저장소 루트에서 새 실행 폴더를 사용한다. 기존 결과가 있으면 덮어쓰지 않고 중단한다. CPU PyTorch는 공식 `https://download.pytorch.org/whl/cpu`에서 설치했고, 학습용 의존성은 `requirements-training.txt`, 실제 버전은 `data/training/environment.json`에 있다.

```powershell
$runDir = 'C:/Users/JIN/Documents/ChatGPT/DFM/study/NEW-RUN'
.venv/Scripts/python.exe scripts/acquire_public_training.py mfcad --root "$runDir/archives"
.venv/Scripts/python.exe scripts/build_training_database.py --archive "$runDir/archives/MFCAD-original.zip" --database "$runDir/training.sqlite" --workers 4
.venv/Scripts/python.exe scripts/audit_external_feature_labels.py --database "$runDir/training.sqlite" --output "$runDir/label-audit"
.venv/Scripts/python.exe scripts/train_external_features.py --database "$runDir/training.sqlite" --output "$runDir/models/external_feature_gnn_v2.json" --epochs 45
.venv/Scripts/python.exe scripts/train_external_plans.py --cases "$runDir/label-audit/pocket-cases.json" --output "$runDir/plan-training"
.venv/Scripts/python.exe scripts/download_thingi.py --root "$runDir"
# download_thingi.py가 저자 v1.5.0 metadata CSV 3개와 SHA도 함께 기록한다.
.venv/Scripts/python.exe scripts/import_thingi_training.py --root "$runDir"
.venv/Scripts/python.exe scripts/train_external_orientation.py --root "$runDir" --output "$runDir/orientation-final" --epochs 70
.venv/Scripts/python.exe scripts/download_mfinstseg.py --root "$runDir"
.venv/Scripts/python.exe scripts/import_mfinstseg_archive.py --root "$runDir" --partitions '../study/public-cad-data-2026-09-29/mfcad'
```

Thingi10K metadata와 MFCAD++ 접근 실패, 실제 원본 SHA·모델 SHA·평가 수치·실패 후 수정은 `validation/external-training-2026-09-30/` 및 로컬 원본 연구 폴더에 보관한다.

## 최종 검사와 실행본

전체 `tests_v3` 최초 실행 1,299개 중 1,292개 통과·7개 실패를 보존했다. 구 표본 모델의 measured_count 누락, 첫 결론에서 요청 전 특징 그림 렌더와 그림 ID 충돌을 수정했다. 비활성 XYZ 위젯을 먼저 편집하거나 삭제된 출처 입력창을 찾던 구 UI 검사도 실제 사용 순서와 새 화면에 맞게 고쳤다. 실패 7개를 모두 재검사했다. 그 후 변경 영역 133개 검사 모두 통과, 추가 원·코너·두 위치 화면 검사 포함 최종 위치 검사 24개 모두 통과했다. 단일 전체 실행이 처음부터 모두 통과했다고 바꾸지 않는다.

바탕화면 `C:/Users/JIN/Desktop/AM-DFM_v3_0`에 배포하고, 그 실행 환경에서 최종 모델·독립 CAD·화면 연동 38개를 통과했다. 저장소와 실행본의 코드·가중치 96파일 SHA가 일치한다. 이전 파일은 `study/external-training-2026-09-30/desktop-before-update/`에 보관했다. 공개 원본 DB 세 개의 SQLite quick_check는 모두 ok이다. 현재 Thingi DB의 적격 표시는 1,052개이며 실제 학습 전 추가 체적 검사를 통과한 수는 1,051개로 구분한다.

실제 localhost:8507에서 Original Prusa MK4S 선택 시 XYZ가 250/210/220으로 채워지는 것과 간결한 종합 결론을 확인했다. 실행 때 대용량 DB·PyTorch·외부 API를 요구하지 않는다. 로컬 Streamlit 서버는 기존 8507에 사용 중인 프로세스가 없는 것을 확인하고 시작했다.

마지막 실제 화면 검사에서 독립 삼각 포켓 STEP를 파일 업로드하고 공구 지름 9·날 길이 10·돌출 길이 12 mm로 검토했다. 학습 특징 1곳이 인식됐고 바닥 폭 10.5·벽 높이 8·진입원 지름 7 mm가 표시됐다. 종합 결론의 조치는 먼저 7 mm보다 작은 공구를 선택한 뒤 그 공구 반경만큼 내부 코너 여유를 추가하는 것이었다. ‘문제 위치 보기’를 누르면 해당 위치 제목에 초점이 이동하고 CAD 면 10·형상 그림·측정표가 바로 표시되는 것을 확인했다. `browser-final-check.json`은 실제 접근성 트리와 화면 확인 기록이다.
