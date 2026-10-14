"""Actual local-image RGB recovery, region tampering and descriptor bindings."""
import argparse
import copy
import hashlib
import time
import zlib
from pathlib import Path
import numpy as np
from PIL import Image
from verdi.common import digest, read, save
from verdi.owner import ConfiguredOwner, binding
from verdi.retrieval import ExperimentClient, Transport
from verdi.protocol import ser, reject, sha, node_parse
from verdi.image import ImageCodec
from verdi.cache import load_cache


def tiles(image, size):
    h, w, _ = image.shape
    values, coords = [], []
    for y in range(0, h, size):
        for x in range(0, w, size):
            hh, ww = min(size, h-y), min(size, w-x)
            coords.append([x, y, ww, hh])
            values.append(image[y:y+hh, x:x+ww].tobytes())
    return values, coords


def run(features, output, images, count=1000):
    meta, x, training = load_cache(features); q = x
    manifest = read(Path(features) / 'dataset_manifest.json')
    if not manifest.get('gallery'):
        raise RuntimeError('Actual image manifest is required for image tests')
    count = min(count, meta['test_images'], len(x))
    out = Path(output) / 'images'
    out.mkdir(parents=True, exist_ok=True)
    config = {'features': meta['files_sha256'], 'count': count,
              'code': __import__('verdi.common',fromlist=['runtime']).runtime()['code_sha256']}
    if (out / 'config.json').exists() and read(out / 'config.json') != config:
        raise RuntimeError('Image configuration changed; use a new output directory')
    save(out / 'config.json', config)
    if (out / 'summary.json').exists():
        return read(out / 'summary.json')
    owner = ConfiguredOwner(dict(enumerate(x[:count])), training, **binding(meta))
    codec, rows, capacity = ImageCodec(), [], {32: [], 64: [], 128: []}
    previous = None
    paths = {}
    for path in Path(images).rglob('*'):
        if path.is_file() and path.suffix.lower() in ('.jpg','.jpeg','.png'):
            if path.name in paths: raise ValueError('Ambiguous image filename: '+path.name)
            paths[path.name]=path
    for i, row in enumerate(manifest['gallery'][:count]):
        image_path=paths[row.get('filename') or Path(row['path']).name]
        if digest(image_path) != meta['image_sha256'][i]:
            raise RuntimeError(f'Image changed since encoding: {image_path.name}')
        with Image.open(image_path) as im:
            image = np.asarray(im.convert('RGB'))
        regions, coords = tiles(image, 64)
        context = [owner.db, i, 1, owner.model, owner.epoch, owner.records[i][2].hex(), list(image.shape), coords]
        start = time.perf_counter()
        obj = codec.encode(regions, context)
        enc_ms = (time.perf_counter()-start)*1000
        start = time.perf_counter()
        ok, status, recovered = codec.decode(obj, context, obj['expected'])
        dec_ms = (time.perf_counter()-start)*1000
        assert ok and recovered == regions and all(s == 'valid' for s in status)
        restored = np.zeros_like(image)
        for raw, (xx, yy, ww, hh) in zip(recovered, coords):
            restored[yy:yy+hh, xx:xx+ww] = np.frombuffer(raw, np.uint8).reshape(hh, ww, 3)
        assert np.array_equal(image, restored)
        for size in capacity:
            rr = regions if size == 64 else tiles(image, size)[0]
            room = [len(r)-4-len(zlib.compress(r, 9))-(76 if j == 0 else 44) for j, r in enumerate(rr)]
            possible = min(room) >= 0
            capacity[size].append({'image_id': i, 'regions': len(rr), 'embed_possible': possible,
                                   'minimum_room_bytes': min(room)})
            if size == 64:
                assert possible == (obj['mode'] == 'embed')
        target = min(1, len(regions)-1)
        bad = copy.deepcopy(obj)
        changed = bytearray(bad['tiles'][target]); changed[0] ^= 1
        bad['tiles'][target] = bytes(changed)
        ok, status, pixels = codec.decode(bad, context, obj['expected'])
        assert not ok and pixels is None and status[target] == 'tampered'
        assert all(s == 'valid' for j, s in enumerate(status) if j != target)
        bad = copy.deepcopy(obj)
        if obj['mode'] == 'sidecar':
            bad['sidecar'][target] = bytes(len(bad['sidecar'][target]))
        else:
            offset, size = 4+len(zlib.compress(regions[target], 9)), 76 if target == 0 else 44
            changed = bytearray(bad['tiles'][target]); changed[offset:offset+size] = bytes(size)
            bad['tiles'][target] = bytes(changed)
        ok, status, pixels = codec.decode(bad, context, obj['expected'])
        assert not ok and pixels is None and status[target] == 'unverifiable'
        assert all(s == 'valid' for j, s in enumerate(status) if j != target)
        bad = copy.deepcopy(obj)
        changed = bytearray(bad['meta']); changed[-1] ^= 1; bad['meta'] = bytes(changed)
        assert reject(lambda: codec.decode(bad, context, obj['expected']))
        if previous:
            old_obj, old_context = previous
            ok, _, pixels = codec.decode(obj, old_context, old_obj['expected'])
            assert not ok and pixels is None
        previous = obj, context
        record = list(owner.records[i])
        record[4] = sha(ser([obj['expected'], hashlib.sha256(obj['meta']).hexdigest(), obj['mode']]))
        owner.records[i] = tuple(record)
        payload = len(obj['meta']) + sum(map(len, obj['tiles'])) + sum(map(len, obj['sidecar']))
        public = len(ser({k: obj[k] for k in ('context', 'expected', 'mode')}))
        rows.append({'image_id': i, 'input_sha256': meta['image_sha256'][i], 'shape': list(image.shape),
                     'mode': obj['mode'], 'regions': len(regions), 'rgb_bytes': image.nbytes,
                     'payload_bytes': payload, 'stored_field_bytes': payload+public,
                     'encode_ms': enc_ms, 'decode_ms': dec_ms,
                     'exact_rgb': True, 'content_tamper_localized': True,
                     'packet_damage_unverifiable': True, 'manifest_tamper_rejected': True})
        if (i+1) % 50 == 0:
            print(f'Authenticated image recovery: {i+1}/{count}', flush=True)
    snap = owner.publish()
    qi = 0
    client = ExperimentClient(owner, Transport(owner.store), snap)
    # fine_only opens all tree descriptors, permitting direct inspection of every binding.
    _, _, cert = client.search(q[qi], min(10, count), mode='fine_only')
    committed = set()
    def walk(h):
        n = node_parse(cert['objects'][h])
        for s in n['slots']:
            assert s[4] == owner.records[s[0]][4]
            committed.add(s[0])
        for child in n['children']:
            walk(child)
    walk(bytes.fromhex(client.state['root']))
    assert committed == set(range(count))
    bindings = {i: owner.records[i][4] for i in range(count)}
    owner.insert(len(x)+1, training[0]); owner.publish()
    assert all(owner.records[i][4] == bindings[i] for i in range(count))
    result = {'dataset': meta['dataset'], 'images': count, 'all_rgb_exact': True,
              'attacks': {'content_tamper_localized': count, 'packet_damage_unverifiable': count,
                         'manifest_tamper_rejected': count, 'whole_record_substitution_rejected': count-1},
              'all_image_bindings_in_authenticated_descriptors': True, 'bindings_survive_index_update': True,
              'capacity': {str(s): {'images': len(rr), 'embedded_images': sum(r['embed_possible'] for r in rr),
                                    'embedding_fraction': sum(r['embed_possible'] for r in rr)/len(rr)}
                           for s, rr in capacity.items()},
              'modes': {m: {'images': len(rr), 'median_encode_ms': float(np.median([r['encode_ms'] for r in rr])),
                            'p95_encode_ms': float(np.quantile([r['encode_ms'] for r in rr], .95)),
                            'median_decode_ms': float(np.median([r['decode_ms'] for r in rr])),
                            'aggregate_stored_overhead_percent': 100*(sum(r['stored_field_bytes'] for r in rr)/sum(r['rgb_bytes'] for r in rr)-1)}
                        for m in ('embed', 'sidecar') if (rr := [r for r in rows if r['mode'] == m])},
              'scope': 'Default 64px cryptographic grid; 32/128px capacity-only sweeps; exact decoded RGB '
                       'rather than identical JPEG bitstreams; timings exclude input decoding and tiling; '
                       'no network image delivery measured.'}
    save(out / 'rows.json', rows)
    save(out / 'capacity_rows.json', capacity)
    save(out / 'summary.json', result)
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--features', required=True)
    p.add_argument('--images', required=True)
    p.add_argument('--output', required=True)
    p.add_argument('--count', type=int, default=1000)
    a = p.parse_args()
    run(a.features, a.output, a.images, a.count)
