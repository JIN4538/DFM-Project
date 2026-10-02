from pathlib import Path
import json
import requests
root = Path(__file__).resolve().parent
urls = {
    'hf_datasets': 'https://huggingface.co/api/datasets?search=mfcad&limit=30',
    'brepmfr_readme': 'https://raw.githubusercontent.com/zhangshuming0668/BrepMFR/main/README.md',
    'qub_download': 'https://pure.qub.ac.uk/files/278385243/MFCAD_dataset.zip',
    'uvnet_mfcad': 'https://uv-net-data.s3.us-west-2.amazonaws.com/MFCADDataset.zip',
    'original_archive': 'https://codeload.github.com/hducg/MFCAD/zip/ef6d58a40164d5192666821ce98d0cc90e379fac',
}
for key, url in urls.items():
    response = requests.get(url, timeout=(25, 35), stream=key.endswith(('download', 'mfcad', 'archive')))
    print(key, response.status_code, response.headers.get('Content-Length'), response.headers.get('Content-Type'), flush=True)
    if key in ('hf_datasets','brepmfr_readme'):
        (root/(key+'.txt')).write_bytes(response.content)
        print(response.text[:7000], flush=True)
    response.close()
