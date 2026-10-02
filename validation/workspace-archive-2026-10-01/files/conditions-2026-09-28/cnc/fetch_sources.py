from pathlib import Path
import concurrent.futures
import hashlib
import html
import json
import re
import requests

ROOT = Path(__file__).parent
SINGLE = ['0068010E','0068020E','0068030E','0068434E','0068435E','0068460E','0068080E','0068470E','0068460L','0068434F','0068470L','0068493L']
STEEL = ['0078010K','0078018S','0078030K']
ITEMS = {f'datron-{sku}': f'https://shop.datron.com/product/single-flute-end-mills/{sku}/' for sku in SINGLE}
ITEMS.update({f'datron-{sku}': f'https://shop.datron.com/product/steel-machining-double-flute-end-mill/{sku}/' for sku in STEEL})
ITEMS.update({
    'haas-vf1': 'https://www.haascnc.com/machines/vertical-mills/vf-series/models/small/vf-1.html',
    'haas-vf2': 'https://www.haascnc.com/machines/vertical-mills/vf-series/models/small/vf-2.html',
    'haas-vf2ss': 'https://www.haascnc.com/machines/vertical-mills/vf-series/models/small/vf-2ss.html',
    'haas-vf3': 'https://www.haascnc.com/machines/vertical-mills/vf-series/models/medium/vf-3.html',
    'datron-neo': 'https://www.datron.com/cnc-machines/datron-neo/',
    'harvey-metric': 'https://www.harveytool.com/products/miniature-end-mills-square-long-reach-standard-flute-metric',
    'hydro-6061.pdf': 'https://www.hydro.com/globalassets/01-products--services/extruded-profiles/americas/ena-resources/alloy-data-sheets/hydro_2019_data_sheet_6061.pdf',
    'outokumpu-supra.pdf': 'https://www.outokumpu.com/-/media/files/products/supra/outokumpu-supra-range-datasheet.pdf?hash=8720C1FF12682806AF1BBC27E00209E0&modified=20251117111951&revision=7a909396-d1f3-4d36-9c1c-99606be41fd2',
    'ensinger-peek': 'https://www.ensingerplastics.com/en-us/shapes/peek-tecapeek-natural',
    'ensinger-pom': 'https://www.ensingerplastics.com/en-us/shapes/acetal-tecaform-ah-natural',
})

def fetch(item):
    key, url = item
    path = ROOT / (key if key.endswith('.pdf') else key + '.html')
    try:
        if not path.exists():
            r = requests.get(url, timeout=40)
            r.raise_for_status()
            path.write_bytes(r.content)
        payload = path.read_bytes()
        result = {'id':key,'url':url,'bytes':len(payload),'sha256':hashlib.sha256(payload).hexdigest()}
        if path.suffix == '.html':
            raw = payload.decode('utf-8', errors='replace')
            raw = re.sub(r'<(script|style)\b[^>]*>.*?</\1>', '', raw, flags=re.S|re.I)
            raw = re.sub(r'</(?:tr|p|div|h\d|li)>', '\n', raw, flags=re.I)
            raw = re.sub(r'</(?:td|th)>', ' | ', raw, flags=re.I)
            text = html.unescape(re.sub(r'<[^>]+>', ' ', raw))
            text = '\n'.join(re.sub(r'\s+', ' ', line).strip() for line in text.splitlines() if line.strip())
            path.with_suffix('.txt').write_text(text, encoding='utf-8')
            if key.startswith('datron-0'):
                match = re.search(r'Additional Information(.*?)Available Options',text,re.S)
                result['specification_excerpt'] = match.group(1).strip()[:1800] if match else 'MISSING'
        return result
    except Exception as exc:
        return {'id':key,'url':url,'error':str(exc)}

if __name__ == '__main__':
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(fetch,ITEMS.items()))
    (ROOT/'fetch-manifest.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(results,ensure_ascii=False,indent=2))
