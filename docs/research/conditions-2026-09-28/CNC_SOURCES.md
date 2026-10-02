# 절삭 공통 조건 DB의 수록 근거와 제외 기록

확인일: 2026-09-28. 데이터: `data/conditions/machining.json`.

이번 수록분은 **정확한 제품 번호의 엔드밀 19개, 장비 3개, 제품·조질을 특정한 소재 6개, 정삭 지침 1개**다. 공식 제조사 출처 24개를 연결했다. 광범위한 범용 CNC 공정 데이터베이스를 완성했다는 뜻은 아니다. 실제 장비로 검증한 자료는 없으며 모든 프로필은 `not_validated_by_project`다.

## 코드로 보내는 값

자동 적용은 선택한 엔드밀의 **명목 지름과 절삭부 길이** 38개 값이다. 이를 현재 코드의 폭/내부 반경/국소 벽 높이와 비교할 수 있다. 날 길이는 한 번에 그 깊이 전체를 절삭하라는 권고가 아니다.

`reach_mm`는 현재 코드와 UI에서 실제 장착된 공구의 끝에서 홀더까지 길이를 뜻한다. 따라서 카탈로그 전체 길이, 목부까지 길이, Harvey의 Overall Reach를 여기에 넣지 않았다. 장착 상태는 사용자 입력으로 남긴다. 엔드밀 자료에서 드릴링의 허용 홀 깊이비를 만들지도 않았다.

샹크·전체 길이·목부 치수·날 수·장비 이동량·주축 속도·소재 물성·정삭 권고는 **참고 전용**이다. 현재 엔진에 없는 홀더 충돌, 절삭력, 처짐, 채터, 공구 수명, 공차 또는 가공 성공 확률을 계산한 것처럼 표시해서는 안 된다.

## 공구 치수

단위 mm. L3는 참고 치수이며 `reach_mm`가 아니다. 모든 제품은 특정 SKU의 명목 치수이며 재연마·실측 보정·장착 상태를 포함하지 않는다.

| 제조사 / 제품 번호 | 지름 | 절삭부 길이 | 샹크 | 전체 길이 | 참고 L3 | 출처 위치 |
|---|---:|---:|---:|---:|---:|---|
| DATRON 0068010E | 1 | 4 | 3 | 38 | 미기재 | SKU Additional Information |
| DATRON 0068020E | 2 | 8 | 3 | 40 | 미기재 | SKU Additional Information |
| DATRON 0068030E | 3 | 10 | 3 | 40 | 미기재 | SKU Additional Information |
| DATRON 0068434E | 4 | 10 | 6 | 50 | 미기재 | SKU Additional Information |
| DATRON 0068435E | 5 | 12 | 6 | 50 | 미기재 | SKU Additional Information |
| DATRON 0068460E | 6 | 14 | 6 | 50 | 미기재 | SKU Additional Information |
| DATRON 0068470E | 10 | 20 | 10 | 60 | 미기재 | SKU Additional Information |
| DATRON 0068460L | 6 | 20 | 6 | 60 | 미기재 | 공식 제품군 Available Options 해당 SKU 행 |
| DATRON 0068434F | 4 | 20 | 6 | 58 | 미기재 | 공식 제품군 Available Options 해당 SKU 행 |
| DATRON 0068470L | 10 | 40 | 10 | 100 | 미기재 | 공식 제품군 Available Options 해당 SKU 행 |
| DATRON 0068493L | 3 | 8 | 6 | 50 | 21 | 공식 제품군 행; 목 지름 D3=2.7 |
| DATRON 0078010K | 1 | 2 | 3 | 38 | 미기재 | 강 가공용 제품군 Available Options 해당 SKU 행 |
| DATRON 0078018S | 1.8 | 1.5 | 3 | 38 | 미기재 | 강 가공용 제품군 Available Options 해당 SKU 행 |
| DATRON 0078030K | 3 | 7 | 3 | 38 | 미기재 | SKU Additional Information |
| Harvey 677722 | 1 | 3 | 3 | 63 | 5 | TOOL DIMENSIONS |
| Harvey 677745 | 2 | 6 | 3 | 63 | 10 | TOOL DIMENSIONS |
| Harvey 677761 | 4 | 12 | 4 | 63 | 20 | TOOL DIMENSIONS |
| Harvey 677666 | 6 | 18 | 6 | 100 | 48 | TOOL DIMENSIONS |
| Harvey 677670 | 8 | 24 | 8 | 100 | 64 | TOOL DIMENSIONS |

