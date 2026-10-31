# Code map

| File | Responsibility |
| --- | --- |
| `src/verdi/protocol.py` | Integer features, encrypted objects, signed states, contexts and framed TCP |
| `src/verdi/retrieval.py` | Packed codes, six modes, final score/ID and complete coverage audit |
| `src/verdi/owner.py` | Geometric and flat publishers |
| `src/verdi/directory.py` | ID-paged authenticated publisher, without geometry |
| `src/verdi/tree.py` | Geometric topology, rotations and updates |
| `src/verdi/image.py` | Regional codec, descriptor commitments and authenticated RGB release |
| `src/verdi/api.py` | Query-ID exclusion and descriptors from verified transcripts |
| `src/verdi/cache.py` | Read-only feature identities and input loading |
| `scripts/demo.py` | Generated Flat + fine TCP and bound-image functional check |
| `scripts/benchmark.py` | Original scale/sensitivity scheduler |
| `scripts/network.py` | Client affinity, paced relay and calibration |
| `scripts/updates.py` | Matched owner timing and reuse checks |
| `scripts/images.py` | Image authentication/recovery checks |
| `scripts/quality.py` | Integer/float neighbor fidelity |
| `scripts/extract_features.py` | Optional encoder API calls, no encoder source bundled |
| `scripts/audit_records.py` | Journal oracle and framing audit |
| `scripts/reconstruct_paper.py` | Current display projection from frozen archives and saved aggregates |
| `scripts/plot_network_profiles.py` | Current Windows network bar figure |
| `scripts/plot_results.py` | Canonically labelled local-journal viewer |
| `configs/paper_manifest.json` | Layout names, versions, source hashes and current display map |
| `paper_data/` | Non-content saved aggregates and rounded figure source |
| `tests/` | Exactness, updates, corruptions, binding and timeout checks |

See [protocol](PROTOCOL.md), [reproduction](REPRODUCING.md) and
[paper alignment](PAPER_ALIGNMENT.md). Historical `full` means Geo + fine.
The directory uses the API's `fine_only` on its own signed snapshot;
it is distinct from Tree + fine even though the bound scheduler is shared.

Only the authors' core code and reconstruction/presentation tools are
provided. Dataset content, feature arrays, weights, keys, unrelated training
code, third-party implementations and manuscript files are excluded.
