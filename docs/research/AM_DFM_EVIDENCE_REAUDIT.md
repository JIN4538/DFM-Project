# 적층제조 제조성 검토의 근거 재감사

감사 기준판의 공정 공통 기하 측정은 유지할 가치가 있다. 그러나 하향면, CAD 원통면, 밀폐 껍질, 법선 관통거리만으로 액조 광경화와 고분자·금속 분말 베드 융해의 주요 제조 문제를 충분히 검토했다고 할 수 없다. 비FDM 공정에는 **층 단면의 크기·경계·변화·연결 관계를 실제로 측정하는 기능**을 보강하고, 그 측정값과 공정 물리의 인과관계를 분리해야 한다.

이 감사의 기준 코드는 `7c5444a81b277e7b8af9bf9cba2408eab9024edc`의 `amdfm/evidence.py`, `profiles.py`, `analysis.py`, `detail_worker.py`이며, 근거 확인 기준일은 2026-09-14이다. 아래 권고는 이 기준의 결함·확장 요구를 기록한다. 최종 구현·무작위 형상 시험의 통과 여부는 별도의 실행 기록으로 확인해야 하며, 이 문서 자체를 실행 검증 완료로 사용하지 않는다. 장비·재료·슬라이서는 미확정이고 부품별 실측 정답과 출력 시편도 제공되지 않았다.

## 1. 근거의 판정 기준

검토 항목이 문헌에 등장한다는 사실만으로 구현된 알고리즘이나 기본 숫자까지 검증되는 것은 아니다. 근거는 다음 네 층으로 구분한다.

| 근거 층 | 허용되는 결론 | 허용되지 않는 확대 |
|---|---|---|
| 수학적 정의·독립 기준형상 | 이 좌표계에서 길이·면적·체적·연결 성분을 정해진 오차로 계산했다 | 출력 성공, 물성·공차 만족 |
| 표준의 공개 범위 | 특정 공정·설계·검증 항목을 구분할 필요가 있다 | 미확보 전문의 조항 준수, 보편 최소 벽·각도 |
| 제조사 장비·재료 가이드 | 명시된 장비와 재료 조건의 설계 참고값 | 모든 SLA/SLS/LPBF의 공통 한계 |
| 원논문의 실험·보정된 물리 모델 | 해당 시편·공정 범위에서 측정된 경향과 모델 성능 | 새 부품·다른 장비에서 같은 오차, 무조건적 성공 확률 |

ISO/ASTM 52910은 AM 설계의 공통 지침, 52911-1과 52911-2는 각각 금속·고분자 레이저 PBF의 공정별 설계, 52902는 기하 능력 평가용 시험물을 다룬다. 공개 Scope를 확인했지만 유료 전문 전체를 새로 확보한 상태는 아니다. 따라서 이러한 표준은 검토 구성과 검증 절차의 근거이고, 45°·0.4 mm와 같은 기본 수치의 출처가 아니다.[^1][^2][^3][^4]

## 2. 기존 구현과 인용의 비판적 대조

| 기준 구현 | 감사 판단 | 필요한 수정·보완 |
|---|---|---|
| `analysis.py` 하향면에 전 공정 공통 `JIANG2018` | FDM 연구를 VPP·LPBF의 직접 근거처럼 노출한다. 하향 법선 계산과 공정 지지 성공은 다른 주장이다 | 공정별 근거 분기. VPP는 박리·신생 성분, LPBF는 열전달·기계적 고정의 출처를 연결 |
| `analysis.py` 벽 항목에 전 공정 공통 `KUIPERS2020`, `PRUSA_ARACHNE` | 두 출처는 FDM 가변 선폭의 필요성을 지지한다. 비FDM 벽 한계의 근거로는 부적절하다 | MEX에서만 선폭 근거 노출. VPP·SLS는 해당 장비 가이드와 사용자가 입력한 검증 조건을 표시 |
| 기본 오버행 45° | 명시된 탐색 설정으로는 사용 가능하다 | 제조 한계·표준 값·합격 기준으로 표시하지 않는다. 수평면 기준 각도 정의를 유지 |
| CAD 원통축 기울기 45° 분류 | 구멍 후보를 찾아보는 표시 정책으로는 가능하다 | 실제 지지 필요 각도, 홀 성공률, 관통홀·배출홀 판정으로 승격하지 않는다 |
| 고분자 PBF 오버행 N/A | FDM 무지지 규칙을 분말 지지 공정에 적용하지 않는 결정은 타당하다 | 모든 방향이 동등하다는 뜻은 아니다. 단면·두께·열이력·청소 검토를 보강 |
| CAD 유효 솔리드의 추가 껍질 수 | 내부 밀폐 경계 탐지의 분명한 기하 의미가 있다 | 열린 컵·굴곡 채널·목 막힘·수지 흡착 컵을 배제할 수 없다 |
| 표본 법선 관통거리 | 위치·법선·교차점과 표본 범위를 보이면 관측값으로 유용하다 | 전역 최소 벽두께나 미세 특징의 완전 탐지로 부르지 않는다 |
| MEX 전용 층간 정밀 검토 | 선폭 opening과 경사 허용 버퍼를 다른 공정에 복제하지 않은 것은 타당하다 | 순수 단면 기하를 공정 공통 기능으로 분리해 비FDM에도 제공 |
| 비지배 방향 비교 | 특정 기하 목적의 절충 대안으로 타당하다 | 후보 집합의 대안을 연속 공간의 제조 최적 방향이라고 부르지 않는다 |
| `UNASSESSED`의 비FDM 항목 | 미구현 범위를 공개하는 계약은 유지해야 한다 | 단면량을 구현한 뒤에도 실제 박리력·열변형·제거 성공은 별도로 남긴다 |

