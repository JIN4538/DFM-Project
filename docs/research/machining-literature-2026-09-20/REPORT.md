# 절삭가공 제조성 검토 문헌 조사 보고서

조사일 2026-09-20

# 절삭 제조성 검토를 위한 문헌 조사와 개발 방향

조사 기준일: 2026년 9월 20일. 대상은 현재 적층·절삭 도구의 근거와 절삭 기능의 다음 개발 단계다. 사출·프레스는 이번 범위에 포함하지 않는다. 대괄호의 문헌 번호는 뒤의 서지 목록과 연결된다.

## 1. 먼저 알아야 할 결론

현재 절삭 도구는 CAD에서 문제를 일찍 발견하고, 선택한 공구와 방향을 바꿀 이유를 설명하는 **초기 설계 검토 도구**로 발전시키는 것이 타당하다. 다음 핵심 투자는 규칙의 개수를 늘리는 일보다, 실제 크기를 가진 공구·홀더가 원소재와 고정구 사이로 들어갈 수 있는지 확인하는 기능이다. 이 기능이 생겨야 ‘보이는 면’에서 ‘선택 공구가 닿는 후보 영역’으로 검토 범위가 구체화된다. 이 방향은 접근성 연구와 상용 CAM의 충돌 처리 구조가 함께 뒷받침한다.[G01][G11][P05]

현재 코드가 제공하는 것은 단일 STEP 솔리드의 일부 원통면·내부 코너·제한된 직사각 포켓에 대한 치수와 공구 조건 비교, 선택 방향에서의 표본 가시성 검토다. 원통면의 직경·축 방향 범위를 측정해도 완전한 홀의 개수와 실제 드릴 깊이가 확정되는 것은 아니다. 가시성도 점에서 뻗는 직선으로 확인하므로 공구 지름, 샤프트, 홀더가 차지하는 공간을 아직 검사하지 않는다. 소재·장비 이름을 기록해도 절삭력이나 처짐 계산에 사용되는 상태는 아니다.

핵심 질문은 ‘이 공구와 방향을 쓰려면 어디를 바꾸거나 추가 확인해야 하는가?’다. 사용자는 위치, 비교값, 조건, 다음 행동을 함께 받아야 한다. ‘내부 반경 2 mm에 지름 6 mm 공구를 선택했으므로 더 작은 공구 또는 반경 변경을 검토하세요’는 행동으로 이어진다. ‘제조성 82점’만으로는 무엇을 바꿀지 알기 어렵다.

아래 내용은 문헌과 현재 구현을 대조한 개발 제안이다. 이번에 기능 구현이나 CAM·실물 시험을 수행했다는 의미는 아니다.

## 2. 현재 인용 자료를 어떻게 세었는가

‘현재 29개 등록’, ‘처음 보관한 14개 문헌’, ‘문서에서 추가로 확인되는 절삭 근거’는 서로 다른 목록이다. 같은 논문이 여러 목록에 다시 등장하므로 합계를 새 논문 수로 사용하면 안 된다.

| 구분 | 무엇을 뜻하는가 | 읽을 때 주의할 점 |
|---|---|---|
| 현재 코드의 출처 29개 | 적층·공통 입력 24개와 절삭 5개의 등록 항목 | 논문 외에 표준 안내, 수학 자료, 파일 규격, API·제조사 문서가 포함됨 |
| 기존 문헌 R01~R14 | 최초 보관 자료와 그 당시 독서 기록 | 현재 기능에서 모두 직접 인용하는 것은 아니며 이번에 전부 재독한 목록도 아님 |
| 절삭 문서에만 있는 5개 | Sandvik 코너·홀, Autodesk 드릴링, 접근성 논문, OCCT API | 코드 등록 5개와 합쳐 현재 절삭 근거는 고유 자료 10개 |
| 이번 조사 F·G·S·P 목록 | 기초, 형상·접근성, 표준, 공정·공구 분야의 조사 기록 | 같은 자료의 기술보고서·학술지판 또는 중복 주제 항목을 고유 문헌 수로 합산하지 않음 |

현재 절삭 등록 5개는 Protolabs 설계 안내, Protolabs Network의 내부 코너 안내, Harvey의 엔드밀 치수 안내, Yeo 등의 특징 인식 논문, Autodesk의 샤프트·홀더 안내다. 이 조합은 검토할 항목을 선택한 이유를 설명한다. 그러나 다섯 자료가 현재 알고리즘의 정확도를 모두 입증하는 것은 아니다. 특히 Autodesk 문서는 우리 도구의 점 가시성 계산을 검증한 자료가 아니라, 실제 충돌 검토에 무엇이 더 필요한지를 보여준다.[G02][G12][P03]

원래 14개 중 Kerbrat 등의 적층·절삭 조합 연구는 이번에도 연결된다.[F02] 기존 R12는 원문 서지와 그림이 불완전한 번역·편집 자료이므로 직접 구현 근거로 확정하지 않는다. 등록 여부, 읽은 범위, 구현에 쓰인 범위를 각각 남겨야 한다.

## 3. 근거마다 맡길 역할이 다르다

표준은 치수·공차·제품 정보를 같은 의미로 전달하고 판정하기 위한 기준이다. ‘모든 알루미늄 벽은 몇 mm 이상이면 가공 가능하다’는 보편 합격표가 아니다. 이번에는 주로 공식 카탈로그의 범위·판본·개정 상태를 확인했다. 유료 전문의 공차표나 판정식을 읽지 않은 항목은 구현 가능한 규칙으로 확정하지 않았다.[S03][S07][S14]

논문은 방법, 가정, 실험 조건과 비교 결과를 제공한다. 공개 본문을 읽은 논문, 초록만 확인한 논문, 저자 저장소의 설명만 읽은 방법을 구분했다. 1990년대 제조성·특징 인식 연구는 낡았다는 이유로 제외할 자료가 아니다. ‘형상 규칙 검사’와 ‘실제 작업 계획을 구성해 평가하는 방법’의 차이, 하나의 형상에 여러 가공 해석이 가능한 이유를 설명한다. 다만 당시의 시스템 성능이나 공구 조건을 현재 장비의 대표값으로 사용하지 않는다.[F01][G09]

제조사 안내는 공구·가공 전략 선택에 유용하지만 해당 공급자의 공구·장비 조건을 다른 업체의 절대 한계로 확대하면 오판이 생긴다.[P01][P04] CAD/CAM 문서는 입력과 기능의 의미를 알려준다. 설명을 읽는 것과 실제 실행 결과를 대조하는 것은 별개다.

표준의 최신판과 설계자가 도면에 지정한 판도 구분해야 한다. 이번 확인 시 AP242는 ISO 10303-242:2025이고, 데이텀 표준은 ISO 5459:2024다.[S01][S05] 하지만 기존 도면에 다른 판이 지정됐다면 임의로 최신판으로 바꾸지 않는다. ASME Y14.5-2018(R2024)의 2024는 재확인 연도이지 새 2024판이라는 뜻이 아니다.[S16] 적용 규격·판본·요구사항을 먼저 입력받아야 한다.

## 4. 우선 보강할 핵심 기능과 그 이유

### CAD의 면과 가공할 특징을 구분하기

STEP의 B-rep는 평면·원통면 같은 표면과 그 경계·연결 관계로 형상을 표현한다. 가공 특징은 구멍, 포켓, 홈처럼 작업과 연결되는 단위다. 구멍 하나가 여러 원통면으로 나뉠 수도 있고, 원통면이 구멍 대신 외부 돌기나 둥근 코너의 일부일 수도 있다. 면을 하나 찾았다는 이유로 구멍 하나를 인식했다고 세면 치수와 개수부터 틀릴 수 있다.[G02][F07]

다음 특징 인식기는 면 사이 연결, 내부·외부 방향, 입구와 바닥, 연결된 원통 구간을 함께 확인해야 한다. 인식된 특징은 원래 CAD의 면 번호와 연결해 클릭하면 위치를 볼 수 있어야 한다. 분할된 원통, 교차 홀, 둥근 포켓, 계단형 포켓을 별도 시험군으로 만들고, 인식하지 못한 형상은 ‘없음’ 대신 ‘이 형식은 아직 확인하지 못함’으로 알려야 한다. 이는 정확성과 사용자 편의성을 동시에 개선한다.

### 공구·홀더가 지나갈 공간 확인하기

작은 구멍 너머의 면이 눈에 보이더라도 큰 공구는 통과하지 못한다. 절삭부가 들어가도 그 위의 샤프트나 홀더가 입구와 부딪힐 수 있다. 접근성 연구는 부품·고정구가 차지하는 공간과 공구 조립체의 공간을 비교하여 충돌 없는 배치를 계산한다. 여기에 실제로 밖에서 그 배치까지 이동할 수 있는 경로가 있는지도 구분해야 한다.[G01]

우선 고정된 한 방향에서 공구·홀더 형상을 사용한 충돌과 도달 검토를 구현하고, 이후 방향별 제거 가능한 영역과 남는 영역을 비교하는 것이 합리적이다. 최종 부품만으로는 충분하지 않다. 가공 전 원소재와 현재까지 제거한 영역, 고정구가 있어야 각 단계의 장애물을 알 수 있다.[G09][G11] CAM 대조에서도 절삭 중 충돌, 이동·복귀 중 충돌, 지정 여유를 구분해야 한다.[G13]

### 공구 길이와 코너 숫자를 정확하게 설명하기

날 길이, 공구 전장, 샹크 아래 길이(LBS, 감소 목부 시작점부터 절삭 끝까지), 장착 후 공구 끝에서 홀더 앞면까지의 돌출 길이는 서로 다르다.[P03] 깊이가 날 길이보다 크다고 모든 가공을 불가능으로 처리하면 감소 목부나 여러 번 나누는 작업의 가능성을 놓친다. 반대로 전장만 충분하다고 접근 가능으로 처리하면 실제 홀더 간섭을 놓친다. 사용자 입력은 이름만 나열하지 말고 작은 치수 그림과 함께 받아야 한다.

내부 코너도 기하 조건과 공정 권고를 나눠 보여야 한다. 공구축과 평행한 오목 원통 코너를 원통 옆날로 가공한다고 가정하면, 공구 지름 D와 코너 반경 R에 대한 단순 기하 필요조건은 D≤2R이다. 바닥과 벽 사이의 코너에는 이 식을 그대로 적용하지 않는다. Sandvik의 최종가공 안내에 나오는 D≤1.5R은 코너에서 물림을 줄이기 위한 권고다.[P01] 둘 다 만족했다고 안정성이나 표면 품질이 보장되지는 않는다. 화면에서는 ‘선택 공구의 크기가 맞는가’와 ‘가공 부담을 줄일 여유가 있는가’를 따로 설명해야 한다.

### 소재·고정·셋업을 설계 검토에 연결하기

같은 외형이라도 소재의 합금·열처리, 벽의 지지 상태, 바이스가 잡는 위치에 따라 변형과 가공 난도가 달라진다.[P08][P11] 소재명을 드롭다운에서 고르게 하는 것만으로 소재를 고려한 해석이 완성되는 것은 아니다. 초기에는 소재 정보, 원소재, 고정할 면, 가공 방향을 명시하고, 고정 때문에 가려지는 영역을 검토하는 기능이 먼저다.

