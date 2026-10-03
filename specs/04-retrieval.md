# 04 – Retrieval: hybrid search, filters, rerank, citations

Milestone: M2 · Depends on: 03 · ADR: 002 (Qdrant embedded)

## Goal
`search_policy` returns the right clause of the right product with a citation label, robust to
boilerplate duplication and vocabulary gaps ("drunk driving" vs "intoxication"). Every stage can be
switched off for the ablation study.

## First task: 1-hour spike (record the outcome in decisions/ADR-002)
Pre-check done 2026-10-03 (see ADR-002): the Qdrant and fastembed features below work in local mode. The spike now only measures quality and latency on the real chunks.
Confirm with the pinned qdrant-client that **embedded (local) mode** supports: named dense + sparse vectors,
`query_points` with `prefetch` and `FusionQuery(fusion=Fusion.RRF)`, payload filters with `MatchAny`.
Confirm fastembed exposes `BAAI/bge-small-en-v1.5`, `Qdrant/bm25` (SparseTextEmbedding) and
`BAAI/bge-reranker-base` (TextCrossEncoder; list with `TextCrossEncoder.list_supported_models()`).
Fallbacks, interface unchanged: fusion in Python (RRF, k = 60) over two queries; reranker
`Xenova/ms-marco-MiniLM-L-6-v2`; LanceDB if Qdrant local mode lacks sparse support.

## Interfaces
```python
# src/insurai/retrieval/index.py      (python -m insurai.retrieval.index  ← make index)
def build_policy_index(chunks: list[PolicyChunk]) -> IndexReport: ...     # recreates collection policy_chunks
def build_sql_examples_index(model: SemanticModel) -> IndexReport: ...    # recreates collection sql_examples

# src/insurai/retrieval/client.py
def get_qdrant(read_only: bool = True) -> QdrantClient: ...
    # Qdrant local mode locks its storage folder to ONE process. read_only=True: try paths.qdrant_path;
    # if locked (RuntimeError "already accessed by another instance"), copy the folder to a per-process
    # temp dir and open the copy (the index is read-only at runtime and tiny). read_only=False (make index)
    # never falls back: it fails with "stop make api / make mcp / make ui, then rerun make index".

# src/insurai/retrieval/search.py
class RetrievalConfig(BaseModel):                 # ablation switches; defaults = full pipeline
    use_dense: bool = True; use_sparse: bool = True; use_filter: bool = True
    use_rerank: bool = True; use_rewrite: bool = True; use_glossary: bool = True
    prefetch_k: int = 20; final_k: int = 5
class RetrievedChunk(BaseModel):
    chunk: PolicyChunk; fused_rank: int; rerank_score: float | None; boosted: bool; via: Literal["search", "neighbour"]
class RetrievalResult(BaseModel):
    query: str; rewritten_query: str; filters: dict; section_hints: list[int]
    chunks: list[RetrievedChunk]; confident: bool; timings_ms: dict[str, float]; sources: list[SourceRef]
def search_policy(ctx: ToolContext, query: str, product: str | None = None, policy_type: str | None = None,
                  section_hints: list[int] | None = None, cfg: RetrievalConfig | None = None) -> RetrievalResult: ...
def similar_sql_examples(question: str, k: int = 3) -> list[VerifiedQuery]: ...
```

## Index layout
- Collection `policy_chunks`: named vectors `dense` (384, cosine) and sparse `bm25` (modifier IDF);
  payload = every PolicyChunk field; payload indexes on product, policy_type, section_no, is_common.
  Point id = UUID5 of chunk_id (stable across rebuilds).
- Collection `sql_examples`: `dense` only; payload {name, question, sql}. Embed the question.
- Storage: `paths.qdrant_path` (embedded mode); `make index` deletes and recreates both collections.

## Pipeline (each stage maps to a RetrievalConfig switch)
1. **Glossary expansion** (use_glossary): append synonyms from config/glossary.yaml whose phrase occurs in the query (case-insensitive, word boundary). Collect `section_hints` from `section_hints` keywords.
2. **LLM rewrite** (use_rewrite, role small, prompt `query_rewrite.md`): returns `{rewritten_query, extra_section_hints, product_mentions}`. Product mentions are only used if the caller passed no product. Cache by (query, product) for the process lifetime.
3. **Filter** (use_filter): product given → `product ∈ {product, "ALL"}`; else policy_type given → `policy_type == type OR is_common`; else no filter (result flags `unfiltered=True`; spec 06 decides whether to ask for a product).
4. **Hybrid search**: prefetch dense top `prefetch_k` and bm25 top `prefetch_k`, fuse by RRF, keep `prefetch_k`. With one of use_dense/use_sparse off, use the other alone.
5. **Rerank** (use_rerank): cross-encoder over (rewritten_query, embed_text); add `section_boost` when the chunk's section is in the hints; sort; keep `final_k`.
6. **Confidence gate**: `confident = rerank_threshold is None or top score ≥ rerank_threshold`. Threshold tuned in M2 on the clause slice to maximise F1 of "answerable vs not" using 10 unanswerable probes (e.g. space tourism, pet insurance).
7. **Context pack**: for each kept product chunk, add same-product neighbours from `retrieval.neighbour_sections` (via="neighbour"), dedupe by chunk_id, keep order: search hits first.
8. **Sources**: one SourceRef per chunk, label = chunk.citation_label.

## Acceptance criteria
- [ ] AC-04-01 Spike outcome recorded in ADR-002 (supported features, chosen fallbacks if any).
- [ ] AC-04-02 `make index` builds both collections from scratch in < 2 min on CPU and is idempotent; policy_chunks has 62 points, sql_examples has 14.
- [ ] AC-04-03 Every point has dense and sparse vectors and the full payload.
- [ ] AC-04-04 EVAL001 (product Health Secure Plus): `[Health Secure Plus §5 Maternity]` in the top 3.
- [ ] AC-04-05 EVAL004 (product Motor Protect Comprehensive): top 1 is `[Motor Protect Comprehensive §9 Exclusions]` and no Two Wheeler Secure chunk appears.
- [ ] AC-04-06 With a product filter, 100% of returned chunks are that product or ALL.
- [ ] AC-04-07 Glossary unit tests: "drunk driving" adds "intoxication"; "PED" adds "pre-existing disease"; "pregnancy" yields hints [5, 4].
- [ ] AC-04-08 Clause slice, full config: recall@5 ≥ 0.95, product precision@5 ≥ 0.90, MRR ≥ 0.85.
- [ ] AC-04-09 Ablation report for configs A dense-only, B bm25-only, C hybrid, D +filter, E +rerank, F +rewrite written to `eval/reports/ablation_<ts>.json`.
- [ ] AC-04-10 p95 search latency < 400 ms on CPU excluding the LLM rewrite (timings_ms in result).
- [ ] AC-04-12 With the API holding the index open, the MCP server and the eval runner still search successfully (copy fallback), and `make index` fails with the stop-the-services message.
- [ ] AC-04-11 After tuning, the 10 unanswerable probes return confident = False in ≥ 8 cases while the clause slice stays ≥ 0.95 recall@5.

## Eval hooks
Clause slice (50), comparisons (10), ablation suite.
