# MFCAD 계열 공개 데이터: 학습 적합성·소규모 실물 파일 감사

확인일: 2026-09-29. 이번 작업은 출처 조사, 공개 STEP 두 개의 로드·라벨 검사, 공개 분할 목록의 중복 검사다. 전체 데이터 내려받기, 모델 학습, 앱 모델 교체는 수행하지 않았다. 기존 앱과 원자료는 수정하지 않았다. 재실행용 읽기 전용 감사 도구만 `scripts/audit_public_cad_data.py`에 추가했다.

이번 감사의 원본 URL·SHA와 결과 JSON은 [evidence/](evidence/)에도 보관했다. 외부 STEP·정답 라벨 원본은 포함하지 않았다. 같은 요청의 공구 자동 제안 구현은 [별도 인수 기록](../../project-knowledge/AUTOMATIC_TOOLING_DATA_2026-09-29.md)을 따른다.

## 결론과 권장 순서

**MFCAD++는 이 프로젝트의 절삭 특징 인식 학습에 사용할 수 있다.** 포켓·구멍·슬롯·단차·모따기·라운드의 면 영역을 먼저 알아내고 기존 기하 측정과 규칙에 연결하는 용도다. 세 데이터 모두 공구의 최적 지름·날장, 규칙 위반 여부, 개선 후 치수, 사용자 선호를 정답으로 제공하는 데이터는 아니다. 그런 학습 타깃은 특징/치수/선택 공구/규칙 버전으로 별도 구성해야 한다.

권장 순서는 MFCAD++ 면 의미분할 → MFInstSeg 인스턴스/바닥면 → 현재 규칙 기반 측정·공구 조건 비교와 연결이다. MFCAD 원본은 작은 로더 시험·기준선에 적합하다. 현재 사용자의 목표인 문헌·규칙에 따른 문제 탐지와 조치 품질을 평가 대상으로 유지한다. 적층 형상에도 일부 공통 기하 표현을 이전할 수 있다는 것은 연구 가설이며, 이 데이터의 가공특징 라벨을 적층 결함 라벨로 바꾸어 부르지 않는다.

## 1차 출처에서 확인한 데이터 정의