기준판이 사용한 근거의 대부분은 기능의 **필요성**을 뒷받침한다. 이것을 숫자 알고리즘의 정확도 검증으로 오해하지 않도록 결과마다 `측정 정의`, `선택한 조건`, `공정에서의 용도`, `계산하지 않은 것`을 나누는 것이 핵심 수정이다.

## 3. 액조 광경화: 단면을 측정하되 힘으로 바꾸지 않는다

### 3.1 박리력과 단면 형상

Pan 등(2017)은 자체 bottom-up 투영 광경화 장비에 로드셀을 설치해 분리력을 측정했다. PDMS 코팅, LS600M·G+ 수지, 인상 속도와 단면 형상을 바꾸는 실험이다. 인쇄 면적만이 아니라 경계 길이, 내부 공극, 수지 점도, 상대 분리 속도, 산소 저해층과 필름 변형이 함께 작용했다. 원통·강체 경계·일정 점도 가정의 식(6)은 반지름의 4제곱과 간극의 역 3제곱을 포함한다. 이를 임의 부품의 면적 하나로 치환해 일반 박리력을 산출할 수 없다.[^5]

Formlabs의 공식 방향 가이드는 큰 평면의 기울임, 최소점과 지지, 분기 결합부, 컵 형태를 따로 다룬다. 같은 문서 안에 Form 2 와이퍼와 Form 3 계열 LFS의 기구 차이가 함께 제시된다. VPP라는 이름 아래 모든 장비에 동일한 탱크 분리 동작이 있다고 가정해서는 안 된다.[^6]

**구현 권고:** 모델의 최종 빌드 좌표계에서 각 관측 단면의 재료 면적 `A`, 전체 경계 길이 `P`, `A/P`, 재료 성분 수, 내부 루프 수·면적을 측정한다. `P`는 외곽과 내측 경계를 포함하는지 명시하고, 0 또는 미확정 분모에서 비율을 생성하지 않는다. 결과 명칭은 “박리 검토에 참고할 단면 기하”로 한다. `A/P`의 단위는 mm이며 힘이나 확률이 아니다.

면적 합의 전역 평균만으로 작은 섬과 좁은 연결부를 숨기지 않는다. 각각의 최대값과 발생 높이, 그래프, 해당 단면의 형상을 제공한다. 상자·환형 단면·여러 성분 등에서 면적과 둘레를 독립 공식에 대조한다. 변형 가능한 필름의 박리, top-down 자유 표면 방식, 연속 인상 방식은 이 기하량의 공정 해석이 다르므로 적용 설명에서 구분한다.

### 3.2 흡착 컵·배출·신생 성분은 별개의 문제다

**단면에 구멍이 있다는 사실은 흡착 컵의 충분조건이 아니다.** 양 끝이 열린 관과 막힌 컵은 중간 높이에서 같은 환형 단면을 가질 수 있다. 반대로 최종 형상에 배출구가 있더라도 그 구멍이 형성되기 전의 인쇄 단계에서 컵 효과가 생길 수 있다. 따라서 완성 CAD의 껍질 수나 2D 내부 루프 수만으로 시간에 따른 압력 평형·배출 가능성을 확정하면 안 된다. 이는 형상 반례로 확인할 수 있는 구분이다.

인접 단면에 직접 겹치지 않는 새로운 재료 성분은 검토 위치를 찾는 데 유용하다. 그러나 일정 높이 간격으로 뽑은 단면 사이에서 연결이 생겼다 사라질 수 있고, 실제 서포트가 모델 외부에 생성될 수도 있다. “관측한 단면 사이에 새 성분이 나타남”과 “해당 인쇄층이 공중에서 실패함”을 구분한다. 실제 층 간격으로 모든 층을 처리한 경우에만 “층”이라 부르고, 부분 높이를 표본 추출한 경우 “표본 단면”이라고 부른다.

### 3.3 Form 4 수치의 올바른 사용

공식 Form 4 가이드는 Grey Resin V5·50 µm 조건의 CAD 설계값을 제시한다. 벽 0.2 mm, 일반 홀 0.5 mm, 배출 홀 0.75 mm는 목적이 다른 값이다. 경사 10° 예에는 35×10×3 mm 시편이 명시돼 있다. 같은 페이지의 치수 공차 시험은 100 µm와 별도 후경화 조건이므로 앞의 50 µm 자료와 합쳐 한 프로필의 보증값으로 만들면 안 된다.[^7]

하드웨어 미확정 상태에서는 이 값들을 자동 적용하지 않는다. 장비·수지·층 높이·형상 종류·기능 요구와 함께 선택하는 참고 조건으로만 사용할 수 있다. 일반 원통면 지름이 검출됐다는 이유로 해당 면이 배출홀이라는 의미를 부여하지 않는다.

## 4. 고분자 PBF: 무지지성과 제조성은 동의어가 아니다

### 4.1 SLS의 설계 조건

Fuse Series 공식 가이드는 Nylon 12를 기준으로 수직벽 0.6 mm와 수평벽 0.3 mm, 공동 배출구는 두 개 이상·각 3.5 mm 이상을 제시한다. 적용 대상은 Fuse 장비와 재료이며 다른 재료의 별도 지침을 확인하도록 한다. 분말이 형상을 지지하더라도 청소 중 얇은 특징의 손상, 열 축적과 방향의 영향이 남는다.[^8]

현재 공개 웹 문서의 “Maintaining Uniform Thickness” 절은 제목과 달리 배출홀 문단을 중복해서 담고 있다. 이 절의 제목만 보고 균일 벽두께 규칙의 상세 내용·수치를 복원하지 않는다. 별도 `Reducing Stress Concentrations`, 방향·패킹 절과 재료별 설명에서 실제로 확인한 범위만 사용한다.[^8]

