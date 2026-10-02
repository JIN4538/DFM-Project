from pathlib import Path
import configparser, hashlib, json
from collections import Counter

ROOT=Path(__file__).parent
REPO=ROOT.parents[2]/'DFM-Project'
SHA=(ROOT/'prusa-commit.txt').read_text(encoding='utf-8-sig').strip()
cfg=configparser.ConfigParser(interpolation=None,strict=False,delimiters=('=',))
ini=ROOT/'PrusaResearch-1.14.2.ini'
cfg.read(ini,encoding='utf-8')
lines=ini.read_text(encoding='utf-8').splitlines()
line_map={}
section=None
for n,line in enumerate(lines,1):
    if line.startswith('['): section=line.strip()[1:-1]
    elif '=' in line and not line.lstrip().startswith(('#',';')):
        line_map[(section,line.split('=',1)[0].strip())]=n

def resolved(section,seen=()):
    if section in seen: raise ValueError('inheritance cycle')
    own=dict(cfg[section]); vals={}; origins={}; kind=section.split(':',1)[0]
    for parent in own.get('inherits','').split(';'):
        if parent.strip():
            values,where=resolved(kind+':'+parent.strip(),seen+(section,))
            vals.update(values); origins.update(where)
    for key,val in own.items(): vals[key]=val; origins[key]=section
    return vals,origins

sources=[]; profiles=[]
def source(id,title,publisher,url,locator,revision='발행판 미표기; 2026-09-28 열람본',limitations=(),filename=None):
    item=dict(id=id,title=title,publisher=publisher,url=url,accessed='2026-09-28',locator=locator,revision=revision,verification='primary_source_checked',limitations=list(limitations))
    if filename: item['sha256']=hashlib.sha256((ROOT/filename).read_bytes()).hexdigest()
    sources.append(item); return id

