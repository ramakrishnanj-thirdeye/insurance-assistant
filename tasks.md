# Tasks

Tick boxes as work lands. Each milestone ends with its gate; do not start the next milestone with a red gate.

## M0 Scaffold
- [x] pyproject, uv lock, Makefile targets as stubs, `src/insurai` package with `settings.py` (pydantic-settings over config/settings.yaml), `llm/` factory, `observability/` logger
- [x] tests/ skeleton with markers; CI-like `make lint test` passing on the empty suite
- [x] Copy the dataset into `data/raw/` (see data/raw/README.md)
- **Gate:** `make lint test` green

## M1 Warehouse — spec 01
- [x] ref tables loader + `coverage_grid` (shared with spec 03)
- [x] build_warehouse from specs/reference/warehouse.sql; DQ report
- [x] `db.connect(read_only=True)`
- **Gate:** AC-01-01 … AC-01-11

## M2 Policy knowledge + retrieval — specs 03, 04
- [x] Qdrant / fastembed spike → ADR-002 (reranker: MiniLM-L-6-v2; threshold −4.66)
- [x] Parser, chunks, coverage loader, `get_coverage` (spec 03)
- [x] Human review of config/coverage_matrix.yaml against the wordings, then `status: reviewed` (AC-03-06)
- [ ] Issue: AC-03-08 deferred (3-day scope). `extract_coverage_draft` and the CLI behind `make coverage-draft` are not built, so the target fails until then
- [x] Index build; search pipeline with ablation switches (spec 04; LLM rewrite and config F `[~] deferred: 3-day scope`)
- [x] Write policy_clauses.jsonl + probes; tune rerank threshold (3-day scope: 30 items incl. seed_rag EVAL001–005, 5 probes)
- [ ] Issue: spec 04 stage 2 (LLM rewrite, `query_rewrite.md`) and ablation config F deferred (3-day scope)
- [x] AC-04-10 resolved: p95 136–214 ms once Python is exempted from Windows power throttling (ADR-002); demo-machine setup is in M8
- [ ] Issue: grow policy_clauses to ~50 items + 10 probes for AC-11-02 (M7)
- **Gate:** AC-03-*, AC-04-*; clause slice recall@5 ≥ 0.95; ablation report exists

## M3 Tools + MCP — spec 05
- [x] Tool schemas, personas enforcement, 8 of 11 tools (spec 05)
- [x] sql_facts generator: 20 items, seed 42, gold recomputed per run (3-day scope; spec 11 says 40)
- [x] FastMCP server (stdio + streamable HTTP), `make mcp-smoke`
- [ ] Issue: analyze_claim and portfolio_audit tools deferred to M5 (spec 07, gold.rule_results); run_analytics to M6 (spec 02). Register them in `tools/registry.py`, then re-run AC-05-01 and `make mcp-smoke` (AC-05-08)
- [ ] Issue: grow sql_facts to 40 items (spec 11)
- [x] policy_details intent added to spec 06 and planner.md v0.2.0 (decided 2026-10-04); SQL013–SQL016 route to it
- Decision 2026-10-04: tools keep per-call read-only DuckDB connections (~15–80 ms) so `make data` can replace the warehouse on Windows without stopping services; revisit only if M7 latency needs it
- **Gate:** AC-05-* (AC-05-09 moved to M8); sql_facts 100%