**구현 권고:** SLS에서는 동일한 단면 면적·둘레·변화량을 측정하되 “지지 필요 면적”으로 표시하지 않는다. 얇은 벽 표본과 국소 특징 위치, CAD 원통면 치수, 밀폐 공동을 함께 제시한다. 분말 배출에는 입구 크기뿐 아니라 채널의 연결성·좁은 목·길이·굴곡·공구 접근성이라는 추가 문제가 있으므로 원통면 목록만으로 배출 검토 완료를 표시하지 않는다.

### 4.2 열수축·뒤틀림은 물성·열이력의 문제다

Li 등(2020)은 PA12의 열전달·열기계 거동·재결정화를 결합하고 실제 시험으로 수축과 휨을 대조했다. EP-P3850, Farsoon FS3300PA, 50×10×1 mm 시편에 출력 조건을 달리한 실험이며 층 높이는 0.10–0.19 mm 범위였다. 동일 형상이라도 스캔·냉각 조건을 바꾸면 결과가 달라진다. “layer-layer angle”은 인접 층의 스캔 각도 차이이며 모델의 빌드 기울기와 다른 변수다.[^9]

따라서 전역 종횡비나 단면 급변 비율만으로 휨 mm, 수축 %, 강도 저하율을 출력하는 것은 근거가 부족하다. 해당 값들은 설계 위치를 찾기 위한 보조 기하량일 수 있으며, 수축 예측에는 온도 의존 물성과 레이저·분말층·예열·냉각·경계조건이 필요하다. 무작위 외부 형상에서 단면 계산이 성공했다고 이 물리 검증이 대체되지는 않는다.

## 5. 금속 LPBF: 단면 변화와 열전달을 함께 해석해야 한다

### 5.1 면적이 작을수록 온도가 낮다는 단순 규칙은 틀릴 수 있다

Mohr 등은 316L 이중벽 압력용기의 실제 열이력과 거시 FEM을 대조했다. SLM280HL, 275 W, 700 mm/s, 해치 0.12 mm, 층 0.05 mm, 베이스 100°C 조건이다. 단면 감소는 입열을 줄이는 동시에 층간 시간도 줄였다. 45° 영역에서는 열전달 조건도 바뀌어 단면이 줄어드는 동안 온도가 계속 상승했다. 논문 §3.1.1은 이러한 경쟁 효과를 실제 형상 구간과 연결한다.[^10]

**구현 권고:** LPBF에 `A(z)`, 단면 면적 증가·감소, 대칭차 면적, 변화 발생 높이를 제공한다. 하향면 후보와 해당 위치를 연결하면 공정 담당자가 열 축적 검토 구간을 찾는 데 도움이 된다. 그러나 이 지표들에 임의 가중치를 곱해 열위험 점수나 예상 휨을 만들지 않는다. 면적 증가와 감소 중 어느 쪽을 무조건 나쁜 것으로 취급하는 것도 피한다.

층 단면의 `A/P`는 LPBF에서도 정의 가능한 기하량이지만, VPP 논문의 분리력 경향을 LPBF 열전달식으로 재사용할 수 없다. 레이저 경로 길이와 단면 면적도 동일하지 않다. 해치 간격만으로 구한 경로 길이는 경계 스캔, 점프, 다중 레이저, 미니멈 층시간 등 실제 작업을 포함하지 않으므로 현재 장비 미정 상태에서는 시간·에너지 계산의 정답으로 사용하지 않는다.

### 5.2 서포트의 목적과 수치 모델의 한계

Cheng 등(2019)은 잔류응력 억제를 위한 격자 서포트 최적화를 다루며, 기계적 고정과 열 방출의 역할을 구분한다. 공개 초록·서론은 형상 기반 서포트량 최소화만으로 충분하지 않음을 뒷받침한다. 다만 이번에 열람한 범위는 공개 미리보기이므로 상세 실험 조건이나 모델의 새로운 재현 성능을 주장하지 않는다.[^11]

Dimopoulos 등(2023)의 실험은 EOS M290·Ti64 Grade 5를 사용하지만 수치 모델 §3.2는 Grade 4 티타늄 성질과 접촉부 1550°C 고정 온도, 주변 분말 제외를 사용한다. 이 단순화와 재료 차이 때문에 표의 최적 서포트 치수·응력을 범용 LPBF 프로필에 복사할 수 없다. 이 연구는 서포트의 열·기계적 역할과 제거성 사이의 절충을 설명하는 정성 근거로 사용한다.[^12]

EOS 공식 설명도 공정 제어에 따라 45°보다 낮은 오버행을 구현한 사례를 제시한다. 제조사의 특수 공정 사례는 보편적인 허용각을 새로 정하는 근거가 아니라, 고정 각도 하나를 공정 불가능 판정에 쓰지 말아야 한다는 반례다.[^13]

### 5.3 분말 제거는 구멍 유무보다 복잡하다

Hunter 등(2020)은 Ti-6Al-4V의 L-PBF와 EBSM 도전 형상을 만들고 초음파·진공 비등·XCT·질량 측정을 비교했다. 헬릭스와 U자 채널에서 직경·굴곡·도구 접촉 가능성에 따라 제거 양상이 달랐다. 같은 방법도 느슨한 L-PBF 분말과 소결된 EBSM 분말에서 다르게 작용했다. 따라서 채널이 외부에 연결된다는 기하 조건은 제거 성공을 보장하지 않는다.[^14]

CAD의 밀폐 공동 탐지는 계속 제공한다. 열린 채널은 “연결성 미평가” 또는 “기하 연결 확인, 실제 제거 미검증”으로 세분하는 것이 바람직하다. 양 끝이 열렸다는 이유만으로 위험 없음, 단일 직경보다 크다는 이유만으로 분말이 완전히 빠짐을 반환하면 안 된다. ASTM F3530의 공개 Scope는 분말 제거 등 후처리 설계 고려의 필요성을 지지하지만 미확보 전문의 수치 한계를 대신하지 않는다.[^15]

