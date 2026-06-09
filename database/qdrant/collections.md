# Qdrant Collections

## meeting_chunks

- **Purpose:** Semantic search over transcript chunks.
- **Vector size:** TODO — match embedding model dimension (e.g. 1536).
- **Distance:** Cosine.
- **Payload fields:** `meeting_id`, `chunk_index`, `speaker`, `text`, `organization_id`.
- **TODO:** Partition or filter by `organization_id` for multi-tenancy.

## meeting_summaries (optional)

- **Purpose:** Search over summary embeddings for cross-meeting discovery.
- **TODO:** Decide single vs multi-collection strategy.
