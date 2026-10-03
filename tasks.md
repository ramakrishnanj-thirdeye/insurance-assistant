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
- [ ] Qdrant / fastembed spike → ADR-002
- [ ] Parser, chunks, coverage loader; human review of config/coverage_matrix.yaml (AC-03-06)
- [ ] Index build; search pipeline with ablation switches
- [ ] Write policy_clauses.jsonl (50) + 10 unanswerable probes; tune rerank threshold
- **Gate:** AC-03-*, AC-04-*; clause slice recall@5 ≥ 0.95; ablation report exists

## M3 Tools + MCP — spec 05
- [ ] Tool schemas, personas enforcement, all tools
- [ ] sql_facts generator (40)
- [ ] FastMCP server, `make mcp-smoke`, Claude Desktop manual check
- **Gate:** AC-05-*; sql_facts 100%

## M4 Agent graph — spec 06 (+ minimal /chat and Chat page)
- [ ] State, nodes, fast path, planner prompt with few-shots, Send fan-out, synthesize, verify stub (V1–V4)
- [ ] Checkpointer, follow-ups, clarifications
- [ ] multi_turn.jsonl (10)
- [ ] Thread store, ownership, status machine, per-turn state reset, history window (specs 06 and 09, ADR-009)
- **Gate:** AC-06-*, AC-06-11, AC-06-12, AC-09-07 … AC-09-09, AC-09-12; routing ≥ 95%; correctness ≥ 90% on sql_facts + policy_clauses

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

## M8 API, UI, demo — specs 09, 10
- [ ] Full API with SSE and resume; audit and eval endpoints
- [ ] Five Streamlit pages; Trace panel; review card
- [ ] `make demo-check`; rehearse the run-of-show
- [ ] Thread list, rename and delete endpoints; Conversations sidebar (specs 09, 10)
- **Gate:** AC-09-*, AC-10-*, AC-09-10, AC-09-11, AC-10-07, AC-11-08; demo-check passes twice

## Open decisions (defaults applied; change here if the business decides otherwise)
- [ ] #1 LLM profile: api-lite (ADR-006)
- [ ] #2 Interactions join on claim_id (ADR-008)
- [ ] #3 Required documents matrix (config/required_documents.yaml)
- [ ] #4 Keep and flag anomalies (ADR-007)
- [ ] #5 Fixed as-of date 2026-10-01 (ADR-007)
- [ ] #6 Critical Care Elite: Cardiac Procedure only (config/coverage_matrix.yaml, assumption A3)
- [ ] #7 Deductible before co-pay (spec 01)
- [ ] #8 All three personas in scope
- [ ] #9 Qdrant embedded, confirmed by the M2 spike (ADR-002)