## 6. 새로 구현할 수 있는 공정 공통 측정 계약

아래는 제조 성공을 판정하는 경험식이 아니라 계산 대상의 정의다. 수식의 신뢰성은 독립 단면 공식과 반례로 검증할 수 있다.

| 측정 | 정의와 단위 | 공정에서의 사용 | 검사해야 할 반례 |
|---|---|---|---|
| 단면 재료 면적 | 실제 재료 다각형 합집합의 면적 `A_i`, mm². 내측 루프 면적은 차감 | VPP 분리 검토, PBF 열이력 검토의 위치 안내, 모든 공정의 재료 분포 | 환형 단면, 내측 공동, 여러 성분, 중첩 셸 |
| 단면 경계 길이 | 재료 경계 전체 길이 `P_i`, mm. 외곽·내측 포함 여부 고정 | 작은 특징과 분리 기하 비교 | 구멍 있는 판과 같은 면적의 고체 판 |
| 면적/경계 비 | `A_i/P_i`, mm; `P_i=0` 또는 미확정이면 null | VPP 형상 비교 보조량 | 같은 면적·다른 둘레, 여러 구멍, 축척 변화 |
| 면적 변화 | `A_i-A_(i-1)`, mm²; 별도로 절댓값 가능 | 급격한 재료 변화 위치 찾기 | 면적이 같은데 단면 위치가 이동하는 형상 |
| 단면 대칭차 | `area(S_i △ S_(i-1))`, mm² | 면적의 순변화가 0인 이동·분기까지 탐지 | 같은 면적의 좌우 이동, 회전 직사각형 |
| 새 재료 영역 | `area(S_i \ S_(i-1))`, mm²; 버퍼 없이 직접 중첩 정의 | VPP/LPBF의 추가 검토 위치 | 경사진 자립면도 차집합이 생김: 이를 곧바로 지지량으로 부르지 않음 |
| 신생 재료 성분 | 관측 단면의 연결 성분 중 직전 단면과 양의 면적으로 겹치지 않는 성분 | 최소점·고립 특징 후보 | 대각 연결, 중간 높이에만 존재하는 연결, 별도 서포트 |
| 내부 루프 | 단면의 내측 경계 개수·면적 | 배출·공동 관찰 시작점 | 관통 튜브와 밀폐 컵의 동일 환형 단면 |
| 단면 체적 적분 | 높이 간격과 단면 면적의 적분 근사, mm³ | B-rep·메시 체적과 독립 일관성 대조 | 얇은 수평 특징 누락, 끝층 폭, 계단형 단면 |

표본 단면의 최대값은 “관측 최대”이지 연속 높이에서의 전역 최대가 아니다. 샘플 수·높이·간격·해석 실패·미측정 구간을 저장해야 한다. 층 높이 또는 표본 간격을 몰래 늘려 완료율을 높이면 안 된다. 첫 단면은 비교 전 단면이 없으므로 면적 변화·신생 성분의 정상 비교 대상으로 취급하지 않는 등 경계 정책을 정의한다.

단면의 방향과 원점은 빠른 검토·3D·내보내기와 같은 최종 배치 행렬을 사용한다. 형상의 절대 크기가 달라도 빌드 공간을 제한하지 않는 실행은 가능하다. 이때 `build_volume_mm=None`은 기하 계산의 크기 제한을 사용하지 않는다는 뜻이며, 실제 장비 수용성을 확인했다는 뜻이 아니다. 필요한 외곽 공간은 계속 수치로 보여준다.

### 구현 후 수용 기준

1. 상자·환형 관·경사 프리즘·단차·열린 컵·밀폐 공동·분기에서 독립 길이·면적·체적 식에 대조한다. 삼각형 분할과 면 순서를 바꿔도 답이 보존돼야 한다.
2. 같은 형상과 빌드축을 함께 회전·평행이동했을 때 관측값을 비교한다. 빌드 평면의 추가 yaw도 내보내기와 같아야 한다.
3. 크기를 `s`배로 바꾸면 길이는 `s`, 면적은 `s²`, 체적은 `s³`, `A/P`는 `s`배가 된다. 단면 높이도 같은 비율로 바꿔 비교한다.
4. 폐곡면 오류·중복·다중 셸·자기교차·예산 초과에서 값 0이나 합격으로 대체하지 않는다. 일부 단면만 유효하면 그 일부의 결과와 실패 이유를 보존한다.
5. 같은 형상을 네 공정으로 실행했을 때 공통 기하량은 일치해야 한다. 공정별로 달라지는 것은 정당한 적용 범위·해석·설정이다.
6. 무작위 외부 형상은 원본 SHA·단위·선택 솔리드·방향·테셀레이션·샘플 정책과 함께 실행한다. 정답 없는 형상의 처리 성공률을 제조성 판정 정확도로 보고하지 않는다.

## 7. 사용자 편의성과 과잉 판정을 함께 줄이는 변경

공정 선택 직후 해당 공정에서 측정하는 것과 미평가 물리를 한 문단으로 제시한다. 결과마다 같은 긴 주의문을 반복하기보다 항목의 측정명과 단위에서 의미를 명확히 한다. 예를 들어 “최소 두께” 대신 “관측 최소 법선 거리”, “SLA 위험도” 대신 “관측 최대 단면적”을 사용한다.