위치 결정은 부품의 위치와 자세를 정하는 일이고, 클램핑은 가공 중 움직이지 않도록 누르는 일이다. 너무 강하게 잡으면 얇은 부분이 변형될 수 있다. 평면 고정구 연구의 접촉·강체 가정을 실제 3차원 부품의 절삭력·변형 보증으로 확장하면 안 된다.[G10] 최근 고정 상태 추정 연구도 실제 변형률과 모델 보정에 의존한다.[P14][P15] 따라서 ‘잡을 곳 후보’와 ‘이 고정력에서 변형이 허용 범위 안인가’를 별도 단계로 개발해야 한다.

### 공차·표면 요구를 빠뜨리지 않기

CAD에서 잰 구멍 지름 10 mm와 설계자가 지정한 10 H7은 정보가 다르다. 전자는 현재 형상 크기이고, 후자는 허용할 크기의 범위를 해석해야 하는 요구다. 기준면을 뜻하는 데이텀, 위치공차, 표면 거칠기까지 있어야 ‘형상은 만들 수 있지만 필요한 품질을 달성하기 어려운 부분’을 검토할 수 있다.[S04][S05][S07][S10]

AP242가 이런 정보를 전달할 수 있어도 사용자의 파일에 실제로 포함됐는지, 우리 파서가 읽었는지는 다시 확인해야 한다. 화면에 보이는 치수 글자와 컴퓨터가 의미를 해석할 수 있는 PMI도 다르다.[S01][S02] 파일을 열면 ‘형상 읽음 / 치수·공차 정보 발견 여부 / 실제 해석 범위’를 알려주고, 없는 요구사항은 사용자나 도면에서 보완받는 구조가 필요하다. 코드 내부의 부동소수점 비교 허용값을 설계 공차나 계측 불확도로 표시해서는 안 된다.[S14]

### 힘·진동·시간은 필요한 입력부터 갖추기

깊이/지름 비율은 긴 공구를 찾는 단서가 될 수 있지만 절삭력·처짐·채터의 완전한 모델은 아니다. 진동에는 공구, 홀더, 장비, 부품, 고정 상태가 함께 관여한다.[P07] 안정성 연구는 구조 동특성과 절삭력 계수 등 추가 입력을 요구한다.[P12] 원문 수식과 조건을 충분히 확인하지 못한 연구를 바로 숫자 계산기에 옮기는 단계는 아니다.[P13]

가공 시간도 부품 체적을 일정 제거율로 나눈 값만으로 완성되지 않는다. 경로 길이, 실제 이송, 가감속, 공구 교환, 셋업과 검사 시간이 필요하다. 실제 장비의 이송 자료를 학습한 시간 예측 연구도 새로운 경로 조건에서 오차가 달라진다.[P16] 초기에는 ‘시간을 늘릴 요인’과 CAM에서 계산한 시간을 구분해 제공하고, 실제 시간 예측은 외부 가공 로그를 확보한 뒤 진행하는 편이 타당하다.

## 5. AI는 무엇을 맡아야 하는가

가장 먼저 도입할 AI는 계산 결과와 근거를 사용자의 말로 설명하고, 부족한 입력을 찾아주는 보조 역할이다. 예를 들어 ‘이 경고가 왜 생겼는지’, ‘작은 공구를 선택하면 어떤 확인이 더 필요한지’를 관련 CAD 위치와 함께 설명한다. 치수와 판정은 검증된 계산 결과에서 가져오고, AI가 임의로 공구 치수나 합격선을 만들지 않도록 해야 한다.

그다음 후보는 복잡한 가공 특징 인식이다. BRepNet, UV-Net, AAGNet 계열은 면의 연결이나 표면 정보를 학습한다.[G03][G04][G06] 하지만 어떤 데이터는 CAD를 만든 명령을, 어떤 데이터는 합성 가공 특징을 정답으로 사용한다. ‘Extrude를 맞혔다’, ‘포켓을 맞혔다’, ‘실제로 품질을 만족하며 가공됐다’는 서로 다른 성과다. 같은 CAD를 회전하거나 조금 바꾼 자료가 학습·시험 양쪽에 들어가지 않도록 부품 계열 단위로 나누어야 한다.

2026년 KAN 연구의 공개 원고 v1은 총 300,000개의 합성 설계를 규칙으로 라벨링했으며 실물 수정·제작 사례도 제시한다.[F05] 실물 사례가 전혀 없다는 평가는 틀리다. 다만 합성 규칙을 잘 학습한 것과 새로운 장비·부품에서 실제 성공할 확률은 다르다. 논문 출력값 0.769를 우리 사용자의 가공 성공률 76.9%로 표시할 근거는 없다.

실제 성공 확률이 목표라면 먼저 성공의 정의를 정해야 한다. 형상 완성, 요구 공차 충족, 표면 품질, 시간·비용 중 무엇을 만족해야 성공인지에 따라 정답이 달라진다. 외부 실물 데이터에는 성공과 실패 사례, 장비·공구·소재·셋업·조건·검사 결과가 함께 있어야 한다. 자료가 없는 단계에서는 ‘규칙 충족 여부’, ‘인식 모델의 확신’, ‘해석하지 못한 범위’를 분리해 제시하는 것이 적절하다.

## 6. 다음 개발의 우선순위

| 순서 | 개발할 내용 | 사용자가 얻는 이득 |
|---|---|---|
| 1 | 특징 정의·적용 조건·미확정 이유와 CAD 위치 연결 | 무엇을 확인했고 어디를 고칠지 이해함 |
| 2 | 원소재와 공구·샤프트·홀더 입력, 고정축 충돌 검토 | 눈에 보이는 면과 실제 도달 영역을 구분함 |
| 3 | 고정구·셋업별 장애물과 제거 가능 영역 | 방향 변경과 추가 작업의 이유를 비교함 |
| 4 | 도면·PMI 요구사항과 검토 결과 연결 | 중요한 공차를 놓치지 않고 추가 정보가 무엇인지 앎 |
| 5 | 근거를 연결하는 AI 설명, 검증된 특징 인식 보조 | 복잡한 결과를 빠르게 이해하고 누락을 줄임 |
| 6 | 외부 공정 데이터 기반 시간·물리·성공 확률 연구 | 조건과 오차 범위가 있는 예측을 얻음 |

화면은 ‘현재 문제 → 위치와 비교값 → 바꿀 선택 → 미확정 범위’ 순서로 구성한다. 색, 미입력, 비교 통과의 뜻을 함께 쓰고, 결론은 먼저 보여준다. 긴 방법 설명과 원자료는 펼쳐 볼 수 있게 둔다.

다음 미팅에서는 같은 포켓에서 공구 크기나 방향을 바꿨을 때 도달 영역과 추가 고정의 필요성이 어떻게 달라지는지 보여주는 편이 설득력이 있다.

## 7. 장비 없이도 할 수 있는 검증

첫 단계는 정답을 알고 만든 CAD다. 구멍·포켓·코너의 치수와 위치를 독립적으로 정의하고 경계값 양쪽을 시험한다. 같은 형상의 이동·회전·단위 변경·면 분할 뒤에도 본질적 결과가 유지되는지 확인한다. 원통면의 단순 구간과 완전한 홀을 구분하는 교차 홀·분할 면 사례도 포함한다. 구현 함수의 출력을 그대로 정답으로 복사하면 독립 검증이 되지 않는다.

두 번째는 다른 도구와의 대조다. CAD 치수와 체적은 독립 기하 계산 또는 다른 CAD 커널의 결과와 비교한다. PMI는 NIST의 기준 도면과 CAD·STEP 파생물로 확인할 수 있다.[F04] 충돌은 동일한 원소재·공구·홀더·고정구·셋업을 지정한 CAM 시뮬레이션과 비교한다. 시뮬레이터의 충돌 옵션이 꺼져 있거나 입력이 다르면 결과를 정답으로 삼지 않는다. 이런 검증은 기하 계산의 타당성을 높이며 실제 표면 품질까지 입증하지는 않는다.

세 번째는 외부 실제 형상이다. 공개 데이터의 면·특징 정답을 전문가가 확인한 일부 형상과 대조하고, 실패 종류와 미인식 영역을 기록한다. MFCAD++ 논문과 배포 목록에는 총수 표기가 다른 부분이 있어 실제 파일 목록을 확보한 뒤 해시·중복·분할 구성을 확인해야 한다.[G05][G07] 합성 데이터에서 잘 된 결과만으로 실제 설계 전반의 성능을 주장하지 않는다.

마지막은 외부 실물 기록의 확보다. 공개 시험 자료, 공동연구기관, 외주 가공 기록에서 조건과 측정 결과가 함께 있는 사례를 수집할 수 있다. 장비가 없다는 이유로 소프트웨어 개발을 멈출 필요는 없다. 다만 CAD 시험, CAM 시뮬레이션, 실물 치수 검사라는 세 결과를 같은 ‘성공’으로 섞지 않고 별도로 표시해야 한다.[S12][S13][S15]

## 8. 먼저 읽을 열 자료와 확보할 것

아래는 권장 독서 순서다. 정확한 서지와 실제 열람 범위는 부록에 정리했다.

| 순서 | 자료 | 먼저 확인할 질문 |
|---|---|---|
| 1 | 제조성 자동 분석 조사 [F01] | 형상 규칙과 작업 계획의 차이는 무엇인가? |
| 2 | Yeo 등의 특징 인식 [G02] | 왜 원통면 하나를 홀 하나로 셀 수 없는가? |
| 3 | Harvey 엔드밀 치수 안내 [P03] | 어떤 길이를 입력받고 비교해야 하는가? |
| 4 | Sandvik 내부 코너 안내 [P01] | 기하 한계와 가공 안정성 권고는 어떻게 다른가? |
| 5 | 접근성 제약 연구 [G01] | 공구와 홀더의 실제 부피를 어떻게 고려하는가? |
| 6 | Autodesk 샤프트·홀더 [P05] | CAM 비교에 어떤 충돌 설정이 필요한가? |
| 7 | 공간 기반 가공 계획 [G11] | 원소재·제거량·셋업은 어떻게 연결되는가? |
| 8 | Carr Lane 위치 결정·고정 [P11] | 잡을 위치가 왜 제조성에 중요한가? |
| 9 | NIST STEP 분석 안내 [S02] | 파일 속 형상과 의미 PMI를 어떻게 구분하는가? |
| 10 | 공차를 고려한 KAN 연구 [F05] | AI가 학습한 정답과 실물 성공을 어떻게 구분하는가? |

구체 구현 전에 확보할 자료는 필요한 조항의 표준 전문, 현재 사용할 공구의 실제 형상·카탈로그, 원소재·고정구가 포함된 CAM 대조 사례, 조건과 측정값이 있는 외부 실물 자료다. 공차 모듈은 ISO 286 등의 원표와 지정 판을, 물리 예측은 아직 초록 수준으로 확인한 절삭력·안정성 논문의 전문과 계수를 먼저 확보해야 한다.[S07][P12][P13]

새 연구도 공개 원고의 판본과 자산을 확인해야 한다. FeatureFox의 2026년 프리프린트는 산업 CAD 사례를 다루지만 코드·데이터가 비공개라 그대로 재현하기 어렵다.[G16] 연구 기여는 AI 도입 자체보다 인식과 기하 검사를 연결하고 미확정 영역을 보존하며 독립 반례로 성능을 입증하는 데서 찾아야 한다.


## 조사 문헌 상세 카드

### F01 Automated manufacturability analysis: A survey

Satyandra K. Gupta; William C. Regli; Diganta Das; Dana S. Nau / 1997 학술지판; 열람 원고는 NIST IR 5713 계열 기술보고서

