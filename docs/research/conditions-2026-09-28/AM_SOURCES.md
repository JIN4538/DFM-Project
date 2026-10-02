# 적층 조건 DB 출처 감사 — 2026-09-28

`data/conditions/am.json`에는 **11개 1차 출처, 33개 조건 기록, 118개 파라미터**를 등록했다. MEX 11개, VPP 8개, 고분자 PBF 9개, 금속 PBF 5개다. 전 세계 장비·재료 전체를 수집했다는 뜻이 아니다. 값의 출처·조건을 확인한 부분을 독립 레코드로 보존한 첫 판이다.

## 실제 계산에 연결되는 범위

| 항목 | 자동 연결 수 | 의미 |
|---|---:|---|
| `build_volume_mm` | 8 | Prusa 4개 / Formlabs VPP 4개 장비의 명목 X·Y·Z 공간. 사용자가 공간 제한을 켤 때만 사용 |
| `layer_height_mm` | 17 | MEX 7개, VPP 4개, Fuse 2개, EOS 4개에 명시된 층 높이 |
| `line_width_mm` | 7 | 정확한 MK4 프리셋의 명목 둘레 선폭. 현재 고정폭 기하 탐색의 입력 |
| 나머지 | 86 | 벽/구멍/배출구/간격, 온도, 노출시간, 재료별 공간, 방향별 시험편 물성 등 열람 전용 |

**최소 벽 기준은 하나도 자동 등록하지 않았다.** 소스의 벽 방향·연결조건·경계값과 현재 법선 레이 표본 측정의 의미가 일치한다는 증거가 부족하기 때문이다. 이 선택은 자료 부족을 숨기는 것이 아니라, 확인한 제조사 수치를 다른 의미의 측정에 잘못 대입하지 않기 위한 것이다. 구멍·배출구·조립 간격도 아직 현재 AM 코드가 자동 측정하지 않으므로 참고값으로 보존했다.

## 출처와 채택 범위

