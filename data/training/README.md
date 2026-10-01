# 외부 데이터와 학습 기록

**최신:** [전수 학습·위치·수정 전후 검증](../../docs/project-knowledge/AI_FULL_CORPUS_2026-09-30.md)과 `full-corpus-catalog.json`을 우선한다. 적격 적층 42,295·절삭 77,883기록 중 가중치 학습은 84,513기록이다. 아래 표는 현재 전수 검사 상태다. 원본·검증·시험·반복 후보 행을 구분한다.

실제 로컬 원본 DB 위치·반입 상태·제품 모델 SHA는 `catalog.json`에 있습니다. 원본 ZIP·DB는 저장소 밖 `study/external-training-2026-09-30/`에 보존합니다. 제품은 학습한 JSON 가중치를 사용하며, 실행 때 대용량 DB나 PyTorch를 읽지 않습니다.

| 자료 | 로컬 반입 | 현재 사용 |
|---|---:|---|
| [MFCAD](https://github.com/hducg/MFCAD) | STEP 15,488개 | 외부 면 라벨로 GNN 학습; CAD 포켓 재측정; 개선안 순위 학습 |
| [Thingi10K](https://github.com/Thingi10K/Thingi10K) | 메시 9,998개 | 개별 이용 조건·형상 품질을 통과한 1,375개로 방향별 기하량 학습 |
| [MFInstSeg](https://github.com/whjdark/AAGNet) | STEP 62,495개 | 전체 면 순서·면적·중심·인접 관계 대조에서 62,395개 검증; 의미·경계·바닥 공동 GNN 학습 |
| [PBF-LB/M orientation](https://huggingface.co/datasets/sebius/pbflbm-part-orientation) | STL 40,000개 | 40,000개 전체에서 방향별 기하량 재측정 |
| [CadQuarry](https://huggingface.co/datasets/jacobjennings/cadquarry) | STEP·STL·파라미터 1,000개 | 메시 품질 통과 920개로 방향 모델 학습; 학습 제외 STEP 시연 형상 제공 |
| [MFCAD++](https://pure.qub.ac.uk/en/datasets/mfcad-dataset-dataset-for-paper-hierarchical-cadnet-learning-from/) | 0개 | 공식 ZIP HTTP 403. 확보·학습 완료로 표현하지 않음 |
| [CADSynth](https://www.scidb.cn/en/detail?dataSetId=931c088fd44f4d3e82891a5180f10d90) | 0개 | 공식 UI 다운로드 미응답·공개 API 403 기록 보존 |

MFCAD의 MIT 원문은 `MFCAD-LICENSE.txt`, 사용한 Thingi10K 개별 모델의 저자·이용 조건·링크는 `thingi-full-attribution.json`입니다. MFInstSeg의 저자 페이지는 CC0를 선언하지만 원본 ZIP에는 별도 이용 조건 파일이 없습니다. 원본 형상은 GitHub에 자동 재배포하지 않습니다.

학습 대상은 서로 다릅니다. 특징 인식은 외부 면 라벨, 방향 예측은 외부 형상에서 독립 계산한 기하량, 개선안 선택은 외부 CAD 치수에 적용한 프로젝트의 명시적 비교 정책입니다. 외부 자료에 전문가의 개선 전후 쌍이 들어 있었다고 설명하지 않습니다.

재현 순서는 `docs/project-knowledge/EXTERNAL_AI_TRAINING_2026-09-30.md`를 따릅니다. 시험 분할·실패·재학습·내보내기 대조는 `validation/external-training-2026-09-30/`에 있습니다.

추가 DB·모델·시연 형상은 `expansion-catalog.json`과 `docs/project-knowledge/AI_EXPANSION_2026-09-30.md`를 따릅니다. 신규 원본은 `study/ai-expansion-2026-09-30/`에 별도로 보존합니다. CadQuarry 소스 문자열은 실행하지 않습니다. PBF 자료의 정위치 회전 라벨은 보관하지만 제조성 최적 방향의 정답으로 사용하지 않습니다.