## M4 Agent graph — spec 06 (+ minimal /chat and Chat page)
- [x] State, nodes, fast path, planner prompt with few-shots, Send fan-out, synthesize, verify V1–V4 (spec 06)
- [x] Checkpointer (memory, sqlite, async sqlite; strict msgpack allowlist), follow-ups, clarifications
- [x] multi_turn.jsonl (10)
- [x] Per-turn state reset, history window, `run_turn`/`resume` with ReviewPending (spec 06, ADR-009)
- [x] Thread store, ownership, status machine with a 300 s lease (`agent.turn_timeout_s`), startup recovery that keeps pending reviews, /chat and /chat/resume over SSE (spec 09 M4 slice, 2026-10-05)
- [x] Chat page (spec 10 M4 slice, 2026-10-06): `ui/app.py` with persona/principal picker, streamed node and tool progress, Trace expander, review card (approve / override / request info), Conversations list; identity and open thread in the URL; UI client `insurai.api.client` (read timeout `turn_timeout_s` + 30 s). AC-10-03, AC-10-07
- [ ] Issue: `agent.tool_transport: mcp` deferred (3-day scope); `build_graph` raises NotImplementedError for it
- [ ] Issue: claim_dossier internals are provisional (needs_human_review from ClaimView flags); spec 07 replaces `assess` with `evaluate_claim` in M5
- [ ] Issue: input guard is deterministic only (PII, injection markers, scope keywords); small-LLM injection confirmation, GUARANTEE_REQUEST path and V5–V7 land with spec 08 in M7
- [ ] Issue: AC-06-10 api-lite smoke skips until an ANTHROPIC_API_KEY exists (local passes)
- [ ] Issue: AC-06-02 intent below target on qwen3:8b (2026-10-05, 68 items, planner.md v0.3.0): intent 0.8971, entity 0.9853 (target met). Decided: rule 7 (counts vs one entity) fixed SQL017/SQL018; rule 2 probe abstains when nothing is confident (EVAL032); claim/policy intents without an ID but with a product become policy_question (EVAL001/012/018/022/028/030). Remaining model misses: SQL010-012 (extra claim_documents on hospital-via-claim), EVAL021 (hospital_check for cashless repairs), EVAL034 (out_of_scope), MT003 (extra claim_analysis), MT006 (only policy_question for "my waiting period"). Earlier, higher scores relied on few-shots that copied golden IDs and phrasing; now guarded by tests/agent/test_prompt_hygiene.py. Re-measure on api-lite when a key exists. Re-run 2026-10-05 after spec 09 (no planner or prompt change): intent 0.9118, entity 1.0; MT006 passed this time (model run-to-run variance)
- [ ] Issue: correctness gate needs the spec 11 judge; partial evidence: e2e_sql_facts gold_in_answer 1.0 (19/19 scored, 2026-10-05, local)
- Recorded 2026-10-05: `make eval-fast` takes ~17 min on the local profile (routing ~11 min, e2e ~5 min). AC-11-04's 10-minute limit applies to api-lite; nothing to change
- **Gate:** AC-06-*, AC-06-11, AC-06-12, AC-09-07 … AC-09-09, AC-09-12; routing ≥ 95%; correctness ≥ 90% on sql_facts + policy_clauses
- **Closed 2026-10-05 with two known open gates** (decided): AC-06-*, AC-09-07 … AC-09-09 and AC-09-12 pass; sql_facts 1.0, policy_clauses recall@5 1.0, e2e gold_in_answer 1.0
  - [ ] Open gate: routing intent_accuracy ≥ 0.95 on qwen3:8b (latest 0.9118, entity_exact 1.0). Re-measure on api-lite when an ANTHROPIC_API_KEY exists
  - [ ] Open gate: correctness ≥ 90% on sql_facts + policy_clauses needs the spec 11 judge (M7)
- Decision 2026-10-05: the local profile sets `seed: 42` on every Ollama role so eval runs are reproducible; earlier local numbers were unseeded

## M5 Claim Dossier — spec 07
- [ ] Rules loader/compiler, evaluate_claim, `make rules`
- [ ] Issue: replace the M1 stub `src/insurai/rules/materialise.py` (logs a warning, exits 0 so `make data` works) with `materialise_portfolio`
- [ ] Dossier subgraph with interrupt; next best actions; customer view
- [ ] claim_analysis.jsonl (22 more curated claims, hand-checked)
- **Gate:** AC-07-*; blocker_mention = 1.0; invented_findings = 0

## M6 Analytics — spec 02
- [ ] Semantic model loader, validator, executor with timeout, repair loop, chart spec
- [ ] analytics.jsonl (20)
- **Gate:** AC-02-*; exec_accuracy ≥ 0.90

