from pathlib import Path
import json, sys, csv, hashlib, zipfile
OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[1]
sys.path.insert(0,str(ROOT/'study/versions/AM-DFM_v2_6/dfm2'))
from src.core.model_loader import load_model
from src.processes.additive import AMRuleEngine
from src.core.reproducibility import save_new_json

rows=json.loads((OUT/'summary.json').read_text(encoding='utf-8'))
for r in rows:
    n=int(r['stem'][:2])
    if 1<=n<=9:
        target=next(x for x in r['rules'] if x['rule_name']==r['target'])
        assert target['status']=='warn',(r['stem'],target)
    if n>=15:
        key=r['target'].removeprefix('layer_')
        assert next(c for c in r['layers']['checks'] if c.get('key')==key)['status']=='risk'
    assert r['mesh_ok']==(n!=14)
    if n!=14: assert r['layers']['status']=='complete'

# Same cavity, explicit alternate process policy; never conflate with FDM.
p=OUT/'13_trapped_cavity.stl'
result=AMRuleEngine().evaluate(load_model(str(p),unit='mm')['mesh'],process_type='SLA')
assert any(g.name=='갇힌 체적' and not g.passed for g in result.gates)
save_new_json(OUT/'13_trapped_cavity_SLA_policy.json',result)

text='''# 규칙별 AM-DFM 시연 형상 — 2026-09-12

직접 만든 STL 18개: 정상 대조 1개, 점수 규칙 10개용 형상, 추가 게이트 4개용 형상, 단면 지표 3개용 형상이다. 수평 구멍은 미구현으로 N/A이며, 밀폐 공동은 FDM에서 차단하지 않는다. 따라서 모든 파일을 일괄적으로 “위반 판정 성공”이라고 설명하지 않는다.

## 공통 설정

- 단위 **mm**, 공정 **FDM**, 적층 방향 **+Z**, 장비 **250×250×250mm**.
- 단면 층 높이 **0.2mm**, 선폭 **0.4mm**, 임계각 **45°**. 회전·크기 변경 없이 원본 모드로 연다.
- 06 파일만 **최소 특징 검사 켜기**, 08 파일만 **두께 변화 검사 켜기**. 다른 파일은 두 옵션을 끈 기본값으로 검증했다.
- 13 파일의 공동 차단 정책을 추가로 보여줄 때만 **SLA**로 바꾼다. 아래 기본 표는 FDM 결과다.
- 메시 손상 시연 14를 제외한 17개 모두 내보낸 STL을 다시 읽었을 때 메시 진단과 엔진 메시 게이트를 통과하고, 요청 단면을 모두 계산했다. 14는 의도대로 메시 실패 및 단면 미확정이다.

## 규칙별 실제 결과

경고(warn)는 현재 규칙 기준 초과/미달, blocked는 프로필 게이트 제한, invalid_input은 입력 문제를 뜻한다. eligible은 점수 산출 대상이라는 뜻이며 모든 규칙 통과나 출력 성공을 뜻하지 않는다.

| 파일 | 목적과 치수 | 목표 항목의 이번 결과 | 추가 설정 |
|---|---|---|---|
'''
csvrows=[]
for r in rows:
    n=int(r['stem'][:2]); target=r['target']
    if 1<=n<=10:
        a=next(v for v in r['rules'] if v['rule_name']==target)
        desc=f"{a['status']}: {a['value']} {a['unit']} / 기준 {a['threshold']}"
        if n==10: desc='N/A — 구멍은 있지만 자동 인식·위반 판정 미구현'
    elif n==0: desc='기본 활성 점수 규칙 모두 pass'
    elif n in [11,12,14]:
        label={11:'최소 벽두께',12:'빌드 볼륨',14:'메시 무결성'}[n]
        g=next(g for g in r['gates'] if g['name']==label)
        assert g['passed'] is False
        desc=f"{label} {g['status']}; {r['status']}"
    elif n==13: desc='FDM: 공동 검출, 게이트 pass(경고 정책); SLA 별도 실행: 공동 게이트 fail'
    else:
        a=next(c for c in r['layers']['checks'] if c.get('key')==target.removeprefix('layer_'))
        desc=f"risk: {a['risk_layers']}개 층 / 총 {r['layers']['expected_layers']}개 층"
    opt='최소 특징 켜기' if n==6 else '두께 변화 켜기' if n==8 else '기본값'
    text+=f"| [{r['stem']}.stl]({r['stem']}.stl) | {r['title']}: {r['design']} | {desc} | {opt} |\n"
    others=', '.join(x['label'] for x in r['rules'] if x['status'] in ['warn','fail'] and x['rule_name']!=target)
    csvrows.append([r['stem']+'.stl',r['title'],r['design'],desc,opt,r['status'],others])

