from pathlib import Path
import hashlib
import json
import re
import requests

root = Path(__file__).resolve().parent
urls = {
    'qub': 'https://pure.qub.ac.uk/en/datasets/mfcad-dataset-dataset-for-paper-hierarchical-cadnet-learning-from/',
    'aagnet': 'https://raw.githubusercontent.com/whjdark/AAGNet/main/README.md',
    'uvnet': 'https://raw.githubusercontent.com/AutodeskAILab/UV-Net/main/README.md',
    'thingi': 'https://raw.githubusercontent.com/Thingi10K/Thingi10K/master/README.md',
    'brepmfr': 'https://api.github.com/repos/zhangshuming0668/BrepMFR',
}
results = {}
for key, url in urls.items():
    try:
        response = requests.get(url, timeout=35)
        (root / (key + '.txt')).write_bytes(response.content)
        links = re.findall(r'https?://[^\s<>"\x27]+', response.text)
        results[key] = dict(url=url, response_url=response.url, status=response.status_code,
                            bytes=len(response.content), sha256=hashlib.sha256(response.content).hexdigest(),
                            links=[link for link in links if any(v in link.lower() for v in ('zip', 'mfcad', 'drive.google', 'license', 'nyu', '10k', 'json'))])
    except requests.RequestException as error:
        results[key] = dict(url=url, error=str(error))
    print(key, json.dumps(results[key]), flush=True)
(root / 'source-access.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
