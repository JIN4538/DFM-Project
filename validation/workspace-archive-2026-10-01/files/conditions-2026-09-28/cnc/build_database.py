"""Curate checked manufacturer facts; not a crawler that promotes unknown values."""
from pathlib import Path
import json
import re

WORK = Path(__file__).parent
REPO = WORK.parents[2] / 'DFM-Project'
SOURCES, PROFILES = [], []

def source(id_, title, publisher, url, locator, revision='웹 표에 별도 판본 없음; 2026-09-28 조회', limitations=None):
    SOURCES.append(dict(id=id_, title=title, publisher=publisher, url=url,
        accessed='2026-09-28', locator=locator, revision=revision,
        verification='primary_source_checked', limitations=limitations or []))
    return id_

def parameter(value, unit, kind, source_id, locator, conditions=(), automatic=False):
    return dict(value=value, unit=unit, kind=kind, source_ids=[source_id], locator=locator,
                conditions=list(conditions), application='automatic' if automatic else 'reference_only')

def profile(id_, label, category, source_id, params, conditions=(), limitations=(), machine='미확정', material='미확정'):
    obj=dict(id=id_,label=label,process='CNC',category=category,machine=machine,material=material,
             conditions=list(conditions),limitations=list(limitations),source_ids=[source_id],parameters=params,
             physical_validation='not_validated_by_project')
    PROFILES.append(obj)
    return obj

def datron_value(text, name):
    matched=re.search(re.escape(name)+r'\s*\|\s*([0-9.]+)(?:\s*mm)?\s*\|',text)
    if not matched:
        raise ValueError(f'Missing DATRON field {name}')
    return float(matched.group(1))

# Independently transcribed nominal dimensions, then compared to downloaded SKU
# tables or the exact SKU row of the official manufacturer's variation table.
datron=[
    ('0068010E',1,4,3,38,1), ('0068020E',2,8,3,40,1),
    ('0068030E',3,10,3,40,1), ('0068434E',4,10,6,50,1),
    ('0068435E',5,12,6,50,1), ('0068460E',6,14,6,50,1),
    # 0068080E quarantined: exact SKU says .8 mm while family row says 8 mm.
    ('0068470E',10,20,10,60,1),
    ('0068460L',6,20,6,60,1), ('0068434F',4,20,6,58,1),
    ('0068470L',10,40,10,100,1), ('0068493L',3,8,6,50,1),
    ('0078010K',1,2,3,38,2), ('0078018S',1.8,1.5,3,38,2),
    ('0078030K',3,7,3,38,2),
]
single_url='https://shop.datron.com/product/single-flute-end-mills/0068460E/'
steel_url='https://shop.datron.com/product/steel-machining-double-flute-end-mill/0078030K/'
single_variants=source('cnc-datron-single-variants','DATRON Single Flute End Mills — SKU variation table','DATRON',single_url,'Available Options; 각 SKU 행과 D1 / D2 / D3 / L1 / L2 / L3 / Flutes 열 순서',limitations=['대상은 제조사에 명시된 알루미늄·황동·플라스틱용 제품군이며 강철은 권장하지 않음.'])
steel_variants=source('cnc-datron-steel-variants','DATRON Steel Machining Double Flute End Mill — SKU variation table','DATRON',steel_url,'Available Options; 각 SKU 행과 D1 / D2 / L1 / L2 / Flutes / Coating 열 순서',limitations=['강 가공용 X.CEED 코팅 제품군 설명이며 모든 강종·경도에 대한 적합 보증이 아님.'])
catalog=source('cnc-datron-tools-catalog','DATRON Tools — dimensional drawings and SKU tables','DATRON',
    'https://www.datron.de/fileadmin/dokumente/broschueren/tools/english/DATRON_Tools_withoutPrices_Cat_EN.pdf',
    'PDF 10, 11, 17쪽 (인쇄 18–20, 33쪽); 단날, toric cut, 강 가공용 2날의 치수 도해와 SKU 표',
    '별도 판본 번호 미확인; PDF metadata CreationDate 2026-03-12 (발행일로 단정하지 않음)',
    ['L2는 도해의 절삭부 치수이며 권장 절입량이나 실제 장착 길이가 아님.'])