선폭은 MEX 설정에만 노출한다. VPP·PBF에서 단면 표본 간격을 입력받는 경우 실제 프린터 층 높이와 구분한다. 장비를 모를 때도 실행할 수 있게 하되, 아무 값이나 넣어야 버튼이 활성화되는 구조는 피한다. 벽·홀 기준을 지정하지 않으면 측정값은 제공하고 합격·불합격만 생략한다.

결과 위치로 바로 이동할 수 있어야 한다. 단면 그래프의 최대값·급변 높이, CAD 면 번호, 두께 표본 좌표, 검토 방향을 한 형상에서 확인하도록 연결한다. 비FDM에서도 지표를 읽은 다음 “이 방향으로 다시 검토”와 “해당 높이의 단면 보기”가 자연스럽게 이어져야 한다.

근거 표시는 긴 참고문헌 목록보다 **이 주장에 이 출처를 쓴 이유**가 우선이다. 조건부 임계값에는 제조사·장비·재료·층 높이·시편 형상을 함께 둔다. 숫자가 없는 정성 근거는 정성 근거라고 표시한다. 개선 전후 비교에서는 동일한 코드·단위·솔리드·방향·조건을 확인한 뒤 측정 변화만 보여준다.

## 8. 지금 구현해서는 안 되는 주장

| 주장 | 부족한 필수 근거 |
|---|---|
| 면적만으로 VPP 박리력 N·서포트 개수 산출 | 수지 점도·필름 탄성/표면·분리 운동·접착/경화·실제 검증 |
| 내부 단면 루프 = 흡착 컵 확정 | 각 인쇄 단계의 3D 개방 경로와 압력 평형·탱크 접촉 조건 |
| 고분자 PBF 하향면 없음 = 제조 위험 없음 | 수축·냉각·패킹·물성·분말 제거·후처리 |
| LPBF 단면 변화율 = 열변형·잔류응력 | 열원·경로·층간 시간·열물성·지지·경계조건·실측 보정 |
| 원통면 직경이 크면 분말/수지 배출 합격 | 입구의 용도, 전체 채널 연결·목·길이·곡률, 제거 공정 |
| 800개 법선 표본에서 위반 없음 = 모든 벽 합격 | 전역/국소 두께 정의와 탐지 범위·오차 보증 |
| 새 ML 논문의 성능을 현재 앱의 정확도로 사용 | 모델 재현·학습 영역·정답 데이터·독립 검증·라이선스 적합성 |

2026년 Demir 등의 LPBF 열 모델 일반화 연구도 단순화한 FEM 학습 데이터, 향후 실제 열 측정 검증, 현재 오버행 미포함이라는 한계를 명시한다. 최신 논문을 인용하는 것만으로 현재 앱의 물리 예측이 검증되지는 않는다. 해당 연구는 장기 확장 방향의 참고이며 즉시 추가할 성공확률 기능의 근거가 아니다.[^16]

MEX의 경우에도 Kuipers 등의 가변 선폭 연구와 PrusaSlicer 문서는 고정 선폭만으로 형상 생략을 확정할 수 없음을 보여준다. 기존 선폭 기반 단면 지표와 실제 슬라이서 경로를 대조하는 분리는 유지한다. 최신 웹 설명에서 구현 동작을 새로 추정하기보다 실제 사용하는 슬라이서 버전과 출력 경로를 기록한다.[^17][^18]

## 9. 입력 형식과 곡면의 의미

STEP, STL, 3MF는 같은 종류의 설계 정보를 전달하지 않는다. STEP 입력은 OCCT의 단위 변환·형상 전송에 따라 해석하며, B-rep 원통면의 지름·축을 읽을 수 있다. 이 소프트웨어는 PMI·치수 공차·원 CAD의 피처 이력을 해석하지 않는다. 솔리드 없이 곡면만 있는 STEP도 치수·면적 관측에 사용할 수 있지만, 곡면 방향만으로 재료 안쪽이나 구멍을 결정하지 않는다. 곡면을 자동 봉합해 원 설계에 없던 재료를 만들어서는 안 된다.[^19]

3MF Core 원문은 선언 단위, 루트 빌드 목록, 상대 객체 변환, 성분 조립의 의미를 명시한다. 이번에 확인한 공식 저장소 원문은 Published v1.4.0이며, 모든 3MF 생태계의 최신판이라는 뜻은 아니다. Production v1.2는 패키지 안의 외부 모델 참조를 다룬다. 루트 모델의 build만 유효하고, 다른 파일을 참조하는 component는 루트에서만 허용된다. 비루트 모델의 중첩 외부 파일 참조는 오류 조건이다. 이러한 문서는 필요한 기하 입력의 근거이며, 선택적으로 지원하는 입력기가 전체 확장·재료·생산 지시·규격 적합을 모두 구현했다는 증거가 아니다.[^20][^21]

STL의 실제 자료 구조는 삼각형 정점과 법선으로 구성된 표면 근사다. 의회도서관의 공식 형식 해설을 이 구조의 출처로 사용하며 OCCT STEP 문서를 STL 입력 처리의 근거로 붙이지 않는다. 해당 해설도 원 1988 규격 전문을 확보하지 못했다고 명시하므로 이를 원 규격 전문 열람으로 기록하지 않는다. STL과 3MF의 삼각형 메시에서 설계된 홀의 지름·축을 자동 복원했다고 주장하지 않는다.[^22]

## 10. 감사 뒤 반영한 내용과 검증 범위

이 절은 2026-09-14 작업 중의 반영 상태이며 앞 절의 기준판 감사를 지우지 않는다. `amdfm/evidence.py`는 공정별 `sources_for`와 단면 해석용 `section_guidance`를 제공한다. `analysis.py`의 하향면·벽·CAD 홀·공동·단면 항목은 해당 공정의 근거를 선택한다. FDM 선폭·브리지 논문을 비FDM 결과의 근거로 연결하지 않으며, 기본 각도와 사용자 입력 벽·홀 수치는 여전히 탐색 조건이다.