| 데이터 | 규모·형식 | 제공 타깃 | 출처 및 적용 |
|---|---|---|---|
| MFCAD | 공식 GitHub tree 직접 집계 STEP 15,488개, `.face_truth` 15,488개 | 15 가공특징+stock의 16개 면 클래스. STEP의 face name은 라벨 인덱스 | [저자 데이터 저장소](https://github.com/hducg/MFCAD), [원본 시각화 로더](https://github.com/hducg/MFCAD/blob/master/occ/dataset_visualizer.py). 작은 면 분류 기준선에 사용 |
| MFCAD++ | 배포 페이지 59,665개, STEP B-Rep 및 HDF5 graph 설명. ZIP 1.5 GB | 24 가공특징+stock = 총 25개 클래스. STEP `ADVANCED_FACE` name에 클래스 자체 저장 | [QUB 배포·DOI](https://pure.qub.ac.uk/en/datasets/mfcad-dataset-dataset-for-paper-hierarchical-cadnet-learning-from/), [저자 생성기 README](https://gitlab.com/qub_femg/machine-learning/mfcad2-dataset/-/blob/main/README.md), [라벨표](https://gitlab.com/qub_femg/machine-learning/mfcad2-dataset/-/blob/main/dataset_description.txt). 곡면/교차 특징을 포함하는 주 학습 후보 |
| MFInstSeg | 공식 분할 목록 총 62,495행. 이번 직접 감사의 서로 다른 ID는 62,477개 | STEP + JSON `seg`(25-class 면 분류), `inst`(면×면 인스턴스 관계), `bottom`(0/1 바닥면) | [AAGNet 저자 저장소](https://github.com/whjdark/AAGNet), [생성·라벨 설명](https://github.com/whjdark/AAGNet/blob/main/dataset/README.md), [공식 배포 링크](https://aistudio.baidu.com/datasetdetail/211864?lang=en). 같은 종류 포켓 여러 개를 나누고 깊이 측정 대상을 찾는 용도 |

MFCAD++의 논문 본문 §6.3에는 **59,655개**, QUB 배포페이지에는 **59,665개**가 기록되어 있다. 논문은 모델당 3–10개 특징을 설명한다. 10개 차이를 임의 교정하지 않고 이번 계획 수치는 실제 배포페이지를 따른다. 전체 ZIP 파일 목록 확인은 미실시다. [원 논문, DOI 10.1016/j.cad.2022.103226](https://doi.org/10.1016/j.cad.2022.103226), [기관 보관 PDF](https://pureadmin.qub.ac.uk/ws/portalfiles/portal/328098955/1_s2.0_S0010448522000240_main.pdf).

24와 25의 차이는 가공특징 수에 stock을 포함하는지에 따른 것이다. MFCAD++ 생성기의 `dataset_description.txt`와 `feature_creation.py`에서 0=chamfer, 1=through_hole, 12=blind_hole, 14=rectangular_pocket, 23=round, 24=stock을 확인했다. MFCAD 원본의 16클래스 인덱스를 그대로 재사용하면 안 된다.

## 라이선스·접근 상태

- **MFCAD:** 공식 저장소 [LICENSE](https://github.com/hducg/MFCAD/blob/master/LICENSE)는 MIT, Copyright (c) 2020 hducg. 이번 샘플과 분할 파일은 공개 raw URL에서 동의·로그인 없이 확보했다.
- **MFCAD++ 데이터:** QUB 배포페이지의 표기는 **CC BY**다. 해당 표에서 구체 버전까지 확인되지는 않았다. 저자 이름·논문·데이터 DOI·원본 URL·취득일을 보존한다. [생성기 코드 LICENSE](https://gitlab.com/qub_femg/machine-learning/mfcad2-dataset/-/blob/main/LICENSE)는 MIT, Copyright (c) 2025 Andrew Colligan이며 데이터 배포 라이선스와 구분한다. ZIP 직접 링크는 이번 웹 접근에서 HTTP 403을 반환했으므로 전체 파일을 확보했다고 보고하지 않는다.
- **MFInstSeg:** [AAGNet 저장소 LICENSE](https://github.com/whjdark/AAGNet/blob/main/LICENSE)는 MIT, Copyright (c) 2023 whj_dark. 공개 코드 및 저장소 샘플에 대한 근거다. 외부 [AI Studio 배포페이지](https://aistudio.baidu.com/datasetdetail/211864?lang=en)의 공개 HTML `keywords`에는 `CC0`가 있고 `description`은 62,495 STEP와 JSON instance labels를 명시한다. 그러나 동적 화면의 라이선스 본문·구체 버전·배포 ZIP 내용은 이번에 확인하지 않았다. 코드 MIT를 외부 전체 데이터의 라이선스로 자동 전파하거나 CC0 전문까지 확인했다고 말하지 않는다.

외부 업로드·계정 로그인·개인정보 제공·접근조건 동의는 수행하지 않았다. 제3자 Hugging Face 재포장은 탐색 중 발견했지만 사실·라이선스의 최종 근거로 채택하지 않았다.

## 분할 감사: 학습 전 반드시 고칠 점

원본 목록은 바꾸지 않고 다운로드한 바이트의 SHA와 원본 commit/blob 일치를 보존했다. 결과는 `study/public-cad-data-2026-09-29/mfcad/inspection.json` 및 `reusable_*_audit.json`에 있다.

| 데이터/분할 | 행 | 서로 다른 ID | 중복 행 |
|---|---:|---:|---:|
| MFCAD train | 9,292 | 9,292 | 0 |
| MFCAD val | 3,097 | 3,097 | 0 |
| MFCAD test | 3,099 | 3,099 | 0 |
| MFInstSeg train | 43,745 | 43,733 | 12 |
| MFInstSeg val | 9,375 | 9,374 | 1 |
| MFInstSeg test | 9,375 | 9,375 | 0 |

MFCAD 공개 분할은 [저자 MFCAD_GNN의 `experiments/simple`](https://github.com/hducg/MFCAD_GNN/tree/master/experiments/simple)에 있다. 세 집합 사이 ID 교집합은 없고 합집합 15,488개다. 이것은 기하 유사 형상의 부재까지 증명하지 않는다.

MFInstSeg의 [공식 분할 목록](https://github.com/whjdark/AAGNet/tree/main/MFInstseg_partition)은 다음 다섯 ID가 서로 다른 split에 겹친다.

| 교집합 | ID |
|---|---|
| train/val | `20221225_205134_10`, `20221225_205134_44`, `20221225_205134_52` |
| train/test | `20221225_205134_40` |
| val/test | `20221225_205134_32` |

따라서 62,495는 이 목록에서의 행 수이며 서로 다른 모델 수라고 그대로 부르면 안 된다. 전체 STEP를 받지 않았으므로 파일 수·기하 고유 개수는 아직 미확인이다. 원본 분할을 보존하고, 교집합 ID를 격리한 별도 clean split과 변경 내역을 만들어 학습해야 한다. 논문 비교용 원 분할 성적과 정리 분할 성적은 따로 기록한다.

MFCAD++ 배포페이지의 분할은 41,766/8,950/8,949(70/15/15%)이다. 전체 목록을 아직 내려받지 않아 교집합 검사는 하지 않았다. AAGNet의 MFCAD++ 재가공본은 위상 오류 파일을 제거해 개수가 줄었다고 [저자 README](https://github.com/whjdark/AAGNet#dataset)에 명시되어 있다. 원본과 정리본의 성적·파일 개수를 혼합하지 않는다.

추가 권장 검사는 STEP 이름·경로·내장 정답을 모델 입력에서 제거하기, 정확 중복 SHA와 기하 유사 그룹 검사, 부품 원형/특징 조합 계열 단위 분할이다. 무작위 면 단위 분할은 동일 부품의 면이 학습·시험에 함께 들어가는 누수를 만든다. 스케일·회전 증강은 분할 후 학습 집합에서만 수행한다.

## 실제 샘플을 읽어 확인한 결과

GitHub tree의 파일 크기를 먼저 확인하고 MFCAD 34,441-byte STEP+30-byte label, MFInstSeg 203,057-byte STEP+19,246-byte JSON만 받았다. 추가로 설명·라이선스·분할 목록을 받았으며 원본 source 25파일 합계는 약 2.03 MB다(API tree 응답·로컬 결과 제외). 공개 원본 파일은 저장소 외부 `study/.../mfcad/`에 있다.

실제 로드 환경: `DFM-Project/.venv/Scripts/python.exe`, Python 3.12.14, OCP 7.9.3.1. 두 STEP 모두 명시적 mm 단위를 포함한다.

| 샘플 | 텍스트/라벨 검사 | OCP 로드·기하 검사 |
|---|---|---|
| MFCAD `0-0-0-0-0-23` | 11면/11라벨, name은 0..10의 순열 | 유효한 단일 solid, 11면, 10×10×10 mm, 체적 850.464754671 mm³ |
| AAGNet `dataset/test` | 27면/27 `seg`, 27×27 대칭 `inst`, `bottom=1` 4면 | 유효한 단일 solid, 27면, 약 61.152895×41.809025×43.721100 mm, 체적 38,541.370279030 mm³ |

**MFCAD 면 순서 함정:** 실제 STEP 텍스트 face name 순서는 `[0,2,10,5,6,1,4,9,8,7,3]`이다. `face_truth[k]`는 k번째로 나타난 면이 아니라 **name이 k인 면**의 클래스다. 원본 로더처럼 `EntityFromShapeResult(...).Name()`을 읽어 매핑해야 한다. 텍스트 순서대로 zip하면 이 샘플부터 잘못된 학습 라벨이 된다.

**라벨명 모순:** 원본 MFCAD 시각화 코드의 `FEAT_NAMES[0]`는 rectangular_through_slot인데, 이번 샘플 label 0의 다섯 면은 두 축으로 45도 기울어진 평면이며 stock의 여섯 면은 축 정렬 평면이다. chamfer라는 해석을 지지한다. 전체 라벨 순서에 관한 [미해결 issue #2](https://github.com/hducg/MFCAD/issues/2)도 있다. 이 이슈의 제안표를 저자의 확정 답변으로 취급하지 않고, 전체 클래스의 독립 기하 검사를 후속 과제로 남긴다.

**MFInstSeg 면 인덱스와 주석 모순:** 이 샘플의 `ADVANCED_FACE` name은 전부 빈 문자열이다. JSON 인덱스는 B-Rep 순회와 맞춰야 한다. OCP에서 중복 제거한 face 순회 결과 label 24는 평면6개, 22는 평면10개, 1은 원통면9개, 23은 원통면2개로 관측됐고 생성기의 23=round와 양립한다. 반면 [dataloader 주석](https://github.com/whjdark/AAGNet/blob/main/dataloader/mfinstseg.py)의 tiny-remap 설명은 0=round, 23=chamfer로 뒤집혀 있다. 실제 [생성기 표](https://github.com/whjdark/AAGNet/blob/main/dataset/feature_creation.py)를 기준으로 어휘를 고정해야 한다. 이번 검사만으로 upstream pythonocc 7.5.1과 OCP 7.9.3.1의 모든 모델 면 순서가 같다고 보장하지 않는다.

이번 BRepCheck 통과는 두 샘플의 CAD 읽기·위상 검사 결과다. 데이터 전체의 품질, 학습 성능 또는 가공 판정의 정확도를 뜻하지 않는다. upstream의 crosscheck 스크립트는 삭제 경로가 있어 실행하지 않고 읽기 전용 검사만 별도로 작성했다.

### 샘플 SHA-256

| 파일 | SHA-256 |
|---|---|
| `mfcad_sample.step` | `56ceb6d91bb7d195501b2f3c72db3594b30f14bfea1780635e60e7bf71916164` |
| `mfcad_sample.face_truth` | `f2f64a06009adaf8da9b90bd957fec6732e9580069a7b88cc4b59169f71ffb30` |
| `mfinstseg_sample.step` | `fbcbc8d3d1996801de47b72432d37de15c8a571201262e6b9f660c782063e2dc` |
| `mfinstseg_sample.json` | `58dba6aa90fdd06be5f68209667afb183c76e3b5f192ae7786177aecea9ea63a` |

`study/public-cad-data-2026-09-29/mfcad/source_manifest.json`은 모든 원본의 URL·불변 URL·바이트 수·SHA를 기록한다. GitHub 원본 20개는 내려받은 바이트의 git blob SHA와 API tree를 대조했다. MFCAD commit `ef6d58a40164d5192666821ce98d0cc90e379fac`, AAGNet commit `e0e36b7a12a7f01a29d7be36efc22730d293a1bd`, MFCAD++ GitLab 조회 commit `c171b76bb6f7e2537fcfafe6324b64a07d5e98db`.

초기 OCP 환경 기록에서 배포 패키지명을 `cadquery-ocp`로 조회해 `PackageNotFoundError`가 한 번 발생했다. OCP 모듈 자체의 `__version__` 조회로 수정 후 두 STEP 로드가 통과했다. 데이터 오류를 수정한 결과가 아니며 다운로드 원본은 바꾸지 않았다.

## 재실행 가능한 감사 도구

[읽기 전용 감사 스크립트](../../../scripts/audit_public_cad_data.py)는 입력 경로를 인자로 받아 파일 SHA, 면/라벨 수, MFCAD name 매핑, MFInstSeg 행렬 구조, split 중복을 검사한다. `--ocp`를 사용하면 설치된 OCP로 실제 STEP 읽기·체적·치수·면별 곡면 종류를 기록한다. 원본이나 기존 보고서를 덮어쓰지 않는다. 전체 데이터의 semantic ground truth 검증 도구는 아니다.

DFM-Project 폴더의 PowerShell에서 실행:

```powershell
$auditData = '../study/public-cad-data-2026-09-29/mfcad'
.venv/Scripts/python.exe scripts/audit_public_cad_data.py --kind mfcad --step "$auditData/mfcad_sample.step" --labels "$auditData/mfcad_sample.face_truth" --split-train "$auditData/mfcad_train_list" --split-val "$auditData/mfcad_valid_list" --split-test "$auditData/mfcad_test_list" --split-format pickle --ocp
.venv/Scripts/python.exe scripts/audit_public_cad_data.py --kind mfinstseg --step "$auditData/mfinstseg_sample.step" --labels "$auditData/mfinstseg_sample.json" --split-train "$auditData/mfinstseg_train.txt" --split-val "$auditData/mfinstseg_val.txt" --split-test "$auditData/mfinstseg_test.txt" --ocp
```

`--output <새 JSON 경로>`로 저장할 수 있다. 기존 경로는 보존을 위해 거부한다. 종료코드 0은 요청한 입력 검사 통과, 2는 발견 사항 또는 불완전 검사다. 이번 재실행은 MFCAD **0**, MFInstSeg **2**였으며 후자는 위에 기록한 실제 split 중복/교집합을 정확히 보고한 결과다. 두 샘플 기하 검사는 모두 통과했다. `.face_truth`/분할 pickle은 임의 객체 생성을 차단하고 정수/문자열 목록 연산만 허용해 읽는다.

## 앱으로 연결할 실제 파이프라인과 평가

1. **입력 계약부터 고정:** 원본 SHA/라이선스/단위/면 인덱스/라벨 어휘/분할 버전의 manifest를 만든다. MFCAD++의 내장 class name 및 MFCAD ID/파일명은 학습 특징에서 제외한다. 보간·정규화한 기하 입력과 원래 mm 치수는 각각 보존한다.
2. **규칙과 별개인 인식 기여를 학습:** face adjacency, 곡면 종류, 면적·곡률·변 연결·오목/볼록과 UV 표본으로 작은 GNN 기준선을 학습한다. MFCAD++으로 면 클래스를 학습하고 MFInstSeg으로 같은 종류 특징의 인스턴스와 바닥면을 확장한다. 복잡한 교차 특징의 위치 recall이 실제 개선 목표다.
3. **치수는 정확 기하로 확인:** 예측 포켓/구멍의 면 그룹을 OCP 측정에 전달한다. 측정 실패/불확실 그룹을 별도로 기록한다. 공구 지름·날장·접근 방향에 대한 규칙 적용은 선택 조건과 문헌 출처를 입력으로 사용한다. 분류 확률을 치수 또는 공구 적합성 확률로 변환하지 않는다.
4. **조치 학습은 별도 데이터:** 검출한 특징에 대해 크기·공구·방향 후보를 만들고, 고정된 규칙 버전으로 재측정한 결과를 `상태-후보-수치변화-위반해소-새문제` 쌍으로 쌓는다. 기존 규칙 결과로 만든 teacher label과 사람이 독립 확인한 라벨을 구분한다. 현재 정책과 동일한 teacher의 일치율만으로 AI 발전을 주장하지 않는다.
5. **분리된 평가:** 면 macro-F1/mIoU, 인스턴스 위치 precision/recall, 치수 절대오차(mm), 기존 인식 대비 추가로 올바르게 찾은 문제, 잘못된 신규 경고, 추천 후 규칙 위반 변화, 선택 regret와 실행시간을 보고한다. 규칙 단독/학습 인식 추가/후보 생성 추가/순위모델 추가를 동일 잠금시험에서 비교한다.
6. **독립 부품 검증:** 지금 보유한 실제 STEP가 모델 선택·수정 과정에 이미 쓰였다면 개발 집합으로 취급한다. 새로운 부품 가족을 별도 잠금시험에 두고, 합성 데이터 내 성적과 분리한다. 학습량 1k/5k/전체 등의 학습곡선은 비용 대비 인식 개선을 보여주기 위한 실험 제안이며 이번에 실행한 결과는 아니다.

첫 구현의 적정 완료 기준은 “공개 특징 라벨을 정확한 면에 연결해 학습하고, 잠금 STEP에서 기존에 놓치던 특징/문제 위치를 늘리며, 잘못된 경고와 추천 악화를 함께 제시”하는 것이다. 공구 최적치수 데이터가 새로 생겼다는 주장이 아니다.
