# Code map

| File | Responsibility |
| --- | --- |
| `src/verdi/tree.py` | Balanced owner tree, rotations, insertion/deletion |
| `src/verdi/protocol.py` | Integer representation, scalar certificates, encrypted objects, signed snapshots, framed TCP, base verifier |
| `src/verdi/retrieval.py` | Packed 4/6/8-bit codes, full VERDI scheduling, internal ablations, coverage audit, grouped summaries |
| `src/verdi/owner.py` | Configurable tree publisher and flat publisher |
| `src/verdi/image.py` | Reversible image codec, regional tags, sidecar, stable descriptor binding and RGB recovery |
| `src/verdi/api.py` | Image-to-image leave-one-out wrapper and verified result descriptors |
| `src/verdi/cache.py` | Read-only feature hashes and array loading |
| `scripts/benchmark.py` | Retrieval scale and parameter sweeps |
| `scripts/network.py` | Separate client, CPU affinity, paced TCP relay, calibration |
| `scripts/updates.py` | Matched update timing/object reuse checks |
| `scripts/images.py` | Supplied-image authentication and recovery checks |
| `scripts/quality.py` | Integer/float neighbor fidelity |
| `scripts/extract_features.py` | Optional image encoder API calls; no encoder source bundled |
| `scripts/audit_records.py` | Independent query-journal oracle and framing audit |
| `scripts/plot_results.py` | Local journal visualization |
| `tests/test_verdi.py` | Exactness, update, corruption, binding and TCP regression checks |

The release extracts the measured author modules into a package and parameterizes filesystem locations. It excludes legacy text-query evaluation, old binary-feasibility routines, unrelated training code, external scheme code, manuscript sources, literature notes, datasets, pretrained weights, local credentials, and private research logs. The paper protocol and measured scheduling are retained. Image encode/decode timers exclude input decoding, tiling, and reassembly as in the recorded image experiment.