prusa=source('AM-PRUSA-FAQ','FAQ - Frequently Asked Questions: printer dimensions','Prusa Research','https://help.prusa3d.com/article/faq-frequently-asked-questions_1932?product=xl','What are the printer dimensions? / CORE One, CORE One L, XL, MK4/S',limitations=['MINI+ 행은 다른 공식 사양과 불일치 가능성이 있어 채택하지 않음.','명목 공간은 브림·서포트·다중 재료 구조의 공간을 보장하지 않음.'])
settings=source('AM-PRUSA-SETTINGS-1142','PrusaSlicer-settings / PrusaResearch 1.14.2','Prusa Research',f'https://github.com/prusa3d/PrusaSlicer-settings/blob/{SHA}/live/PrusaResearch/1.14.2.ini','INI section/key and inherited section; 각 파라미터의 줄 번호 참조',f'config_version 1.14.2; commit {SHA}',limitations=['해당 판의 명시적 프로필만 채택; 최신 설정이라는 의미가 아님.','설정값은 재료의 출력 한계·강도·실제 압출폭을 보증하지 않음.'],filename=ini.name)
fvol=source('AM-FORMLABS-VOLUME','What is the largest part I can print on a Formlabs printer?','Formlabs','https://formlabs.com/support/What-is-the-build-volume-of-the-Form-3L-and-Form-3BL/','Form 4/4L/3/3L sections; Fuse table and corner-radius note',limitations=['외곽 박스 검토에만 사용. 서포트·플랫폼 부착·배치 여유를 별도 고려.','Fuse 치수는 재료·PreForm 설정판에 따라 변경되며 모서리가 둥글다.'])
f4=source('AM-FORMLABS-FORM4-DESIGN','Design specifications for 3D models (Form 4 generation)','Formlabs','https://formlabs.com/support/Design-specifications-for-3D-models-Form-4-generation/','Grey Resin V5 / 50 microns note; named feature sections',limitations=['Form 4 + Grey Resin V5 + 50 µm 기준. 다른 레진·방향·크기에서 보편 한계 아님.','벽 0.2 mm 권장과 0.2 mm 이하 변형 경고가 함께 있음; 경계값을 합격으로 자동 판정하지 않음.'])
fuse=source('AM-FORMLABS-FUSE-SPECS','Fuse Series SLS 3D Printers Technical Specifications','Formlabs','https://formlabs.com/3d-printers/fuse-1/tech-specs/','Quick Stats / Fuse 1 and Fuse 1+ 30W columns',limitations=['빌드 공간의 둥근 모서리·재료별 수축 보정을 이 표만으로 처리할 수 없음.'])
sls=source('AM-FORMLABS-FUSE-DESIGN','Design specifications for 3D models (Fuse 1 generation)','Formlabs','https://formlabs.com/support/Design-specifications-for-3D-models-Fuse-1/','Nylon 12 basis; wall/hole/drain sections; material-specific characteristics',limitations=['기본 특징 치수는 Fuse 1 + Nylon 12 기준; 다른 분말로 복사하지 않음.','서비스 Form Now의 별도 강화 기준과 구분. 제조 성공률 자료가 아님.'])
nylon=source('AM-FORMLABS-NYLON12-TDS-REV01','Nylon 12 Powder: Material Properties Data','Formlabs','https://formlabs-media.formlabs.com/datasheets/2201730-TDS-ENUS-0.pdf','PDF p.2, Mechanical Properties and footnotes 1-2','Rev.01 / 11.04.2020 as printed; V1 FLP12G01',limitations=['과거 판본의 시험 재료 물성; 현행 분말의 설계 허용응력으로 사용하지 않음.','현재 다른 TDS에 탄성률 1900 MPa도 존재하므로 판본을 섞지 않음.'],filename='formlabs-nylon12-rev01.pdf')
p110=source('AM-EOS-P110','FORMIGA P 110 Velocis','EOS GmbH','https://www.eos.info/polymer-solutions/polymer-printers/formiga-p-110-velocis','Technical Data / Build Volume; Materials & Processes',limitations=['챔버 명목 치수; 열수축 보정 후 완성 부품 크기와 동일하다고 보장하지 않음.'])
m290=source('AM-EOS-M290','EOS M 290 System Data Sheet','EOS GmbH','https://www.eos.info/metal-solutions/metal-printers/data-sheets/sds-eos-m-290','Technical Data / Build Volume and asterisk','Last changed 2026-07-23; status 2026-09-28',limitations=['325 mm 높이는 빌드 플랫폼 포함·응용조건 의존. 실제 부품 공간으로 자동 대입하지 않음.'])
steel=source('AM-EOS-316L-202207','EOS StainlessSteel 316L Material Data Sheet','EOS GmbH','https://www.eos.info/03_system-related-assets/material-related-contents/metal-materials-and-examples/metal-material-datasheet/stainlesssteel/material_datasheet_eos_stainlesssteel_316l_en_web.pdf','PDF pp.5,7,10,12; p.29 limitations','Status 07/2022; 29 pages',limitations=['지정 장비·ParameterSet·분말에 한한 자료. 현재 316L-4404/4441 제품명에 임의 대응시키지 않음.','물성은 보증값 또는 설계 허용응력이 아님.'],filename='eos-316l.pdf')
al=source('AM-EOS-ALSI10MG-PDF','EOS Aluminium AlSi10Mg Material Data Sheet','EOS GmbH','https://www.eos.info/03_system-related-assets/material-related-contents/metal-materials-and-examples/metal-material-datasheet/aluminium/material_datasheet_eos_aluminium-alsi10mg_en_web.pdf','PDF pp.5,7,11,13; p.36 limitations','36-page PDF; M290 sections CR774; immutable SHA recorded',limitations=['웹 현행 분말 설명과 PDF의 조성값을 섞지 않음.','물성은 지정 장비·분말·설정·가공 시험편 조건의 관측치이며 부품 강도 보증값 아님.'],filename='eos-alsi10mg.pdf')

def param(value,unit,source_id,locator,kind='manufacturer_guidance',application='reference_only',conditions=()):
    return dict(value=value,unit=unit,kind=kind,source_ids=[source_id],locator=locator,conditions=list(conditions),application=application)
def add(id,label,process,category,machine,material,parameters,source_ids,conditions=(),limitations=()):
    profiles.append(dict(id=id,label=label,process=process,category=category,machine=machine,material=material,conditions=list(conditions),limitations=list(limitations),source_ids=source_ids,parameters=parameters,physical_validation='not_validated_by_project'))

for slug,machine,vol,heading in [('mk4s','Original Prusa MK4S',[250,210,220],'MK4/S, MK3.9/S'),('xl','Original Prusa XL',[360,360,360],'XL'),('core-one','Prusa CORE One',[250,220,270],'CORE One'),('core-one-l','Prusa CORE One L',[300,300,330],'CORE One L')]:
    add('am-prusa-'+slug,machine+' · 공간 사양','MEX','machine',machine,'미확정',{'build_volume_mm':param(vol,'mm',prusa,'What are the printer dimensions? / '+heading+' / Build volume','machine_specification','automatic',['X,Y,Z 순서'])},[prusa],['제조사 명목 빌드 공간을 선택한 시나리오'],['소재·노즐·온도·벽 기준은 미확정. 공간만 맞아도 출력 가능 판정은 아님.'])

