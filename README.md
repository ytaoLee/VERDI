# VERDI

Author implementation of **VERDI: Verifiable Encrypted Image Retrieval with Dynamic Updates**.

VERDI performs image-to-image retrieval using encrypted image embeddings. An authorized client scores authenticated objects locally, verifies exact integer top-k coverage, and removes the query image from the final neighbors. A dynamic authenticated tree separates record revisions from snapshot versions. The image module binds RGB carriers to feature records, supports regional diagnosis, and recovers valid embedded or sidecar records exactly.

## Installation

Use Python 3.11 for the recorded experiment environment. From the repository root:

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install -e . --no-deps
python -m unittest discover -s tests -v
python scripts/demo.py
```

The demo generates small input fixtures and checks the actual encrypted protocol over TCP. Its output is a functional check and is not a paper experiment.

## Paper experiments

Datasets and model weights are obtained separately; see [dataset setup](docs/DATASETS.md). The repository contains image filename orders, query IDs, cache hashes, and the original protocol parameters. It contains no dataset images, captions, feature arrays, keys, external method implementations, or manuscript files.

```bash
python scripts/benchmark.py --cache-root /path/to/verdi_features --output outputs/pilot --pilot --queries 2 --repeats 1
python scripts/benchmark.py --cache-root /path/to/verdi_features --output outputs/retrieval --queries 30 --repeats 3
python scripts/network.py --features /path/to/verdi_features/coco --output outputs/network
python scripts/updates.py --features /path/to/verdi_features/coco --output outputs/updates --sizes 1000 10000 50000
python scripts/quality.py --features /path/to/verdi_features/coco --output outputs/quality
```

See [reproduction instructions](docs/REPRODUCING.md), [protocol and measurement scope](docs/PROTOCOL.md), and the [code map](docs/CODE_MAP.md). All six retrieval modes are internal layouts or ablations of VERDI. `full` retains both filters and complete coverage verification. No external comparison implementation is bundled.

The code is a research implementation: collection-authorized clients hold decryption keys, access traces remain visible, and the prototype requires Python assertions to be enabled. CPU-constrained and paced-relay runs emulate a desktop client and controlled application links. The repository does not claim phone measurements or semantic image-relevance accuracy.

## Release

The public release packages the measured core algorithms and makes file paths portable. Query journals are produced locally rather than shipping datasets or historical experiment archives. [License](LICENSE) states the current rights; third-party Python dependencies are installed separately under their own terms.