for sku,d,l2,shank,oal,flutes in datron:
    issteel=flutes==2
    local=WORK/f'datron-{sku}.txt'
    if local.exists():
        text=local.read_text(encoding='utf-8').split('Additional Information',1)[1]
        assert [datron_value(text,f) for f in ['Cutting Diameter (D1)','Cutting Depth (L2)','Shank (D2)','Length (L1)','Flutes']]==[d,l2,shank,oal,flutes],sku
        url=f'https://shop.datron.com/product/{"steel-machining-double-flute-end-mill" if issteel else "single-flute-end-mills"}/{sku}/'
        sid=source('cnc-datron-'+sku.lower(),f'DATRON {sku} — nominal tool dimensions','DATRON',url,'Additional Information; 선택된 SKU '+sku)
        locator='SKU '+sku+'; Additional Information'
    else:
        sid=steel_variants if issteel else single_variants
        text=(WORK/('datron-0078030K.txt' if issteel else 'datron-0068460E.txt')).read_text(encoding='utf-8')
        start=text.index('Available Options')
        text=text[start:]
        # Match the exact ordered variant dimensions, not the selectable option list.
        fmt=lambda v:f'{v:g}'
        if issteel:
            row=' / '.join([fmt(d)+' mm',fmt(shank)+' mm',fmt(oal)+' mm',fmt(l2)+' mm',str(flutes),'X.CEED'])
        else:
            d3,l3=('2.7 mm','21 mm') if sku=='0068493L' else ('-','-')
            row=' / '.join([fmt(d)+' mm',fmt(shank)+' mm',d3,fmt(oal)+' mm',fmt(l2)+' mm',l3,str(flutes)])
        assert row in text and re.search(re.escape(row)+r'\s*SKU:\s*'+sku,text), (sku,row)
        locator='Available Options; SKU '+sku+' 행'
    conditions=['정확한 SKU '+sku+'의 미사용 공구 명목 치수', '선택한 공구로 고정축 엔드밀 기하 비교를 수행할 때 사용']
    target='강 가공용 X.CEED 코팅; 강종·경도·가공 조건 추가 확인' if issteel else '제조사 대상: 알루미늄·황동·플라스틱; 강철에는 권장하지 않음'
    params={
        'tool_diameter_mm':parameter(d,'mm','tool_specification',sid,locator+'; Cutting Diameter (D1)',conditions,True),
        'flute_length_mm':parameter(l2,'mm','tool_specification',sid,locator+'; Cutting Depth (L2)',conditions,True),
        'shank_diameter_mm':parameter(shank,'mm','tool_specification',sid,locator+'; Shank (D2)'),
        'overall_length_mm':parameter(oal,'mm','tool_specification',sid,locator+'; Length (L1)'),
        'flute_count':parameter(flutes,'count','tool_specification',sid,locator+'; Flutes'),
        'catalog_material_application':parameter(target,'text','manufacturer_guidance',sid,'제품군 Description; 소재별 절삭 데이터 별도 확인'),
    }
    if sku=='0068493L':
        params['catalog_l3_mm']=parameter(21,'mm','tool_specification',sid,locator+'; L3',['카탈로그 L3이며 실제 홀더 장착 도달 길이가 아님'])
        params['neck_diameter_mm']=parameter(2.7,'mm','tool_specification',sid,locator+'; D3')
        params['tool_end_geometry']=parameter('toric cut','text','tool_specification',catalog,'PDF 11쪽, 인쇄 20쪽; Single Flute End Mill with toric cut')
    if issteel:
        params['coating']=parameter('X.CEED','text','tool_specification',sid,locator+'; Coating')
    obj=profile('cnc-datron-'+sku.lower(),f'DATRON {sku} · Ø{d:g} / 날 {l2:g} mm · {flutes}날'+(' · toric cut' if sku=='0068493L' else ''),'tool',sid,params,
        conditions+[target], ['날 길이는 절삭부 치수이며 전 깊이 일괄 절삭 권고가 아님.',
        '실제 장착 도달 길이 reach_mm는 미확정. 전체 길이 L1 또는 L3로 대체하지 않음.',
        '날/몸통/홀더 충돌·절삭력·처짐·채터·냉각·칩 배출은 이 프로필만으로 검증되지 않음.',
        '소재군 설명은 공작물의 실제 재료 선택이나 개별 강종 적합 판정을 대신하지 않음.'])
    obj['source_ids'].append(catalog)
    for field in ('tool_diameter_mm','flute_length_mm'):
        params[field]['source_ids'].append(catalog)
        page='17쪽 (인쇄 33쪽)' if issteel else ('11쪽 (인쇄 20쪽)' if sku=='0068493L' else '10쪽 (인쇄 18–19쪽)')
        params[field]['locator']+='; 카탈로그 PDF '+page+' SKU/도해 교차 확인'
    if sku=='0068493L':
        obj['limitations'].append('toric cut 끝날 형상은 현재 원통 공구 폭/깊이 비교에서 모델링하지 않음. 바닥 형상·잔삭 여부 별도 확인.')

