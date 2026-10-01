# 공개 CAD·적층 데이터 대안과 학습 우선순위

조사일: 2026-09-29. 공식 데이터 설명·원저자 저장소·논문과 현재 런타임/검증 기록을 대조했다. 이번 조사는 데이터 다운로드·모델 훈련·앱 반영 완료를 뜻하지 않는다. MFCAD++ 상세는 같은 폴더의 별도 조사 기록을 따른다.

## 현재 AI의 역할과 결과

`amdfm/neural_orientation.py`는 26방향에서 이미 측정한 높이·하향면 지표로 미측정 방향의 값을 예측하고 다음 측정 방향을 고른다. 높이망은 35→64→48→24→1, 하향면망은 62→96→64→32→1이며 지도학습으로 훈련한 딥러닝이다. 원시 STEP의 특징을 읽는 모델은 아니다. 선택 방향은 기하 엔진으로 재측정한다.

`dfm/rl_planner.py`는 기존 엔진이 찾은 홀·오목 원통·직사각 포켓의 치수와 공구 조건을 바꾸는 순서를 제안한다. 64→64→32→1 신경망의 Double DQN이므로 **절삭도 이미 딥러닝을 사용한 강화학습**이다. 딥러닝은 모델 구조, 지도/강화학습은 학습 방식으로 서로 배타적인 선택이 아니다. AM에는 방향 평가를 빠르게 예측하는 회귀 문제, CNC에는 선행 변경이 다음 행동을 가능하게 하는 순차 문제를 설정한 것이 현재 구분의 이유다. 공정 자체가 특정 학습법을 요구해서 나눈 것은 아니다.

- AM 생성 시험 120형상·960조건에서 최종 추천은 기존 26방향 대비 개선 643/동일 287/악화 30. 후보 최선의 평균 후회값은 큰 면+보간 0.005502, 큰 면+신경망 0.004287이나, 큰 면 후보 자체의 효과가 크다. [방법](../../../validation/neural-localization-2026-09-29/orientation/METHOD.md).
- CNC 최종 수치 시나리오 490건에서 DQN은 기존 후보의 정확한 최저비용 대비 우수 0/열세 151/동일 339, 실제 최종 선택 경로의 신규 채택 0. 따라서 현 DQN을 더 학습하면 최선이라는 근거는 없다. [최종 결과](../../../validation/neural-localization-2026-09-29/rl/FINAL_RESULTS.md).
- 별도 실제 STEP 감사에서는 CNC 33파일·594조건 중 선택안 비교 122건에서 1건 비용 감소, AM 47파일·188조건에서 새 신경망 방향 채택은 같은 부품의 2공정 조건이었다. 수치 시나리오 결과와 합쳐 일반 정확도로 부르지 않는다. [CNC](../../../validation/neural-localization-2026-09-29/cad-audit/cnc-run-003/README.md), [AM](../../../validation/neural-localization-2026-09-29/cad-audit/am-run-003/README.md).

## 데이터별 실제 학습 대상

| 자료 | 공식 제공 내용 | 이 프로젝트의 적합한 사용 | 사용권·확보 상태 |
|---|---|---|---|
| Fusion 360 Gallery Segmentation | 현 STEP 포함 35,680부품, 확장 STEP 42,912개. 각 면에 Extrude/Cut/Fillet/Chamfer/Revolve 등의 8개 생성연산 라벨 | B-Rep 면·인접관계 인코더 사전학습. 가공 특징 데이터로 미세조정하기 전 보조 학습 | 비상업 연구 전용, 전체 데이터 재배포 금지. 공식 다운로드 링크 있음 |
| Fusion 360 Gallery Assembly의 holes | 8,251조립체·154,468부품, ASM 특징인식으로 구한 홀 종류·지름·길이·축·위치·면/모서리 | 실제 설계 홀 인식의 외부 비교·추가 학습. 카운터보어/카운터싱크 등 기존 범위 확장 후보 | 같은 Autodesk 데이터 라이선스. 메타데이터 규격 확인, 파일은 미다운로드 |
| ABC | 100만 CAD 모델. STEP·Parasolid·메시·해석 곡면/곡선 및 기하 라벨 | B-Rep 표현 학습, 복잡한 실제 형상 표본, 현재 엔진 실패 사례 발굴 | 논문은 MIT 배포를 설명하나 공식 사이트는 CAD 저작권이 제작자에게 있고 Onshape 조건을 참조하도록 함. 개별 출처·조건 기록 필요 |
| Thingi10K | 10,000개 3D 프린팅용 모델과 기하·출처·개별 라이선스 메타데이터 | AM 방향별 측정 데이터 확대, 비정상 메시·복합 형상 시험 | 모델별 10종 라이선스가 혼재. 허용되는 모델을 필터링. 공식 미러·패키지 있음 |
| Slice-100K | 10만 개 이상 G-code와 STL·분류·렌더링. PrusaSlicer로 만든 압출 적층 경로 | 슬라이서 파생량 학습·경로 대조 후보. 최적 방향이나 DFM 수정 정답으로 직접 사용 불가 | 데이터셋 CC-BY-4.0, 원모델 권리 별도. 공식 README가 데이터 링크 장애를 명시하므로 현재 즉시 확보 가능으로 간주하지 않음 |
| DeepCAD | 178,238 CAD 생성 명령 시퀀스. Onshape/ABC 계열의 스케치·돌출 표현 | 향후 파라메트릭 CAD 수정·생성 연구 | 코드 MIT, 원모델 조건은 별도. 지금의 문제 탐지·조치 품질에 대한 직접 정답이 없어 우선순위 낮음 |
| Fusion 360 Reconstruction | 8,625개 사람의 스케치·돌출 순서와 중간 형상 | 편집 가능한 설계 시퀀스 학습. DFM 수정 전후 쌍을 별도로 만들 때 유용 | Autodesk 비상업 연구 조건. CAD 작성 순서가 제조 조치의 정답이라는 뜻은 아님 |
| NIST Engineering Design Models / AM Bench | 전자는 산업 CAD 보관본, 후자는 명시된 적층 조건의 측정·벤치마크 | CAD는 외부 형상 시험. AM Bench는 해당 측정량·조건을 다룰 때 선택 | CAD 저장소는 public-domain으로 설명하나 일부 오래된 파일은 열리지 않을 수 있음. AM Bench는 데이터별 DOI·메타데이터를 따라 선택. 현재 방향/조치 정답 학습의 일차 자료는 아님 |