DATRON 단날은 제조사에서 알루미늄·황동·플라스틱을 대상으로 설명하며 강에는 권장하지 않는다. 0078 계열의 세 제품은 강 가공용 2날 X.CEED 코팅이다. 해당 소재군 설명을 공작물의 정확한 재료나 개별 강종 적합 승인으로 자동 설정하지 않는다. Harvey 다섯 제품은 무코팅 4날 Square 형상이다. 사이트 소재 아이콘의 전체 텍스트가 나열된 것을 모든 소재의 적합 판정으로 사용하지 않았다.

- [DATRON 단날 공식 표](https://shop.datron.com/product/single-flute-end-mills/0068460E/): D1, D2, D3, L1, L2, L3, 날 수의 열 순서를 확인했다.
- [DATRON 강 가공용 2날 공식 표](https://shop.datron.com/product/steel-machining-double-flute-end-mill/0078030K/): D1, D2, L1, L2, 날 수, 코팅 열 순서를 확인했다.
- [DATRON 공식 치수 카탈로그](https://www.datron.de/fileadmin/dokumente/broschueren/tools/english/DATRON_Tools_withoutPrices_Cat_EN.pdf): PDF 10·11·17쪽의 도해와 표를 렌더해 확인했다. L2가 절삭부 길이임을 대조했다. 0068493L은 toric cut 제품이므로 끝날 곡면을 현재 단순 원통 비교에서 계산하지 않는 한계를 명시했다. PDF 생성 메타데이터는 2026-03-12이며 발행일로 단정하지 않는다.
- [Harvey Metric 제품군](https://www.harveytool.com/products/miniature-end-mills-square-long-reach-standard-flute-metric): 정확한 SKU의 TOOL DIMENSIONS를 각각 열어 확인했다. 개별 링크와 해당 값 위치는 JSON 출처 카드에 있다.

## 장비와 소재

- **Haas VF-2 / VF-2SS / VF-3**: 각 모델의 공식 METRIC Travels 및 Max Speed 표를 확인했다. 이동량은 각각 762×406×508 / 762×406×508 / 1016×508×635 mm, 최대 주축 속도는 8100 / 12000 / 8100 rpm이다. 이는 표준 구성 사양이며 바이스·소재·공구/홀더가 설치된 실제 가공 공간이 아니다. CNC 배치 적합 판정으로 자동 사용하지 않는다. [VF-2](https://www.haascnc.com/machines/vertical-mills/vf-series/models/small/vf-2.html), [VF-2SS](https://www.haascnc.com/machines/vertical-mills/vf-series/models/small/vf-2ss.html), [VF-3](https://www.haascnc.com/machines/vertical-mills/vf-series/models/medium/vf-3.html).
- **Hydro 6061 T6/T6511 및 T4/T4511 압출재**: 공식 2019/01 개정 PDF 2쪽 표와 주석을 원페이지로 대조했다. 최소 인장/항복 강도와 25°C 대표 열전도율을 구별해 저장했다. 판재·단조재·적층재로 전용하지 않는다. [Hydro 원문](https://www.hydro.com/globalassets/01-products--services/extruded-profiles/americas/ena-resources/alloy-data-sheets/hydro_2019_data_sheet_6061.pdf).
- **Outokumpu Supra 316L/4404 및 316Ti/4571**: 공식 PDF 8쪽 Table 7을 원페이지로 대조했다. 밀도, 20°C 탄성률·열전도율, 20–100°C 열팽창계수만 수록했다. 마지막 값의 원문 단위 `10^-6/K`를 `1/K`로 변환한 사실을 각 항목에 기록했다. 공급자 데이터시트가 EN 10088-1을 인용한 것이며 EN 전문 자체를 검증한 자료로 표시하지 않는다. [공식 데이터시트](https://www.outokumpu.com/-/media/files/products/supra/outokumpu-supra-range-datasheet.pdf?hash=8720C1FF12682806AF1BBC27E00209E0&modified=20251117111951&revision=7a909396-d1f3-4d36-9c1c-99606be41fd2).
- **Ensinger TECAPEEK natural / TECAFORM AH natural**: 제조사 `/en/` SI 표에서 밀도, 인장 탄성률, 인장 강도를 수록했다. 시험방법 DIN EN ISO 527-2와 1 / 50 mm/min 조건을 보존했다. `/en-us/`의 ASTM·psi 표와 값·시험조건이 달라 단순 환산해서 섞지 않았다. [TECAPEEK](https://www.ensingerplastics.com/en/shapes/peek-tecapeek-natural), [TECAFORM AH](https://www.ensingerplastics.com/en/shapes/acetal-tecaform-ah-natural).
- **Sandvik 내부 코너 정삭**: 정삭 시 공구 지름/부품 코너 반경 1.5 이하 권고를 참고 전용으로 저장했다. 현재 기하 비교의 필요조건 `D ≤ 2R`를 이 값으로 바꾸지 않는다. [Finishing 절](https://www.sandvik.coromant.com/en-us/knowledge/milling/milling-inside-corners).

## 충돌·보류·제외한 자료

1. **DATRON 0068080E 제외**: 공식 개별 SKU의 Additional Information은 D1 `.8 mm`, 공식 제품군 Available Options와 카탈로그 PDF는 `8 mm`로 서로 다르다. 원문 다운로드 후 독립 전사값과 자동 대조하면서 실패를 확인했다. 카탈로그로 상세 웹 표의 오기 가능성을 좁혔지만 혼란스러운 SKU를 이번 자동 적용 DB에는 넣지 않았다.
2. **카탈로그 길이로 장착 도달 길이 추정 금지**: Harvey Overall Reach 및 DATRON L3는 별도 참고 필드다. 전체 길이에서 임의의 고정 길이를 빼거나, 그대로 `reach_mm`에 입력하지 않았다.
3. **드릴 허용 L/D 없음**: 엔드밀 제품 길이비, 일반적인 3D/5D/6D 수치를 드릴 가공의 보편적 성공 경계로 가져오지 않았다.
4. **소재 물성의 지역/시험방법 차이**: Ensinger 미국 페이지에는 SI 페이지와 다른 시험값과 일부 의심스러운 단위 표기가 존재한다. 이번 값은 서로 일관된 SI 표로 제한했다. VICTREX 450G 수지 물성을 완성 stock shape의 물성으로 대체하지 않았다.
5. **웹 접근 실패**: 일부 SKU와 Haas 사이트의 직접 HTTP 다운로드는 403이었다. DATRON은 접근 가능한 공식 제품군의 해당 SKU 행을 확인한 경우에만 수록했다. Haas는 웹 도구로 공식 모델표를 확인했다. 실패 응답을 확인 성공으로 기록하지 않았다. VF-1·DATRON neo는 이번 장비 수록에서 제외했다.
6. **재료와 공구의 자동 적합 결론 없음**: 소재명 또는 제조사 설명 하나로 공구·속도·이송·절입·냉각의 완전한 조합을 만들지 않았다. 사용자가 갖고 있지 않은 공구를 보유한 것으로 설정하지 않는다.

## 검증 기록과 재확인

`study/conditions-2026-09-28/cnc/`에 다운로드 원문, 파일 SHA manifest, 최소한의 전사/대조 스크립트, 세 PDF의 관련 표·도해 렌더 및 `curation-validation.json`을 보존했다. 원문 PDF/HTML 전체를 이번 DB 파일에 복사하거나 배포하지 않는다. 숫자·조건·출처 위치만 큐레이션했다.

`build_database.py`는 독립 전사한 19개 공구의 치수와 실제 SKU/제품군 행을 대조하고, SI 고분자 표 두 개, 출처 ID 연결, 자동 적용 허용 항목, 양수/mm, `reach_mm`와 드릴 깊이비의 미입력을 검사했다. 실패한 D1 충돌은 위 제외 기록에 남겼다. 코드 통합·UI·CAD 계산 회귀검사는 상위 통합 작업의 실제 결과로 별도 기록한다. 여기의 출처 확인을 해당 계산 검사나 실물 검증으로 바꾸어 설명하지 않는다.
