# Reproduction

Run numerical benchmarks sequentially after editable installation. Rebuilding
saved summaries is different from generating a fresh performance run.

## Current display reconstruction

Download the unchanged `artifact-v1.0` and `artifact-v1.1` release ZIPs.
The root for v1 has `SHA256SUMS.json`; the root for v1.1 has `MANIFEST.json`.
Use Python 3.11 and NumPy 1.26.4:

~~~bash
python scripts/reconstruct_paper.py --artifact-v1 /path/to/v1 --artifact-v1-1 /path/to/v1.1 --output outputs/paper
~~~

The tool pins the manifest hashes, checks every recorded file hash, invokes
the author auditors, then selects the current rows and columns. It exports:

| Current display | Frozen source |
| --- | --- |
| Table II, largest-gallery ablation | Saved Windows scale aggregates in `paper_data/core_summary.json` |
| Table III, independent queries | v1.1 panel records, combined in/out stratum |
| Table IV, mixed load | v1 historical `table_VI`; eight flat/directory rows and publication columns |
| Table V, paired image formats | v1 historical `table_VII`; storage and decode pairs |
| Table VI, matched local comparison | v1 historical `table_VIII`; 10/40/80 budgets, Geo + fine and Flat + fine |
| Table VII, fresh matched network | v1.1 10/40 records; median CI and empirical P95 |
| Figures 3/5 quantitative sources | Saved scale/update aggregates |
| Figure 4 quantitative source | Rounded Windows profile medians and CIs |

`--core-only` exports saved core quantities without running an artifact.
It does not pretend to rebuild the artifact-dependent tables. The saved core
CI fields are retained, not recomputed from absent raw trials. All old rows,
columns and budget-80 network records remain in their original artifacts.
See [alignment and source identities](PAPER_ALIGNMENT.md).

The current Figure 4 can be drawn with the provided script after installing
the optional plots dependency:

~~~bash
python scripts/plot_network_profiles.py --output outputs/windows_network
~~~

It uses all 18 displayed medians/CIs with square axes and zero-based scales.
Its CSV is a display source, not a new experiment or raw query journal.
`plot_results.py` is a general local-journal viewer with canonical mode labels;
it is not a substitute for the frozen display reconstruction.

## Fresh retrieval runs

Obtain [legal inputs and exact cache identities](DATASETS.md) first:

~~~bash
python scripts/benchmark.py --cache-root /path/to/verdi_features --output outputs/pilot --pilot --queries 2 --repeats 1
python scripts/benchmark.py --cache-root /path/to/verdi_features --output outputs/retrieval --queries 30 --repeats 3
python scripts/audit_records.py --features /path/to/verdi_features/coco --records outputs/retrieval/coco
python scripts/audit_records.py --features /path/to/verdi_features/flickr30k --records outputs/retrieval/flickr30k
python scripts/quality.py --features /path/to/verdi_features/coco --output outputs/quality
~~~

The scale scheduler evaluates COCO 1K/5K/10K/50K and Flickr30k 1K/5K/10K/25K,
with the frozen 30-image panel and three repetitions. Fourteen 10K sensitivity
groups retain their original settings and Geo + fine/Flat + fine controls,
although the final paper summarizes the parameter trade-off in prose.
Query records use the original keys, exact integer oracles, and self exclusion.
Partial tails are saved separately. Resume only with identical cache/source/
configuration; use a new output folder after changes. Generated fixtures
in tests and the demo are not performance evidence.

## Controlled client/network, owner updates and images

~~~bash
python scripts/network.py --features /path/to/verdi_features/coco --output outputs/network
python scripts/updates.py --features /path/to/verdi_features/coco --output outputs/updates --sizes 1000 10000 50000
python scripts/images.py --features /path/to/verdi_features/coco --images /path/to/coco/images --output outputs/images --count 1000
~~~

The Windows-style network harness separates client/server/relay, limits
logical CPU affinity, samples RSS every 5 ms, and actually paces application
frames at 50/200 Mb/s and nominal 2/10 ms RTT. Pre/post calibration retains
20 pings and three 16 MiB transfers per direction. Failed gates stop a run.
This is desktop emulation without a memory cap. Linux routed external
measurements and the mixed/paired studies use the frozen artifact harnesses,
not a simplified replacement in this repository.

Owner payload counts exclude image preparation/upload and network latency
unless an experiment explicitly measures acknowledged mixed-load uploads.
Image encode/decode excludes input decoding, tiling and separate RGB
reassembly. The independent query panel has one timing per image and
stratified in/out resampling. Mixed-load mean cost sums query, owner and
acknowledged-upload intervals per query; it is not a query-latency median.

Unless locally specified, measured panels use 30 query images with three
runs each, shuffled order and excluded warmups. Traffic/storage/payloads/
reads/rounds are arithmetic means, times are medians in ms, and intervals
are 95% CIs from 2,000 query/image block resamples preserving repetitions
or format pairs. P95 is the empirical 95th percentile.

New timings depend on hardware, OS, numerical libraries and link conditions.
The original Windows, earlier WSL2 local suite, and refreshed WSL2 network
suite are separate environments. Do not pool their latency records or rename
fresh timings as the frozen measurements.
