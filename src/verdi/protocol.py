"""VERDI v2: authenticated encrypted objects and certified scalar filtering.

Reference implementation, not a production service. Queries stay at the client.
The benchmark uses a separate loopback TCP server process and counts actual
framed application bytes. TCP/IP and TLS overhead are not included.
"""
import copy
import hashlib
import heapq
import json
import math
import multiprocessing as mp
import secrets
import socket
import struct
import time
from pathlib import Path
import numpy as np
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from .tree import Tree, normalise

# Protocol checks below use assertions in this research prototype. Refuse
# optimized Python rather than silently disabling authenticated verification.
if not __debug__:
    raise RuntimeError('VERDI checks require Python without -O or PYTHONOPTIMIZE')

SCALE = 32767
SLOT = struct.Struct('>QQ32s32s32s')
HEAD = struct.Struct('>cQQQI32s')
ZERO = bytes(32)


def ser(x):
    return json.dumps(x, sort_keys=True, separators=(',', ':')).encode()


def sha(x):
    return hashlib.sha256(x).digest()


def ceil_sqrt(x):
    x = int(x)
    r = math.isqrt(x)
    return r + (r * r != x)


def norm(x):
    a = np.asarray(x, dtype=np.int64)
    return ceil_sqrt(a @ a)


def fixed(x):
    return np.rint(normalise(x) * SCALE).astype(np.int64)