확인: 출판사 서지와 초록 및 NIST 공개 원고의 관련 본문 확인 / NIST 37쪽 PDF의 §3, §4.2, §5.1–5.3. 학술지 9권 168–190쪽과 PDF 페이지 체계가 다름

핵심: 형상 규칙을 직접 검사하는 방식과 공정 계획을 만들어 평가하는 방식을 구분한다. 절삭에서는 같은 부품에 여러 작업 방법이 있고 작업 간 상호작용도 있으므로 국소 규칙만으로 전체 제조성을 결정하기 어렵다.

적용: 현재 도구를 초기 설계 검토로 정의하고, 이후 공구·셋업·작업 순서별 대안을 비교하는 구조. 수정 제안에 설계 기능과 요구사항을 함께 보존할 필요성.

입력: 부품 형상, 치수·공차·표면 요구, 사용 가능한 제조 자원, 기능상 변경 금지 조건

한계: 1997년 당시 시스템 동향을 2026년 시장 현황으로 단정하거나, 특정 공차·최소 벽 수치를 보편 규칙으로 도입하는 것.

판본: 신규 조사. 오래된 논문이지만 규칙 검토와 공정 계획의 구분에 직접 관련. 본문에 인용된 다른 논문을 모두 읽었다는 의미는 아님.

