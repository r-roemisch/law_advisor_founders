# Postgres for bookkeeping, a switchable search index

Postgres always holds the bookkeeping data: Source Registry state, Legal Status, Change Records, conversations, and evaluation results. The search index (chunks and embeddings) sits behind a switchable backend: pgvector by default, with Qdrant and Chroma as alternatives. The point of this project is to compare RAG approaches, not to settle on one database. A named Retrieval Strategy fixes chunking × embedding model × index backend × search mode, and strategies are compared on the Golden Set.

## Considered Options

The initial strategies. More can be added through config (see ADR 0007). Each comparison changes exactly one variable relative to a neighbour:

| | Chunking | Embedding | Backend | Search | Compared against |
|---|---|---|---|---|---|
| S1 (default) | structure-aware | text-embedding-3-small | pgvector | hybrid | — |
| S2 | fixed-size | text-embedding-3-small | pgvector | hybrid | S1 (chunking) |
| S3 | structure-aware | text-embedding-3-small | pgvector | vector-only | S1 (hybrid vs vector-only) |
| S4 | structure-aware | text-embedding-3-small | Qdrant | hybrid | S1 (backend) |
| S5 | structure-aware | text-embedding-3-small | Chroma | vector-only | S3 (backend) |
| S1-mistral | structure-aware | mistral-embed | pgvector | hybrid | S1 (embedding) |
| S1-large | structure-aware | text-embedding-3-large | pgvector | hybrid | S1 (embedding) |
| S4-oai-large | structure-aware | text-embedding-3-large | Qdrant | hybrid | S4 (embedding) |
| S6 | semantic | text-embedding-3-small | pgvector | hybrid | S1, S2 (chunking) |
| S7 | structure-aware + multi-query | text-embedding-3-small | pgvector | hybrid | S1 (query transformation) |
| S8 | structure-aware + LLM rerank | text-embedding-3-small | pgvector | hybrid | S1 (reranking) |

Chroma's native hybrid search runs only on Chroma Cloud (as of 2026-10), so S5 is vector-only. S8 reranks with the utility model through OpenRouter rather than a local cross-encoder, so the stack needs no PyTorch. All embedding models are called through OpenRouter. The original plan used bge-m3 and Qwen3 embeddings; ADR 0008 explains the change.

## Consequences

Each strategy is a separate index that must be re-embedded whenever a Source changes, so the update pipeline writes to every active strategy. Strategies can be switched off in config so update runs stay fast during development.
