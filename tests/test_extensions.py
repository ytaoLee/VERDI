import copy
import socket
import struct
import unittest
from unittest.mock import patch
import numpy as np
from verdi import DirectoryOwner, ImageCodec, RetrievalClient, Transport, fixed, oracle
from verdi.protocol import recv_exact


def partial_response_server(store, pipe):
    listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(1)
    pipe.send(listener.getsockname()[1]);conn,_=listener.accept();conn.settimeout(5)
    try:
        size,=struct.unpack('>I',recv_exact(conn,4));recv_exact(conn,size)
        conn.sendall(struct.pack('>I',100))
        conn.recv(1)  # Wait until the timed-out client closes the session.
    finally:
        conn.close();listener.close()


class ExtensionTests(unittest.TestCase):
    def setUp(self):
        rng=np.random.default_rng(20261022)
        self.x=fixed(rng.normal(size=(66,16)));self.x[1]=self.x[0]

    def test_directory_exact_ties_negatives_and_page_updates(self):
        for bits in (4,6,8):
            owner=DirectoryOwner(dict(enumerate(self.x[:64])),self.x[:20],bits=bits,capacity=8)
            for q in (self.x[0],-self.x[0],np.zeros(16,dtype=np.int64)):
                top,_,_=RetrievalClient(owner,Transport(owner.store),owner.publish()).search(q,11,mode='fine_only')
                self.assertEqual(top,oracle(owner.features,q,11))
            for i in range(16,24):owner.delete(i)
            owner.insert(65,self.x[65]);snap=owner.publish()
            top,_,_=RetrievalClient(owner,Transport(owner.store),snap).search(self.x[0],11,mode='fine_only')
            self.assertEqual(top,oracle(owner.features,self.x[0],11))

    def test_directory_rejects_missing_evidence_and_stale_pin(self):
        owner=DirectoryOwner(dict(enumerate(self.x[:64])),self.x[:20]);snap=owner.publish()
        c=RetrievalClient(owner,Transport(owner.store),snap);_,_,cert=c.search(self.x[0],11,mode='fine_only')
        bad=copy.deepcopy(cert);del bad['objects'][owner.records[next(iter(cert['done']))][2]]
        with self.assertRaises(Exception):c.verify(self.x[0],11,bad)
        owner.delete(32);new=owner.publish();latest=RetrievalClient(owner,Transport(owner.store),new)
        with self.assertRaises(Exception):latest.verify(self.x[0],11,cert)

    def test_directory_empty_and_invalid_id(self):
        owner=DirectoryOwner({0:self.x[0]},self.x[:20],capacity=8)
        before=dict(owner.features)
        for i in (-1,8*65536,1.0):
            with self.assertRaises(ValueError):owner.insert(i,self.x[1])
            self.assertEqual(set(before),set(owner.features))
        owner.delete(0);snap=owner.publish()
        with self.assertRaises(Exception):RetrievalClient(owner,Transport(owner.store),snap).search(self.x[0],1,mode='fine_only')

    def test_same_image_forced_sidecar_and_authentication(self):
        codec=ImageCodec();regions=[bytes(32*32*3)];context=['test',1,1,[32,32,3]]
        auto=codec.encode(regions,context);side=codec.encode(regions,context,force_sidecar=True)
        self.assertEqual(auto['mode'],'embed');self.assertEqual(side['mode'],'sidecar')
        for obj in (auto,side):
            ok,status,pixels=codec.decode(obj,context,obj['expected'])
            self.assertTrue(ok);self.assertEqual(pixels,regions)
            bad=copy.deepcopy(obj);raw=bytearray(bad['tiles'][0]);raw[0]^=1;bad['tiles'][0]=bytes(raw)
            ok,status,pixels=codec.decode(bad,context,obj['expected'])
            self.assertFalse(ok);self.assertIsNone(pixels)

    def test_partial_tcp_response_times_out_without_acceptance(self):
        with patch('verdi.protocol.server_main',partial_response_server):
            transport=Transport({},network=True,timeout=.15)
            try:
                with self.assertRaises(TimeoutError):transport.fetch([bytes(32)],'partial')
                self.assertEqual(transport.rounds,0)
            finally:transport.close()
        with self.assertRaises(ValueError):Transport({},timeout=0)
