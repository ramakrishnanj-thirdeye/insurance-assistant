# ADR-002 Qdrant in embedded mode for hybrid retrieval
Status: accepted (M2 spike done 2026-10-04, spec 04)

**Context.** 62 policy chunks, 10 of 15 sections identical across products; we need dense + BM25 fusion and payload filters, locally, with a production path.
**Decision.** qdrant-client in local (embedded) mode with named dense and sparse vectors, RRF fusion via the query API, payload filters on product/policy_type/section. Embeddings and reranker via fastembed (ONNX, CPU).
**Consequences.** Same API on Docker or Qdrant Cloud later. Embedded mode locks its folder to one process (verified: a second client raises RuntimeError), so runtime readers go through `get_qdrant()`, which falls back to a private copy of the 62-point index; `make index` requires the services to be stopped.
**Spike outcome.** Pre-checked 2026-10-03 with qdrant-client 1.19.1 and fastembed 0.8.1: local mode supports named dense + sparse (IDF) vectors, `query_points` with prefetch + RRF fusion, and `MatchAny` payload filters; `BAAI/bge-reranker-base` is in `TextCrossEncoder.list_supported_models()`. No fallback needed for Qdrant or fusion.
M2 spike (2026-10-04, CPU, warm models, clause slice of 30 items + 5 unanswerable probes, config E = hybrid + product filter + rerank, glossary on):

| Reranker | prefetch k | recall@5 | product P@5 | MRR | p50 ms | p95 ms |
| --- | --- | --- | --- | --- | --- | --- |
| BAAI/bge-reranker-base | 20 | 1.00 | 1.00 | 0.967 | 3817 | 4653 |
| BAAI/bge-reranker-base | 12 | 1.00 | 1.00 | 0.967 | 3268 | 3696 |
| Xenova/ms-marco-MiniLM-L-6-v2 | 20 | 1.00 | 1.00 | 0.950 | 99 | 133 |
| Xenova/ms-marco-MiniLM-L-6-v2 | 12 | 1.00 | 1.00 | 0.950 | 92 | 174 |

Decision: **Xenova/ms-marco-MiniLM-L-6-v2 with prefetch k = 20.** bge-reranker-base ties on recall@5 and gains 0.017 MRR (one item ranked 2nd instead of 1st), but its p95 is 3.7–4.7 s, far above the 800 ms we would have accepted; MiniLM meets the original AC-04-10 budget of 400 ms. Two findings: (1) with onnxruntime's default thread pool (all cores) the three ONNX sessions contend and the pipeline ran ~10× slower, so `retrieval.onnx_threads: 8` caps each model; (2) huggingface_hub rejects fastembed's partial bm25 snapshot as incomplete under `local_files_only`, so the runtime loads each model from its snapshot directory under `paths.models_dir` and only `make index` downloads. Confidence gate: top MiniLM scores are ≤ −9.9 for the probes and ≥ 0.59 for answerable items; the F1 sweep sets `rerank_threshold: -4.66` (5/5 probes not confident, 0 answerable rejected). Latency caveat: on the dev laptop (i5-13450HX, AC power) the identical rerank call runs at ~60 ms and then, after about a second of sustained load, at 450–1300 ms; the eval runs that hit this report config E p95 1.3–1.6 s. Latency was measured with VS Code in the foreground, so the Python eval process ran in the background; Windows 11 EcoQoS throttles background processes on hybrid Intel CPUs (P-cores + E-cores), which matches the step change. Re-measured 2026-10-04 with the base Python interpreter exempted from power throttling (`powercfg`, verified "Never On"), power mode Best performance, plugged in; three `make eval-ablation` runs, p50/p95 ms:

| Config | Run 1 | Run 2 | Run 3 |
| --- | --- | --- | --- |
| A dense-only | 8.1 / 10.2 | 7.8 / 10.0 | 7.5 / 9.3 |
| B bm25-only | 2.1 / 2.9 | 1.9 / 2.9 | 1.7 / 2.1 |
| C hybrid | 9.7 / 11.5 | 9.5 / 11.6 | 9.3 / 11.6 |
| D +filter | 10.5 / 13.1 | 10.8 / 14.0 | 10.6 / 12.2 |
| E +rerank | 101.5 / 135.7 | 124.3 / 185.4 | 117.8 / 213.5 |

Config E p95 stays under 400 ms in every run (AC-04-10 met), with recall@5 1.00 and 5/5 probes not confident each time. The demo machine needs the same setup: see tasks.md M8 ("Demo machine: Best performance power mode, plugged in, powercfg throttling exemption for Python"). Index build: 7 s with cached models (first `make index` also downloads ~1.3 GB, ~2 min on this link).
**Alternatives.** Chroma (no native sparse), FAISS (no payload filters), LanceDB (good fallback), DuckDB VSS + FTS (one file, weaker hybrid story).