[원문](https://link.springer.com/article/10.1007/BF01596601)

### F02 A new DFM approach to combine machining and additive manufacturing

Olivier Kerbrat; Pascal Mognol; Jean-Yves Hascoët / 2011

확인: 기존 저장소 R01 기록 대조 및 공개 저자 원고 관련 본문 재확인 / 18쪽 arXiv PDF §2.1–2.3, Table 1, §5; 기존 저장소 학술지 PDF는 9쪽

핵심: 적층과 절삭의 전역·국소 난이도를 CAD 위치에 연결하고 부품 분할과 공정 조합을 검토한다. 도구 유연성, 제거량, 재료와 표면 요구를 포함하지만 서로 다른 공정의 지표를 바로 합산할 수 없다.

적용: 사용자가 수정할 위치를 보여주는 설계 검토, 적층과 절삭에서 동일 설계 대안을 비교하는 프레임워크.

입력: 원소재와 제거 체적, 재료, 표면 요구, 공구 조건, 분할·조립 요구사항

한계: 논문의 난이도 지표를 우리 코드의 성공 확률·원가 절감률로 사용하거나 현재 툴이 분해 최적화를 구현했다고 설명하는 것.

판본: 기존 인용 R01의 재검토이며 신규 문헌 수에 중복 집계하지 않음. 수치가 높을수록 어려운 지표 방향을 주의.

[원문](https://arxiv.org/abs/1106.3176)

### F03 STEP File Analyzer and Viewer

National Institute of Standards and Technology / 웹 문서 조회판 2026-09-20

확인: 공식 본문 확인 / Description, Analyzer의 semantic PMI·graphic PMI·validation properties, Syntax Checker, Testing STEP Implementations

핵심: 기계가 해석할 수 있는 의미 PMI와 화면에 표시할 주석 모양인 그래픽 PMI를 분리한다. STEP의 기본 구문, 치수·공차 정보, 원 CAD와의 검증 속성을 별도로 조사할 수 있다.

적용: STEP 입력 시 형상만 읽혔는지, PMI가 존재하는지, 그 의미까지 파싱했는지 구분. 독립 도구를 이용한 입력 정보 대조.

입력: 원본 STEP, 적용 AP와 판, semantic/graphic PMI 엔티티, CAD 검증 속성

한계: STEP 파일이면 원 설계 치수·공차·이력·재료가 모두 포함되거나, B-rep 읽기에 성공하면 PMI까지 해석했다는 결론.

판본: 신규 조사. 문서 열람이며 NIST 프로그램을 실제 실행한 결과는 아님.

[원문](https://www.nist.gov/services-resources/software/step-file-analyzer-and-viewer)

### F04 MBE PMI Validation and Conformance Testing Project

National Institute of Standards and Technology / 역사적 검증 프로젝트의 공식 공개 페이지

확인: 공식 프로젝트 본문과 공개 모델 안내 확인 / Test System Components, Test Cases, Test Case Expert Review, CAD Model Verification and Derivative File Validation

핵심: 전문가가 정의한 시험 도면과 CAD를 비교하고, 여러 CAD 시스템의 모델 및 STEP 파생물을 교차 검증한다. 단일 주석용 ATC, 결합 CTC, 전체 공차 FTC를 구분한다.

적용: 장비 없이 PMI 파서의 기대값을 독립적으로 검증할 자료. 원본 CAD와 교환 파일을 별도로 검증하는 시험 설계.

입력: 시험 정의, 원 CAD, 파생 STEP, 주석별 기대 의미와 대응 면

한계: 가공 결과의 치수 달성이나 최신 ASME판 준수 인증. 페이지는 1994·2003판 기준 시험임을 명시하며 당시의 '최신' 표현은 현재판 정보가 아님.

판본: 신규 조사. CAD 및 도면의 공개 여부를 확인했으며 본 작업에서 모델 전부 다운로드·실행하지 않음.

[원문](https://www.nist.gov/ctl/smart-connected-systems-division/smart-connected-manufacturing-systems-group/mbe-pmi-validation)

### F05 Kolmogorov-Arnold Networks-Based Tolerance-Aware Manufacturability Assessment Integrating Design-for-Manufacturing Principles

Masoud Deylami; Negar Izadipour; Adel Alaeddini / 2026 arXiv v1

확인: 공개 원고 관련 본문과 표 확인 / §3.2–3.3 Tables 2–5, §4.3–4.4, §6 Case Study, §7

핵심: 드릴링·포켓 밀링·조합 시나리오에 규칙으로 라벨링한 총 300,000개 합성 설계를 학습한다. §6에는 중간 수정안의 변형과 최종 제작 사례도 제시한다. 따라서 실물 사례가 전혀 없는 연구라고 설명하면 틀린다.

적용: 공차와 공구 가용성을 포함한 특징 데이터, 규칙 기반 라벨의 학습 가능성, 수정 이유를 보여주는 사용자 흐름.

입력: 시나리오별 설계 매개변수와 공차, 공구 카탈로그, 명시된 라벨 생성 규칙; 확률 연구에는 별도의 실측 결과

한계: 모델 출력 0.769를 일반 부품의 실제 제작 성공률 76.9%로 이전하는 것. 합성 라벨 성능과 한 설계 사례는 외부 장비·부품의 확률 보정 근거가 아님.

판본: 신규 조사. 검토판은 arXiv v1. HTML에 Journal of Manufacturing Systems 표기가 있으나 이 조사에서는 출판사 최종 게재 서지·DOI를 확인하지 않았으므로 게재 확정으로 표기하지 않음.

[원문](https://arxiv.org/abs/2601.06334)

### F06 Systematic approach to analysing the manufacturability of machined parts

Satyandra K. Gupta; Dana S. Nau / 1995

확인: 출판사 검색 결과의 서지·초록 확인; 직접 페이지 열기 실패, 본문 미확인 / 초록의 대안 작업 생성과 공정 계획 평가 설명

핵심: 같은 설계를 만드는 여러 작업 계획을 생성하고 설계·제조 목적에 맞는 대안을 평가하는 접근을 제시한다.

적용: 다음 연구 단계로 공정 계획 기반 DFM을 검토할 근거와 읽을 문헌 선정.

입력: 설계, 원소재, 제조 작업 후보, 자원·품질·원가 요구

한계: 원문을 확보하지 않고 구체 알고리즘·복잡도·공차식을 구현하거나 실험 성능을 인용하는 것.

판본: 신규 조사. Computer-Aided Design 27(5), 323–342. 출판사 검색 색인의 DOI 10.1016/0010-4485(95)96797-P와 저자의 USC 공식 서지를 대조했다. 직접 페이지 열기 실패는 그대로 보존한다.

[원문](https://www.sciencedirect.com/science/article/pii/001044859596797P)

### F07 Open CASCADE Technology Reference Manual BRepTools Class Reference

Open Cascade / 조회 웹 문서 8.0.1

확인: 공식 API 본문 확인 / UVBounds 세 오버로드의 선언과 설명

핵심: UVBounds는 트림된 면·와이어·모서리의 매개변수 경계를 반환한다. 해당 원통면 구간을 재는 도구이지 완전한 홀의 제조 깊이나 경로를 복원하는 함수가 아니다.

적용: 현재 CAD 치수 추출의 의미와 원통면 분할 반례 설명.

입력: TopoDS_Face와 트림 위상, 매개곡면 정의, 실제 설치 버전

한계: API 문서만으로 설치된 버전의 수치 정확도나 구멍 인식의 완전성 보증.

판본: 기존 재감사 E09. 웹은 8.0.1, 현재 검토된 OCP 환경은 7.9.3.1 계열이므로 버전 차이를 기록한다.

[원문](https://occt3d.com/dev/doc/refman/html/class_b_rep_tools.html)

### S01 ISO 10303-242:2025 — Industrial automation systems and integration — Product data representation and exchange — Part 242: Application protocol: Managed model-based 3D engineering

국제표준화기구(ISO) / 2025

확인: 공식 카탈로그의 적용 범위·서지·발행/개정 상태 확인; 유료 규정 본문 미열람 / 공식 페이지 Abstract; General information; Life cycle

핵심: 형상뿐 아니라 치수·기하공차, 표면 조건, 제조 특징, 제품·공정 정보를 교환할 수 있는 AP242 범위를 확인했다.; 개발 권고: 파일 형식, 실제 포함된 정보, 현재 읽은 정보를 각각 표시한다.

적용: STEP 입력의 PMI·검증 속성·형상 연결 요구사항 설계

입력: 원본 STEP; FILE_SCHEMA 및 AP 판; 의미 PMI 엔티티; 단위·형상 연결; 내보내기 옵션

한계: AP242 파일이면 반드시 설계치수·공차가 있음; B-rep 로딩만으로 PMI를 읽었다는 주장; 제조 성공 판정

판본: 2025-08, 4판 Published. 2022판 Withdrawn. 90.92 개정 예정 및 차기 CD 표시; CD를 현행 규정으로 취급하지 않음.

[원문](https://www.iso.org/standard/84300.html)

### S02 STEP File Analyzer and Viewer User Guide (Update 7), NIST AMS 200-12

Robert R. Lipman; Soonjo Kwon / 2021

확인: 공개 원문 PDF에서 관련 절 선별 열람; 전권 정독·도구 실행은 하지 않음 / 표지와 2021-10 서지; 6 Analysis Reports, 인쇄 p.40/PDF p.48; 6.1 Semantic PMI, 인쇄 pp.42–44/PDF pp.50–52; 6.1.3·6.1.4 치수와 기하공차, 인쇄 pp.44–47; 6.1.7 Coverage, 인쇄 p.53; 6.2 Graphic PMI, 인쇄 p.55; 6.6.1 NIST 기대 주석과 대조, 인쇄 p.65

핵심: 의미 PMI는 계산 가능한 정의와 형상 연계를, 그래픽 PMI는 보이는 주석을 전달하므로 동일시할 수 없다.; 치수 유형·값·상하한·대상 면 연결을 추적하고, NIST 기준 모델의 기대 주석과 대조하는 방법을 제공한다.

적용: PMI 유무·가져오기 손실·면 연결 검사; NIST 기준 사례와 독립 대조

입력: PMI가 포함된 STEP; 기대 주석이 알려진 기준 CAD/도면; 파서 결과의 원본 엔티티 ID

한계: PMI 가져오기 성공이 실제 가공 가능성이나 치수 만족을 증명함; 그래픽 주석 OCR만으로 검증된 의미 PMI 확보

판본: 문서는2021년판이다. 현재 NIST 도구 페이지는5.41 및2026-01 이후 GitHub 배포 안내를 표시하므로 문서 시점과 실행 버전을 분리할 것.

[원문](https://doi.org/10.6028/NIST.AMS.200-12)

### S03 ISO 8015:2011 — Geometrical product specifications (GPS) — Fundamentals — Concepts, principles and rules

국제표준화기구(ISO) / 2011

확인: 공식 카탈로그의 적용 범위·서지·발행/개정 상태 확인; 유료 규정 본문 미열람 / 공식 페이지 Abstract; General information; Life cycle

핵심: GPS 표기의 작성·해석·적용의 기본 틀이다.; 개발 권고: CAD 좌표에서 얻은 치수와 설계자가 지정한 요구사항을 다른 데이터로 관리한다.

적용: 적용 규격·판·기본 해석 규칙의 명시

입력: 도면 또는 PMI의 적용 규격과 판; 명시 요구사항; 해당 형상·측정 연산 정의

한계: 공차 미입력 시 임의 일반공차 부여; ISO와 ASME 규칙의 무조건 혼합; 절삭성 한계값

판본: 2011-06,2판 Published;2021 재확인. 본문 개별 기본원칙 조항은 이번 조사에서 검증하지 않음.

[원문](https://www.iso.org/standard/55979.html)

### S04 ISO 1101:2017 — Geometrical product specifications (GPS) — Geometrical tolerancing — Tolerances of form, orientation, location and run-out

국제표준화기구(ISO) / 2017

확인: 공식 카탈로그의 적용 범위·서지·발행/개정 상태 확인; 유료 규정 본문 미열람 / 공식 페이지 Abstract; General information; Life cycle

핵심: 형상·자세·위치·흔들림에 대한 기하공차 언어와 해석의 기반이다.; 개발 권고: 공차 종류·값·대상 특징·데이텀·수식어를 함께 저장한다.

적용: GD&T 입력/표시 구조와 지원 유형 선언

입력: 공차 프레임; 데이텀 연결; 수식어; 설계 요구 표준 판

한계: 공칭 CAD 형상만으로 완성품의 실제 평면도·위치도를 검사; 공구가 들어가면 모든 GD&T 만족

판본: 2017-02,4판 Published;2022 재확인. 카탈로그가 ISO16792를 통한 3D CAD 부착 표기도 설명함.

[원문](https://www.iso.org/standard/66777.html)

### S05 ISO 5459:2024 — Geometrical product specifications (GPS) — Geometrical tolerancing — Datums and datum systems

국제표준화기구(ISO) / 2024

확인: 공식 카탈로그의 적용 범위·서지·발행/개정 상태 확인; 유료 규정 본문 미열람 / 공식 페이지 Abstract; General information; Life cycle

핵심: 데이텀 및 데이텀계의 표시·이해·설정 연산을 다룬다. 검사 연산 자체는 적용 범위에서 분리된다.; 개발 권고: CAD 세계좌표, 가공 셋업 좌표, 설계 데이텀계를 구분한다.

적용: 데이텀 없는 위치공차 검토의 보류; 기준면·축·기준계 연결

입력: 데이텀 지정 면/특징; 순서·수식어; 좌표 변환; 설계 공차

한계: 평평한 면이면 자동으로 설계 데이텀 또는 안정한 고정면; 표준만으로 지그·클램프 설계 자동 검증

판본: 2024-10,3판 Published;2011판 Withdrawn. 최대·최소실체 데이텀 상세는 ISO2692의 별도 범위라고 카탈로그가 명시.

[원문](https://www.iso.org/standard/87855.html)

### S06 ISO 14405-1:2025 — Geometrical product specifications (GPS) — Dimensional tolerancing — Part 1: Linear sizes

국제표준화기구(ISO) / 2025

확인: 공식 카탈로그의 적용 범위·서지·발행/개정 상태 확인; 유료 규정 본문 미열람 / 공식 페이지 Abstract; General information; Life cycle

핵심: 원통·구·서로 마주보는 평행 평면의 선형 크기 표기를 다룬다.; 개발 권고: 직경·두께·평면 간격을 단순 길이 하나로 합치지 말고 치수의 대상과 정의를 남긴다.

적용: 치수 유형과 측정 연산 구분

입력: 특징의 유형; 치수 지정 방식; 수식어; 상하한과 단위

한계: 모든 최단거리·임의 바운딩박스가 설계 크기 치수; 선형 치수만으로 기능 적합성 추론

판본: 2025-08,3판 Published;2016판 Withdrawn. 초록 자체가 기능/용도와 치수 특성의 관계는 제공하지 않는다고 명시.

[원문](https://www.iso.org/standard/14405-1)

### S07 ISO 286-1:2010 / ISO 286-2:2010 — Geometrical product specifications (GPS) — ISO code system for tolerances on linear sizes — Part 1: Basis of tolerances, deviations and fits; Part 2: Tables of standard tolerance classes and limit deviations for holes and shafts

국제표준화기구(ISO) / 2010

확인: 공식 카탈로그의 적용 범위·서지·발행/개정 상태 확인; 유료 규정 본문 미열람; 실제 공차표 수치는 미열람 / 두 부의 Abstract·General information·Life cycle

핵심: 끼워맞춤·치수공차 등급과 편차 체계를 다루며2부에 구멍/축의 한계편차 표가 있다.; 개발 권고: H7 같은 명시 기호를 치수 구간·규격 판과 함께 해석하는 모듈 후보이다.

적용: 명시 끼워맞춤 요구의 구조화

입력: 공칭 치수; 구멍/축 구분; 명시 등급; 상대 부품 조건; 도면 지정 판

한계: H7이 보편적으로 드릴링만으로 가능한지 판정; 공칭 직경만으로 끼워맞춤 등급 자동 선택; 실제값을 확인하지 않은 공차표 복제

판본: 둘 다2판 Published.1부2010-04/2026 재확인;2부2010-06/90.60 검토 종료 상태. 두 부 모두2013 Cor1 연결 확인. 개정판 자동 치환 금지.

[원문](https://www.iso.org/standard/45975.html)

### S08 ISO 2768-1:1989 — General tolerances — Part 1: Tolerances for linear and angular dimensions without individual tolerance indications

국제표준화기구(ISO) / 1989

확인: 공식 카탈로그의 적용 범위·서지·발행/개정 상태 확인; 유료 규정 본문 미열람; 등급별 수치표 미열람 / 기존판 Abstract·Life cycle; 후속 ISO2768의 발행 단계

핵심: 개별 허용차가 표시되지 않은 선형·각도치수의 일반공차를 다룬다.; 개발 권고: 도면의 명시 인용·등급이 있을 때만 해당 판을 적용한다.

적용: 일반공차 입력의 출처·등급·판 관리

입력: 도면의 규격 인용; 등급; 치수 범위; 개별 공차의 우선 적용 여부

한계: 도면 없는 STEP에 일반공차 자동 부여; 2768의 모든 부가 이미 철회되었다는 주장; 일반공차 등급을 장비 성능 보증으로 사용

판본: 1989-11,1판 Published;2022 재확인 후 개정 예정. 후속 ISO2768은 확인 시60.00 Under publication이며 Published로 단정하지 않음. 후속판의 연도도 임의 부여하지 않음.

[원문](https://www.iso.org/standard/7748.html)

### S09 ISO 22081:2021 — Geometrical product specifications (GPS) — Geometrical tolerancing — General geometrical specifications and general size specifications

국제표준화기구(ISO) / 2021

확인: 공식 카탈로그의 적용 범위·서지·발행/개정 상태 확인; 유료 규정 본문 미열람 / 22081 Abstract·Life cycle; 2768-2 철회 및 대체 관계

핵심: 일반 기하·크기 요구의 정의와 해석 규칙이며 적용 대상과 제외 대상이 구분된다.; 개발 권고: 옛2768-2 등급과 새22081 요구를 동일한 수치표인 것처럼 자동 변환하지 않는다.

적용: 일반 기하공차의 적용 범위 모델링; 과거 인용과 현재판의 명시적 구분

입력: 명시 일반 요구; 대상 특징; 규격 판; 데이텀계 등 적용 정보

한계: 22081이 모든 누락공차를 채워주는 보편 공차표; 옛2768-mK의 K를 새표준으로 단순 이름 바꾸기

판본: 2021-02,1판 Published;2026 재확인. ISO2768-2:1989는2021-02-04 철회,22081로 대체. 부별 상태를 구분할 것.

[원문](https://www.iso.org/standard/72514.html)

### S10 ISO 21920-1/-2/-3:2021 — Geometrical product specifications (GPS) — Surface texture: Profile — Part 1: Indication of surface texture; Part 2: Terms, definitions and surface texture parameters; Part 3: Specification operators

국제표준화기구(ISO) / 2021

확인: 공식 카탈로그의 적용 범위·서지·발행/개정 상태 확인; 유료 규정 본문 미열람; 매개변수 계산식·필터 기본값·평가 길이 조항 미열람 / 세 부의 Abstract·General information·Life cycle

핵심: 표면거칠기는 요구 표시, 매개변수 정의, 평가 연산을 함께 다뤄야 한다.; 개발 권고: Ra 숫자 하나만 받아 형상의 좋고 나쁨을 판정하지 말고 대상 면·매개변수·평가 조건·근거를 기록한다.

적용: 표면 요구의 구조화와 기존 표준 판 관리

입력: 대상 면; Ra/Rz 등 명시 매개변수; 단위; 평가 조건; 표준 판; 해당 가공·측정 증거

한계: CAD의 매끈한 면이 실제 저거칠기 가공 보증; Ra3.2µm 등을 모든 절삭의 보편 가능 한계로 설정; 거칠기 요구가 입력되지 않았는데 통과 판정

판본: 세 부 모두2021-12,1판 Published/90.92 및 차기 CD.1부는1302:2002,2부는4287:1997 및13565-2/-3 등,3부는4288:1996을 대체.2부 영어·불어2022-06 수정판 표시.

[원문](https://www.iso.org/standard/72196.html)

### S11 ISO 13399-1:2006 — Cutting tool data representation and exchange — Part 1: Overview, fundamental principles and general information model

국제표준화기구(ISO) / 2006

확인: 공식 카탈로그의 적용 범위·서지·발행/개정 상태 확인; 유료 규정 본문 미열람 / 공식 페이지 Abstract; General information; Life cycle; Amendments; Corrigenda

핵심: 절삭 공구 데이터의 범주·관계·정보 교환 모델을 정의한다.; 개발 권고: 공구 본체, 날부, 섕크, 홀더와 조립 상태를 구분하여 실제 도달·충돌 검토에 연결한다. 개별 속성 코드는 관련 부·사전 확인 후 채택한다.

적용: 공구 카탈로그 데이터 표준화 확장

입력: 제조사 공구 데이터; 공구 조립/홀더 형상; 장착 상태; 속성 단위·정의

한계: 공구 전체 길이를 장착 돌출 길이로 치환; 공구 데이터 형식 준수가 절삭 안정성 보증; 1부만 보고 전체 사전 속성을 구현했다고 주장

판본: 2006-02,1판 Published;2021 재확인. Amd1:2010,Cor1:2008,Cor2:2011 존재. 수정 문서의 실제 규정 내용은 이번 조사에서 미열람.

[원문](https://www.iso.org/standard/36757.html)

### S12 ISO 230-2:2014 — Test code for machine tools — Part 2: Determination of accuracy and repeatability of positioning of numerically controlled axes

국제표준화기구(ISO) / 2014

확인: 공식 카탈로그의 적용 범위·서지·발행/개정 상태 확인; 유료 규정 본문 미열람 / 공식 페이지 Abstract; General information; Life cycle; Amendment1 존재

핵심: 직선·회전 개별축의 위치결정 정확도와 반복성을 직접 반복 측정하는 시험이다.; 개발 권고: 장비 능력 자료의 시험조건과 불확도를 저장하고 완성품 공차와 구분한다.

적용: 외부 장비 성능 성적서의 기록 항목 설계

입력: 장비별 시험성적서; 축·위치; 시험 환경; 반복 측정; 불확도

한계: 장비의 반복정밀도 숫자를 모든 형상의 가공공차로 복사; 기계 시험 없이 기하 계산으로 장비 정확도 검증

판본: 2014-05,4판 Published;2025 재확인. Amd1:2016 존재. 본문 시험 절차·수식 미열람.

[원문](https://www.iso.org/standard/55295.html)

### S13 ISO 10791-7:2020 — Test conditions for machining centres — Part 7: Accuracy of finished test pieces

국제표준화기구(ISO) / 2020

확인: 공식 카탈로그의 적용 범위·서지·발행/개정 상태 확인; 유료 규정 본문 미열람 / 공식 페이지 Abstract; General information; Life cycle

핵심: 정삭 조건의 표준 시험편을 이용해3~5동시축 머시닝센터의 절삭 정확도를 평가하는 범위다.; 개발 권고: 향후 외부 가공 시험 자료를 얻으면 시험편·셋업·조건을 함께 비교한다.

적용: 실물 절삭 정확도 검증 계획과 외부 시험편 자료 선별

입력: 정의된 실물 시험편; 장비·공구·셋업; 정삭 조건; 치수 측정과 불확도

한계: 임의 STEP 몇 개의 CAD 치수를 읽는 테스트가 해당 표준 절삭시험 통과; 이 표준의 시험공차를 모든 부품 허용공차로 전용

판본: 2020-01,3판 Published;2025 재확인,2014판 Withdrawn. 시험편 도면·수치 허용값 본문은 미열람.

[원문](https://www.iso.org/standard/73814.html)

### S14 ISO 14253-1:2017 — Geometrical product specifications (GPS) — Inspection by measurement of workpieces and measuring equipment — Part 1: Decision rules for verifying conformity or nonconformity with specifications

국제표준화기구(ISO) / 2017

확인: 공식 카탈로그의 적용 범위·서지·발행/개정 상태 확인; 유료 규정 본문 미열람 / 공식 페이지 Abstract; General information; Life cycle

핵심: 규격 경계 근처의 적합·부적합 판단에서 측정불확도를 고려하는 규칙의 범위다.; 개발 권고: 계산 오차, 측정불확도, 공정 변동, 설계 허용공차를 별도 필드로 보존한다.

적용: 검사 결과와 적합 판정의 분리 설계

입력: 실제 측정값; 규격 상하한; 측정불확도 모델; 합의된 의사결정 규칙

한계: 코드의1e-9mm 수치 비교대를 ISO 적합성 가드밴드로 설명; 공정 데이터 없이 제조 성공 확률 도출; 측정불확도와 실패 확률 동일시

판본: 2017-10,3판 Published;2023 재확인. 기본 확률값·가드밴드 산식 등 유료 세부 조항을 이 조사로 확정하지 않음.

[원문](https://www.iso.org/standard/70137.html)

### S15 ISO 15530-3:2011 — Geometrical product specifications (GPS) — Coordinate measuring machines (CMM): Technique for determining the uncertainty of measurement — Part 3: Use of calibrated workpieces or measurement standards

국제표준화기구(ISO) / 2011

확인: 공식 카탈로그의 적용 범위·서지·발행/개정 상태 확인; 유료 규정 본문 미열람 / 공식 페이지 Abstract; General information; Life cycle

핵심: 교정된 유사 형상·치수의 시편/표준을 이용하는 CMM 측정불확도 평가 접근을 다룬다.; 개발 권고: 외부 치수 측정 데이터를 받을 때 장비 명칭만 받지 말고 해당 측정 과업의 불확도 근거를 요구한다.

적용: 외부 측정 데이터의 신뢰성 평가 항목

입력: 실측 시편; 교정성적서; 측정 절차; 기하·치수 유사성; 측정 시스템

한계: CAD 기준형상 시험을 CMM 교정시험으로 간주; 실측자료 없이 측정불확도를 가정한 적합 판정

판본: 2011-10,1판 Published;2022 재확인.2004년 TS판 대체. 실험 절차 및 수식 세부 미열람.

[원문](https://www.iso.org/standard/53627.html)

### S16 ASME Y14.5-2018 (R2024) — Dimensioning and Tolerancing

American Society of Mechanical Engineers (ASME) / 2018

확인: 발행기관 공식 상품 페이지의 판·설명 열람; 유료 규정 본문 미열람 / 상품 제목2018(R2024); Description; 이전2009판 대체 안내

핵심: 도면·디지털 모델의 GD&T 기호, 해석과 요구 정의를 다루는 체계다.; 개발 권고: ISO GPS와 ASME의 적용 체계를 파일·도면 단위로 명시하고 서로 다른 기본규칙을 섞지 않는다.

적용: ASME 기반 고객 도면/PMI 지원 모듈의 근거

입력: 명시 적용 규격·판; 공차 프레임·데이텀·수식어; 도면/PMI

한계: 일부 기호가 같다는 이유로 ISO와 동일한 해석; 제조법별 가공 가능 수치 제공

판본: 공식 제품 페이지에서2018(R2024) 확인. 일부 ASME 주제 소개 페이지의2019 표기와 충돌하므로 규격 제품 페이지를 우선함. R2024는 재확인 연도이며 새2018 본문 개정 연도가 아님.

[원문](https://www.asme.org/codes-standards/find-codes-standards/y14-5-dimensioning-tolerancing)

### S17 ASME Y14.41-2026 — Digital Product Definition Data Practices

American Society of Mechanical Engineers (ASME) / 2026

확인: 공식 ASME 제품 페이지 및 ANSI 승인 공고 해당 항목 열람; 유료 규정 본문 미열람 / ASME 상품 제목2026·Description; ANSI Standards Action2026-01-30,Vol.57No.05,p.34:Final Actions

핵심: 디지털 제품 정의 데이터 세트의 작성·개정 요구를 다룬다.; 개발 권고: 모델·주석·관련 문서와 변경 이력을 묶어 관리하며, 형상만 읽은 결과를 완전한 제품 정의로 표시하지 않는다.

적용: 디지털 제품 정의 입력·추적성 설계

입력: 모델 및 주석; 관련 도면·문서; 개정 이력; 적용 데이터 정의 체계

한계: 2019판을 현행판으로 무조건 표기; AP242 형상 파일이 요구사항을 완전 전달한다고 가정

판본: 공식 제품 제목2026 확인. ANSI 공고는2019판 개정,최종 승인2026-01-21로 명시. ASME 페이지의 일부 재확인 템플릿 변수는 미치환 상태라 그 변수를 근거로 삼지 않음.

[원문](https://www.asme.org/codes-standards/find-codes-standards/y14-41-digital-product-definition-data-practices)

### S18 ISO 16792:2021 — Technical product documentation — Digital product definition data practices

국제표준화기구(ISO) / 2021

확인: 공식 카탈로그의 적용 범위·서지·발행/개정 상태 확인; 유료 규정 본문 미열람 / 공식 페이지 Abstract; General information; Life cycle; 후속 DIS의 개발 상태

핵심: 3D 모델 단독 또는 디지털2D도면과 함께 사용하는 제품 정의 데이터 작성·개정·표시를 다룬다.; 개발 권고: 형상, PMI, 도면 간 누락과 연결 상태를 사용자에게 보여준다.

적용: 3D/2D 복합 입력의 범위와 추적성 설계

입력: CAD/PMI/도면; 판·개정; 정보 간 연계

한계: 이 표준 하나로 GPS 공차 의미 전체를 해석; DIS 초안 문구를 발행된 의무 규정으로 표시

판본: 2021-04,3판 Published/90.92. 차기 ISO/DIS16792는4판 개발 중,40.20(2026-07-08)이며 발행판이 아님.

[원문](https://www.iso.org/standard/73871.html)

### G01 Topology Optimization with Accessibility Constraint for Multi-Axis Machining

Amir M. Mirzendehdel; Morad Behandish; Saigopal Nelaturi / 2020

확인: full_text_sections / arXiv v1 §2.1–2.1.5, 식 (1)–(19), §3 예제 조건, §4 결론; 특히 식 (5)의 Minkowski 합과 경로 연결성 한계

핵심: 부품·고정구와 절삭부·홀더를 함께 모델링해 무충돌 자세와 제거 가능한 영역을 계산한다. 공구 표면·방향을 이산 표본화하며, 무충돌 자세가 있어도 외부에서 연속 진입하는 경로가 없을 수 있다.

적용: 표본 레이 가시성을 유한 공구 접근성으로 확대해서는 안 된다는 근거. 공구·홀더·고정구와 방향별 접근성 확장 설계.

입력: 목표부품·소재 영역·고정구·절삭부·홀더 형상, 사용 가능 방향, 공간/방향 해상도

한계: 현재 레이 코드의 정확도, 실제 가공 성공, 공차·표면품질·절삭역학 보증. 논문의 완화값을 제조 허용오차로 사용하지 않는다.

판본: 현재 문헌 재감사 E07에 이미 인용. 공개본은 예시가 실제 산업 셋업이 아님을 Fig.1 설명에서 명시한다. DOI는 arXiv Related DOI와 출판사 ScienceDirect 서지(Computer-Aided Design 122, 102825, May 2020)로 교차확인했다.

[원문](https://arxiv.org/html/2002.07627)

### G02 Machining feature recognition based on deep neural networks to support tight integration with 3D CAD systems

Changmo Yeo; Byung Chul Kim; Sanguk Cheon; Jinwon Lee; Duhwan Mun / 2021

확인: full_text_sections / System construction and process; Feature descriptor / Base face; Feature descriptor definition, Tables 1–3

핵심: CAD 면의 기하·경계·인접 정보를 특징 기술자로 사용하여 결과를 원본 면에 연결한다. 원통은 한 면 또는 두 반원통 면이 될 수 있으며 연구는 두 반원통 표현을 가정한다.

적용: 내부 원통면을 완성된 구멍 개수로 세지 않기; 분할·교차 형상을 별도 검증; 안정적인 CAD 면 ID 유지.

입력: B-rep 면 종류·루프·인접면·연속성·오목/볼록·폭, 특징 라벨

한계: 임의 STEP에서 모든 홀·포켓 인식 보증, 특징 분류 확률을 가공 성공 확률로 사용.

판본: 현재 CNC_FACE_RECOGNITION/E08. Nature 직접 열기는 리다이렉트 실패였고 PMC의 공개 본문을 실제 읽었다. 이번에는 성능 수치를 재사용하지 않는다.

[원문](https://pmc.ncbi.nlm.nih.gov/articles/PMC8590007/)

### G03 BRepNet: A Topological Message Passing System for Solid Models

Joseph G. Lambourne; Karl D. D. Willis; Pradeep Kumar Jayaraman; Aditya Sanghi; Peter Meltzer; Hooman Shayani / 2021

확인: full_text_sections / arXiv v2 §3.1–3.5, 식 (2)–(3), §4 Fusion 360 Gallery segmentation dataset, §5.1–5.4

핵심: 면·모서리·방향 있는 coedge의 위상 순회를 신경망 연산에 사용한다. 대표 데이터의 라벨은 Extrude/Cut/Fillet/Chamfer/Revolve 등 CAD 작성 연산에서 나온다.

적용: 곡면과 위상 관계를 유지하는 학습 입력 설계, 원본 CAD 면에 예측을 연결하는 방법.

입력: B-rep face/edge/coedge, next/previous/mate 연결, 곡면 종류·면적·길이·오목볼록 속성, 학습 라벨

한계: CAD 작성 이력 분류를 절삭 공정계획·실제 제조가능성 정답으로 동일시하는 것.

판본: 추가 문헌. CVF 직접 페이지 열기는 실패했고 arXiv v2 방법·실험 절을 읽었다. 학습·재현 실행은 하지 않았다.

[원문](https://arxiv.org/html/2104.00706)

### G04 UV-Net: Learning from Boundary Representations

Pradeep Kumar Jayaraman; Aditya Sanghi; Joseph G. Lambourne; Karl D. D. Willis; Thomas Davies; Hooman Shayani; Nigel Morris / 2021

확인: full_text_sections / arXiv v2 §3.1–3.2 식 (1)–(3); §4.1 데이터셋; §4.2.2 분할 실험과 Table 2

핵심: 매개변수 UV 공간의 점·법선·트림 마스크와 면 인접 그래프를 결합한다. 합성 MFCAD 면 라벨과 ABC의 CAD 연산 추정 라벨은 서로 다른 평가 과제다.

적용: B-spline 등으로 표현이 바뀐 동일 기하의 학습 입력, 트림 영역 보존, 데이터셋별 검증 분리.

입력: 평가 가능한 매개곡면/곡선, UV 표본·법선·트림 마스크·인접성

한계: UV 표본만으로 작은 형상 전수 측정 보증. 높은 합성 데이터 분할 성능을 산업 CAD나 제조 성공률로 이전.

판본: 추가 문헌. 논문의 10×10 표본은 실험 설정이며 우리 툴의 정확도 보장 해상도로 채택하지 않는다. 현재 엔진의 해석 CAD 치수는 유지할 것을 권고.

[원문](https://arxiv.org/html/2006.10211)

### G05 Hierarchical CADNet: Learning from B-Reps for Machining Feature Recognition

Andrew R. Colligan; Trevor T. Robinson; Declan C. Nolan; Yang Hua; Weijuan Cao / 2022

확인: indexed_fulltext_excerpt_only / 출판사 검색 색인에서 §1, §5.1–5.2, §6.1–6.4, §7–8의 본문 발췌를 확인; 직접 HTML/PDF 열기는 실패

핵심: 면 인접 그래프와 표면 메시 그래프를 계층적으로 결합하며, 교차 특징을 늘린 MFCAD++를 제안한다. 기존 합성 데이터의 단순 소재·교차 제한·일부 통상 밀링 불가 형상을 지적한다.

적용: 교차 특징과 비평면을 포함하는 검증셋 필요성; 면 분류뿐 아니라 특징별 평가가 필요하다는 조사 근거.

입력: B-rep 인접성·모서리 볼록성·삼각형 표면 그래프, 특징 라벨

한계: 논문 전체 원문을 직접 확보했다는 주장, 데이터셋 모델이 모두 실제 가공 검증되었다는 주장.

판본: 이전 조사에서는 미확보 후보. 이번에도 직접 열기 403/실패이며 색인 발췌 수준을 보존한다. §6.3은 59,655개, 공식 데이터 페이지 G07은 59,665개로 불일치.

[원문](https://doi.org/10.1016/j.cad.2022.103226)

### G06 AAGNet: A graph neural network towards multi-task machining feature recognition

Hongjin Wu; Ruoshan Lei; Yibing Peng; Liang Gao / 2024

확인: author_repository_readme_only / 공식 README Abstract, Dataset, Training, Testing on feature-level recognition and localization performance, Citation

핵심: 의미 분할·특징 인스턴스 분할·바닥면 분할을 함께 다룬다. MFInstSeg는 인스턴스 라벨을 제공한다. 저자는 MFCAD++의 위상 오류를 정리해 원본보다 작은 학습/평가셋을 썼다고 명시한다.

적용: 동일 종류의 여러 포켓을 구분하는 인스턴스 평가; 원본/정제 데이터 및 제외 형상 기록.

입력: B-rep 기하 속성 인접 그래프(gAAG), 의미·인스턴스·바닥면 정답

한계: 출판사 논문 전부 정독·성능 재현, 신경망의 높은 확률을 가공 안전 확률로 표시.

판본: 추가 문헌. 출판사 직접 열기 실패. DOI·저자·권86/102661은 저자 저장소 서지 확인. Python/OCCT 환경도 현 프로젝트와 달라 재현 환경을 격리해야 한다.

[원문](https://github.com/whjdark/AAGNet)

### G07 MFCAD++ Dataset. Dataset for paper: Hierarchical CADNet: Learning from B-Reps for Machining Feature Recognition

Andrew Colligan; Trevor T. Robinson; Declan C. Nolan; Yang Hua / 2022

확인: dataset_metadata_only / 공식 데이터 설명, train/val/test 표기, licence, DOI, 배포 파일 정보

핵심: B-rep 가공 특징 라벨 데이터이며 공식 설명은 train 41,766 / val 8,950 / test 8,949, 총 59,665개를 적는다. 가공 결과 센서·불량 라벨 데이터가 아니다.

적용: 장비 없이 특징 인식기를 비교할 공개 기준셋 후보, 학습/평가 분리와 배포 라이선스 확인.

입력: 약 1.5GB 공개 배포 파일, CAD/특징 라벨/분할 목록

한계: 실물 성공 데이터 대체, 배포 파일 전체를 검증했다고 주장, 모든 생성 모델의 통상 밀링 가능성 보증.

판본: 다운로드·모델별 검사는 이번 문헌 조사에서 하지 않았다. CC BY 표기 확인. G05의 59,655와 다르므로 실제 파일 목록·해시·중복 수를 확보 후 확정해야 한다.

[원문](https://pure.qub.ac.uk/en/datasets/mfcad-dataset-dataset-for-paper-hierarchical-cadnet-learning-from/)

### G09 Building MRSEV models for CAM applications

Satyandra K. Gupta; Thomas R. Kramer; Dana S. Nau; William C. Regli; Guangming Zhang / 1994

확인: partial_pdf_pages / NIST PDF의 본문 p.121, p.123, p.127, p.129, p.131에 보이는 §3.3–3.6, §4.1; 실제 표시 쪽이 건너뛰어 완전본으로 취급하지 않음

핵심: 소재에서 제거할 체적을 여러 가능한 특징 집합으로 해석하고 평가한다. 제거 체적은 특징 부피 전체가 아니라 당시 소재와의 교집합이며 비절삭부 간섭도 구분한다.

적용: 원통면 하나를 유일한 드릴 작업으로 고정하지 않는 이유; 소재 입력과 대안 특징/작업 표현의 필요.

입력: 목표부품 P·소재 S, 특징의 위치/방향/형상, 공구 절삭부·비절삭부, 평가 함수

한계: 원본 전체가 확보됨, 모든 상호작용 특징 인식 보증, 1994 MRSEV를 현행 STEP 표준 판본으로 동일시.

판본: 추가 전통 문헌. 제공 PDF는 10쪽인데 서지는 pp.121–139이며 파싱된 쪽은 주로 홀수다. 스크린샷 요청도 시간 초과여서 누락 의심을 보존한다. 발췌 범위를 넘어 인용하지 않는다.

[원문](https://tsapps.nist.gov/publication/get_pdf.cfm?pub_id=821983)

### G10 A Complete Algorithm for Designing Planar Fixtures Using Modular Components

Randy C. Brost; Ken Goldberg / 1994

확인: author_html_excerpt / Problem Statement; Overview; Transforming the Input; Enumerating Locator Triplets; Enumerating Clamp Configurations; Introduction의 한계

핵심: 격자 위 3개 위치결정 요소와 1개 클램프로 평면 내 형상 구속을 제공하는 배치를 열거하고 접근 금지 영역과 간섭을 거른다. 접촉은 이상적인 강체·마찰 없는 점 조건이다.

적용: 고정구 충돌과 부품 구속을 별도 검사해야 함. 큰 바닥면만으로 고정 안정성을 판정하면 안 됨.

입력: 다각형 윤곽, 접근 금지 영역, 고정구 판의 격자, 위치결정 요소·클램프 형상/이동범위, 품질 기준

한계: 3차원 전체 고정 보증, 절삭력에 의한 변형·진동·허용 클램프 힘·공차 보증.

판본: 저자 HTML은 1994 ICRA판이라고 명시한다. 동일 제목의 1996 IEEE TRA 12(1):31–46, DOI 10.1109/70.481749 확장판 PDF는 최초 열기 이후 시간 초과였다. 두 판을 혼동하지 않는다.

[원문](https://goldberg.berkeley.edu/fixturing/fixture_algorithm.htm)

### G11 Automatic Spatial Planning for Machining Operations

Saigopal Nelaturi; Gregory Burton; Christian Fritz; Tolga Kurtoglu / 2015

확인: full_text_sections / 6쪽 PDF pp.2–3: §II–IV, 식 (1)–(4); PDF p.5: §VI의 고정구 논의

핵심: 공구·도달 가능한 작업공간으로 최대 제거 체적을 계산하고, 제거 체적 집합을 덮는 작업 순서를 검색한다. 셋업마다 고정구와 남은 소재 상태가 달라진다.

적용: 방향별 가시성 비율을 셋업 수로 바로 바꾸지 않기; 소재·공구 집합·중간 형상·고정구가 있는 계획 구조.

입력: 목표부품·초기소재·중간소재, 공구 형상, 기계의 도달 공간/회전, 고정구 후보

한계: 사용자가 임의 방향 하나를 고르면 실제 기계가 그 자세를 실현한다는 보증; 논문 실행시간의 현 구현 전이.

판본: 추가 문헌. 저자 PDF의 수식과 입력 조건을 읽었으며 자체 재현은 하지 않았다. 단순 가시성 점수와 제조 계획 비용을 분리할 근거.

[원문](https://www.cs.toronto.edu/~fritz/publications/nel-bur-fri-kur-case2015.pdf)

### G12 Shaft and Holder Modes reference

Autodesk Fusion Documentation / 발행연도 미표시

확인: official_full_page / 모드 5개 설명과 Detect tool length 절

핵심: 샤프트·홀더별 여유 거리와 실제 경로를 사용해 회피·삭제·길이 연장·실패 처리를 구분한다.

적용: 지름/돌출 길이 숫자만으로 충돌 검사를 완료할 수 없음; 실제 장착 형상과 경로 검토가 필요.

입력: 사용자 정의 샤프트·홀더, 간격, 가공 전략과 경로

한계: 이 문서의 예시 여유 5mm를 보편 안전 간격으로 적용. Fusion 결과를 직접 실행한 것처럼 보고.

판본: 현재 CNC_ACCESS_SCOPE/E05 관련. 발행연도·버전 번호 미표시이며 조회일을 기준으로 기록.

[원문](https://help.autodesk.com/cloudhelp/ENU/Fusion-CAM/files/GUIDD505C759-C325-4C99-BBDD-35FE39B3761F.htm)

### G13 Avoid collisions when drilling holes

Autodesk Fusion Documentation / 발행연도 미표시

확인: official_full_page / 본문 전체, Using collision avoidance for drilling 단계 1–9

핵심: 절삭 중 샤프트/홀더 충돌과 홀 사이 연결 이동 중 절삭부 충돌을 별도 설정으로 다룬다.

적용: 홀 치수 검사와 진입·복귀·다음 홀로의 이동 검사를 분리하는 결과 구조.

입력: 드릴·샤프트·홀더 형상, 홀 작업, 복귀 정책, 이동 간격, 경로

한계: 축이 일치하고 지름이 작으면 드릴 경로 전체가 안전하다는 판정.

판본: 현재 재감사 E06. 공식 도움말의 기능 설명이며 소프트웨어 실행 검증이나 산업 표준은 아니다.

[원문](https://help.autodesk.com/view/fusion360/ENU/?contextId=DRILLING-COLLISION-AVOIDANCE)

### G14 Automated Process Planning for Turning: A Feature-Free Approach

Morad Behandish; Saigopal Nelaturi; Chaman Singh Verma; Mats Allard / 2019

확인: full_text_sections / arXiv v3(2019-07-02) §3.1 Turning Axes와 turnability ratio; §3.2 Fixturing; §3.3 식 (1)–(2); §3.4 식 (3)

핵심: 부품을 한 축으로 회전시킨 포락 형상과 원형상 차이로 선삭 후보를 찾고, 이후 척·공구·기계 간섭을 포함해 실제 제거 가능한 체적을 좁힌다. 축대칭 정도와 공구별 선삭성은 다른 검토다.

적용: 절삭 확장의 범위를 밀링/드릴링과 선삭으로 명시적으로 분리; 원통 유무만으로 선삭 판정 금지.

입력: 후보 회전축·목표부품·봉 소재·척/고정 조건·인서트/홀더·기계 운동 범위

한계: 현재 툴의 선삭 기능이 구현됐다는 주장; turnability ratio를 가공 성공 확률로 표기.

판본: 추가 문헌. 비용이 제거 체적에 비례한다는 가정을 보편 견적식으로 가져오지 않는다. 현재 제품은 제한된 고정축 기하 검토이며 이 알고리즘 미구현.

[원문](https://arxiv.org/html/1905.09434)

### G15 Automated Process Planning for Hybrid Manufacturing

Morad Behandish; Saigopal Nelaturi; Johan de Kleer / 2018

확인: full_text_sections / arXiv v1(2018-05-18) §4 Definition 3; §5 식 (5)–(7); §6 Definition 5와 §9 예제의 가정

핵심: 기하학적 제거/적층 가능 영역을 만든 뒤 유한 Boolean 표현으로 대안 작업 순서를 찾는다. 예제의 비용·공차·공구 크기는 시연 가정이며 물리 검증은 별도 단계다.

적용: 현재 허용 범위인 적층·절삭의 공통 결과 표현과 대안 계획 연구. 형상 검토와 공정계획·물리 검증을 구분.

입력: 공정별 도구와 허용 운동, 영향 영역, 목표 형상, 공차/교환가능성 정의, 비용 모형

한계: 사출·프레스 확장 근거, 예제 수치를 보편 규칙으로 채택, 계획 식의 성립을 실제 제조 성공으로 간주.

판본: 추가 문헌. 적층+절삭의 후속 연구 참고이며 앱 기능 추가는 이번 조사에서 하지 않았다. 형상적 도달 영역과 실제 공구 경로를 혼동하지 않는다.

[원문](https://arxiv.org/html/1805.07035)

### G16 FeatureFox: Sample-Efficient Panoptic Graph Segmentation for Machining Feature Recognition in B-Rep 3D-CAD Models

Bertram Fuchs; Altay Kacan; Aaron Haag; Oliver Lohse / 2026

확인: full_text_sections / v1 §III 방법, §IV-C 평가 정의·Table II, §IV-F 산업 CAD 예제, §V 한계

핵심: 면 사이 경계 분류 후 연결성분으로 특징 인스턴스를 만들고 종류를 분류한다. 의미와 개체 분리를 함께 평가하는 PQ를 사용한다. 서로 떨어진 면들이 하나의 제조 특징인 경우를 처리하지 못함을 밝힌다.

적용: 1인 프로젝트의 가벼운 학습 기준선 후보; 면 정확도 외에 특징 개체별 품질 평가. 합성셋과 산업 CAD를 별도로 검증.

입력: B-rep 면/모서리 속성, 면 경계 라벨, 인스턴스와 종류 라벨

한계: 논문의 높은 PQ를 가공 성공 확률로 사용, 1개 공개 산업 예제의 정성 결과를 광범위 산업 검증으로 확대.

판본: 2026-04-29 v1의 공개 본문을 확인. 심사 완료는 확인하지 못했다. 저자가 회사 방침상 코드·데이터 비공개를 명시한다. 대규모 실부품 독립 평가와 분포 이동 검증이 먼저 필요하다.

[원문](https://arxiv.org/html/2604.26770v1)

### P01 Milling inside corners

Sandvik Coromant / 발행연도 미표시

확인: 공개 HTML 본문 / Considerations; Solution – limit the arc of engagement; Roughing; Finishing

핵심: 내부 코너에서 공구 물림이 커져 진동·날 손상이 생길 수 있다. 최종가공 안내의 공구 지름 D≤1.5R은 물림을 줄이는 공정 권고다.

적용: R과 선택 공구 반경 비교, 반경·공구·경로의 대안 제시.

입력: 내부 반경, 공구 형식·지름, 경로, 물림, 이송, 재료·장비.

한계: 1.5R을 보편 불가능 경계로 사용하거나, 기하 필요조건 D≤2R 충족을 실제 안정 가공으로 승격.

판본: 기존 M01/E01 재확인. 코드에 Sandvik 직접 인용은 없고 코너 기능의 외부 교차 근거다.

[원문](https://www.sandvik.coromant.com/en-us/knowledge/milling/milling-inside-corners)

### P02 Milling holes and cavities/pockets

Sandvik Coromant / 발행연도 미표시

확인: 공개 HTML 본문 / Hole milling: creating openings; Widening a hole or a cavity; How to open up / widen a cavity or pocket

핵심: 동일 공동도 드릴링·램핑·플런지·잔삭 등 경로 선택이 달라진다. 긴 돌출, 안정성, 칩 배출 조건에 따라 전략을 바꾼다.

적용: 포켓 깊이·폭 검토에 공구/가공법과 경로 조건을 연결하고 다른 방법을 제시.

입력: 공동과 원소재, 공구·절입, 재료, 냉각·칩 배출, 장비 방향·출력.

한계: 깊이비 하나로 모든 포켓을 가공 불가 판정; 특정 전략의 절입·속도 수치를 모든 엔드밀에 이식.

판본: 기존 M02/E02 재확인. 현재 앱은 이 문서의 경로 생성·절삭력 모델을 구현하지 않았다.

[원문](https://www.sandvik.coromant.com/en-us/knowledge/milling/milling-holes-cavities-pockets)

### P03 The Anatomy of an End Mill

Harvey Performance Company / 2017

확인: 공개 HTML 본문 / Cutter Diameter; Shank Diameter; Overall Length (OAL) & Length of Cut (LOC); Overall Reach/Length Below Shank (LBS)

핵심: 날 길이 LOC, 전장 OAL, 샹크 아래 길이 LBS는 서로 다르다. LBS는 감소 목부가 시작되는 곳부터 절삭 끝까지의 길이이며 목부 길이만을 뜻하지 않는다. 감소 목부는 깊은 포켓에서 샹크 마찰 회피에 관련된다.

적용: 공구 입력을 절삭부·목부·샹크·장착 돌출로 나누고 각 치수의 측정 시작점을 그림으로 표시.

입력: 공구 카탈로그 치수, 공구 어셈블리와 실제 장착 상태.

한계: LBS를 장착한 공구 끝~홀더 앞면 길이로 간주; 긴 LOC만으로 깊은 벽 가공성을 확정.

판본: 기존 E04, 코드 CNC_TOOL_DIMENSIONS. 게시 2017-12-10; 페이지 메타데이터에 2023-10-24 수정 시각도 노출.

[원문](https://www.harveyperformance.com/in-the-loupe/end-mill-anatomy/)

### P04 CNC Machining DFM Toolkit / Designing for Machined Parts

Protolabs / 발행연도 미표시

확인: 공개 HTML 본문 / Holes; Threading; Walls and Features; Radii; Navigating Critical Machining Advisories

핵심: 영국판은 홀을 엔드밀로 보간하는 자사 방식을 설명하며 6D보다 깊은 홀은 전용 드릴·양면 작업 등이 필요할 수 있다고 한다. 얇은 벽도 자사 공구셋 조건의 난이도 안내다.

적용: 위치별 설계 조치, 사용자 공구/서비스 프로필, 공급자 한계 표시.

입력: 실제 홀 깊이·지름, 공구·가공법, 소재, 공급자/지역 서비스 프로필.

한계: 6D를 드릴링 전체의 한계 또는 현재 원통면 축 구간/D의 보편 합격선으로 사용.

판본: 기존 M03/E03, 코드 CNC_GEOMETRY. 미국판과 문구/수치가 다르므로 국가·조회일을 보존한다.

[원문](https://www.protolabs.com/en-gb/resources/design-for-machining-toolkit/)

### P06 Drilling tips

Sandvik Coromant / 발행연도 미표시

확인: 공개 HTML 본문 / Internal/external coolant; Dry drilling; Chip control tips; Feeds and speeds; Hole quality; Material-specific tips

핵심: 칩 배출은 소재, 드릴/인서트 형상, 냉각 압력·유량과 절삭 조건에 의존한다. >3D 내부 냉각 선호 문구는 해당 드릴 적용 가이드의 권고다.

적용: 깊은 홀의 칩·냉각 확인 항목과 부족 입력 표시; 드릴 형식을 분리한 프로필.

입력: 진짜 드릴링 깊이, DC, 드릴 형식/팁/홈, 재료·경도, 이송·속도, 냉각 유량·압력.

한계: 3D가 넘으면 가공 불가; 깊이비만으로 칩 막힘 확률 산출; 드릴링 권고를 측면 밀링에 그대로 적용.

판본: 신규. 추정 URL /drilling/chip-control-and-cutting-fluid 는 열리지 않았고, 공식 Drilling 목차의 링크를 따라 이 실제 본문을 확인했다.

[원문](https://www.sandvik.coromant.com/en-us/knowledge/drilling/drilling-tips)

### P07 How to reduce vibration in milling

Sandvik Coromant / 발행연도 미표시

확인: 공개 HTML 본문 / Cutting tool; Holding tool; Silent Tools; Cutting data and tool path; Machine tool; Workpiece and its fixture

핵심: 진동에는 공구·홀더·장비·부품·고정구가 관여한다. 돌출이 공구 지름의 4배를 넘으면 진동 경향이 두드러질 수 있다는 안내는 감쇠 공구 선택의 맥락이다.

적용: 공구 돌출비와 지지 조건을 위험 요인으로 설명; 지름·길이만으로 안정성을 단정하지 않는 설계.

입력: 실제 돌출 길이·공구 지름, 홀더, 물림/경로, 회전수, 강성·감쇠, 고정 방향.

한계: 4D를 홀 깊이 또는 보편 채터 한계로 사용; 형상만으로 안정 RPM을 계산.

판본: 신규. 제품 홍보를 포함하는 제조사 권고로, 특정 제품의 성능 주장을 우리 도구의 검증값으로 채택하지 않는다.

[원문](https://www.sandvik.coromant.com/en-us/knowledge/milling/vibration)

### P08 How to do milling in different materials

Sandvik Coromant / 발행연도 미표시

확인: 공개 HTML 본문 / Milling steel; ferritic/martensitic and austenitic/duplex stainless steel; cast iron (선별)

핵심: 같은 강재 계열도 합금·열처리·조직에 따라 가공성이 달라진다. 버·구성인선·가공경화·열균열은 재료와 절삭 조건의 결합 문제다.

적용: 소재 등급·열처리·경도를 별도 입력하고 버/표면 문제의 발생 기전을 설명.

입력: 소재 표준·등급·상태·경도, 공구 재종/코팅, 절삭 속도·이송·절입·냉각.

한계: 재료명 한 단어를 성공률 또는 처짐으로 변환; 본문 속도·냉각 권고의 무조건 전용.

판본: 신규. 전체 소재별 절삭 데이터베이스를 구축하거나 모든 절을 수치 검증한 자료가 아니다.

[원문](https://www.sandvik.coromant.com/en-us/knowledge/milling/milling-different-materials)

### P09 Thread milling application tips

Sandvik Coromant / 발행연도 미표시

확인: 공개 HTML 본문 / Choice of cutting diameter; Thread milling tool path; Feed per tooth; Machine software feed; Number of passes; Thread milling hole sizes

핵심: 나사 밀링에서는 나사 지름·피치와 공구 지름에 따라 윤곽 오차와 실질 물림이 달라진다. 공구 지름≤나사 지름의 70%는 윤곽 편차 감소 권고다.

적용: 나사 규격·피치·유효 길이와 탭/나사밀의 가공법을 구분하고 원통면만으로 나사를 추정하지 않는 설계.

입력: 나사 규격, 피치, 내외부, 유효 길이, 바닥 여유, 공구 형식, 허용 윤곽 편차, 3축 동시 경로.

한계: 70%를 일반 엔드밀/드릴 지름 한계나 나사 체결강도 보증으로 사용.

판본: 신규. 현재 원통면 검토는 나사 가공 검토가 아니다.

[원문](https://www.sandvik.coromant.com/en-us/knowledge/threading/thread-milling/application-tips)

### P10 Advanced Tips for CNC Designs and Drawings [Webinar Recording]

Greg Paulsen; Steve Zimmerman; Xometry / 2024

확인: 공개 HTML 전사와 Q&A (영상 전체 시청 아님) / Q&A; common features versus cost-driving features; walls, corners, holes, threads, edge breaks and technical drawings

핵심: 박벽·특수공구·여러 작업·표면가공은 시간과 원가에 영향을 준다. 나사는 가공법과 바닥 여유를 함께 지정하며, 기능적 모따기와 단순 모서리 제거를 구분한다.

적용: 가공 불가/추가 작업/비용 요인을 분리하고 도면의 의도·공차·검사 조건을 요청하는 UX.

입력: 작업 종류, 공급자 공구셋, 도면·표면/모서리 요구, 수량, 셋업·공차·검사.

한계: 금속 벽 0.030 in, 드릴 깊이 10D, 나사 길이 2D 등의 서비스 권고를 보편 실패 임계값이나 체결강도 설계로 전용.

판본: 신규. 게시 2024-08-08, 갱신 2026-02-27. 발표자의 구어적 범용 표현보다 명시 조건과 표준을 우선한다.

[원문](https://www.xometry.com/resources/blog/advanced-tips-for-cnc-designs-and-drawings-webinar/)

### P11 Guide To Locating & Clamping Principles

Carr Lane Manufacturing / 발행연도 미표시

확인: 공개 HTML 본문 / Basic principles; External surfaces/3-2-1; Machining forces; Locating guidelines; Redundant location; Clamp positioning

핵심: 위치 결정과 눌러 고정하는 기능을 나누고, 절삭력 방향·지지점·고정 위치·칩 간섭을 고려한다. 약한 부분을 과도하게 조이면 변형될 수 있다.

적용: 셋업에 지지/클램프 영역·힘·기준면을 요구하고 공구 접근과 고정 안정성을 별도 검토.

입력: 기준면, 접촉영역, 구속·마찰, 고정력/순서, 절삭력, 원소재·부품 형상.

한계: 3-2-1 점이 있다는 이유만으로 마찰·강성·절삭력에 대한 고정 충분성 확정; 안내의 '12 freedoms'를 12 독립 강체 자유도로 설명.

판본: 신규. 원문은 6 자유도의 양·음 방향을 따로 세어 12라고 서술한다. 독립 자유도 설명과 구분 필요.

[원문](https://www.carrlane.com/engineering-resources/fixture-design-principles/locating-clamping-principles)

### P12 Analytical Prediction of Stability Lobes in Milling

Yusuf Altintas; Erhan Budak / 1995

확인: 저자 업로드 페이지의 서지·초록 확인; PDF 페이지 존재만 확인, 본문 수식 미검토 / Abstract (저자 Yusuf Altintas 업로드 ResearchGate 페이지)

핵심: 채터 안정성 계산에 구조 전달함수, 절삭력 계수, 반경 방향 물림, 날 수가 필요하다고 초록이 명시한다.

적용: 지름·길이만으로 채터 합격을 판정하지 않고 FRF와 공정 조건을 요구할 연구 근거.

입력: 접촉부 동특성/FRF, 절삭력 계수, 물림, 날 수, RPM·축 절입.

한계: 수식 구현 완료, 외부 FRF 없이 특정 RPM/절입의 안정성을 보증.

판본: 신규. CIRP Annals 44(1), 357–362. https://www.researchgate.net/publication/223283875_Analytical_Prediction_of_Stability_Lobes_in_Milling 의 저자 업로드 초록을 읽었다. 웹 PDF 6쪽 인식/스크린샷 호출은 실제 수식 판독 증거로 세지 않았고 직접 다운로드는 403.

[원문](https://doi.org/10.1016/S0007-8506(07)62342-7)

### P13 Analytical models for high performance milling. Part I: Cutting forces, structural deformations and tolerance integrity

Erhan Budak / 2006

확인: 저자 소속대학 저장소 서지·초록; 원문 PDF 등록 사용자 제한 / Abstract; official bibliographic record

핵심: 절삭력, 공구·부품 처짐, 형상오차 모델로 공정 변수와 품질·장비 제약을 함께 검토하는 연구다.

적용: 박벽/공구 처짐을 힘-강성-공차 문제로 정의하고 기하 규칙과 분리할 연구 방향.

입력: 절삭력 계수 또는 힘, 실제 공구/부품 강성, 절입·이송·속도, 요구 공차.

한계: 초록만으로 세부 수식·계수의 정당성 검증; 재료/하중 없는 일반 처짐값 산출.

판본: 신규. International Journal of Machine Tools and Manufacture 46(12–13), 1478–1488. 출판사 직접 열기도 실패하여 초록 수준으로 보존.

[원문](https://research.sabanciuniv.edu/id/eprint/191/)

### P14 On-Machine Estimation of Workholding State for Thin-Walled Parts

Jingkai Zeng; Koji Teramoto; Hiroki Matsumoto / 2021

확인: 공개 원문 PDF, 본문·표와 도면 선별 시각 확인 / §2–5; pp. 861–866; p.864 Tables 1–2, Fig.9 시각 확인

핵심: 국소 변형률 측정과 접촉 FEM으로 고정력·변형을 추정한다. A2017 시험에서 고정 순서에 따라 변형이 달라졌다. 고정력 추정 평균 편차는 10% 미만이나 변형 추정 평균 차이는 약 22%로, 출력 지표마다 검증 성능이 다르다.

적용: 박벽 형상 하나로 변형을 확정할 수 없고 접촉·고정력·순서·물성·측정이 필요하다는 근거.

입력: CAD·재료 탄성, 접촉/마찰, 클램프 모델·힘·순서, 국소 변형률 측정, FEM.

한계: 본문의 마찰 0.1 또는 500/200 N을 모든 고정구 기본값으로 사용; 사례의 추정 오차를 범용 정확도나 성공 확률로 표시.

판본: 신규. International Journal of Automation Technology 15(6), 860–867. PDF 본문 8쪽. 원문 p.864와 그림을 렌더해 표의 문자인식 깨짐을 시각 대조했다.

[원문](https://www.jstage.jst.go.jp/article/ijat/15/6/15_860/_pdf)

### P15 On-Machine Estimation of Workpiece Deformation for Thin-Structured Parts Machining

Koji Teramoto / 2017

확인: 공개 원문 PDF, 수식·실험 절과 도면 선별 시각 확인 / §3 Eq.(1) F=KU; §4–6; pp.979–983; p.981 Figs.3–7 시각 확인

핵심: 탄성 FEM의 경계조건을 국소 변형률로 추정하고 다점/바이스 고정 사례와 비교한다. 소변형 선형 탄성 가정이며 실제 고정 변화에 맞추는 보정이 핵심이다.

적용: 벽 두께 기준만으로 공차를 보장할 수 없고 지지·하중·물성·허용 변형이 필요하다는 근거.

입력: 형상·물성, 지지/하중 후보, 접촉 가정, 변형률 측정점, 허용 치수 오차.

한계: 측정 없이 현재 앱에서 고정 변형을 검증했다는 주장; 정적 고정 변형을 절삭 중 채터 모델로 사용.

판본: 신규. International Journal of Automation Technology 11(6), 978–983. 바이스 사례 알루미늄; 다점 힘 50/50/50 N과 30/50/40 N은 사례값.

[원문](https://www.jstage.jst.go.jp/article/ijat/11/6/11_978/_pdf/-char/en)

### P16 Machining Cycle Time Prediction: Data-driven Modelling of Machine Tool Feedrate Behavior with Neural Networks

Chao Sun; Javier Dominguez-Caballero; Rob Ward; Sabino Ayvar-Soberanis; David Curtis / 2021

확인: 공개 원문 PDF 20쪽; 방법·시험·표 확인 (게시된 프리프린트 기준) / §2 입력/학습; §3 실험; §4 Tables 2–4; §5 한계; PDF p.17 Table 4 시각 확인

핵심: NC 명령 이송과 실제 이송은 다를 수 있다. 장비에서 얻은 이송 자료로 시간 예측을 학습했으며 새 경로 상황에서는 오차가 커지는 사례도 설명한다.

적용: 원가에 필요한 가공시간은 형상 체적만으로 확정하지 않고 경로·장비 거동·셋업 비용과 구분.

입력: NC 경로, 명령 이송·가속도·경로 각도, 실제 이송/시간, 장비·제어기, 조건 분리 평가.

한계: 논문의 90% 이상 시간 예측 정확도를 제조 성공 확률로 사용; 같은 부품 8포켓 결과를 모든 장비/부품 일반화 성능으로 표시.

판본: 신규. v2 2021-12-02. Starrag Scharmann Ecospeed 2538/Siemens 840D 사례. 학습에 사용한 포켓도 전체 결과표에 포함된다. 저널 출판판 동일성은 이번에 검증하지 않았다.

[원문](https://arxiv.org/abs/2106.09719v2)