def ini_param(section,key,unit,application='reference_only',conditions=()):
    vals,origins=resolved(section); origin=origins[key]
    raw=vals[key]
    try: value=float(raw)
    except ValueError: value=raw
    locator=f'{section} -> {origin} / {key}; L{line_map[(origin,key)]}'
    return param(value,unit,settings,locator,'slicer_setting',application,conditions)

mex_cases=[('pla-015','Prusament PLA','Prusament PLA @PG','0.15mm QUALITY @MK4 0.4',0.4),('pla-020','Prusament PLA','Prusament PLA @PG','0.20mm QUALITY @MK4 0.4',0.4),('petg-020','Prusament PETG','Prusament PETG @PG','0.20mm QUALITY @MK4 0.4',0.4),('asa-020','Prusament ASA','Prusament ASA @MK4','0.20mm QUALITY @MK4 0.4',0.4),('pcblend-020','Prusament PC Blend','Prusament PC Blend @MK4','0.20mm QUALITY @MK4 0.4',0.4),('pla-025-n06','Prusament PLA','Prusament PLA @PG 0.6','0.25mm QUALITY @MK4 0.6',0.6),('petg-025-n06','Prusament PETG','Prusament PETG @PG 0.6','0.25mm QUALITY @MK4 0.6',0.6)]
for slug,mat,fil,pr,nz in mex_cases:
    prs='print:'+pr; fil='filament:'+fil; printer=f'printer:Original Prusa MK4 {nz} nozzle'
    pars={'layer_height_mm':ini_param(prs,'layer_height','mm','automatic'),
          'line_width_mm':ini_param(prs,'perimeter_extrusion_width','mm','automatic',['명목 둘레 선폭을 사용하는 고정폭 기하 탐색. 실제 경로의 가변폭·첫층·브리지 폭은 다를 수 있음.']),
          'nozzle_diameter_mm':ini_param(printer,'nozzle_diameter','mm'),
          'nozzle_temperature_c':ini_param(fil,'temperature','degC'),
          'first_layer_nozzle_temperature_c':ini_param(fil,'first_layer_temperature','degC'),
          'bed_temperature_c':ini_param(fil,'bed_temperature','degC'),
          'slicer_density_g_cm3':ini_param(fil,'filament_density','g/cm3')}
    add('am-prusa-mk4-'+slug,f'MK4 · {mat} · {pr}','MEX','process','Original Prusa MK4 (non-Input Shaper)',mat,pars,[settings],['PrusaResearch 1.14.2의 선택된 공식 프리셋 조합','실제 슬라이싱 시 원본 전체 프로필이 필요함'],['노즐 지름을 최소 벽 두께로 사용하지 않음.','열변형·접착·건조·챔버 환경은 계산하지 않음.','밀도는 슬라이서 입력값이며 해당 부품 실측 밀도가 아님.'])

for slug,machine,vol,heading in [('form4','Formlabs Form 4',[200,125,210],'Form 4 and Form 4B'),('form4l','Formlabs Form 4L',[353,196,350],'Form 4L and Form 4BL'),('form3','Formlabs Form 3',[145,145,185],'Form 3 and Form 3B'),('form3l','Formlabs Form 3L',[335,200,300],'Form 3L and Form 3BL')]:
    add('am-'+slug,machine+' · 공간 사양','VPP','machine',machine,'미확정',{'build_volume_mm':param(vol,'mm',fvol,heading,'machine_specification','automatic',['X,Y,Z 순서'])},[fvol],['제조사 명목 공간'],['서포트·플랫폼 여유·레진별 후경화 변형은 포함하지 않음.'])

