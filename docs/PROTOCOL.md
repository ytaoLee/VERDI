# Protocol and measurement scope

## Shared acceptance rules

The trusted owner generates valid integer features, quantizers and error
certificates. Each descriptor commits the record/revision, full-vector
ciphertext digest, fine-packet digest and image commitment. Typed, ordered
list or child/page encodings fix the live set under an owner-signed snapshot.

The client holds collection keys and verification material and obtains its
snapshot pin through a trusted channel. It authenticates objects before use,
decrypts code/error packets for conservative score bounds and fetches full
vectors when required. Every live record must be evaluated or covered by a
valid exclusion. The final audit checks coverage and exclusions against the
final score/ID boundary, including ties and negative scores. It never consults
owner plaintext vectors to establish the ranking.

The signed directory, bound approximations and image commitments implement
a concrete composition of established mechanisms. The compact filtering
principle and cryptographic primitives are not claimed as new.

## Layout and mode names

| Display | Record/API mode | Snapshot/layout |
| --- | --- | --- |
| Geo + fine | `full` | Geometric tree; coarse and fine bounds |
| Tree + fine | `fine_only` | Tree with all branches opened, no geometric bounds |
| Tree + coarse | `coarse_only` | Geometric bounds, no fine packets |
| Tree scan | `scan` | Tree traversal without either bound |
| Flat + fine | `flat_fine` | `FlatOwner` or `flat_snapshot`, `flat-list-v1` |
| Flat scan | `flat_scan` | Flat listing with bulk full-vector reads |
| ID directory + fine | recorded `directory_fine`; API `fine_only` | `DirectoryOwner`, `id-directory-v1` |

Choose the owner, snapshot and mode together. The same `fine_only` API mode
means Tree + fine on a tree and ID directory + fine on a directory.
A tree snapshot cannot be passed to `flat_fine`. For a new flat service,
`FlatOwner.publish()` creates the flat snapshot directly; `flat_snapshot`
is the unchanged benchmark helper for deriving a flat control from a tree owner.
Low-level defaults remain `full`; the paper recommends an explicit Flat + fine
configuration for its measured query workload.

## Integer representation and query semantics

`fixed` re-normalizes cached vectors in float64, scales by 32767 and rounds
ties to even. Ranking uses exact integer inner products, with ascending ID
for equal scores. Fine codes bound scores; they do not define final scores.
Their certified error includes clipping, including out-of-range updates.
Defaults are six bits, page/leaf capacity 16, batch 16 and ten returned images.

For an in-gallery image, `image_search(..., query_id=id, k=10, mode=...)`
verifies eleven before excluding the query ID. For an outside image,
`query_id=None` verifies ten directly. Integer exactness differs from
float-neighbor agreement and semantic relevance.

## Updates and image release

Record contexts bind database/model identity, key epoch, record ID/revision,
and the required vector/configuration digests. Global snapshot version is
separate. Changed snapshots can refer to unchanged ciphertexts without
reauthenticating those objects. A flat publisher replaces its listing; an
ID directory reuses unchanged pages; a geometric tree can reuse unaffected
objects. Directory publication enumerates live pages and tree publication
walks the tree. Neither reference publisher has logarithmic total CPU cost.

`bind_image` fixes the feature digest, revision, dimensions and coordinates
in the image context and installs the image commitment before publication.
After verified retrieval, `authenticated_slots` extracts descriptors from an
already verified certificate. `recover_image` checks the selected descriptor
and manifest/carrier/packet bindings and releases RGB only after whole-image
acceptance. Regional diagnosis alone never authorizes release. Auto embedding
and forced sidecars retain these checks; valid recovery is exact RGB, not JPEG
container reconstruction. Logical deletion does not erase historical objects.

## Costs and boundaries

The server receives encrypted objects and visible requests, not query
coordinates or keys. Confidentiality is relative to the stated access,
length, revision, topology and reuse leakage. A retained old pin intentionally
selects an old state; latest-state freshness depends on trusted pin delivery.
A server can prevent completion. The configurable socket timeout bounds
inactivity, not total query duration or availability.

The client/server constructors are an in-memory research harness, not a
production key-provisioning or persistence service. Prototype integrity checks
use assertions and optimized Python execution is refused.

Retrieval timers include transport/hash checks, decryption, scoring and final
coverage audit. They exclude enrollment, initial upload, connection setup,
encoding, oracle calculation and image delivery. Plain TCP application bytes
count both directions and framing, without network headers/TLS. Decimal MB/kB
and binary MiB are distinct. CPU/audit/decrypt intervals can overlap.