단면 검토는 실행 전 `unknown`으로 시작한다. 추가된 공통 단면 계산에서 면적, 외·내곽을 포함한 경계 길이, A/P, 성분 수, 내부 루프 수, 이전 표본과의 면적 증감·대칭차·차집합을 관측한다. 관측 높이 사이에서 직접 겹침이 없는 **신생 성분을 개별 추적하거나 지지 실패를 판정하는 기능은 구현 완료로 기술하지 않는다.** 표본 수와 실제 적층 높이도 구분한다. 부분 계산을 전체 높이의 최소·최대 보증으로 사용하지 않는다.

곡면 STEP은 B-rep 면적과 메시 외곽 치수를 제공하고 재료 체적·하향면 면적·벽·내측 원통면 수·밀폐 공동·재료 단면은 미확정으로 유지한다. 고분자 PBF의 하향면 항목은 FDM 무지지 규칙의 적용 제외를 나타내는 `not_applicable`이며 곡면 입력에서도 그 상태를 우선한다. 나머지 공정의 곡면 하향면 상태는 `unknown`이다. 어느 경우에도 미측정 면적을 0으로 바꾸지 않는다. 원통면의 지름과 축을 관측하더라도 재료 안쪽 역할은 `unknown`이다. 여러 CAD 솔리드나 메시 객체의 합집합이 미확정인 경우, 기존 조립체 체적 및 재료 단면 보류 조건을 유지한다.

근거 연결·곡면 의미에 관한 새 회귀검사와 기존 CAD·계약·단면 검사를 함께 실행한 결과는 **124개 통과, 66.68초**이다. 이 실행은 아래 명령으로 재현할 수 있다. 실행 중 VPP 단면 안내의 표현을 실제 구현된 성분 수·차집합 범위에 맞췄고, Bottom-up 적용 조건을 상세 결과에서도 보존되는 제한 목록에 명시했다. 이 마지막 변경은 안내 문장만 바꾸며 계산·임계값·API는 바꾸지 않는다.

```powershell
.venv/Scripts/python.exe -m pytest tests_v3/test_process_evidence.py tests_v3/test_analysis_evidence.py tests_v3/test_cad_and_geometry.py tests_v3/test_contracts.py tests_v3/test_cross_sections.py -q
```

마지막 안내 표현을 반영한 뒤 `test_process_evidence.py`, `test_analysis_evidence.py`를 새 프로세스에서 다시 실행해 **63개 통과, 1.49초**를 확인했다. 이후 전수 실행에서 곡면 STEP의 고분자 PBF 하향면 상태가 곡면 분기 때문에 `unknown`이 되는 것을 발견해, 공정상 `not_applicable`을 우선하는 분류 계약을 복원했다. 이는 계산값 변경이 아니며 위 시험 수치에 포함되지 않은 후속 변경이다. 동결 전수 결과를 덮어쓰지 않고 곡면 2개의 고분자 PBF 사례를 별도 재시험한다.

이는 자동화된 기하·근거 의미 계약의 검증이다. 무작위 외부 형상의 전수 실행 기록, 로컬 앱 화면 점검, 실제 프린터의 치수·출력 성공 검증은 서로 다른 증거이며 합쳐서 “제조 정확도 100%”로 표현하지 않는다. 전수 실행 엔진의 지문과 안내·상태 변경 시점도 최종 실행 기록에서 구분한다.

추가로 CAD 재메싱 후보를 만들 때 `BRepBuilderAPI_Copy(shape, True, False)`로 기하를 복사하고 기존 삼각분할을 공유하지 않도록 하는 후속 수정이 있다. 이는 문구 수정이 아니며 재시도 메시의 생성·채택에 영향을 줄 수 있다. 관련 2개 파일을 별도로 재검증하며 위 124개·63개 통과를 이 후속 코드 전체의 검증으로 사용하지 않는다. 자세한 동결 이후 차이와 최종 집계는 [무작위 형상 전수 검토 인수 기록](../project-knowledge/RANDOM_CORPUS_REAUDIT_2026-09-14.md)을 따른다.

## 11. 출처와 확인 범위

다음 표는 논문·표준의 제목만 수집한 목록이 아니라 실제 판단에 사용한 절과 적용 한계를 기록한다. 웹 본문은 고정 PDF 쪽수가 없으므로 절 제목으로 찾는다. PDF 쪽수는 표지·서지 페이지를 포함하는 물리 쪽수이며 인쇄 쪽과 구분한다. 이 목록이 적층제조 문헌 전체를 포괄하거나 모든 전문을 확보했다는 뜻은 아니다.