f4pars={'layer_height_mm':param(.05,'mm',f4,'Opening note: Grey Resin V5 at 50 microns','manufacturer_guidance','automatic'),
 'supported_wall_guidance_mm':param(.2,'mm',f4,'Minimum supported wall thickness',conditions=['다른 벽에 두 측면 이상 연결된 벽. 0.2 mm 이하 변형 가능 경고 포함.']),
 'unsupported_wall_guidance_mm':param(.2,'mm',f4,'Minimum unsupported wall thickness',conditions=['다른 벽에 두 측면 미만 연결된 벽. 0.2 mm 이하 변형·탈락 경고 포함.']),
 'minimum_hole_mm':param(.5,'mm',f4,'Minimum hole diameter'),
 'minimum_drain_hole_mm':param(.75,'mm',f4,'Minimum drain hole diameter',conditions=['밀폐 공동의 레진·공기 배출 목적; 현재 공동 연결성은 자동 계산하지 않음.']),
 'minimum_clearance_mm':param(.4,'mm',f4,'Minimum clearance'),
 'overhang_angle_reference_deg':param(10,'deg',f4,'Minimum unsupported overhang angle',conditions=['수평 기준; 길이35×폭10×두께3 mm 시험형상. 10° 이하 파손 경고.']),
 'horizontal_span_reference_mm':param(29,'mm',f4,'Maximum horizontal support span length',conditions=['폭5×두께3 mm 보; 다른 단면으로 일반화하지 않음.'])}
add('am-form4-grey-v5-005','Form 4 · Grey Resin V5 · 0.05 mm 설계 가이드','VPP','process','Formlabs Form 4','Formlabs Grey Resin V5',f4pars,[f4],['제조사 CAD 특징 권장값; 실측 완성 치수와 구분'],['벽 레이 표본은 연결 측면·전체 최소 두께를 보증하지 않아 벽 기준 자동 적용 제외.','구멍·배출구·간격은 자료 열람용이며 현재 검사 완료 표시를 하지 않음.'])

for h,pr in [(.025,'0.025 UltraDetail @SL1S'),(.05,'0.05 Normal @SL1S'),(.1,'0.1 Fast @SL1S')]:
    section=f'sla_material:Prusament Resin Tough Prusa Orange @{h} SL1S'
    pars={'layer_height_mm':ini_param('sla_print:'+pr,'layer_height','mm','automatic'),
          'exposure_time_s':ini_param(section,'exposure_time','s'),
          'initial_exposure_time_s':ini_param(section,'initial_exposure_time','s')}
    add('am-prusa-sl1s-orange-'+str(h).replace('.',''),f'SL1S · Tough Prusa Orange · {h} mm','VPP','process','Original Prusa SL1S SPEED','Prusament Resin Tough Prusa Orange',pars,[settings],['PrusaResearch 1.14.2의 레진·층높이 일치 프리셋'],['노출시간은 원본 프로필 설정값; 다른 색상·레진·장비에 적용하지 않음.','후경화·세척·구조강도 검증 미포함.'])

for id,machine in [('am-fuse1','Formlabs Fuse 1'),('am-fuse1plus','Formlabs Fuse 1+ 30W')]:
    pars={'nominal_build_volume_mm':param([165,165,300],'mm',fuse,'Quick Stats / '+machine+' / Build Volume','machine_specification'),
          'layer_height_mm':param(.11,'mm',fuse,'Quick Stats / '+machine+' / Layer Thickness','machine_specification','automatic'),
          'build_chamber_corner_radius_mm':param(16,'mm',sls,'Build volume / rounded-corners note','machine_specification')}
    add(id,machine+' · 모서리·수축 보정 필요','PBF_POLYMER','machine',machine,'미확정',pars,[fuse,sls],['Fuse 1 generation; 110 µm = 0.11 mm'],['명목 박스는 실제 허용 부품 공간이 아니므로 공간 한계에 자동 대입하지 않음.','현행 PreForm에서 재료·설정판별 실제 배치 확인 필요.'])
add('am-eos-p110-velocis','EOS FORMIGA P 110 Velocis · 명목 공간','PBF_POLYMER','machine','EOS FORMIGA P 110 Velocis','미확정',{'nominal_build_volume_mm':param([200,250,330],'mm',p110,'Technical Data / Build Volume','machine_specification')},[p110],['제조사 장비 사양'],['수축 보정·재료·여유 공간 미확정; 실제 부품 허용 박스로 자동 적용하지 않음.'])