text+='''
## 시연에서 함께 설명할 점

- **하나의 목표 규칙을 보여주는 모델이지, 반드시 그 규칙만 반응하는 모델은 아니다.** 01 얇은 판은 종횡비도 경고, 02 오버행은 서포트 비율도 경고, 06 작은 특징은 권장 벽두께도 경고, 07 기울어진 판은 오버행도 경고다. 실제 형상에서는 이런 위험이 연결돼 있다. `결과표.csv`에 동반 점수 경고를 기록했다.
- 11은 권장 벽두께와 종횡비에도 경고가 생긴다. 12는 장비 수용 게이트와 장비 여유 규칙이 함께 반응한다. 15와 17은 3D 최소 벽두께 게이트에서도 제한되지만 단면 결과를 별도로 제공한다.
- 17의 0.16mm 돌출판은 **Z방향으로 얇다**. 평면 안에서는 넓으므로 이번 단면 얇은 특징 지표는 clear이고, 한 층에만 나타나는 지표는 risk다. Z=5.1mm 근처를 보여준다. 적층 높이·시작 평면을 바꾸면 검출이 달라질 수 있다.
- 16 브리지는 **Z=10.1mm**, 15 얇은 벽은 **Z=5.1mm** 부근에서 목표 표시를 살펴본다. 브리지 후보는 처짐이나 실제 브리지 출력 가능 길이를 확정하는 결과가 아니다.
- 07은 최저점이 플레이트에 닿도록 옮긴 경사 판이다. 실물 출력 시 접착과 지지까지 검증한 형상이 아니다.
- 13 밀폐 공동은 FDM에서는 경고 정책으로 통과한다. 동일 파일의 SLA 추가 실행에서는 공동 게이트 fail을 확인했다. 이 차이는 코드의 공정별 정책 시연이며 SLA 실증을 뜻하지 않는다. STL의 내부 껍질 방향을 임의로 뒤집거나 공동을 메우지 않는다.
- 06 복셀 소실량은 실제 출력에서 사라질 체적 비율이 아니다. 08 두께비는 표본 레이 기반 보조 지표이며 실제 국소 두께비의 정확한 계측을 보장하지 않는다. 두 옵션은 기본 비활성이다.
- 10은 현 기능의 한계를 정직하게 설명하는 파일이다. 구멍 주위에서 다른 지표가 반응하더라도 수평 구멍 규칙이 검출했다고 설명하지 않는다.

## 미팅 순서 제안

전체 18개를 모두 실시간으로 돌리기보다 00 대조 → 01 권장 벽 → 11 최소 벽 게이트 → 03 서포트 → 09 간격 → 16 브리지 단면 → 17 한 층 특징을 먼저 보여준다. 나머지는 해당 기능 질문에 대비해 준비한다. 14 메시 손상은 마지막에 입력 문제와 제조성 위험의 차이를 설명할 때 쓴다.

## 검증 범위와 재현

원본 애플리케이션 소스를 바꾸지 않고 로컬 v2.6 분석 엔진을 실제 실행했다. 각 STL 옆 JSON은 해당 실행의 상세 결과, runtime.json은 환경과 원본 소스 SHA, summary.json은 요약이다. 파일 체크섬은 manifest.json에 있다. 13의 별도 SLA 결과는 이름에 SLA_policy가 붙은 JSON이다.

모델 치수는 현재 코드의 각 규칙을 시연하기 위해 선택한 값이다. 문헌이 규정한 공인 시험편·보편적 제조 한계가 아니다. 높은 점수·메시 통과·단면 완료를 출력 성공으로 해석하지 않는다. 메시 검사는 자기교차 전수 증명이 아니다. 실물 출력, 슬라이서 경로 및 브라우저 UI 조작은 이번 검증 범위 밖이다. 촬영 전에 현재 사용 중인 앱에서 위 설정으로 확인한다.

생성기는 build_rule_models.py다. 기존 실행 결과를 보존하므로 새로 생성하려면 deliverables 아래 새 폴더에 생성기를 복사해 실행한다. study/.venv 환경의 trimesh, manifold3d 및 프로젝트 의존성이 필요하다. 초기 실행에서는 생성기 콘솔 출력의 속성명 오류를 수정한 뒤 전체 18개를 완료했다. 이는 애플리케이션 코드 변경이나 형상 판정 실패가 아니다.
'''
(OUT/'사용안내.md').write_text(text,encoding='utf-8')
with (OUT/'결과표.csv').open('w',encoding='utf-8-sig',newline='') as f:
    w=csv.writer(f);w.writerow(['파일','목적','치수','목표 결과','설정','평가 상태','동반 점수 경고']);w.writerows(csvrows)
manifest={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in OUT.iterdir() if p.is_file() and p.suffix=='.stl'}
save_new_json(OUT/'manifest.json',manifest)
zip_path=OUT.parent/'AM_DFM_rule_models_18.zip'
with zipfile.ZipFile(zip_path,'x',zipfile.ZIP_DEFLATED) as z:
    for p in sorted(OUT.iterdir()):
        if p.is_file(): z.write(p,'AM_DFM_rule_models/'+p.name)
with zipfile.ZipFile(zip_path) as z:
    assert z.testzip() is None
    assert sum(n.endswith('.stl') for n in z.namelist())==18
print('Verified 18 STL files; 9/9 implemented score targets warn; 3/3 layer targets risk; ZIP OK')
