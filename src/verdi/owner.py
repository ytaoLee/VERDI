"""Configurable VERDI publisher and flat layout used in internal ablations."""
import secrets
import numpy as np
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from .protocol import Owner, QuantTree, SLOT, SCALE, ser
from .retrieval import BitQuantizer
from .common import signature

class ConfiguredOwner(Owner):
    def __init__(self, features, training, capacity=16, bits=6, db='VERDI', model='integer16'):
        self.tree = QuantTree(features, capacity)
        self.quantizer = BitQuantizer.fit(training, bits)
        self.d = self.quantizer.d
        self.keys = {k: secrets.token_bytes(32) for k in ('full', 'fine', 'summary')}
        self.signing = Ed25519PrivateKey.generate()
        self.db, self.model, self.epoch = db, model, 1
        self.store, self.records, self.summary_cache = {}, {}, {}
        self.config = self.put(self.enc('summary', self.quantizer.bytes(), self.context('config', 0)))
        for i, x in features.items():
            self.add_record(i, x)
        self.version = 0


class ConfiguredFlatOwner(ConfiguredOwner):
    def __init__(self, features, training, **kwargs):
        # Initialize encryption and contexts with zero tree records, then retain
        # a flat dictionary; tree construction is excluded from flat build time.
        super().__init__({}, training, **kwargs)
        self.features = {i: np.asarray(x, dtype=np.int64).copy() for i, x in features.items()}
        for i, x in self.features.items():
            self.add_record(i, x)

    def insert(self, i, x):
        assert i not in self.features
        self.features[i] = np.asarray(x, dtype=np.int64).copy()
        self.add_record(i, x)

    def delete(self, i):
        del self.features[i]

    def publish(self):
        root = self.put(b'F' + len(self.features).to_bytes(8, 'big') +
                        b''.join(SLOT.pack(*self.records[i]) for i in sorted(self.features)))
        self.version += 1
        state = ser({'db': self.db, 'model': self.model, 'epoch': self.epoch,
                     'version': self.version, 'root': root.hex(), 'config': self.config.hex(),
                     'count': len(self.features), 'd': self.d, 'scale': SCALE,
                     'capacity': self.tree.capacity, 'layout': 'flat-list-v1'})
        return self.put(len(state).to_bytes(4, 'big') + state + self.signing.sign(state))


def binding(meta):
    return {'db': meta['dataset'] + ':' + meta['protocol'],
            'model': 'OpenAI-CLIP-ViT-B32;encoder=' + signature(meta['identity']) + ';integer16-scale32767'}