poly=[('nylon12','Nylon 12 Powder',[160.2,160.2,297.3]),('nylon12gf','Nylon 12 GF Powder',[159.9,159.9,294.1]),('nylon11','Nylon 11 Powder',[158.3,158.3,295.0]),('nylon11cf','Nylon 11 CF Powder',[164.6,164.6,291.7]),('tpu90a','TPU 90A Powder',[161.2,161.2,295.0])]
for id,mat,vol in poly:
    pars={'material_part_size_reference_mm':param(vol,'mm',sls,'Build volume / '+mat,conditions=['웹 자료의 최대 치수; 모서리 R16과 설정판 갱신 때문에 완전한 허용 직육면체가 아님.'])}
    limits=['재료 지원 장비·현행 PreForm 설정판 확인 필요. 기본 Nylon 12 특징 규칙을 다른 분말로 복사하지 않음.']
    if id=='nylon12':
        pars.update({'vertical_wall_guidance_mm':param(.6,'mm',sls,'Minimum supported/unsupported wall thickness',conditions=['수직 벽; 두 연결 조건 모두 같은 권장값.']),
                     'horizontal_wall_guidance_mm':param(.3,'mm',sls,'Minimum supported/unsupported wall thickness',conditions=['수평 벽; 방향이 다른 벽으로 일반화하지 않음.']),
                     'minimum_hole_mm':param(1.,'mm',sls,'Minimum hole diameter',conditions=['구멍 길이·벽 두께·분말 제거 접근성이 별도로 영향.']),
                     'minimum_drain_hole_mm':param(3.5,'mm',sls,'Minimum drain hole diameter',conditions=['공동마다 최소 두 개 배출구 권장; 현재 공동 연결성 검사는 미지원.'])})
    elif id=='nylon11':
        pars['integrated_assembly_clearance_mm']=param(1.,'mm',sls,'Nylon 11 Powder design considerations / Clearances')
        limits.append('큰 XY 단면의 휨·작은 특징 재현은 정량 판정하지 않음.')
    elif id=='tpu90a':
        pars['integrated_assembly_clearance_mm']=param(1.,'mm',sls,'TPU 90A Powder design considerations / Clearances',conditions=['두꺼운 단면 근처는 더 큰 간격이 필요할 수 있음.'])
        limits.append('XY 축의 원형 구멍은 타원화 가능; 현재 물리 변형 계산 없음.')
    elif id=='nylon12gf': limits.append('내부 표면 세척 접근성·취성·거친 표면을 별도 검토.')
    else: limits.append('탄소섬유 정렬 때문에 X/Y/Z 물성이 다름; 등방성 강도로 취급하지 않음.')
    add('am-fuse-'+id,'Fuse 1 계열 · '+mat+' 설계 참고','PBF_POLYMER','material','Formlabs Fuse 1 generation · 재료 지원 모델 확인 필요','Formlabs '+mat,pars,[sls],['Nylon 12 기본 특징은 Fuse 1 시험조건; 나머지는 각 재료별 절의 가이드'],limits)

add('am-fuse1-nylon12-properties-rev01','Fuse 1 · Nylon 12 V1 · 2020 물성 판본','PBF_POLYMER','material','Formlabs Fuse 1','Formlabs Nylon 12 Powder V1 FLP12G01',{
 'tensile_strength_mpa':param(50,'MPa',nylon,'PDF p.2 / Ultimate Tensile Strength','material_property',conditions=['ASTM D638 Type 1; 23°C·50%RH에서 7일 조절. 시험편 방향은 해당 행에 미명시.']),
 'tensile_modulus_mpa':param(1850,'MPa',nylon,'PDF p.2 / Tensile Modulus','material_property',conditions=['ASTM D638 Type 1; 23°C·50%RH에서 7일 조절.']),
 'elongation_xy_percent':param(11,'%',nylon,'PDF p.2 / Elongation at Break (X/Y)','material_property',conditions=['ASTM D638 Type 1; XY 시편; 23°C·50%RH에서 7일 조절.']),
 'elongation_z_percent':param(6,'%',nylon,'PDF p.2 / Elongation at Break (Z)','material_property',conditions=['ASTM D638 Type 1; Z 시편; 23°C·50%RH에서 7일 조절.'])},[nylon],['과거 판본의 제조사 시험값을 비교·추적하기 위한 기록'],['현재 분말·부품의 강도 계산 또는 설계 허용응력으로 자동 적용하지 않음.'])

add('am-eos-m290','EOS M 290 · 플랫폼 포함 명목 공간','PBF_METAL','machine','EOS M 290','미확정',{'nominal_build_volume_mm':param([250,250,325],'mm',m290,'Technical Data / Build Volume and asterisk','machine_specification')},[m290],['높이에는 빌드 플랫폼 포함'],['플랫폼·서포트·베이스 제거 여유 미확정; actual build_volume_mm 자동 적용 제외.'])

