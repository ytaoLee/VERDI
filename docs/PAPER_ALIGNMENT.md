# Paper-to-code alignment

This map follows the 2026-10-31 manuscript edition, using stable LaTeX labels
as well as current numbers. It contains no manuscript source or third-party
implementation. `configs/paper_manifest.json` is the machine-readable map.

## What is unchanged

The measured numerical/cryptographic core remains in `v0.1.0`
(`ef72147555c3`) plus the recorded extensions. Public `v0.2.0`
(`10990ba35319`) exposes the ID directory, forced-sidecar option and
configurable inactivity timeout. This synchronization changes documentation,
examples, names and result projection tools; it does not replace frozen
code or regenerate performance data. Lower-level `mode="full"` defaults
remain Geo + fine; examples explicitly select the recommended `flat_fine`.

| Paper mechanism | Implementation |
| --- | --- |
| Integer score and deterministic ID ties | `protocol.fixed`, `oracle`, `ExperimentClient.search/verify` |
| Fine certificate, clipping and integer bound | `retrieval.BitQuantizer`, `Client.fine`, `ExperimentClient` |
| Full live-set coverage and final exclusions | `ExperimentClient.verify` |
| Flat listing and publication | `ConfiguredFlatOwner`, `flat_parse` |
| ID pages without geometric summaries | `DirectoryOwner` with `mode="fine_only"` |
| Optional geometric tree | `ConfiguredOwner` and `QuantTree` with `mode="full"` |
| Snapshot versus record revision | `Owner.context/add_record`, signed publish state and client pin |
| Descriptor-bound RGB release | `bind_image`, `authenticated_slots`, `recover_image` |

A correct signed directory with valid bounds and complete binding/coverage
checks can provide the stated guarantees. The implementation specifies that
composition; it does not claim a new compact filtering principle or
cryptographic primitive.

## Current results and archived identities

The public manifest maps Tables II-VII and Figures 3-5. Tables III-VII are
projected from recomputed frozen records; Table II and scale/update sources
are saved author aggregates. The Windows bar CSV contains the rounded
display values. Neither representation is described as raw per-query data.

The v1.1 network records use the fresh matched 10/40 budgets and the updated
WSL2 kernel. v1 retains earlier 10/80 network records and the earlier local
10/40/80 suite. The current local and network tables are not pooled.
External results keep their native approximation/privacy/caching contract;
they are not interchangeable exact-coverage controls.

Flat + fine saves communication with additional local processing.
Flat scan can be faster locally. ID-directory advantages are established
only for the 10K mixed loopback study; maximum-scale and WAN extrapolations
are not reported. Image embedding and sidecars have the same release
binding but different storage/decoding costs. New artifact reconstructions
check data identities; they do not create new measurements.

## Artifact trust and inputs

Both ZIP digests and manifest digests are pinned in the public manifest.
The reconstructor checks paths and file hashes before running the frozen
author reconstruction scripts. Outputs must be outside artifact roots.
Datasets, feature arrays, weights, private keys and third-party source
trees are not included. Obtain legal inputs separately for fresh execution.

The protocols and input orders are reproducible. Fresh encryption randomness
and execution environments produce different state hashes and timings;
frozen non-content records provide the exact historical evidence.
