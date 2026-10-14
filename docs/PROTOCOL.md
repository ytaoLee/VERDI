# Protocol and measurement scope

- The owner creates encrypted full vectors, packed scalar codes with conservative reconstruction-error certificates, and encrypted subtree summaries. Objects are addressed by SHA-256. AES-256-GCM authenticates encrypted feature objects; Ed25519 signs the snapshot.
- The client receives a trusted owner snapshot digest, collection keys, and signature verification material. The server receives encrypted objects. Queries remain at the client; object requests and access traces are visible to the server.
- The verifier recursively accounts for every committed active record through exact evaluation or a certified upper bound and checks deterministic score/ID ordering. It does not consult the owner's plaintext vectors.
- Fine-code calibration uses disjoint training images. Clipping is included in each record's integer reconstruction error. Default parameters are scale=32767, 6-bit scalar codes, leaf capacity=16, batch=16, returned k=10.
- Stable contexts include the database, encoder identity, key epoch, record ID, revision, and full-vector digest where required. Snapshot versions change independently. Updates retain surviving encrypted objects and image commitments.
- The image codec uses keyed global/regional authentication and encrypted metadata. Capacity permits reversible packet embedding; otherwise the whole record uses sidecars. Corruption diagnostics do not authorize image release. The authenticated descriptor must supply the expected binding.
- Object requests use length-prefixed TCP frames. Bytes count both application directions and framing. Timers include decryption, scoring, and coverage verification; feature encoding and image network delivery are outside retrieval timers.

The in-memory owner/keys and loopback object server are an executable research harness. The release provides core algorithms and measured experiment tooling, rather than production key provisioning, persistence, or a deployed image service. Python optimization is refused because it would remove prototype assertion checks.
