"""Read-only image feature caches; caption features are never required."""
import json
from pathlib import Path
import numpy as np
from .common import digest
from .protocol import fixed


def paper_inputs():
    return json.loads(Path(__file__).with_name('paper_inputs.json').read_text(encoding='utf-8'))


def load_cache(folder, verify_paper=True):
    folder = Path(folder)
    meta = json.loads((folder/'features_complete.json').read_text(encoding='utf-8'))
    expected = paper_inputs()[meta['dataset']]['files_sha256'] if verify_paper else meta['files_sha256']
    for name in ('gallery.npy', 'calibration.npy'):
        if digest(folder/name) != expected[name]:
            raise ValueError('Feature hash mismatch: ' + name)
    gallery = np.load(folder/'gallery.npy', mmap_mode='r', allow_pickle=False)
    calibration = np.load(folder/'calibration.npy', mmap_mode='r', allow_pickle=False)
    if gallery.ndim != 2 or calibration.ndim != 2 or gallery.shape[1] != calibration.shape[1]:
        raise ValueError('Inconsistent feature arrays')
    return meta, fixed(gallery), fixed(calibration)
