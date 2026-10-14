"""Reversible regional image authentication with an explicit sidecar fallback."""
import hashlib, hmac, json, secrets, struct, zlib
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from .protocol import ser

def ctr(key,iv,data):
    e=Cipher(algorithms.AES(key),modes.CTR(iv)).encryptor();return e.update(data)+e.finalize()


class ImageCodec:
    def __init__(self):
        self.kenc=secrets.token_bytes(32);self.kpayload=secrets.token_bytes(32);self.kmeta=secrets.token_bytes(32)
        self.kglobal=secrets.token_bytes(32);self.kregion=secrets.token_bytes(32)
    def region_key(self,context,iv,j):
        return hmac.new(self.kenc,ser(['carrier-key',context,iv.hex(),j]),hashlib.sha256).digest()
    def encode(self,tiles,context):
        compressed=[zlib.compress(x,9) for x in tiles]
        lengths=[76 if j==0 else 44 for j in range(len(tiles))]
        embed=all(len(t)-4-len(z)>=need for t,z,need in zip(tiles,compressed,lengths))
        mode='embed' if embed else 'sidecar'
        ivs=[secrets.token_bytes(16) for _ in tiles]
        meta={'mode':mode,'lengths':[len(t) for t in tiles],'zlen':[len(z) for z in compressed] if embed else [],'ivs':[iv.hex() for iv in ivs]}
        nonce=secrets.token_bytes(12);mc=nonce+AESGCM(self.kmeta).encrypt(nonce,ser(meta),ser(['meta',context]));mh=hashlib.sha256(mc).digest()
        plain=[struct.pack('>I',len(z))+z+b'\0'*(len(t)-4-len(z)) for t,z in zip(tiles,compressed)] if embed else tiles
        original=[ctr(self.region_key(context,iv,j),iv,t) for j,(iv,t) in enumerate(zip(ivs,plain))]
        g=hmac.new(self.kglobal,ser(['global',context])+mh+b''.join(original),hashlib.sha256).digest()
        packets=[];marked=[]
        for j,C in enumerate(original):
            tag=hmac.new(self.kregion,ser(['region',context,j])+mh+C,hashlib.sha256).digest()[:16]
            n=secrets.token_bytes(12);a=tag+(g if j==0 else b'');p=n+AESGCM(self.kpayload).encrypt(n,a,ser(['payload',context,j])+mh);packets.append(p)
            assert len(p)==lengths[j]
            if embed:
                start=4+len(compressed[j]);marked.append(C[:start]+p+C[start+len(p):])
            else:marked.append(C)
        expected=hashlib.sha256(mc+b''.join(marked)+ (b''.join(packets) if not embed else b'')).hexdigest()
        return {'context':context,'meta':mc,'tiles':marked,'sidecar':packets if not embed else [],'expected':expected,'mode':mode}
    def decode(self,obj,expected_context=None,expected_digest=None):
        # Expected values come from the verified record descriptor, not the CS.
        if expected_context is not None and obj['context']!=expected_context:
            return False,[],None
        context=obj['context'];mc=obj['meta'];meta=json.loads(AESGCM(self.kmeta).decrypt(mc[:12],mc[12:],ser(['meta',context])))
        mh=hashlib.sha256(mc).digest();statuses=[];restored=[];g=None
        for j,C in enumerate(obj['tiles']):
            try:
                need=76 if j==0 else 44
                if meta['mode']=='embed':
                    start=4+meta['zlen'][j];p=C[start:start+need]
                    iv=bytes.fromhex(meta['ivs'][j])
                    stream=ctr(self.region_key(context,iv,j),iv,bytes(len(C)))
                    r=C[:start]+stream[start:start+need]+C[start+need:]
                else:p=obj['sidecar'][j];r=C
                a=AESGCM(self.kpayload).decrypt(p[:12],p[12:],ser(['payload',context,j])+mh)
                assert len(a)==(48 if j==0 else 16)
                if j==0:g=a[16:]
                tag=hmac.new(self.kregion,ser(['region',context,j])+mh+r,hashlib.sha256).digest()[:16]
                statuses.append('valid' if hmac.compare_digest(tag,a[:16]) else 'tampered');restored.append(r)
            except Exception:statuses.append('unverifiable');restored.append(None)
        global_ok=False
        if g is not None and all(x is not None for x in restored):
            expected=hmac.new(self.kglobal,ser(['global',context])+mh+b''.join(restored),hashlib.sha256).digest();global_ok=hmac.compare_digest(g,expected)
        actual=hashlib.sha256(mc+b''.join(obj['tiles'])+(b''.join(obj['sidecar']) if meta['mode']=='sidecar' else b'')).hexdigest()
        wanted=obj['expected'] if expected_digest is None else expected_digest
        accepted=global_ok and all(s=='valid' for s in statuses) and actual==wanted
        pixels=None
        if accepted:
            pixels=[]
            for j,r in enumerate(restored):
                iv=bytes.fromhex(meta['ivs'][j])
                p=ctr(self.region_key(context,iv,j),iv,r)
                if meta['mode']=='embed':
                    ell=struct.unpack('>I',p[:4])[0];assert ell==meta['zlen'][j]
                    p=zlib.decompress(p[4:4+ell])
                assert len(p)==meta['lengths'][j];pixels.append(p)
        return accepted,statuses,pixels

def tiles(image, size):
    h, w, _ = image.shape
    values, coords = [], []
    for y in range(0, h, size):
        for x in range(0, w, size):
            hh, ww = min(size, h-y), min(size, w-x)
            coords.append([x, y, ww, hh])
            values.append(image[y:y+hh, x:x+ww].tobytes())
    return values, coords


def image_commitment(obj):
    """Digest stored in the authenticated descriptor's image slot."""
    from .protocol import sha
    return sha(ser([obj['expected'], hashlib.sha256(obj['meta']).hexdigest(), obj['mode']]))


def bind_image(owner, codec, record_id, image, region_size=64):
    """Bind canonical RGB to an existing feature record before publication."""
    import numpy as np
    image = np.asarray(image)
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError('Expected nonempty uint8 RGB pixels')
    if min(image.shape[:2]) < 1 or region_size < 1:
        raise ValueError('Invalid image or region size')
    regions, coords = tiles(image, region_size)
    slot = owner.records[record_id]
    context = [owner.db, int(record_id), slot[1], owner.model, owner.epoch,
               slot[2].hex(), list(image.shape), coords]
    obj = codec.encode(regions, context)
    record = list(slot)
    record[4] = image_commitment(obj)
    owner.records[record_id] = tuple(record)
    return obj


def recover_image(codec, obj, authenticated_slot, verified_state):
    """Only release RGB after descriptor binding and whole-image acceptance."""
    import numpy as np
    i, revision, feature_hash, _, commitment = authenticated_slot
    if image_commitment(obj) != commitment:
        raise ValueError('Image commitment mismatch')
    context = obj['context']
    expected = [verified_state['db'], i, revision, verified_state['model'],
                verified_state['epoch'], feature_hash.hex()]
    if context[:6] != expected:
        raise ValueError('Record context mismatch')
    ok, status, regions = codec.decode(obj, context, obj['expected'])
    if not ok:
        raise ValueError('Image authentication failed: ' + ','.join(status))
    shape, coords = context[6:]
    image = np.zeros(shape, dtype=np.uint8)
    for raw, (x, y, w, h) in zip(regions, coords):
        image[y:y+h, x:x+w] = np.frombuffer(raw, np.uint8).reshape(h,w,3)
    return image
