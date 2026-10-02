"""Version, source fingerprints and portable JSON for saved evaluations."""
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
import hashlib
import json
import math
import platform

import numpy as np

APP_VERSION = '2.6'
ROOT = Path(__file__).resolve().parents[2]


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def runtime_record():
    files = sorted(ROOT.joinpath('src').rglob('*.py')) + [ROOT / n for n in ('cura_check.py', 'audit_models.py', 'run_app.py')]
    sources = {p.relative_to(ROOT).as_posix(): file_sha256(p) for p in files if p.is_file()}
    packages = {}
    for name in ('numpy', 'scipy', 'trimesh', 'rtree', 'manifold3d', 'streamlit', 'plotly', 'pandas', 'shapely'):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    return {
        'app_version': APP_VERSION,
        'created_at_utc': datetime.now(timezone.utc).isoformat(),
        'python': platform.python_version(), 'platform': platform.system(),
        'packages': packages, 'source_files_sha256': sources,
        'code_sha256': hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest(),
    }


def json_ready(value):
    """Unavailable/nonfinite numbers become null; never emit NaN or Infinity."""
    if is_dataclass(value):
        return json_ready(asdict(value))
    if isinstance(value, np.ndarray):
        return json_ready(value.tolist())
    if isinstance(value, np.generic):
        return json_ready(value.item())
    if isinstance(value, dict):
        return {str(k): json_ready(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_ready(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, Path):
        return str(value)
    return value


def json_text(value):
    return json.dumps(json_ready(value), ensure_ascii=False, indent=2, allow_nan=False)


def save_new_json(path, value):
    """Never overwrite a previous result or a user's measurements."""
    text = json_text(value)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        stream.write(text + '\n')
    return str(path)