| 번호 | 출처·확인 위치 | 확인 범위·조건 | 연결 기능과 한계 |
|---|---|---|---|
| 1 | ISO/ASTM 52910:2018, 공식 Scope | 공개 소개·범위; 전문 전체 재확보 아님 | 공통 설계 고려의 구성. 보편 숫자 기준 아님 |
| 2 | ISO/ASTM 52902:2023, 공식 Scope | 공개 범위; 전문 미확보 | 알려진 형상·기하 능력 검증의 필요. 자체 CAD 시험이 표준 인증은 아님 |
| 3 | ISO/ASTM 52911-1:2019, Scope | 금속 레이저 PBF 공식 범위 | 금속 공정 분리. 상세 조항 준수 주장 불가 |
| 4 | ISO/ASTM 52911-2:2019, Scope | 고분자 레이저 PBF 공식 범위 | SLS 공정 분리. 모든 PBF/분말 재료로 일반화 불가 |
| 5 | Pan, He, Xu, Feinerman (2017), §§2.2, 3.1–3.2, 4, 5.1–5.2 | 저자 대학의 PDF 10쪽. 물리 pp.4–8 = 인쇄 pp.355–359. 원통식(6)·형상 실험·재료·기구 조건 확인 | VPP A·P·A/P 측정의 필요. 일반 힘 예측식으로 구현하지 않음 |
| 6 | Formlabs, Model orientation best practices for SLA printing | 웹 `Tilting a flat surface`, `Preserving integrity at intersections`, `Reducing minima`, `Preventing suction cups` 본문 | VPP 방향·최소점·컵 검토. Form 계열의 제조사 가이드 |
| 7 | Formlabs, Design specifications for 3D models (Form 4 generation) | 웹 조건 주석, 벽·경사·일반홀·배출홀, 공차 및 비교표 | 장비별 임계값 구분. 50 µm 설계 가이드와 100 µm 공차 시험 분리 |
| 8 | Formlabs, Fuse Series SLS Design Guide | 웹 기준 조건, 벽·배출구·응력 집중·패킹·시험편 권고 확인 | SLS 벽·배출 검토. 균일두께 절의 잘못 연결된 본문은 채택하지 않음 |
| 9 | Li, Yuan, Zhu, Li, Zhang (2020), Polymers 12, 1373 | 원문 XML §§2.1–2.3, 3.3, 4. DOI 원문의 공개 아카이브. PA12·실험·물성/열이력 조건 확인 | SLS 휨은 기하 하나의 함수가 아님. 동일 장비·재료 보정 필요 |
| 10 | Mohr et al., 온라인 2024/권호 2025, §§2.1–2.3, 3.1.1 | Springer 전체 웹 본문. 형상·316L 조건·실측 열이력과 FEM 비교 구간 | LPBF 단면 변화 관측. 면적과 온도의 단조 관계 주장 불가 |
| 11 | Cheng et al. (2019), Additive Manufacturing 27, 290–304 | 출판사 공개 초록·서론만 확인; 상세 전문 재현 아님 | 잔류응력·지지 설계의 필요. 최적 서포트 재현 성능 미주장 |
| 12 | Dimopoulos et al. (2023), Materials 16, 7164 | 원문 XML §§2–3, 6–7. 실험 재료와 수치 재료·열경계 차이 확인 | 지지의 열·고정·제거 절충. 최적 숫자를 앱 규칙에 이식하지 않음 |
| 13 | EOS, Support-Free Metal 3D Printing: Pros & Cons (2022) | 공식 설명의 지지 역할·특수 저각도 공정 사례 | 45° 보편 한계의 반례. 제조사 성능을 독립 검증으로 사용하지 않음 |
| 14 | Hunter et al. (2020), §§2.1–2.2, 3.1.2–3.1.3, 4 | Springer 공개 원문. L-PBF/EBSM 채널과 제거·XCT·질량 한계 확인 | 제거 연결성과 물리 세척 성능 분리. 1개 구멍 기준의 합격식 금지 |
| 15 | ASTM F3530-22, 공개 Scope | 금속 PBF-LB 후처리 설계; 전문 미확보 | 분말 제거 검토 필요. 채널 최소 수치 근거로 쓰지 않음 |
| 16 | Demir, Zohdi, Gu (2026), Discussion | 출판사 웹 본문의 미평가 영역·실험 검증 필요·서지 확인 | 열 ML 장기 확장과 한계. 현 앱의 정확도 근거 아님 |
| 17 | Kuipers et al. (2020), arXiv v1 Abstract | 공개 원고 서지·초록 재확인; 상세 원고 검토는 기존 연구 기록 참조 | MEX 가변 선폭에 의한 고정 선폭 판정 한계 |
| 18 | PrusaSlicer, Arachne perimeter generator | 공식 페이지·목차 재확인. 동적 웹 본문 노출이 불완전하여 새로운 기본값을 추출하지 않음 | 기존 가변 선폭 출처 유지. 버전별 실행 검증 별도 |
| 19 | OCCT, STEP translator | 공식 STEP reader·단위·shape transfer 문서와 설치된 API | CAD 단위·솔리드·곡면 해석. PMI·설계 이력 복원 완료 아님 |
| 20 | 3MF Consortium, Core v1.4.0 | 공식 저장소 Published 2025-02-06 판, §§2.1, 2.3, 3.3–3.4, 4.1–4.2 본문 | 선언 단위·루트 빌드·객체 변환·성분 입력. 전체 규격 적합을 주장하지 않음 |
| 21 | 3MF Consortium, Production v1.2 | 공식 저장소 Published v1.2, §§2, 3.1–3.3 본문 | 패키지 내부 외부 모델 참조·비루트 참조 금지·루트 build 의미 |
| 22 | Library of Congress, STL File Format Family | Description, Identification and description, Format specifications 본문 | STL 삼각형·법선 구조. 원 1988 규격 전문 자체가 아님 |