for sku,d,l2,l3,shank,oal in [
    ('677722',1,3,5,3,63),('677745',2,6,10,3,63),('677761',4,12,20,4,63),
    ('677666',6,18,48,6,100),('677670',8,24,64,8,100)]:
    text=(WORK/f'harvey-{sku}.txt').read_text(encoding='utf-8').split('TOOL DIMENSIONS',1)[1]
    fields=['Cutter Diameter','Length of Cut','Overall Reach','Shank Diameter','Overall Length']
    for field,value in zip(fields,[d,l2,l3,shank,oal]):
        m=re.search(re.escape(field)+r'\s+([\d.]+)\s+mm',text)
        assert m and float(m.group(1))==value,(sku,field)
    sid=source('cnc-harvey-'+sku,f'Harvey Tool {sku} — Square, Long Reach, Standard Flute, Metric','Harvey Tool',
        f'https://www.harveytool.com/products/tool-details-{sku}','TOOL DIMENSIONS; Catalog Page 33',
        limitations=['제조사 명목 치수. 재료 아이콘의 전체 텍스트를 각 소재에 대한 적합 승인으로 해석하지 않음.'])
    conditions=['정확한 공구 번호 '+sku+'; 무코팅 UN; 4날 Square; 초경 제품군','고정축 엔드밀 기하 비교용 명목 치수']
    params={key:parameter(value,'mm','tool_specification',sid,'TOOL DIMENSIONS; '+field,conditions,key in ('tool_diameter_mm','flute_length_mm'))
        for key,field,value in zip(['tool_diameter_mm','flute_length_mm','catalog_overall_reach_mm','shank_diameter_mm','overall_length_mm'],fields,[d,l2,l3,shank,oal])}
    params['flute_count']=parameter(4,'count','tool_specification',sid,'TOOL DIMENSIONS; Flutes')
    params['coating']=parameter('UN','text','tool_specification',sid,'TOOL DIMENSIONS; Coating')
    profile('cnc-harvey-'+sku,f'Harvey {sku} · Ø{d:g} / 날 {l2:g} mm · 4날','tool',sid,params,conditions,
        ['카탈로그 Overall Reach L3는 날 끝부터 목부 끝까지 치수이며 장착된 홀더 끝까지의 길이 reach_mm가 아님.',
         '날 길이는 명목 절삭부 길이이며 허용 절입량·안정성·공구 수명이 아님.',
         '실제 장착 도달 길이, 소재 적합성, 절삭조건과 홀더/몸통 충돌은 별도 확인.'])

for model,segment,travel,rpm in [('VF-2','small',[762,406,508],8100),('VF-2SS','small',[762,406,508],12000),('VF-3','medium',[1016,508,635],8100)]:
    url=f'https://www.haascnc.com/machines/vertical-mills/vf-series/models/{segment}/{model.lower()}.html'
    sid=source('cnc-haas-'+model.lower(),f'Haas {model} — specifications','Haas Automation',url,'Travels (METRIC), Spindle / Max Speed',limitations=['표준 장비 구성; 연식·지역·선택 사양에 따라 실제 장비와 달라질 수 있음.'])
    profile('cnc-haas-'+model.lower(),'Haas '+model+' · 장비 사양 참고','machine',sid,
        {'axis_travel_mm':parameter(travel,'mm','machine_specification',sid,'Travels; X Axis, Y Axis, Z Axis (METRIC)', ['순서 X,Y,Z; 표준 구성']),
         'maximum_spindle_rpm':parameter(rpm,'rpm','machine_specification',sid,'Spindle; Max Speed',['표준 구성'])},
        ['공식 웹사이트 표준 사양; 실제 보유 장비 구성 미확인'],
        ['축 이동량은 가공 가능한 완성품 크기·고정 공간이 아님. 소재·바이스·홀더·원점·이동 경로 여유가 필요함.',
         '현재 코드는 장비 이동/동역학 모델을 구현하지 않으므로 이 수치는 참고 정보로만 저장함.'],machine='Haas '+model)

