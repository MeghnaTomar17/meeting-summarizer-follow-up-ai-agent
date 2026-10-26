# Qdrant Collection, Persistence & Retrieval — through Phase 10.5

This document defines the retrieval-index contract and the Search-owned
persistence boundary. It does not imply that a Qdrant server is currently
available or that semantic search works. PostgreSQL remains authoritative for
all domain records.

## `meeting_chunks`

| Setting | Contract |
|---------|----------|
| Collection identity | `QDRANT_COLLECTION_NAME`, default `meeting_chunks` |
| Vector size | `EMBEDDING_DIMENSIONS`, default `1536`; one model identity/dimension per collection generation |
| Distance | `QDRANT_DISTANCE_METRIC`, default `Cosine`; allowed `Cosine`, `Dot`, `Euclid` |
| Point identity | UUIDv5 of the fixed Phase 10.1 namespace and `v1:{meeting_id}:{transcript_id}:{chunk_index}` |
| Source | Canonically normalized transcript segments from PostgreSQL, grouped in order into complete-segment chunks |

The character target defaults to `TRANSCRIPT_CHUNK_MAX_CHARACTERS=2000`. It is
a grouping target, not a token budget; a segment longer than the target is
kept intact. Text is the source segment text joined with newlines. Speaker
labels are metadata, not a rewritten transcript. No segment overlap is
introduced in 10.1.

## Payload schema

`TranscriptChunk` is the typed payload contract:

| Field | Purpose |
|-------|---------|
| `schema_version` | Payload evolution; starts at `1` |
| `chunk_id` | Same deterministic UUID as the Qdrant point ID |
| `meeting_id`, `transcript_id` | Bind the indexed projection to its PostgreSQL source |
| `owner_id` | Persisted `Meeting.created_by`; primary user-scope filter |
| `organization_id` | Persisted meeting organization metadata; not by itself authorization |
| `chunk_index` | Zero-based deterministic position in normalized transcript order |
| `source_segments` | Ordered per-segment metadata: source index, optional speaker, and optional start/end timestamps |
| `start_ms`, `end_ms` | Minimum/maximum source timestamps when provided; otherwise null |
| `language` | Transcript language when provided |
| `text` | Only the chunk’s transcript text, not a copied Meeting/Transcript entity |

No meeting title, description, participants, full transcript, user profile,
password, authorization token, AI result, or ORM state belongs in this payload.

## Ownership and retrieval filters

Index scope is resolved by a trusted server-side workflow from the persisted
Meeting and Transcript, after the existing Meeting Service ownership check.
`owner_id` maps to `Meeting.created_by`. Retrieval must derive allowed owner
and meeting scope from the authenticated principal and server-side
authorization; arbitrary client `meeting_id` or `user_id` values cannot grant
access. Current Meeting authorization is creator-based. Organization
membership is not modeled, so `organization_id` is useful tenant metadata but
is not a sufficient access-control filter by itself.

## Point identity and lifecycle semantics

Point identity depends on source identities and chunk position, not text or
embedding provider. Re-indexing the same source position upserts the same
point; changed content at that position replaces the projection. Re-indexing
must also remove stale chunk positions when chunk count/order changes. A
transcript replacement/content edit is re-read from PostgreSQL and re-indexed;
a meeting deletion removes its points by `meeting_id` (or exact transcript
identity as applicable). Qdrant failure must not roll back or corrupt
PostgreSQL. Retry/reconciliation and atomic cross-store replacement are not
provided by the persistence repository.

Changing the embedding model or vector dimensions requires a compatible
collection generation and rebuild; vectors of different dimensions or model
identities must not be mixed. At the Phase 10.3 checkpoint, Search Service
prepared typed records but did not persist them. Phase 10.4 adds the repository
behavior below; durable indexing workers, retrieval, and RAG remain deferred.

## Phase 10.4 persistence behavior

`QdrantVectorRepository` lives in Search Service and accepts only typed
`TranscriptIndexBatch` values. `initialize_collection()` is explicit: it
creates `QDRANT_COLLECTION_NAME` when absent, or checks the existing unnamed
vector configuration against the configured dimensions and distance. A
mismatch raises a controlled error; the repository never recreates or deletes
an incompatible collection.

`upsert_transcript_batch()` scrolls the configured collection by
`transcript_id`, validates the incoming configured model/dimensions, upserts
all desired points using their deterministic UUIDs, and then removes stale
IDs found by that transcript filter. The point payload is the typed
`TranscriptChunk` data plus `embedding_model`; the vector remains the point's
vector field. Empty batches remove all points for the transcript. Repeating an
identical batch reuses the same IDs and is idempotent at the point-write level.

Replacement is not atomic. If scrolling fails, no write begins. If upsert
fails, stale deletion is not attempted (the server may still have applied an
ambiguous request, so retry uses the same deterministic IDs). If stale deletion
fails after upsert, desired and stale points may coexist until a successful
retry. Meeting/transcript deletes use Qdrant payload filters. None of these
operations participates in a PostgreSQL transaction; PostgreSQL remains the
source of truth and Phase 9 owns durable job retries.

The repository does not authorize users or read ORM state. Its internal caller
must pass records produced from a trusted `TranscriptIndexScope`; the repository
persists only the typed chunk and embedding metadata carried by those records.
No public search route or retrieval path is included. The integration test is
opt-in via `RUN_QDRANT_INTEGRATION=1`; the default test suite uses a fake client.

## Phase 10.5 authenticated retrieval

Search Service accepts a strict query/top-k request and does not accept owner,
organization, scope, or raw Qdrant filter fields. Gateway authenticates the
external user, then signs a short-lived RS256 internal principal for the
`search-service` audience using the existing Gateway key. Search verifies
signature, issuer, expiry, internal-principal type, and exact audience using
its configured public verification key. The external access JWT is not
forwarded or accepted as an internal principal.

The current authorization model supports only the meeting creator. Search
uses the verified principal subject as `owner_id` and Qdrant requires that
payload match in the vector query itself. There is no unfiltered fallback or
post-query authorization filter. `organization_id` is never used as proof of
membership. Production deployments must configure the matching public key in
Search Service; private signing material remains only in Gateway. Docker
configuration was not changed in Phase 10.5.

Results validate the point UUID against `chunk_id`, validate the persisted
`TranscriptChunk` payload and finite score, and return only meeting/transcript/
chunk provenance, text, language, source speaker/time metadata, and score.
Scores are the raw configured Qdrant distance scores; higher scores rank as
more similar. Vectors, owner/organization IDs, the embedding identity payload,
and arbitrary payload fields are not returned. This retrieval flow is covered
with fake embeddings/Qdrant in tests; live Qdrant and embedding-provider calls
remain unverified. RAG, reranking, and hybrid search are out of scope.
