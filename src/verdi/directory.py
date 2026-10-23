"""ID-paged authenticated directory with complete fine-bound verification.

Pages have fixed ID ranges and a binary authenticated directory. Geometric
summaries are absent. Use RetrievalClient with mode='fine_only'. The reference
publisher enumerates live pages, so publication time is not logarithmic.
"""
from .owner import ConfiguredFlatOwner
from .protocol import SLOT, HEAD, ZERO, SCALE, ser
from numbers import Integral


class DirectoryOwner(ConfiguredFlatOwner):
    page_universe = 65536

    def __init__(self, features, training, capacity=16, **kwargs):
        if not isinstance(capacity, Integral) or capacity < 1:
            raise ValueError('Page capacity must be positive')
        capacity = int(capacity)
        for i in features:
            self._check_id(i, capacity)
        super().__init__(features, training, capacity=capacity, **kwargs)

    def _check_id(self, record_id, capacity=None):
        capacity = self.tree.capacity if capacity is None else capacity
        if not isinstance(record_id, Integral) or not 0 <= record_id < capacity*self.page_universe:
            raise ValueError('Record ID outside directory universe')

    def insert(self, i, x):
        self._check_id(i)
        super().insert(i, x)

    def publish(self):
        pages = {}
        for i in sorted(self.features):
            pages.setdefault(i // self.tree.capacity, []).append(i)

        def visit(lo, hi, nid):
            live = [p for p in pages if lo <= p < hi]
            if not live:
                return None
            if hi - lo == 1:
                ids = pages[lo]
                raw = HEAD.pack(b'L', nid, len(ids), min(ids), 0, ZERO)
                return self.put(raw + b''.join(SLOT.pack(*self.records[i]) for i in ids)), len(ids), min(ids), 0
            mid = (lo+hi)//2
            a, b = visit(lo, mid, 2*nid), visit(mid, hi, 2*nid+1)
            if a is None:
                return b
            if b is None:
                return a
            count, low, height = a[1]+b[1], min(a[2], b[2]), 1+max(a[3], b[3])
            raw = HEAD.pack(b'I', nid, count, low, height, ZERO)+a[0]+b[0]
            return self.put(raw), count, low, height

        root = visit(0, self.page_universe, 1)[0] if pages else ZERO
        self.version += 1
        state = ser(dict(db=self.db, model=self.model, epoch=self.epoch,
                         version=self.version, root=root.hex(), config=self.config.hex(),
                         count=len(self.features), d=self.d, scale=SCALE,
                         capacity=self.tree.capacity, layout='id-directory-v1',
                         page_universe=self.page_universe))
        return self.put(len(state).to_bytes(4, 'big')+state+self.signing.sign(state))
