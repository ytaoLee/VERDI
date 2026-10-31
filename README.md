# VERDI

Author implementation of **VERDI: Verifiable Encrypted Image Retrieval with Dynamic Updates**.

VERDI is a client-assisted verification protocol for image-to-image retrieval.
The authorized client holds collection-level decryption keys, keeps its query
local, and checks exact fixed-point score/ID ranking under a trusted snapshot pin.
Accepted image release is bound to the selected record revision. The verifier
accounts for every live record; authentication of returned objects alone is
insufficient.

## Layouts and deployment

The verification core supports three authenticated layouts:

| Layout | Owner and explicit search mode | Role in the current paper |
| --- | --- | --- |
| Flat listing | `FlatOwner`, `flat_fine` | Recommended fine-filtered layout for the measured empty-cache query workloads |
| ID directory | `DirectoryOwner`, `fine_only` | Lower update traffic with higher owner work in the tested 10K mixed loopback workloads |
| Geometric tree | `Owner`, `full` | Optional subtree bounds; observed pruning does not offset its costs |

Clients must be able to decrypt, score and audit locally. At COCO 50K,
Flat + fine uses 52.9% less mean traffic than Flat scan, with 41.4% higher
local median latency. Controlled 10K links favor Flat + fine, while bulk
Flat scan is faster locally. This is a communication/processing trade-off,
not a universal latency advantage. Access traces remain visible.

The raw key `full` means **Geo + fine**. The legacy API default remains
`full` for compatibility; use explicit modes as below. Frozen record keys
are preserved. [Protocol](docs/PROTOCOL.md) and
[paper alignment](docs/PAPER_ALIGNMENT.md) document the exact mapping.

## Install and check

Use Python 3.11 and NumPy 1.26.4 for the recorded reconstruction environment.

~~~bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install -e . --no-deps
python -m unittest discover -s tests -v
python scripts/demo.py
~~~

The demo uses generated fixtures, Flat + fine over TCP, authenticated result
descriptors and exact RGB recovery. Carriers are supplied locally in this
functional example; it does not time image delivery or produce paper measurements.
Python assertions must remain enabled.

Given integer gallery/training features and a local integer query:

~~~python
from verdi import FlatOwner, Transport, image_search

owner = FlatOwner(features, calibration, capacity=16, bits=6)
snapshot = owner.publish()
transport = Transport(owner.store, network=True)
try:
    neighbors, stats, certificate = image_search(
        owner, transport, snapshot, query,
        query_id=query_id, k=10, mode="flat_fine", batch=16
    )
finally:
    transport.close()
~~~

Use `query_id=None` for an outside query. For a gallery query, its ID causes
top-(k+1) verification followed by local self exclusion. Image commitments
must be bound with `bind_image` before publication for image recovery;
the retrieval-only benchmark deliberately excludes image transfers.

## Reproduce the current displays

[Artifact v1.0](https://github.com/ytaoLee/VERDI/releases/tag/artifact-v1.0)
retains the original mixed-load, paired-format and matched local/network
records. [Artifact v1.1](https://github.com/ytaoLee/VERDI/releases/tag/artifact-v1.1)
adds the independent in/out query panel and fresh budget-10/40 network suite.
Both archives and core tags remain unchanged.

Download and unpack both ZIPs, verify their SHA-256 values in
[the manifest](configs/paper_manifest.json), then run:

~~~bash
python scripts/reconstruct_paper.py --artifact-v1 /path/to/v1 --artifact-v1-1 /path/to/v1.1 --output outputs/paper
~~~

This verifies archived file identities, runs the frozen record auditors and
exports the current Tables II-VII with stable labels. Table II is projected
from saved author aggregates; Tables III-VII are rebuilt from archived
non-content records. Historical filenames such as `table_VI.json` are not
the current paper numbering. The fresh 10/40 network suite is not pooled
with earlier 10/80 timings.

~~~bash
# Saved core aggregates only; no artifact download or benchmark:
python scripts/reconstruct_paper.py --core-only --output outputs/paper_core
# Optional plotting dependency and the current Windows network bar figure:
python -m pip install -e ".[plots]"
python scripts/plot_network_profiles.py --output outputs/windows_network
~~~

The figure CSV contains rounded published display values, not raw trials.
See [reproduction details](docs/REPRODUCING.md) for fresh benchmark commands,
statistics, environment separation and excluded timing stages.

## Inputs, versions and scope

[Dataset setup](docs/DATASETS.md) lists legal input acquisition and cache
identities. Datasets, captions, feature arrays, model weights and private
keys are not redistributed. Frozen `v0.1.0` (`ef72147555c3`) plus recorded
extensions produced the measurements. Public `v0.2.0` (`10990ba35319`) adds
ID pages, forced sidecars and configurable inactivity timeouts. Subsequent
documentation and reconstruction tools do not replace those measured identities.

Image recovery concerns canonical RGB pixels, not original JPEG containers.
CPU affinity and shaped links are desktop/controlled-network experiments.
The repository does not claim mobile hardware, hidden accesses or semantic
image-relevance accuracy. External implementations are obtained separately;
none are copied here. [Code map](docs/CODE_MAP.md), [License](LICENSE).
