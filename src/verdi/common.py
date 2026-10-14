"""Portable provenance, atomic checkpoints and defaults."""
import hashlib
import json
import os
import platform
import sys
from pathlib import Path

DEFAULT_DATA = 'data'
SEED = 20261009
CLIP_REV = 'd05afc436d78f1c48dc0dbf8e5980a9d471f35f6'
MODEL_SHA = '40d365715913c9da98579312b702a82c18be219cc2a73407c4526f58eba950af'


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for b in iter(lambda: f.read(4 * 1024 * 1024), b''):
            h.update(b)
    return h.hexdigest()


def signature(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def runtime():
    import numpy as np
    import cryptography
    try:
        import psutil
        ram = psutil.virtual_memory().total
    except ImportError:
        ram = None
    return {'python': sys.version, 'platform': platform.platform(),
            'processor': platform.processor(), 'logical_cpus': os.cpu_count(),
            'ram_bytes': ram,
            'numpy': np.__version__, 'cryptography': cryptography.__version__,
            'thread_settings': {k: os.environ.get(k) for k in
                                ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS')},
            'code_sha256': {p.name: digest(p) for p in Path(__file__).parent.rglob('*.py')
                            if '.venv' not in p.parts}}