class QuantTree(Tree):
    def __init__(self, features, capacity=16):
        super().__init__(features, [], capacity)

    def refresh(self, n):
        if n.leaf:
            assert n.ids
            n.ids.sort()
            x = np.stack([self.features[i] for i in n.ids])
            n.count, n.minid, n.height = len(n.ids), min(n.ids), 0
            n.counts = x.sum(0)
            n.center = (n.counts + n.count // 2) // n.count
            n.radius = max(norm(row - n.center) for row in x)
            for i in n.ids:
                self.locations[i] = n
        else:
            a, b = n.left, n.right
            a.parent = b.parent = n
            n.count = a.count + b.count
            n.minid = min(a.minid, b.minid)
            n.height = 1 + max(a.height, b.height)
            n.counts = a.counts + b.counts
            n.center = (n.counts + n.count // 2) // n.count
            n.radius = max(c.radius + norm(c.center - n.center) for c in (a, b))
        return n

    def split(self, ids):
        x = np.stack([self.features[i] for i in ids])
        a = int(np.argmax(((x - x[0]) ** 2).sum(1)))
        b = int(np.argmax(((x - x[a]) ** 2).sum(1)))
        delta = ((x - x[a]) ** 2).sum(1) - ((x - x[b]) ** 2).sum(1)
        order = sorted(range(len(ids)), key=lambda j: (int(delta[j]), ids[j]))
        mid = len(ids) // 2
        return [ids[j] for j in order[:mid]], [ids[j] for j in order[mid:]]

    def route(self, x, n):
        return int(((np.asarray(x) - n.center) ** 2).sum())

    def check(self):
        seen = set()
        def visit(n):
            if n.leaf:
                assert 1 <= len(n.ids) <= self.capacity
                assert not seen.intersection(n.ids)
                seen.update(n.ids)
                assert all(self.locations[i] is n for i in n.ids)
                ids = list(n.ids)
            else:
                assert n.left.parent is n and n.right.parent is n
                assert abs(n.left.height - n.right.height) <= 1
                assert n.height == 1 + max(n.left.height, n.right.height)
                ids = visit(n.left) + visit(n.right)
            x = np.stack([self.features[i] for i in ids])
            assert n.count == len(ids) and n.minid == min(ids)
            assert np.array_equal(n.counts, x.sum(0))
            assert np.array_equal(n.center, (n.counts + n.count // 2) // n.count)
            assert all(norm(row - n.center) <= n.radius for row in x)
            return ids
        if self.root:
            visit(self.root)
        assert seen == set(self.features)


class Quantizer:
    def __init__(self, lo, step):
        self.lo = np.asarray(lo, dtype=np.int64)
        self.step = np.asarray(step, dtype=np.int64)
        assert self.lo.shape == self.step.shape and (self.step > 0).all()
        self.d = len(self.lo)

    @classmethod
    def fit(cls, training):
        lo, hi = training.min(0), training.max(0)
        return cls(lo, np.maximum(1, (hi - lo + 62) // 63))

    def bytes(self):
        return struct.pack('>I', self.d) + self.lo.astype('>i4').tobytes() + self.step.astype('>u4').tobytes()

    @classmethod
    def from_bytes(cls, raw):
        d, = struct.unpack('>I', raw[:4])
        assert len(raw) == 4 + d * 8
        return cls(np.frombuffer(raw[4:4+d*4], '>i4'), np.frombuffer(raw[4+d*4:], '>u4'))

    def reconstruct(self, code):
        return self.lo + self.step * code

    def encode(self, x):
        code = np.clip((x - self.lo + self.step // 2) // self.step, 0, 63).astype(np.uint8)
        error = norm(x - self.reconstruct(code))
        bits = ((code[:, None] >> np.arange(5, -1, -1)) & 1).astype(np.uint8).ravel()
        return np.packbits(bits).tobytes() + struct.pack('>I', error)

    def decode(self, raw):
        code_bytes = (self.d * 6 + 7) // 8
        assert len(raw) == code_bytes + 4
        bits = np.unpackbits(np.frombuffer(raw[:code_bytes], np.uint8))[:self.d*6].reshape(self.d, 6)
        code = bits @ (1 << np.arange(5, -1, -1))
        error, = struct.unpack('>I', raw[-4:])
        return self.reconstruct(code), error


def node_parse(raw):
    assert len(raw) >= HEAD.size
    kind, nid, count, low, height, summary = HEAD.unpack(raw[:HEAD.size])
    assert kind in (b'L', b'I') and count > 0
    rest = raw[HEAD.size:]
    if kind == b'I':
        assert len(rest) == 64
        children, slots = [rest[:32], rest[32:]], []
    else:
        assert len(rest) == count * SLOT.size and height == 0
        slots = [SLOT.unpack(rest[j:j+SLOT.size]) for j in range(0, len(rest), SLOT.size)]
        ids = [r[0] for r in slots]
        assert ids == sorted(set(ids)) and low == ids[0]
        children = []
    return {'nid': nid, 'count': count, 'min': low, 'height': height,
            'summary': summary, 'children': children, 'slots': slots}


class Owner:
    def __init__(self, features, training, capacity=16):
        self.tree = QuantTree(features, capacity)
        self.quantizer = Quantizer.fit(training)
        self.d = self.quantizer.d
        self.keys = {k: secrets.token_bytes(32) for k in ('full', 'fine', 'summary')}
        self.signing = Ed25519PrivateKey.generate()
        self.db, self.model, self.epoch = 'VERDI', 'integer16-scale32767', 1
        self.store, self.records, self.summary_cache = {}, {}, {}
        self.config = self.put(self.enc('summary', self.quantizer.bytes(), self.context('config', 0)))
        for i, x in features.items():
            self.add_record(i, x)
        self.version = 0

    def put(self, raw):
        h = sha(raw)
        self.store[h] = raw
        return h

    def context(self, kind, i, revision=1, full=None):
        return ser([kind, self.db, self.model, self.epoch, int(i), revision,
                    full.hex() if full else None, self.config.hex() if kind == 'fine' else None])

    def enc(self, kind, plain, aad):
        n = secrets.token_bytes(12)
        return n + AESGCM(self.keys[kind]).encrypt(n, plain, aad)

    def add_record(self, i, x):
        x = np.asarray(x, dtype=np.int64)
        assert x.shape == (self.d,) and ((x >= -SCALE) & (x <= SCALE)).all()
        revision = self.records[i][1] + 1 if i in self.records else 1
        full = self.put(self.enc('full', x.astype('>i2').tobytes(), self.context('full', i, revision)))
        fine = self.put(self.enc('fine', self.quantizer.encode(x), self.context('fine', i, revision, full)))
        # The vector benchmark excludes image transfers. This binding slot is
        # replaced by the image/metadata/sidecar commitment in an image service.
        image = sha(ser(['image-not-materialized-in-vector-benchmark', i, revision]))
        self.records[i] = (int(i), revision, full, fine, image)

    def publish(self):
        def visit(n):
            raw_summary = n.center.astype('>i2').tobytes() + struct.pack('>Q', n.radius)
            cachekey = (n.nid, raw_summary)
            if cachekey not in self.summary_cache:
                self.summary_cache[cachekey] = self.put(self.enc('summary', raw_summary, self.context('summary', n.nid)))
            hsummary = self.summary_cache[cachekey]
            suffix = b''.join(SLOT.pack(*self.records[i]) for i in n.ids) if n.leaf else visit(n.left) + visit(n.right)
            return self.put(HEAD.pack(b'L' if n.leaf else b'I', n.nid, n.count, n.minid, n.height, hsummary) + suffix)
        root = visit(self.tree.root) if self.tree.root else ZERO
        self.version += 1
        state = ser({'db':self.db, 'model':self.model, 'epoch':self.epoch,
                     'version':self.version, 'root':root.hex(), 'config':self.config.hex(),
                     'count':len(self.tree.features), 'd':self.d, 'scale':SCALE,
                     'capacity':self.tree.capacity})
        packet = struct.pack('>I', len(state)) + state + self.signing.sign(state)
        return self.put(packet)

    def insert(self, i, x):
        self.tree.insert(i, x)
        self.add_record(i, x)

    def delete(self, i):
        self.tree.delete(i)


def recv_exact(sock, n):
    out = bytearray()
    while len(out) < n:
        part = sock.recv(n - len(out))
        if not part:
            raise ConnectionError('Incomplete response')
        out.extend(part)
    return bytes(out)


def server_main(store, pipe):
    server = socket.socket()
    server.bind(('127.0.0.1', 0))
    server.listen(1)
    pipe.send(server.getsockname()[1])
    conn, _ = server.accept()
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    try:
        while True:
            size, = struct.unpack('>I', recv_exact(conn, 4))
            request = recv_exact(conn, size)
            if request == b'X':
                break
            count, = struct.unpack('>I', request[:4])
            assert len(request) == 4 + count * 32
            objects = [store[request[j:j+32]] for j in range(4, len(request), 32)]
            response = struct.pack('>I', count) + b''.join(struct.pack('>I', len(o)) + o for o in objects)
            conn.sendall(struct.pack('>I', len(response)) + response)
    finally:
        conn.close()
        server.close()


class Transport:
    def __init__(self, store, network=False, timeout=30):
        if timeout is not None and timeout <= 0:
            raise ValueError('Socket inactivity timeout must be positive or None')
        self.store = store
        self.network = network
        self.sock = self.process = None
        if network:
            parent, child = mp.Pipe(False)
            self.process = mp.Process(target=server_main, args=(store, child))
            self.process.start()
            port = parent.recv()
            self.sock = socket.create_connection(('127.0.0.1', port), timeout=timeout)
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.reset()

    def reset(self):
        self.bytes, self.rounds, self.parts = 0, 0, {}

    def fetch(self, hashes, kind):
        if not hashes:
            return []
        request = struct.pack('>I', len(hashes)) + b''.join(hashes)
        if self.network:
            self.sock.sendall(struct.pack('>I', len(request)) + request)
            size, = struct.unpack('>I', recv_exact(self.sock, 4))
            response = recv_exact(self.sock, size)
        else:
            objects = [self.store[h] for h in hashes]
            response = struct.pack('>I', len(objects)) + b''.join(struct.pack('>I',len(o)) + o for o in objects)
        count, = struct.unpack('>I', response[:4])
        assert count == len(hashes)
        cursor, objects = 4, []
        for h in hashes:
            size, = struct.unpack('>I', response[cursor:cursor+4])
            cursor += 4
            obj = response[cursor:cursor+size]
            cursor += size
            assert len(obj) == size and sha(obj) == h, 'Authentication before decryption'
            objects.append(obj)
        assert cursor == len(response)
        size = 8 + len(request) + len(response)
        self.bytes += size
        self.rounds += 1
        self.parts[kind] = self.parts.get(kind, 0) + size
        return objects

    def close(self):
        if self.sock:
            self.sock.sendall(struct.pack('>I',1) + b'X')
            self.sock.close()
            self.process.join(timeout=5)
            assert self.process.exitcode == 0


class Client:
    def __init__(self, owner, transport, snapshot):
        self.keys = dict(owner.keys)
        self.public_key = owner.signing.public_key()
        self.transport = transport
        self.snapshot = snapshot  # trusted owner-channel digest for this query
        self.objects = {}

    def fetch(self, hashes, kind):
        missing = list(dict.fromkeys(h for h in hashes if h not in self.objects))
        for h, raw in zip(missing, self.transport.fetch(missing, kind)):
            self.objects[h] = raw
        return [self.objects[h] for h in hashes]

    def open_state(self):
        raw = self.fetch([self.snapshot], 'snapshot')[0]
        length, = struct.unpack('>I', raw[:4])
        assert len(raw) == 4 + length + 64
        self.public_key.verify(raw[-64:], raw[4:4+length])
        self.state = json.loads(raw[4:4+length])
        assert self.state['d'] > 0 and self.state['scale'] == SCALE
        return self.state

    def aad(self, kind, i, revision=1, full=None):
        s = self.state
        return ser([kind, s['db'], s['model'], s['epoch'], int(i), revision,
                    full.hex() if full else None, s['config'] if kind == 'fine' else None])

    def decrypt(self, kind, h, aad):
        raw = self.objects[h]
        assert sha(raw) == h
        return AESGCM(self.keys[kind]).decrypt(raw[:12], raw[12:], aad)

    def summary(self, node):
        raw = self.decrypt('summary', node['summary'], self.aad('summary',node['nid']))
        d = self.state['d']
        assert len(raw) == d * 2 + 8
        return np.frombuffer(raw[:d*2], '>i2').astype(np.int64), struct.unpack('>Q',raw[-8:])[0]

    def full(self, slot):
        i, revision, he, _, _ = slot
        raw = self.decrypt('full', he, self.aad('full', i, revision))
        assert len(raw) == self.state['d'] * 2
        return np.frombuffer(raw, '>i2').astype(np.int64)

    def fine(self, slot):
        i, revision, he, hf, _ = slot
        return self.quantizer.decode(self.decrypt('fine',hf,self.aad('fine',i,revision,he)))

    @staticmethod
    def excluded(upper, low, top, k):
        return len(top) >= k and (upper < top[-1][0] or (upper == top[-1][0] and low > top[-1][1]))

    def search(self, q, k=10, batch=16, fullscan=False):
        self.objects = {}
        self.transport.reset()
        start = time.perf_counter()
        state = self.open_state()
        assert 1 <= k <= state['count'] and batch >= 1
        q = np.asarray(q, dtype=np.int64)
        assert q.shape == (state['d'],) and ((q >= -SCALE) & (q <= SCALE)).all()
        qnorm = norm(q)
        self.quantizer = None
        if not fullscan:
            hc = bytes.fromhex(state['config'])
            self.fetch([hc], 'quantizer')
            raw = self.decrypt('summary', hc, self.aad('config', 0))
            self.quantizer = Quantizer.from_bytes(raw)
        root = bytes.fromhex(state['root'])
        nodes, slots, done, pruned, scores, top = {}, {}, set(), set(), {}, []
        queue, serial = [], 0

        def offer_nodes(hashes):
            nonlocal serial
            raw_nodes = self.fetch(hashes, 'headers')
            parsed = [node_parse(raw) for raw in raw_nodes]
            if not fullscan:
                self.fetch([n['summary'] for n in parsed], 'coarse_summaries')
            for h, n in zip(hashes, parsed):
                assert h not in nodes
                nodes[h] = n
                if fullscan:
                    upper = 0
                else:
                    center, radius = self.summary(n)
                    upper = int(q @ center) + qnorm * radius
                serial += 1
                heapq.heappush(queue, (-upper, n['min'], serial, 'node', h))

        offer_nodes([root])
        while queue:
            actions = []
            while queue and len(actions) < batch:
                neg, low, _, kind, ref = heapq.heappop(queue)
                if not fullscan and self.excluded(-neg, low, top, k):
                    if kind == 'node':
                        pruned.add(ref)
                    continue
                actions.append((kind, ref))
            children, newslots, exact = [], [], []
            for kind, ref in actions:
                if kind == 'record':
                    exact.append(slots[ref])
                    continue
                n = nodes[ref]
                if n['children']:
                    children.extend(n['children'])
                else:
                    for slot in n['slots']:
                        assert slot[0] not in slots
                        slots[slot[0]] = slot
                        newslots.append(slot)
            if children:
                offer_nodes(children)
            if newslots:
                if fullscan:
                    exact.extend(newslots)
                else:
                    self.fetch([s[3] for s in newslots], 'fine_codes')
                    for slot in newslots:
                        center, error = self.fine(slot)
                        upper = int(q @ center) + qnorm * error
                        serial += 1
                        heapq.heappush(queue, (-upper, slot[0], serial, 'record', slot[0]))
            if exact:
                self.fetch([s[2] for s in exact], 'full_vectors')
                for slot in exact:
                    i = slot[0]
                    assert i not in done
                    done.add(i)
                    scores[i] = int(q @ self.full(slot))
                top = sorted([(s,i) for i,s in scores.items()], key=lambda a:(-a[0],a[1]))[:k]
        transcript = {'objects':dict(self.objects), 'pruned':set(pruned), 'done':set(done), 'top':list(top), 'fullscan':fullscan}
        self.verify(q, k, transcript)
        elapsed = time.perf_counter() - start
        return top, {'records':len(done), 'record_pruning':1-len(done)/state['count'],
                     'coarse_pruned_nodes':len(pruned), 'opened_headers':len(nodes),
                     'bytes':self.transport.bytes, 'rounds':self.transport.rounds,
                     'parts':dict(self.transport.parts), 'seconds':elapsed}, transcript

    def verify(self, q, k, transcript):
        # Independent certificate audit. No owner-side plaintext is consulted.
        self.objects = transcript['objects']
        for h, raw in self.objects.items():
            assert sha(raw) == h
        raw = self.objects[self.snapshot]
        length, = struct.unpack('>I', raw[:4])
        assert len(raw) == length + 68
        self.public_key.verify(raw[-64:], raw[4:4+length])
        self.state = json.loads(raw[4:4+length])
        fullscan = transcript['fullscan']
        if not fullscan:
            hc = bytes.fromhex(self.state['config'])
            self.quantizer = Quantizer.from_bytes(self.decrypt('summary', hc, self.aad('config', 0)))
        qnorm, covered, seen, evaluated, used_prunes = norm(q), 0, set(), {}, set()
        top = transcript['top']
        assert len(top) == k and top == sorted(top,key=lambda a:(-a[0],a[1]))
        visited = set()

        def walk(h):
            nonlocal covered
            assert h not in visited
            visited.add(h)
            n = node_parse(self.objects[h])
            if h in transcript['pruned']:
                assert not fullscan
                center, radius = self.summary(n)
                upper = int(q @ center) + qnorm * radius
                assert self.excluded(upper, n['min'], top, k)
                covered += n['count']
                used_prunes.add(h)
                return n
            if n['children']:
                a, b = [walk(c) for c in n['children']]
                assert n['count'] == a['count'] + b['count']
                assert n['min'] == min(a['min'],b['min'])
                assert n['height'] == 1 + max(a['height'],b['height'])
            else:
                for slot in n['slots']:
                    i = slot[0]
                    assert i not in seen
                    seen.add(i)
                    covered += 1
                    if i in transcript['done']:
                        evaluated[i] = int(q @ self.full(slot))
                    else:
                        assert not fullscan
                        center, error = self.fine(slot)
                        upper = int(q @ center) + qnorm * error
                        assert self.excluded(upper, i, top, k)
            return n

        walk(bytes.fromhex(self.state['root']))
        assert covered == self.state['count']
        assert used_prunes == transcript['pruned']
        assert set(evaluated) == transcript['done']
        actual = sorted([(s,i) for i,s in evaluated.items()], key=lambda a:(-a[0],a[1]))[:k]
        assert actual == top
        return True


def oracle(features, q, k):
    return sorted([(int(q @ x),i) for i,x in features.items()],key=lambda a:(-a[0],a[1]))[:k]


def reject(fn):
    try:
        fn()
    except Exception:
        return True
    return False