| ID | 원문 | 채택한 범위 / 확인 위치 |
|---|---|---|
| AM-PRUSA-FAQ | [Prusa FAQ](https://help.prusa3d.com/article/faq-frequently-asked-questions_1932?product=xl) | `What are the printer dimensions?`의 MK4/S, XL, CORE One, CORE One L 공간 |
| AM-PRUSA-SETTINGS-1142 | [고정 커밋의 PrusaResearch 1.14.2 INI](https://github.com/prusa3d/PrusaSlicer-settings/blob/a40f669e7c3ff4dfe05a937fc08fc57993dcf0d5/live/PrusaResearch/1.14.2.ini) | 정확한 print/filament/printer 및 SLA 프로필. 각 JSON 파라미터에 상속 원점과 줄 번호 기록 |
| AM-FORMLABS-VOLUME | [Formlabs 장비 공간](https://formlabs.com/support/What-is-the-build-volume-of-the-Form-3L-and-Form-3BL/) | Form 4/4L/3/3L; Fuse 재료별 공간 및 모서리 주석 |
| AM-FORMLABS-FORM4-DESIGN | [Form 4 설계 사양](https://formlabs.com/support/Design-specifications-for-3D-models-Form-4-generation/) | Grey Resin V5·50 µm 조건의 벽/구멍/배출/간격/특정 보 시험 가이드 |
| AM-FORMLABS-FUSE-SPECS | [Fuse 사양 비교](https://formlabs.com/3d-printers/fuse-1/tech-specs/) | Fuse 1, Fuse 1+ 30W 열의 챔버·층 높이. Fuse X1 값과 구별 |
| AM-FORMLABS-FUSE-DESIGN | [Fuse 1 세대 설계 사양](https://formlabs.com/support/Design-specifications-for-3D-models-Fuse-1/) | Nylon 12 기본 특징, Nylon 12 GF/11/11 CF/TPU90A별 조건 |
| AM-FORMLABS-NYLON12-TDS-REV01 | [Nylon 12 V1 TDS](https://formlabs-media.formlabs.com/datasheets/2201730-TDS-ENUS-0.pdf) | PDF 2쪽, 물성 표와 각주. 2020 Rev.01 판본 |
| AM-EOS-P110 | [FORMIGA P 110 Velocis](https://www.eos.info/polymer-solutions/polymer-printers/formiga-p-110-velocis) | Technical Data의 명목 챔버 크기 |
| AM-EOS-M290 | [M 290 장비 사양](https://www.eos.info/metal-solutions/metal-printers/data-sheets/sds-eos-m-290) | Technical Data와 플랫폼 포함 각주 |
| AM-EOS-316L-202207 | [316L Material Data Sheet](https://www.eos.info/03_system-related-assets/material-related-contents/metal-materials-and-examples/metal-material-datasheet/stainlesssteel/material_datasheet_eos_stainlesssteel_316l_en_web.pdf) | PDF 5/7/10/12쪽, M290의 20/40 µm 공정 정보·제조상태 방향별 인장값; 29쪽 한계 |
| AM-EOS-ALSI10MG-PDF | [AlSi10Mg Material Data Sheet](https://www.eos.info/03_system-related-assets/material-related-contents/metal-materials-and-examples/metal-material-datasheet/aluminium/material_datasheet_eos_aluminium-alsi10mg_en_web.pdf) | PDF 5/7/11/13쪽, M290의 30/60 µm 공정 정보·제조상태 방향별 인장값; 36쪽 한계 |

웹 원문은 2026-09-28에 직접 열람했다. 공식 사이트라고 해서 표의 모든 숫자를 검증 없이 수용하지 않았다. 원문의 핵심 값·연결 조건은 JSON 안에 있고 원문 전체를 배포 파일에 복제하지 않았다.

## 오류·판본·적용 조건을 구분한 항목

1. **명목 공간과 실제 부품 공간:** M290의 명목 Z에는 플랫폼이 포함된다. Fuse는 재료별 수축 보정과 둥근 모서리가 있다. 두 값을 허용 직육면체로 자동 대입하면 틀린 통과가 가능하므로 참고 전용이다. P110도 챔버 사양을 수축 보정된 완성 부품 공간으로 바꾸지 않았다.
2. **Prusa FAQ의 MINI+:** 열람본에 다른 공식 안내와 일치하지 않을 가능성이 있는 공간 행이 있다. 해당 행은 DB에 채택하지 않았다. 원문의 오타를 추측으로 수정해 확정값으로 만들지 않았다.
3. **Prusa 버전과 모델:** INI `1.14.2`를 선택한 재현용 판본이다. 현재 최신 판본이라는 주장이 아니다. MEX 조건은 `MK4` non-Input Shaper이며 MK4S·MK4IS로 자동 대체하지 않는다. 소재·노즐에 맞는 `compatible_printers_condition`을 확인했다.
4. **상속 해석:** 자식 프로필에 없는 층 높이·선폭·온도는 상속 원점을 추적했다. 최종 필드와 원점의 실제 줄 번호를 보존했다. `0.4 mm` 노즐에서 `0.45 mm`, `0.6 mm` 노즐에서 `0.65 mm`인 명목 둘레 설정을 노즐 지름과 구분했다.
5. **명목 선폭:** 위 선폭은 설정값이다. 실제 가변폭 생성기·첫층·브리지·갭 채움까지 일정하다는 뜻이 아니다. 고정폭 탐색 결과를 완전한 PrusaSlicer 경로 검증으로 설명하지 않는다. 온도·밀도도 현재 물리 해석을 실행시키는 값이 아니다.
6. **Form 4 경계:** 지지/비지지 벽 권장값은 같지만, 그 값 이하에서 변형 가능하다는 본문도 있다. 현재 코드에서 등호를 곧바로 합격 처리하지 않도록 자동 벽 기준을 배제했다. 구멍의 CAD 의도값과 표의 실제 출력 치수를 혼합하지 않았다.
7. **조건부 각도:** Form 4의 경사각 수치는 특정 길이·폭·두께의 시험 보에 한정된다. 전체 VPP 공정의 하향면 임계각으로 전이하지 않았다.
8. **서로 다른 SLS 기준:** [Form Now 안내](https://now.formlabs.com/resources/nylon-12-sls)는 원 제조사 설계 문서보다 강화된 서비스 기준이라고 밝힌다. 그 수치와 Fuse 원 설계 가이드의 방향별 벽 기준을 한 보편 수치로 합치지 않았다.
9. **Nylon 12 물성 판본:** 2020 TDS의 탄성률과 [다른 공식 TDS](https://formlabs-media.formlabs.com/filer_public/d9/6e/d96ee043-0503-438f-b732-e0e8a03f9276/nylon_12_tds.pdf)의 값이 다르다. 이번에는 실제 원페이지와 시험조건을 대조한 2020판을 별도 기록으로 명시했다. 현행 제품 물성으로 최신값처럼 표시하지 않는다.
10. **EOS 벽 수치:** 316L의 공정별 벽 수치 차이를 PDF 이미지에서 확인했다. 크고 작음을 보고 임의 수정하거나 평균내지 않았다. 형상·지지·방향 조건이 충분하지 않으므로 참고값에 한정한다.
11. **EOS 물성:** 제조상태/열처리 상태, 수직/수평, 시험편 가공 여부와 표본 수를 구분했다. AlSi10Mg 60 µm 표에는 표본 수가 없어 추정하지 않았다. 실측 결함 면적률을 출력 성공 확률로 바꾸지 않았다.
12. **화학 조성:** EOS의 현행 HTML과 보관 PDF에서 일부 합금 조성 범위가 다르다. 이번 DB는 서로 다른 판본의 조성을 합쳐 등록하지 않았다.

## 재현용 파일 지문

| 작업용 원본 | SHA-256 |
|---|---|
| PrusaResearch-1.14.2.ini | `dcac7cbf4b32ead42d145481cde0f162b949bf4024c7fe45f88ac0b2c2ec1371` |
| eos-316l.pdf | `c834280f977c0dde9039319b8fa11d3882d48ad75e50b47754359ce9044eac6f` |
| eos-alsi10mg.pdf | `5af0eb6a8884baaaeed3850260b651abe14dcdd3d8d9ea39e937496fe992c41f` |
| formlabs-nylon12-rev01.pdf | `d2742113e14b958ae21c68f92df2ffe9a6006e2c4a70974c7d80d22a02b9f400` |

원본·상속 해석 결과·PDF 확인 이미지는 저장소 옆 `study/conditions-2026-09-28/am/`에 있다. 이것은 검토 작업 보관소이며 앱은 로컬 JSON만 사용한다. PDF 주요 데이터 9쪽을 렌더하여 행·열·조건·단위를 원페이지와 대조했다. 전문을 모두 전사하거나 모든 물성을 등록한 작업은 아니다.

## 완료한 데이터 검사

- 각 프로필의 `source_ids`와 모든 수치의 출처/위치/성격/자동 적용 여부를 연결했다.
- 알 수 없는 값은 필드를 생략했고 `0` 또는 허위 합격 기준을 넣지 않았다.
- 현재 `ConditionLibrary`에 AM JSON 단독으로 로드: **33개 모두 통과**.
- 현재 `am_profile()`로 **33개 모두 실제 `Profile` 생성·검증 통과**.
- 실제 자동 연결 키는 공간·층높이·명목선폭뿐임을 확인했다.
- INI에서 가져온 **58개 수치**를 파라미터가 지정한 원본 줄의 값과 독립 재대조했고, 원본 파일 4개의 SHA-256을 다시 확인했다.
- 위 검사는 스키마·단위·계산 입력 연결 확인이며 물리적 출력/소재 인증 검증이 아니다. 앱 전체 회귀검사와 UI 확인은 통합 작업 기록을 따른다.

장비 설정·레진 색상/판본·분말 제품번호·공구 조건을 사용자가 바꾸면 자료의 일치 여부도 달라진다. 기록을 많이 모았다는 이유만으로 성공 확률, 모든 방향의 최적성, 실제 제조 가능성을 확정하지 않는다.
