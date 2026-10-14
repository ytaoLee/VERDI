# Reproducing the image-to-image experiments

Run commands from the repository root after editable installation. Perform numerical runs sequentially so that unrelated benchmarks do not compete for CPU or network resources.

## Retrieval and parameter sensitivity

`scripts/benchmark.py` implements the measured image-to-image scheduler with portable cache/output arguments. It evaluates COCO at 1K/5K/10K/50K and Flickr30k at 1K/5K/10K/25K, 30 published image queries, three repetitions, and six internal modes. Fourteen 10K sensitivity settings vary scalar bits (4/6/8), leaf capacity (8/16/32), request batch (1/4/16/64), and returned k (1/5/10/50), using full VERDI and flat plus fine filtering.

```bash
python scripts/benchmark.py --cache-root /path/to/verdi_features --output outputs/retrieval
python scripts/audit_records.py --features /path/to/verdi_features/coco --records outputs/retrieval/coco
python scripts/audit_records.py --features /path/to/verdi_features/flickr30k --records outputs/retrieval/flickr30k
```

Each query authenticates protocol top-(k+1), removes its image ID, then keeps k neighbors. Integer inner products use normalized embeddings rounded with ties to even at scale 32767; equal scores use ascending image ID. All modes retain the independent coverage verifier. `queries.jsonl`, integer oracles, environment, configuration, summaries, and failures are written under the selected output. Resume only with the identical source/configuration/cache. Checkpoints preserve complete rows and save incomplete trailing bytes separately.

`quality.py` compares integer nearest neighbors with FP64 accumulation over cached FP32 vectors for the evaluation image prefix. It reports ordered agreement and set overlap; it does not measure semantic relevance.

## Client constraints and controlled links

`network.py` isolates the client in a separate process, sets one/two logical CPU affinities, samples RSS every 5 ms, and counts both directions of actual TCP application frames. Four paced links combine 50/200 Mb/s and 2/10 ms nominal RTT. Each is checked before and after by 20 measured pings and three 16 MiB transfers in each direction. A failed calibration stops the run. OS scheduling can affect the observed link values; raw calibration records are retained.

```bash
python scripts/network.py --features /path/to/verdi_features/coco --output outputs/network
# Short local-only functional run:
python scripts/network.py --features /path/to/verdi_features/coco --output outputs/network_local --n 1000 --queries 2 --repeats 1 --profiles local_1cpu
```

The affinity experiment requires a platform with psutil CPU affinity support (Windows or Linux). There is no hard RAM cap. Query timers exclude encoder calls, server connection setup, and image delivery. Decryption CPU can overlap verification CPU. Application traffic excludes TCP/IP and TLS.

## Updates and image authentication

`updates.py` measures the original owner maintenance/publication code on matched insertion/deletion traces. Post-update queries use image vectors and an integer oracle. It records unchanged surviving descriptors, newly materialized payloads, and exactness. Publication currently walks the full tree; compact changed-object bytes do not establish logarithmic end-to-end publication time.

```bash
python scripts/updates.py --features /path/to/verdi_features/coco --output outputs/updates --sizes 1000 10000 50000
python scripts/images.py --features /path/to/verdi_features/coco --images /path/to/coco/images --output outputs/images --count 1000
python scripts/plot_results.py --records outputs/retrieval/coco/scale_1000/queries.jsonl --output outputs/plots/coco_1000
```

`images.py` retains the original regional encode/decode timers, 32/64/128-pixel capacity checks, content/packet/metadata corruption checks, whole-record substitution checks, and authenticated descriptor commitments. Input decoding, tiling and reassembly are outside encode/decode timers. Exact recovery refers to decoded RGB bytes. The core API and tests also connect authenticated result descriptors to bound image recovery.

Functional tests/demo use generated fixtures and are never substituted for the real dataset experiments. Historical result archives and the manuscript remain in the authors' research workspace, outside this core-code release.
