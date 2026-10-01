from pathlib import Path
import configparser, json
import pypdfium2 as pdfium
from pypdf import PdfReader

ROOT = Path(__file__).parent
cfg = configparser.ConfigParser(interpolation=None, strict=False, delimiters=('=',))
cfg.read(ROOT / 'PrusaResearch-1.14.2.ini', encoding='utf-8')

def resolved(section, seen=()):
    if section in seen:
        raise ValueError('cycle')
    own = dict(cfg[section])
    values, origins = {}, {}
    category = section.split(':',1)[0]
    for parent in own.get('inherits','').split(';'):
        parent=parent.strip()
        if parent:
            inherited, paths = resolved(category+':'+parent, seen+(section,))
            values.update(inherited)
            origins.update(paths)
    for key,value in own.items():
        values[key]=value
        origins[key]=section
    return values,origins

selections = ['print:0.15mm QUALITY @MK4 0.4','print:0.20mm QUALITY @MK4 0.4','print:0.25mm QUALITY @MK4 0.6',
 'filament:Prusament PLA @PG','filament:Prusament PETG @PG','filament:Prusament ASA @MK4','filament:Prusament PC Blend @MK4',
 'printer:Original Prusa MK4 0.4 nozzle','printer:Original Prusa MK4 0.6 nozzle',
 'filament:Prusament PLA @PG 0.6','filament:Prusament PETG @PG 0.6']
keys=['layer_height','extrusion_width','perimeter_extrusion_width','external_perimeter_extrusion_width','perimeter_generator',
 'temperature','first_layer_temperature','bed_temperature','filament_density','nozzle_diameter','printer_model','bed_shape','max_print_height',
 'compatible_printers_condition']
out={}
for section in selections:
    vals,origins=resolved(section)
    out[section]={key:{'value':vals[key],'origin':origins[key]} for key in keys if key in vals}
(ROOT/'resolved-settings.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(out,ensure_ascii=False,indent=2))
for filename, pages in [('eos-316l.pdf',[4,6,9,11,28]),('eos-alsi10mg.pdf',[4,6,10,12,35]),('formlabs-nylon12-rev01.pdf',[1])]:
    doc=pdfium.PdfDocument(str(ROOT/filename))
    reader=PdfReader(ROOT/filename)
    for index in pages:
        page=doc[index]
        page.render(scale=1.4).to_pil().save(ROOT/f'{Path(filename).stem}-p{index+1}.png')
    print(filename, 'lastpage=',reader.pages[-1].extract_text()[-2500:])