[^1]: ISO. [ISO/ASTM 52910:2018 — Additive manufacturing — Design — Requirements, guidelines and recommendations](https://www.iso.org/standard/67289.html). 공식 Scope.
[^2]: ISO. [ISO/ASTM 52902:2023 — Additive manufacturing — Test artefacts — Geometric capability assessment of additive manufacturing systems](https://www.iso.org/standard/79683.html). 공식 Scope.
[^3]: ISO. [ISO/ASTM 52911-1:2019 — Additive manufacturing — Design — Part 1: Laser-based powder bed fusion of metals](https://www.iso.org/standard/72951.html). 공식 Scope.
[^4]: ISO. [ISO/ASTM 52911-2:2019 — Additive manufacturing — Design — Part 2: Laser-based powder bed fusion of polymers](https://www.iso.org/standard/72952.html). 공식 Scope.
[^5]: Pan, Y., He, H., Xu, J., Feinerman, A. (2017). [Study of separation force in constrained surface projection stereolithography](https://yayuepan.lab.uic.edu/wp-content/uploads/sites/779/2021/01/8edafea83b2e3d9d65896da53bcf9ab108dc.pdf). Rapid Prototyping Journal 23(2), 353–361. DOI: [10.1108/RPJ-12-2015-0188](https://doi.org/10.1108/RPJ-12-2015-0188). 저자 대학 공개 PDF.
[^6]: Formlabs. [Model orientation best practices for SLA printing](https://formlabs.com/support/Model-Orientation/). 날짜 미표기 웹 문서; 2026-09-14 확인.
[^7]: Formlabs. [Design specifications for 3D models (Form 4 generation)](https://formlabs.com/support/Design-specifications-for-3D-models-Form-4-generation/). 날짜 미표기 웹 문서; 2026-09-14 확인.
[^8]: Formlabs. [Fuse Series SLS Design Guide](https://formlabs.com/eu/white-papers/fuse-series-sls-design-guide/). 날짜 미표기 웹 문서; 2026-09-14 확인.
[^9]: Li, J., Yuan, S., Zhu, J., Li, S., Zhang, W. (2020). [Numerical Model and Experimental Validation for Laser Sinterable Semi-Crystalline Polymer: Shrinkage and Warping](https://doi.org/10.3390/polym12061373). Polymers 12(6), 1373. 원문 확인 경로: [Europe PMC full-text XML](https://www.ebi.ac.uk/europepmc/webservices/rest/PMC7361694/fullTextXML).
[^10]: Mohr, G., Chaudry, M. A., Scheuschner, N., Blasón González, S., Madia, M., Hilgenberg, K. (온라인 2024; 권호 2025). [Thermal history transfer from complex components to representative test specimens in laser powder bed fusion](https://link.springer.com/article/10.1007/s40964-024-00689-8). Progress in Additive Manufacturing 10, 943–958. DOI: 10.1007/s40964-024-00689-8.
[^11]: Cheng, L., Liang, X., Bai, J., Chen, Q., Lemon, J., To, A. (2019). [On utilizing topology optimization to design support structure to prevent residual stress induced build failure in laser powder bed metal additive manufacturing](https://www.sciencedirect.com/science/article/pii/S2214860418309035). Additive Manufacturing 27, 290–304. DOI: 10.1016/j.addma.2019.03.001. 공개 미리보기 확인.
[^12]: Dimopoulos, A., Salimi, M., Gan, T.-H., Chatzakos, P. (2023). [Support Structures Optimisation for High-Quality Metal Additive Manufacturing with Laser Powder Bed Fusion: A Numerical Simulation Study](https://doi.org/10.3390/ma16227164). Materials 16(22), 7164. 원문 확인 경로: [Europe PMC full-text XML](https://www.ebi.ac.uk/europepmc/webservices/rest/PMC10673092/fullTextXML). 편집자와 저자를 구분했다.
[^13]: EOS (2022). [Support-Free Metal 3D Printing: Pros & Cons](https://www.eos.info/content/blog/2022/support-free). 제조사 공식 설명.
[^14]: Hunter, L. W., Brackett, D., Brierley, N., Yang, J., Attallah, M. M. (2020). [Assessment of trapped powder removal and inspection strategies for powder bed fusion techniques](https://link.springer.com/article/10.1007/s00170-020-04930-w). The International Journal of Advanced Manufacturing Technology 106, 4521–4532. DOI: 10.1007/s00170-020-04930-w.
[^15]: ASTM International. [F3530-22 — Standard Guide for Additive Manufacturing — Design — Post-Processing for Metal PBF-LB](https://store.astm.org/f3530-22.html). 공개 Scope.
[^16]: Demir, K. G., Zohdi, T., Gu, G. X. (2026). [Enabling geometry and toolpath generalization for machine learning based thermal modeling in laser powder bed fusion](https://www.nature.com/articles/s44387-026-00088-0). npj Artificial Intelligence 2, 63. DOI: 10.1038/s44387-026-00088-0. 공개 페이지의 Published 2026-05-24, Version of record 2026-08-17 표기를 구분했다.
[^17]: Kuipers, T., Doubrovski, E. L., Wu, J., Wang, C. C. L. (2020). [A framework for adaptive width control of dense contour-parallel toolpaths in fused deposition modeling](https://arxiv.org/abs/2004.13497). arXiv:2004.13497v1; 16쪽 저자 원고.
[^18]: Prusa Research. [Arachne perimeter generator](https://help.prusa3d.com/article/arachne-perimeter-generator_352769). PrusaSlicer 공식 Knowledge Base.
[^19]: Open CASCADE Technology. [STEP translator](https://dev.opencascade.org/doc/overview/html/occt_user_guides__step.html). 공식 사용자 가이드. 설치된 cadquery-ocp-novtk의 OCCT 7.9.3 API와 구분해 확인.
[^20]: 3MF Consortium. [3MF Core Specification v1.4.0](https://github.com/3MFConsortium/spec_core/blob/master/3MF%20Core%20Specification.md). 공식 저장소 원문, Published 2025-02-06; 2026-09-14 확인. master 링크는 이후 변경될 수 있으므로 확인한 판을 명시했다.
[^21]: 3MF Consortium. [3MF Production Extension v1.2](https://github.com/3MFConsortium/spec_production/blob/master/3MF%20Production%20Extension.md). 공식 저장소 원문, Published v1.2; 2026-09-14 확인.
[^22]: Library of Congress. [STL (STereoLithography) File Format Family](https://wwws.loc.gov/preservation/digital/formats/fdd/fdd000504.shtml). Sustainability of Digital Formats, fdd000504. 공식 형식 해설이며 원 1988 규격 전문은 아니다.