metal=[('316l-surface-020','EOS StainlessSteel 316L',.02,steel,5,7,'316L_Surface_1.X',[.3,.4],540,640,189,162),
       ('316l-flex-040','EOS StainlessSteel 316L',.04,steel,10,12,'316L_040_FlexM291_1.X',.1,570,640,105,90),
       ('alsi10mg-flex-030','EOS Aluminium AlSi10Mg',.03,al,5,7,'AlSi10Mg_FlexM291 2.01',.4,460,450,261,108),
       ('alsi10mg-core-060','EOS Aluminium AlSi10Mg',.06,al,11,13,'AlSi10Mg_060_CoreM291 1.00',None,440,440,None,None)]
for id,mat,h,src,pinfo,pmech,setting,wall,tsz,tsxy,nz,nxy in metal:
    cond=['EOS M 290; '+setting,'분말 제품번호 '+('9011-0032' if src==steel else '9011-0024')+'; Argon']
    cond.append('EOSPRINT 2.7 이상; EOSYSTEM 2.11 이상; HSS blade' if src==steel else ('EOSPRINT 1.6 이상; EOSYSTEM 2.4 이상; HSS blade' if h==.03 else 'EOSPRINT 2.6 이상; EOSYSTEM 2.6 이상; HSS blade'))
    pars={'layer_height_mm':param(h,'mm',src,f'PDF p.{pinfo} / Process Information / Layer thickness','manufacturer_guidance','automatic',cond),
          'parameter_set':param(setting,'text',src,f'PDF p.{pinfo} / EOSPAR or MaterialSet','manufacturer_guidance'),
          'tensile_strength_vertical_mpa':param(tsz,'MPa',src,f'PDF p.{pmech} / as manufactured / Vertical / Tensile strength','material_property',conditions=['ISO 6892-1; 제조상태'+('; B10 절삭 시험편' if src==al else '')]+(['n='+str(nz)] if nz else ['표본 수 미표기'])),
          'tensile_strength_horizontal_mpa':param(tsxy,'MPa',src,f'PDF p.{pmech} / as manufactured / Horizontal / Tensile strength','material_property',conditions=['ISO 6892-1; 제조상태'+('; B10 절삭 시험편' if src==al else '')]+(['n='+str(nxy)] if nxy else ['표본 수 미표기']))}
    if wall is not None:
        key='minimum_wall_reference_range_mm' if isinstance(wall,list) else 'minimum_wall_reference_mm'
        pars[key]=param(wall,'mm',src,f'PDF p.{pinfo} / Minimum wall thickness',conditions=['벽의 방향·높이·지지 조건이 이 행에 완전히 특정되지 않아 자동 비교 제외.'])
    if src==al:
        pars['build_platform_temperature_c']=param(35 if h==.03 else 100,'degC',src,f'PDF p.{pinfo} / Build platform temperature')
    add('am-eos-m290-'+id,f'M290 · {mat} · {h} mm · {setting}','PBF_METAL','process','EOS M 290',mat,pars,[src],cond,['명시된 판본·ParameterSet의 제조사 조건; 현재 판매/장비 설정과 동일함을 자동 보증하지 않음.','전체 제조 레시피가 아니며 장비 실행에는 제조사 원본 ParameterSet·작업지침이 필요.','제조사 평균/대표 시험편 값은 부품 강도·피로·공차·성공 확률이 아님.','열응력·변형·서포트·스캔 경로·분말 제거는 별도 검토.'])

for profile in profiles:
    if settings in profile['source_ids']:
        profile['slicer']='PrusaSlicer / PrusaResearch 1.14.2'
doc={'schema_version':1,'sources':sources,'profiles':profiles}
dest=REPO/'data/conditions/am.json'; dest.parent.mkdir(parents=True,exist_ok=True)
dest.write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
stats={'sources':len(sources),'profiles':len(profiles),'process_counts':dict(Counter(p['process'] for p in profiles)),
       'parameters':sum(len(p['parameters']) for p in profiles),
       'automatic_parameters':sum(v['application']=='automatic' for p in profiles for v in p['parameters'].values())}
(ROOT/'am-build-stats.json').write_text(json.dumps(stats,indent=2),encoding='utf-8')
print(dest); print(json.dumps(stats,indent=2))