위 표의 연결 근거:

- Fusion segmentation [공식 규격](https://github.com/AutodeskAILab/Fusion360GalleryDataset/blob/master/docs/segmentation.md), [현재 다운로드 표](https://github.com/AutodeskAILab/Fusion360GalleryDataset), [라이선스](https://github.com/AutodeskAILab/Fusion360GalleryDataset/blob/master/LICENSE.md). 논문의 35,858개는 구형 SMT 자료이며 그중 178개는 STEP 변환 시 라벨 일관성을 확보하지 못해 현 기본판에서 제외됐다. 공식 문서 안의 분할 합계는 구형 숫자가 남아 있으므로 실제 배포판의 파일목록·분할 JSON으로 다시 고정해야 한다.
- Fusion assembly [공식 규격](https://github.com/AutodeskAILab/Fusion360GalleryDataset/blob/master/docs/assembly.md). 단위는 cm. `diameter`는 카운터보어/카운터싱크를 포함한 최대경이고 `length`는 마지막 원통 구간 바닥까지다. 현재 앱의 개별 원통 구간 정의와 즉시 동일시하지 않는다. 면 인덱스 참조는 원본 SMT 기준이므로 STEP 변환 뒤 면 대응을 검증해야 한다. ASM 자동 라벨이며 전문가가 검수한 DFM 판정은 아니다.
- ABC [공식 사이트](https://deep-geometry.github.io/abc-dataset/), [원논문](https://openaccess.thecvf.com/content_CVPR_2019/papers/Koch_ABC_A_Big_CAD_Model_Dataset_for_Geometric_Deep_Learning_CVPR_2019_paper.pdf), [현재 Onshape 조건](https://www.onshape.com/en/legal/terms-of-use). 현재 조건은 무료계정의 공개 문서 이용권과 과거/별도 LICENSE 탭의 예외를 구분한다. 코드 저장소 MIT 표기만으로 모든 원본 CAD의 무조건적 사용권을 대신하지 않는다.
- Thingi10K [저자 저장소](https://github.com/Thingi10K/Thingi10K), [원논문](https://arxiv.org/abs/1605.04797). 동일 Thing에 속한 변형·여러 파일을 같은 분할에 넣는다.
- Slice-100K [원논문](https://proceedings.neurips.cc/paper_files/paper/2024/hash/e8699fa39bf3117065b6727dccaafd54-Abstract-Datasets_and_Benchmarks_Track.html), [보충자료](https://proceedings.neurips.cc/paper_files/paper/2024/file/e8699fa39bf3117065b6727dccaafd54-Supplemental-Datasets_and_Benchmarks_Track.pdf), [공식 README](https://github.com/idealab-isu/Slice-100K). 2026-03-04자 접근 링크 장애 안내를 조사일에 확인했다. 공식 [Hugging Face 항목](https://huggingface.co/datasets/idealab-isu/Slice-100K)도 데이터가 없는 상태여서 전체 파일을 확보했다고 보고하지 않는다.
- DeepCAD [논문](https://openaccess.thecvf.com/content/ICCV2021/papers/Wu_DeepCAD_A_Deep_Generative_Network_for_Computer-Aided_Design_Models_ICCV_2021_paper.pdf), [저자 저장소](https://github.com/rundiwu/DeepCAD), [코드 라이선스](https://github.com/rundiwu/DeepCAD/blob/master/LICENSE). Fusion reconstruction [공식 연구 페이지](https://www.research.autodesk.com/publications/fusion-360-gallery/).
- NIST [CAD 저장소](https://github.com/usnistgov/engineering-design-models), [AM Bench 설명](https://www.nist.gov/ambench), [데이터 접근 안내](https://www.nist.gov/ambench/am-bench-data-management-systems).

## 가장 실용적인 개선 순서 — 현재 코드·결과에 따른 제안

1. **절삭 특징 인식을 먼저 학습한다.** STEP의 면·모서리·인접관계를 읽는 작은 그래프 모델로 홀·포켓·홈 등 특징 후보와 면 묶음을 낸다. MFCAD 계열을 주 학습 대상으로 검토하고 Fusion 생성연산 라벨은 사전학습, Assembly 홀 정보와 기존 외부 STEP는 별도 평가/미세조정 대상으로 둔다. 모델이 후보를 찾으면 CAD 커널이 치수·축·깊이·공구 관계를 계산한다. 최종 산출은 라벨뿐 아니라 `feature instance → CAD face IDs → measured dimensions → finding` 연결이다. 현재 DQN은 특징을 인식하지 않으므로 단순 추가 훈련으로 이 누락을 해결할 수 없다.
2. **AM은 실제 형상에서 방향별 학습 자료를 만든다.** Thingi10K의 허용된 모델과 출처가 확인된 STEP를 부품 계열로 나눈 뒤 기존 26방향·큰 면·구면 방향을 동일 설정으로 측정한다. 현 모델이 취약한 오목형상, 큰 평면과 작은 특징의 혼합, 복합체를 추가한다. 목표가 현 규칙 지표 최적화인 만큼 장비 없이도 학습 표적을 만들 수 있다. 이것은 규칙을 더 잘 탐색하는 학습이며 규칙 자체를 새로 발견했다는 주장은 하지 않는다. Slice-100K의 접근이 복구되면 슬라이서 수치까지 확장할 수 있다.
3. **CNC 계획기는 탐색 결과를 지도학습하는 기준선부터 둔다.** 현 상태전이·비용은 알려져 있고 계산도 싸다. 작은 문제는 전수/분기 탐색, 큰 문제는 고정 예산 beam search로 더 좋은 경로를 생성하고 이를 모방하는 정책·후보 순위 모델을 학습한다. 같은 개별 특징 행동 공간·같은 예산으로 기존 조합, greedy, search, imitation, DQN을 비교해야 한다. 기존 일괄 후보보다 넓어진 행동 공간 효과를 강화학습 성과로 합산하지 않는다. 좋은 기록이 확보된 뒤 offline RL을 비교 후보로 추가할 수 있지만, 현재 자료만으로 RL이 가장 유리하다고 정할 이유는 없다.
4. **수정의 정답을 별도로 축적한다.** 공개 CAD의 원형·생성순서는 좋은 수정안의 정답이 아니다. 현재 조건, 잠긴 치수/기능, 가능한 수정, 재계산 결과, 사용자의 명시적 선택과 이유를 저장한다. 실제 공구 규격도 후보 제약으로 연결하면 임의 지름·길이의 공구 제안을 줄일 수 있다. 공구 카탈로그는 학습 정답이라기보다 가능한 행동을 제한하는 자료다.

형상 인코더의 구현 후보는 [UV-Net](https://github.com/AutodeskAILab/UV-Net)과 [BRepNet](https://github.com/AutodeskAILab/BRepNet)이다. UV-Net은 면/모서리의 UV 표본과 인접 그래프를, BRepNet은 B-Rep 위상 구조를 사용하는 방법이다. 이는 바로 DFM을 완성하는 사전학습 모델이라는 뜻이 아니다. 현재 확인한 코드 라이선스는 [UV-Net MIT](https://github.com/AutodeskAILab/UV-Net/blob/main/LICENSE), [BRepNet CC-BY-NC-SA-4.0](https://github.com/AutodeskAILab/BRepNet/blob/master/LICENSE)로 서로 다르며 데이터 조건과 별개다.

## 다음 실험의 최소 계약

- 원본 SHA·출처·라이선스·단위·가공/설계 라벨 의미·CAD 커널 버전·변환 실패를 기록한다. 정규화 CAD에 임의 mm 의미를 붙이지 않는다. Fusion segmentation STEP의 최장 축 [-10,10] 정규화와 assembly의 cm 단위도 구별한다.
- 부품 계열/원 설계/변형 기준으로 train-validation-test를 나눈다. 같은 형상의 다른 방향이나 조립체의 같은 부품을 양쪽에 흩뜨리지 않는다. DeepCAD/ABC 원출처 중복도 확인한다.
- 인식은 클래스별 precision/recall·면 IoU·특징 인스턴스 재현율, 측정은 치수·축 오차, 조치는 미해결 규칙 수·동일 비용·실제 최종 선택·계산 시간을 따로 평가한다. 인식 IoU를 최종 DFM 정확도로 표현하지 않는다.
- 현재 엔진 단독, 모델 단독 후보, 모델+기하 재검산을 같은 보류 사례까지 비교한다. 학습 이후 보지 않은 외부 STEP에서 실패 유형·범위 증가를 확인한 후 런타임에 연결한다.

이 순서는 확정된 성능 향상 결과가 아니라 현재의 인식 범위, 학습 표적과 최종 평가를 근거로 한 개발 우선순위다. 이번 작업에서는 원본 학습자료, 모델 가중치, 런타임 코드를 변경하지 않았다.