sid=source('cnc-hydro-6061-2019','Hydro Alloy 6061 — Extruded Mechanical and Physical Property Limits','Hydro',
    'https://www.hydro.com/globalassets/01-products--services/extruded-profiles/americas/ena-resources/alloy-data-sheets/hydro_2019_data_sheet_6061.pdf',
    'PDF 2쪽; 6061 Extruded Mechanical and Physical Property Limits, Standard Tempers; 주석 1–3',
    'Revision 2019/01 (2/2019)', ['압출재·명시한 조질의 제조사 자료. 다른 제조사/판재/단조재/적층재에 자동 전용하지 않음.'])
for temper,tensile,yield_,conductivity in [('T6 / T6511',260,240,167),('T4 / T4511',180,110,155)]:
    cond=['Hydro 6061 압출재; Standard Tempers '+temper,'인장강도 값은 해당 표의 최소값; 성적서·제품 형상/치수 확인 필요']
    profile('cnc-hydro-6061-'+('t6' if 'T6' in temper else 't4'), 'Hydro 6061 '+temper+' 압출재 · 물성 참고','material',sid,
        {'tensile_strength_min_mpa':parameter(tensile,'MPa','material_property',sid,'PDF 2쪽; '+temper+'; Ultimate (min.)',cond),
         'yield_strength_02_min_mpa':parameter(yield_,'MPa','material_property',sid,'PDF 2쪽; '+temper+'; Yield 0.2% offset (min.)',cond),
         'thermal_conductivity_w_mk':parameter(conductivity,'W/(m K)','material_property',sid,'PDF 2쪽; '+temper+'; Typical Thermal Conductivity',['25 °C의 대표값'])},cond,
        ['물성은 절삭 계수·이송·절입·가공 성공 확률이 아님. 현재 물리 계산에 적용하지 않음.',
         '원문 조질/시험편 단면 두께의 조건을 따름. 납품 배치 성적서를 대체하지 않음.'],material='Hydro 6061 '+temper+' extrusion')

sid=source('cnc-outokumpu-supra','Outokumpu Supra range datasheet — Physical properties','Outokumpu',
    'https://www.outokumpu.com/-/media/files/products/supra/outokumpu-supra-range-datasheet.pdf?hash=8720C1FF12682806AF1BBC27E00209E0&modified=20251117111951&revision=7a909396-d1f3-4d36-9c1c-99606be41fd2',
    'PDF 8쪽 Table 7; Metric values according to EN 10088-1',
    '공식 다운로드 URL revision 7a909396-d1f3-4d36-9c1c-99606be41fd2; 본문 표를 대조',
    ['공급자 데이터시트가 EN 표를 인용한 것임. 프로젝트가 EN 전문을 별도로 검증했다는 뜻이 아님.'])
for grade,expansion in [('316L/4404',16),('316Ti/4571',16.5)]:
    cond=['Outokumpu Supra '+grade+'; Table 7 해당 행']
    profile('cnc-outokumpu-'+grade.replace('/','-').lower(),'Outokumpu Supra '+grade+' · 물성 참고','material',sid,
        {'density_kg_dm3':parameter(8,'kg/dm3','material_property',sid,'PDF 8쪽 Table 7; '+grade+' Density',cond),
         'elastic_modulus_gpa':parameter(200,'GPa','material_property',sid,'PDF 8쪽 Table 7; '+grade+' Modulus of elasticity',cond+['20 °C']),
         'thermal_conductivity_w_mk':parameter(15,'W/(m K)','material_property',sid,'PDF 8쪽 Table 7; '+grade+' Thermal conductivity',cond+['20 °C']),
         'thermal_expansion_per_k':parameter(expansion*1e-6,'1/K','material_property',sid,'PDF 8쪽 Table 7; '+grade+' Coefficient of thermal expansion',cond+['20–100 °C; 표의 10^-6/K 단위를 1/K로 변환'])},cond,
        ['물성 참고값만 저장하며 절삭력·변형·채터·내부응력 또는 제조 성공을 계산하지 않음.','실제 소재 규격·열처리·배치 및 공작물 상태 확인 필요.'],material='Outokumpu Supra '+grade)