## M7 Guardrails + full eval — specs 08, 11
- [ ] Input guard, verifier V1–V7, conflict rendering, log redaction
- [ ] comparisons.jsonl (10), adversarial.jsonl (25), judge_calibration.jsonl (20)
- [ ] Runner, reports, baseline, `make eval-fast` gate
- **Gate:** AC-08-*, AC-11-*; all spec 00 targets met; baseline committed
- [ ] Eval follow-up: false-premise adversarial items, e.g. "Why is CLM300210 pending?" (it is Approved); the agent should correct the premise from tool facts. Seen 2026-10-06 on qwen3:8b: the planner routed it to claim_analysis and paused for review instead
- [ ] Eval follow-ups: harder clause items (no product named, no shared words, multi-section); distinct labels per §15 FAQ pair; guarantee questions answered with the §15 citation rather than refused (EVAL029/030, spec 08)

## M8 API, UI, demo — specs 09, 10
- [x] API with SSE and resume, /health, /coverage-matrix, /claims/{id}/dossier (narrate=false, provisional assessment), /eval/reports (spec 09, 2026-10-05)
- [ ] Issue: AC-09-04 deferred (3-day scope): `/audit/summary` and `/audit/claims` need `portfolio_audit` (spec 07, M5)
- [ ] Issue: AC-09-06 deferred (3-day scope): `POST /eval/run` and `--via-api` (eval threads with source=eval, deleted after the run) need the spec 11 runner (M7)
- [ ] Issue: `/claims/{id}/dossier?narrate=true` returns 501 until the spec 07 narrative (M5); `token` SSE events are not emitted (synthesize uses structured output)
- Recorded 2026-10-05: the busy lock is in-process, so `make api` must run a single uvicorn worker; production needs a database- or Redis-level lock (spec 09 Behaviour)
- [ ] Five Streamlit pages; Trace panel; review card (Chat page, minimal trace and review card done in M4)
- [ ] Issue: Chat page leftovers for M8: Claim Dossier, Coverage Matrix, Leakage Radar and Eval Dashboard pages; citation chips with clause expanders; Altair charts for analytics; full AC-10-02 trace fields; blockers and next actions on the review card (need spec 07)
- [ ] `make demo-check`; rehearse the run-of-show
- [ ] Claude Desktop manual check with the README config (AC-05-09, moved from M3)
- [x] Thread list, rename and delete endpoints (spec 09, 2026-10-05)
- [x] Conversations sidebar (spec 10, 2026-10-06)

### M8 polish list
- [ ] Greeting fast path: deterministic answers to hello and thanks, with no LLM call
- [ ] UI: show `answered_by: "draft"` as "template (no LLM)"
- [ ] Client-friendly trace view with plain labels; keep the raw JSON in an "engineer details" expander
- [ ] Named verifier checks, with the detail shown on failure: V1 Citations are real, V2 Facts are cited, V3 Numbers traced to data, V4 No promises
- [ ] Project `.streamlit/config.toml` that skips the first-run email prompt and turns off usage stats (`browser.gatherUsageStats = false`)
- [ ] Demo-machine checklist:
  - Run the API without `--reload`
  - Ollama `keep_alive` set, plus a warm-up request before the demo
  - Check the GPU/CPU split (`ollama ps`) at `num_ctx` 8192
  - Windows power mode Best performance, laptop plugged in
  - `powercfg` power-throttling exemptions for Python and Ollama
  - Port 8000 cleanup if a stale API holds it: `Get-NetTCPConnection -LocalPort 8000 -State Listen | Select-Object OwningProcess`, then `Stop-Process -Id <pid>` (Git Bash: `netstat -ano | findstr :8000`, then `taskkill /PID <pid> /F`)

- **Gate:** AC-09-*, AC-10-*, AC-09-10, AC-09-11, AC-10-07, AC-11-08; demo-check passes twice

## Open decisions (defaults applied; change here if the business decides otherwise)
- [ ] #1 LLM profile: api-lite (ADR-006)
- [ ] #2 Interactions join on claim_id (ADR-008)
- [ ] #3 Required documents matrix (config/required_documents.yaml)
- [ ] #4 Keep and flag anomalies (ADR-007)
- [ ] #5 Fixed as-of date 2026-10-01 (ADR-007)
- [x] #6 Critical Care Elite: Cardiac Procedure only (config/coverage_matrix.yaml, assumption A3). Assumptions A1 to A3 accepted for the PoC on 2026-10-04; confirm with the business before production
- [ ] #7 Deductible before co-pay (spec 01)
- [ ] #8 All three personas in scope
- [x] #9 Qdrant embedded, confirmed by the M2 spike (ADR-002)
