# ADR-002 Qdrant in embedded mode for hybrid retrieval
Status: accepted, pending the M2 spike (spec 04)

**Context.** 62 policy chunks, 10 of 15 sections identical across products; we need dense + BM25 fusion and payload filters, locally, with a production path.
**Decision.** qdrant-client in local (embedded) mode with named dense and sparse vectors, RRF fusion via the query API, payload filters on product/policy_type/section. Embeddings and reranker via fastembed (ONNX, CPU).
**Consequences.** Same API on Docker or Qdrant Cloud later. Embedded mode locks its folder to one process (verified: a second client raises RuntimeError), so runtime readers go through `get_qdrant()`, which falls back to a private copy of the 62-point index; `make index` requires the services to be stopped.
**Spike outcome.** Pre-checked 2026-10-03 with qdrant-client 1.19.1 and fastembed 0.8.1: local mode supports named dense + sparse (IDF) vectors, `query_points` with prefetch + RRF fusion, and `MatchAny` payload filters; `BAAI/bge-reranker-base` is in `TextCrossEncoder.list_supported_models()`. Still to confirm in M2: retrieval quality and latency on the real 62 chunks.
**Alternatives.** Chroma (no native sparse), FAISS (no payload filters), LanceDB (good fallback), DuckDB VSS + FTS (one file, weaker hybrid story).