for key,brand,polymer,density,modulus,tensile,path in [
    ('peek','TECAPEEK natural','PEEK',1.31,4200,116,'peek-tecapeek-natural'),
    ('pom','TECAFORM AH natural','POM-C',1.41,2800,67,'acetal-tecaform-ah-natural')]:
    local=(WORK/f'ensinger-{key}-si.txt').read_text(encoding='utf-8')
    assert f'{density} g/cm3' in local
    for prop,value in [('Modulus of elasticity (tensile test)',modulus),('Tensile strength',tensile)]:
        assert re.search(re.escape(prop)+r'\s*\|\s*'+str(value)+r'\s*\|\s*MPa',local),(key,prop)
    sid=source('cnc-ensinger-'+key,f'Ensinger {brand} — stock shapes, SI technical details','Ensinger',
        'https://www.ensingerplastics.com/en/shapes/'+path,'Facts / Density; Technical details / Mechanical properties',
        limitations=['/en/ SI·DIN EN ISO 표만 사용. /en-us/ ASTM·psi 표와 시험조건/값이 달라 혼합하지 않음.'])
    cond=['Ensinger '+brand+' 비충전 stock shapes; '+polymer,'해당 제품·시험방법의 참고 물성']
    profile('cnc-ensinger-'+key,'Ensinger '+brand+' · 물성 참고','material',sid,
        {'density_g_cm3':parameter(density,'g/cm3','material_property',sid,'Facts / Density',cond),
         'tensile_modulus_mpa':parameter(modulus,'MPa','material_property',sid,'Technical details; Modulus of elasticity (tensile test)',cond+['DIN EN ISO 527-2; 1 mm/min']),
         'tensile_strength_mpa':parameter(tensile,'MPa','material_property',sid,'Technical details; Tensile strength',cond+['DIN EN ISO 527-2; 50 mm/min'])},cond,
        ['최소 가공 벽 두께나 절삭 계수가 아님. 현재 코드에 물리 계산용으로 자동 적용하지 않음.',
         '소재 배치·시험온도/습도·가공 열이력은 실제 제품 확인 필요. 지역별 데이터와 단순 환산해 혼합하지 않음.'],material='Ensinger '+brand)

sid=source('cnc-sandvik-inside-corners','Sandvik Coromant — Milling inside corners','Sandvik Coromant',
    'https://www.sandvik.coromant.com/en-us/knowledge/milling/milling-inside-corners','Finishing',limitations=['제조사 정삭 지침. D <= 2R의 순수 기하 필요조건이나 보편적인 가공 불가능 경계가 아님.'])
profile('cnc-sandvik-corner-finishing','내부 코너 정삭 · Sandvik 공구 선정 참고','process',sid,
    {'finishing_cutter_diameter_to_corner_radius_max':parameter(1.5,'ratio','manufacturer_guidance',sid,'Finishing; cutter diameter / component radius',
        ['내부 코너 밀링의 정삭','절삭 물림각·경로·이송을 함께 고려하는 제조사 권고'])},
    ['내부 코너 정삭용 공구 선정 참고'],
    ['참고 전용이며 현재 합격/불가 판정 기준을 바꾸지 않음.','도면의 반경을 자동 수정하거나 가공 안정성을 보장하지 않음.'])

source_ids={s['id'] for s in SOURCES}
assert len(source_ids)==len(SOURCES)
assert len({p['id'] for p in PROFILES})==len(PROFILES)
automatic=[]
for p in PROFILES:
    assert set(p['source_ids'])<=source_ids
    for field,param in p['parameters'].items():
        assert set(param['source_ids'])<=source_ids
        if param['application']=='automatic':
            assert p['category']=='tool' and field in ('tool_diameter_mm','flute_length_mm')
            assert param['unit']=='mm' and param['value']>0
            automatic.append((p['id'],field,param['value']))
    assert 'reach_mm' not in p['parameters'] and 'hole_depth_ratio_limit' not in p['parameters']

output=REPO/'data/conditions/machining.json'
output.parent.mkdir(parents=True,exist_ok=True)
output.write_text(json.dumps(dict(schema_version=1,sources=SOURCES,profiles=PROFILES),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
result={'profiles':len(PROFILES),'sources':len(SOURCES),'categories':{c:sum(p['category']==c for p in PROFILES) for c in ('tool','machine','material','process')},'automatic_parameter_count':len(automatic),'source_table_transcription_checks':'19 tool rows and 2 SI polymer tables passed; Hydro/Outokumpu PDF tables and DATRON PDF 10/11/17 dimensional drawings/tables visually checked; 3 Haas web tables checked','quarantined':['DATRON 0068080E: exact-SKU D1=.8 mm; official family row and PDF D1=8 mm'],'reach_omitted':True,'hole_ratio_omitted':True}
(WORK/'curation-validation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
