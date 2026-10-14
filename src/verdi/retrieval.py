"""Certified scalar filtering, coverage verification and internal layouts."""
import heapq, json, struct, time
import numpy as np
from .protocol import (Owner, Client, Transport, QuantTree, Quantizer, SCALE, SLOT, HEAD, ZERO,
                       fixed, norm, sha, ser, node_parse, oracle, reject)

class BitQuantizer(Quantizer):
    def __init__(self, lo, step, bits=6):
        super().__init__(lo, step)
        assert bits in (4, 6, 8)
        self.bits, self.maximum = bits, (1 << bits) - 1

    @classmethod
    def fit(cls, training, bits=6):
        lo, hi = training.min(0), training.max(0)
        maximum = (1 << bits) - 1
        return cls(lo, np.maximum(1, (hi - lo + maximum - 1) // maximum), bits)

    def bytes(self):
        prefix = struct.pack('>I', self.d)
        if self.bits != 6:
            prefix += struct.pack('>I', self.bits)
        return prefix + self.lo.astype('>i4').tobytes() + self.step.astype('>u4').tobytes()

    @classmethod
    def from_bytes(cls, raw):
        d, = struct.unpack('>I', raw[:4])
        if len(raw) == 4 + d * 8:
            offset, bits = 4, 6
        else:
            assert len(raw) == 8 + d * 8
            bits, = struct.unpack('>I', raw[4:8])
            offset = 8
        return cls(np.frombuffer(raw[offset:offset+d*4], '>i4'),
                   np.frombuffer(raw[offset+d*4:], '>u4'), bits)

    def encode(self, x):
        code = np.clip((x - self.lo + self.step // 2) // self.step,
                       0, self.maximum).astype(np.uint8)
        error = norm(x - self.reconstruct(code))
        bits = ((code[:, None] >> np.arange(self.bits-1, -1, -1)) & 1).astype(np.uint8).ravel()
        return np.packbits(bits).tobytes() + struct.pack('>I', error)

    def decode(self, raw):
        size = (self.d * self.bits + 7) // 8
        assert len(raw) == size + 4
        bits = np.unpackbits(np.frombuffer(raw[:size], np.uint8))[:self.d*self.bits].reshape(self.d, self.bits)
        code = bits @ (1 << np.arange(self.bits-1, -1, -1))
        error, = struct.unpack('>I', raw[-4:])
        return self.reconstruct(code), error


def flat_snapshot(owner, tree_snapshot):
    raw = owner.store[tree_snapshot]
    length, = struct.unpack('>I', raw[:4])
    state = json.loads(raw[4:4+length])
    ids = sorted(owner.tree.features)
    body = b'F' + struct.pack('>Q', len(ids)) + b''.join(SLOT.pack(*owner.records[i]) for i in ids)
    state['root'] = owner.put(body).hex()
    state['layout'] = 'flat-list-v1'
    encoded = ser(state)
    return owner.put(struct.pack('>I', len(encoded)) + encoded + owner.signing.sign(encoded))


def flat_parse(raw):
    assert len(raw) >= 9 and raw[:1] == b'F'
    count, = struct.unpack('>Q', raw[1:9])
    assert len(raw) == 9 + count * SLOT.size
    slots = [SLOT.unpack(raw[i:i+SLOT.size]) for i in range(9, len(raw), SLOT.size)]
    ids = [s[0] for s in slots]
    assert ids == sorted(set(ids))
    return slots


class ExperimentClient(Client):
    def open_quantizer(self):
        h = bytes.fromhex(self.state['config'])
        self.fetch([h], 'quantizer')
        self.quantizer = BitQuantizer.from_bytes(self.decrypt('summary', h, self.aad('config', 0)))
        assert self.quantizer.d == self.state['d']

    def search(self, q, k=10, batch=16, mode='full'):
        assert mode in ('full', 'fine_only', 'coarse_only', 'scan', 'flat_fine', 'flat_scan')
        self.objects = {}
        self.transport.reset()
        start, cpu = time.perf_counter(), time.process_time()
        state = self.open_state()
        assert 1 <= k <= state['count'] and batch >= 1
        q = np.asarray(q, dtype=np.int64)
        assert q.shape == (state['d'],) and ((q >= -SCALE) & (q <= SCALE)).all()
        fine = mode in ('full', 'fine_only', 'flat_fine')
        coarse = mode in ('full', 'coarse_only')
        flat = mode.startswith('flat_')
        qnorm = norm(q)
        self.quantizer = None
        if fine:
            self.open_quantizer()
        root = bytes.fromhex(state['root'])
        nodes, slots, done, pruned, scores, top = {}, {}, set(), set(), {}, []
        queue, serial = [], 0

        def offer_records(newslots):
            nonlocal serial
            self.fetch([s[3] for s in newslots], 'fine_codes')
            for slot in newslots:
                center, error = self.fine(slot)
                upper = int(q @ center) + qnorm * error
                serial += 1
                heapq.heappush(queue, (-upper, slot[0], serial, 'record', slot[0]))

        def offer_nodes(hashes):
            nonlocal serial
            parsed = [node_parse(raw) for raw in self.fetch(hashes, 'headers')]
            if coarse:
                self.fetch([n['summary'] for n in parsed], 'coarse_summaries')
            for h, n in zip(hashes, parsed):
                assert h not in nodes
                nodes[h] = n
                if coarse:
                    center, radius = self.summary(n)
                    upper = int(q @ center) + qnorm * radius
                else:
                    upper = float('inf')  # Open all committed branches before exact candidates.
                serial += 1
                heapq.heappush(queue, (-upper, n['min'], serial, 'node', h))

        if flat:
            assert state.get('layout') == 'flat-list-v1'
            listing = flat_parse(self.fetch([root], 'headers')[0])
            assert len(listing) == state['count']
            slots = {s[0]: s for s in listing}
            if fine:
                offer_records(listing)
            else:
                for slot in listing:
                    serial += 1
                    heapq.heappush(queue, (0, slot[0], serial, 'record', slot[0]))
        else:
            offer_nodes([root])
        while queue:
            actions = []
            action_limit = state['count'] if mode == 'flat_scan' else batch
            while queue and len(actions) < action_limit:
                neg, low, _, kind, ref = heapq.heappop(queue)
                if (fine or coarse) and self.excluded(-neg, low, top, k):
                    if kind == 'node':
                        pruned.add(ref)
                    continue
                actions.append((kind, ref))
            children, newslots, exact = [], [], []
            for kind, ref in actions:
                if kind == 'record':
                    exact.append(slots[ref])
                else:
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
                if fine:
                    offer_records(newslots)
                else:
                    exact.extend(newslots)
            if exact:
                self.fetch([s[2] for s in exact], 'full_vectors')
                for slot in exact:
                    i = slot[0]
                    assert i not in done
                    done.add(i)
                    scores[i] = int(q @ self.full(slot))
                top = sorted([(s, i) for i, s in scores.items()], key=lambda a: (-a[0], a[1]))[:k]
        transcript = {'objects': dict(self.objects), 'pruned': pruned, 'done': done,
                      'top': top, 'fine': fine, 'coarse': coarse, 'flat': flat}
        verify_start, verify_cpu = time.perf_counter(), time.process_time()
        self.verify(q, k, transcript)
        verify_seconds, verify_cpu_seconds = time.perf_counter()-verify_start, time.process_time()-verify_cpu
        stats = {'records': len(done), 'fine_records': len(slots) if fine else 0,
                 'coarse_pruned_nodes': len(pruned), 'opened_headers': 1 if flat else len(nodes),
                 'bytes': self.transport.bytes, 'rounds': self.transport.rounds,
                 'parts': dict(self.transport.parts), 'seconds': time.perf_counter()-start,
                 'client_cpu_seconds': time.process_time()-cpu,
                 'verification_seconds': verify_seconds, 'verification_cpu_seconds': verify_cpu_seconds}
        return top, stats, transcript

    def verify(self, q, k, transcript):
        self.objects = transcript['objects']
        for h, raw in self.objects.items():
            assert sha(raw) == h
        raw = self.objects[self.snapshot]
        length, = struct.unpack('>I', raw[:4])
        assert len(raw) == length + 68
        self.public_key.verify(raw[-64:], raw[4:4+length])
        self.state = json.loads(raw[4:4+length])
        assert 1 <= k <= self.state['count']
        fine, coarse, flat = transcript['fine'], transcript['coarse'], transcript['flat']
        if fine:
            h = bytes.fromhex(self.state['config'])
            self.quantizer = BitQuantizer.from_bytes(self.decrypt('summary', h, self.aad('config', 0)))
            assert self.quantizer.d == self.state['d']
        qnorm, covered, seen, evaluated, used_prunes = norm(q), 0, set(), {}, set()
        top = transcript['top']
        assert len(top) == k and top == sorted(top, key=lambda a: (-a[0], a[1]))
        visited = set()

        def check_slot(slot):
            nonlocal covered
            i = slot[0]
            assert i not in seen
            seen.add(i)
            covered += 1
            if i in transcript['done']:
                evaluated[i] = int(q @ self.full(slot))
            else:
                assert fine
                center, error = self.fine(slot)
                assert self.excluded(int(q @ center) + qnorm * error, i, top, k)

        def walk(h):
            nonlocal covered
            assert h not in visited
            visited.add(h)
            n = node_parse(self.objects[h])
            if h in transcript['pruned']:
                assert coarse
                center, radius = self.summary(n)
                assert self.excluded(int(q @ center) + qnorm * radius, n['min'], top, k)
                covered += n['count']
                used_prunes.add(h)
                return n
            if n['children']:
                a, b = [walk(c) for c in n['children']]
                assert n['count'] == a['count'] + b['count']
                assert n['min'] == min(a['min'], b['min'])
                assert n['height'] == 1 + max(a['height'], b['height'])
            else:
                for slot in n['slots']:
                    check_slot(slot)
            return n

        root = bytes.fromhex(self.state['root'])
        if flat:
            assert self.state.get('layout') == 'flat-list-v1'
            for slot in flat_parse(self.objects[root]):
                check_slot(slot)
        else:
            walk(root)
        assert covered == self.state['count']
        assert used_prunes == transcript['pruned']
        assert set(evaluated) == transcript['done']
        actual = sorted([(s, i) for i, s in evaluated.items()], key=lambda a: (-a[0], a[1]))[:k]
        assert actual == top
        return True


def reachable(owner, snapshot):
    raw = owner.store[snapshot]
    size, = struct.unpack('>I', raw[:4])
    state = json.loads(raw[4:4+size])
    result = {snapshot, bytes.fromhex(state['config'])}
    root = bytes.fromhex(state['root'])
    if root == ZERO:
        return result
    def slots(ss):
        for s in ss:
            result.update((s[2], s[3]))
    def walk(h):
        result.add(h)
        n = node_parse(owner.store[h])
        result.add(n['summary'])
        slots(n['slots'])
        for child in n['children']:
            walk(child)
    if state.get('layout') == 'flat-list-v1':
        result.add(root)
        slots(flat_parse(owner.store[root]))
    else:
        walk(root)
    return result


def summarize(rows):
    groups = {}
    for r in rows:
        groups.setdefault(r['query'], []).append(r)
    means = np.asarray([np.mean([r['bytes'] for r in group]) for group in groups.values()])
    boot = np.random.default_rng(911).choice(means, (2000, len(means)), replace=True).mean(1)
    for group in groups.values():
        assert len({r['bytes'] for r in group}) == 1
        assert len({r['records'] for r in group}) == 1
    return {'queries': len(groups), 'runs': len(rows), 'all_exact': True,
            'mean_bytes': float(np.mean([r['bytes'] for r in rows])),
            'mean_bytes_query_bootstrap_ci95': np.quantile(boot, [.025, .975]).tolist(),
            'mean_records': float(np.mean([r['records'] for r in rows])),
            'mean_fine_records': float(np.mean([r['fine_records'] for r in rows])),
            'mean_rounds': float(np.mean([r['rounds'] for r in rows])),
            'mean_coarse_pruned_nodes': float(np.mean([r['coarse_pruned_nodes'] for r in rows])),
            'median_ms': float(np.median([r['seconds']*1000 for r in rows])),
            'p95_ms': float(np.quantile([r['seconds']*1000 for r in rows], .95)),
            'median_client_cpu_ms': float(np.median([r['client_cpu_seconds']*1000 for r in rows])),
            'median_verification_ms': float(np.median([r['verification_seconds']*1000 for r in rows])),
            'mean_parts': {p: float(np.mean([r['parts'].get(p, 0) for r in rows]))
                           for p in sorted(set().union(*(r['parts'] for r in rows)))}}
