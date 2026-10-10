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
- [x] analyze_claim and portfolio_audit registered (2026-10-06, spec 07): AC-05-01 tests for both (portfolio_audit supervisor-only), `make mcp-smoke` passes with 10 tools
- [x] run_analytics registered (2026-10-08, spec 02): AC-05-01 persona-gate tests; `make mcp-smoke` passes with 11 tools
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
- [x] claim_dossier internals replaced by the spec 07 engine (2026-10-06)
- [x] Issue: input guard is deterministic only (PII, injection markers, scope keywords); small-LLM injection confirmation, GUARANTEE_REQUEST path and V5–V7 land with spec 08 in M7. Closed 2026-10-09 (M7a), except the LLM injection confirmation, which is deferred (3-day scope)
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
- [x] Rules loader/compiler, evaluate_claim, `make rules` (2026-10-06): config/rules.yaml v2 (message_if, formats, next best actions, P1 insight, explain/assess keywords, premise status words); every AC-07-03/04 count reproduced; `make rules` 0.8 s, warm evaluate_claim 80–90 ms
- [x] `materialise_portfolio` replaced the M1 stub; gold.rule_results (claim, product, status, R01–R12, R04_severity, C1–C4, P1)
- [x] Dossier subgraph: gather_facts (parallel) → evaluate_rules → fetch_clauses → assemble (false premise) → review (assess mode only) → narrate (completeness guard) → customer_draft; next best actions; customer view
- [x] Spec 06 additions (2026-10-06): explain vs assess (rule 8), the narrative is the answer on claim-analysis turns (streamed as attempt 1 through the draft gate; mixed turns synthesize), deterministic claim-analysis fallback, reviewer note as a V3 source; AC-06-15 … AC-06-18
- [x] Root cause of the M4 post-override failure (reproduced 2026-10-06 on qwen3:8b): the generator cited evidence-block ids (`[e2]`) instead of source labels, so V2 failed twice and the policy-wording abstention was shown. Fixed: no block ids, V1 names `[eN]`, deterministic claim-analysis fallback. Also found: the dossier evidence carried the narrative, so V3 accepted its own invented numbers; model-written text is no longer a number source
- [~] claim_analysis.jsonl: 7 drafted (CA004–CA010, 10 items in total under the 3-day scope; spec 11 says 25). Labels derived by `python -m insurai.eval.claim_labels` independently of the engine; the two implementations agree on all 120,000 claims
- [x] CA004–CA010 signed off (Ram, 2026-10-06); `draft` tags removed; CA010 must_mention "Under Review" (the completeness guard now states the claim status when the narrative omits it; dossier_narrative.md v0.2.1)
- [ ] Issue: grow claim_analysis to 25 items (spec 11)
- **Gate:** AC-07-*; blocker_mention = 1.0; invented_findings = 0
- Recorded 2026-10-06 (`make eval-fast`, local profile, judge llama3.1:8b, ~22 min): claim_analysis 10 items: rule_status_exact, docs_exact, consistency_exact, review_interrupt, blocker_mention 1.0, invented_findings 0. M5 gate met. Other slices: policy_clauses recall@5 1.0, mrr 0.95; sql_facts 1.0; routing 75 items (the 7 new CA items included) intent 0.92, entity 1.0 (on the original 68 items 5 misses, 0.9265); e2e_sql_facts gold_in_answer 0.9474
  - [ ] Routing follow-up: CA010 "Give me a summary of claim …" routed to claim_status, not claim_analysis (planner miss on a new draft item)
  - [ ] e2e follow-up: SQL009 (gold: no missing documents) now scores the synthesized answer, which lists pending documents but never says none are missing; the earlier hit came from the abstain fallback, which the [eN] fix makes rare. Synthesize should state "no documents are missing" when the checklist's missing list is empty
- Decision 2026-10-06: the local judge is llama3.1:8b (another model family, ADR-006 amendment); eval runners judge in a second phase after all answers are generated

## M5.5 Deterministic routing and answers (before M6)
- [x] Intent pruning by trigger words: drop planner intents whose trigger words are absent from the message (e.g. an extra claim_documents on a hospital question; SQL010–SQL012, MT003). Spec 06 rule 9, AC-06-19 (2026-10-07). Trigger lists built from planner.md intent definitions, config lists and glossary synonym groups; the golden-coverage safety net passed with no additions (no words added because of an eval item)
- [x] Summary, overview and why questions about a claim promoted to claim_analysis in explain mode (CA010 "Give me a summary of claim …" routed to claim_status). Spec 06 rule 10, AC-06-20 (2026-10-07)
- [x] Deterministic template answers for single SQL-fact intents, with no synthesize LLM call: claim_status; claim_documents, with an explicit "no documents are missing" when the missing list is empty (SQL009); hospital_check; policy_details. AC-06-21 (2026-10-07); persona-filtered fields only, customer-persona tests per template
- [x] Premise check extended to claim_status answers ("Why is CLM300210 pending?" when routed to claim_status). AC-06-22 (2026-10-07)
- **Gate:** routing intent_accuracy ≥ 0.95 on the local profile; e2e_sql_facts gold_in_answer 1.0; no regression in `make eval-fast`
  - Measured 2026-10-07 (qwen3:8b): routing intent 0.9733 (73/75; misses EVAL021, EVAL034), entity 1.0; e2e_sql_facts gold_in_answer 1.0 (19/19 scored, SQL009 now passes)

## M6 Analytics — spec 02
- [x] Semantic model loader, validator, executor with timeout, repair loop, chart spec (2026-10-08). AC-02-01…06, AC-02-08
- [x] gold.rule_results in the semantic model, supervisor only (`analytics_hidden_tables`); 3 new verified queries (17 in total; approved_paid_in_full_despite_copay = 20,903); sql_examples re-indexed (AC-04-02 now 17)
- [x] UI: final SSE event carries the analytics result; Chat page shows chart (Altair), table and SQL. Verification fallback renders the result table with its [sql:…] citation, never the abstain text
- [x] analytics.jsonl: 15 items (decided 2026-10-08, 3-day scope; spec 11 says 20)
- [x] analytics_checklist.md signed off (Ram, 2026-10-08); `draft` tags removed. Gold changes at sign-off: ANA002 no longer rounds (the question does not ask for it); ANA011 asks for the four biggest claims (fifth place was a tie at 1,400,000). New test: no gold `ORDER BY … LIMIT n` has a tie at position n
- [ ] Issue: grow analytics to 20 items (spec 11)
- [ ] Open gate: AC-02-07 exec_accuracy 0.6667 on qwen3:8b on the signed-off set (2026-10-08, 30 verified queries; repair_rate 0.067, p50 10.0 s, p95 31.9 s; unsafe_blocked 1.0); target 0.90. Misses: ANA002 rounds the average (unrounded gold since sign-off), ANA003 extra hospital_id + Health filter, ANA006 extra channel column (new; passed at 0.80 before the enum-value fix changed the prompt context), ANA009 `required` filter + extra column, ANA014 rebuilt C3 from document rows. Before sign-off: 0.80 (below). Earlier: 0.6667 on qwen3:8b with 17 verified queries (10/15; unsafe_blocked 1.0, repair_rate 0.20, p50 11.7 s, p95 26.1 s; text_to_sql.md v0.3.0). Misses: ANA003 extra hospital_id column and Health filter; ANA009 wrong grouping plus an unasked `required` filter; ANA012 aggregated per customer instead of listing claims; ANA013/ANA014 rebuilt C1/C3 from rule columns instead of the flags. Experiment: generator thinking on (env override, not committed) reached 0.80 but p50 72 s, p95 520 s, with truncated JSON at max_output_tokens 1200. Re-measure on api-lite when a key exists
- Experiment 2026-10-08 (time-boxed 1 h, analytics slice only, own phase): verified_queries grown to 30 (13 general: flags as filters, top-N, record listings, shares, trends; hygiene-checked against the eval items) and an optional `sql` LLM role (falls back to generator; ADR-006 amendment, CLAUDE.md rule 8). qwen3:8b: exec_accuracy 0.80, repair_rate 0.067, p50 9.9 s, p95 26.4 s (misses ANA003 extra hospital_id + Health filter, ANA009 wrong grouping + `required`, ANA014 rebuilt C3). qwen2.5-coder:7b: 0.80, repair_rate 0.0, p50 6.7 s, p95 43.9 s incl. a cold load, 8.8 s warm (misses ANA002 no ROUND, ANA006 extra channel column, ANA009 `required`). Kept qwen3:8b (equal accuracy; no model swap inside an analytics turn); coder left commented in settings.yaml
  - [x] Sign-off questions decided 2026-10-08: ANA002 gold unrounded; ANA009 question and gold kept (filtering on `required` is a model error)
- [x] Semantic-layer improvement (prompted by ANA009): claim_documents described as every document record plus a 'No record' row per required type with no record; `required` documented for questions about required documents only. Model behaviour unchanged on qwen3:8b so far
- [x] Semantic-model fix 2026-10-08: four enum columns carried duplicate `sample_values` keys (YAML kept the last silently) and nine enum columns had none; fixed, values from the warehouse, and a test now rejects duplicate keys in semantic_model.yaml
- Recorded 2026-10-08: routing before the ANA items joined 0.96 / entity 0.9867 (75 items; misses SQL004, EVAL021, EVAL034); after, 0.9667 / 0.9889 (90 items; ANA 15/15; misses EVAL021, EVAL034, MT006, the last two run-to-run variance seen before). Other eval-fast slices unchanged: policy_clauses recall@5 1.0, sql_facts 1.0, e2e gold_in_answer 1.0, claim_analysis all 1.0
- **Gate:** AC-02-*; exec_accuracy ≥ 0.90

## M7 Guardrails + full eval — specs 08, 11
- [x] M7a, spec 08 remainder (2026-10-09): V5 PII leakage, V6 hidden fields (terms and the customer's own values), V7 groundedness judge (verify_groundedness.md v0.3.0), `guardrails.v7_live` (local off: V7 skipped in the trace, eval only; api profiles on), guarantee requests answered from the wording (§14/§15 pinned by chunk id in finalize_plan, the claim's needs, explain mode, no fast path), conflict rendering with a deterministic completion (waiting period), log redaction (PII filter on every insurai logger, `redact_for_logs`). AC-08-01, 04, 06–14
  - Found by the live AC-08-09 test (qwen3:8b): "What's the waiting period on POL…?" was routed to policy_details alone, so §4 never reached the evidence. The policy_details worker now fetches the product's coverage cell for a conflict concept the question asks about (spec 06 rule 5 note)
  - Found by eval-fast: V3 feedback repeated a raw phone number from the answer (orphans are now masked); a mandated sentence written without its period before the label got a second copy as the lead (now matched without the period)
  - Interface additions: `search_policy(..., pinned_sections=None)` (specs 04, 05), `Intent.pinned_sections`, `AnswerDraft.llm_written`, `CheckOutcome.skipped`
- Recorded 2026-10-09 (`make eval-fast`, local, ~30 min; report fast_20261009T012818Z): gate unchanged, fails only on the known open AC-02-07 (analytics.exec_accuracy 0.6667). policy_clauses recall@5 1.0, mrr 0.95; sql_facts 1.0; routing intent 0.9778 (was 0.9667; misses EVAL021, EVAL034; the guarantee augmentation changed no scored route), entity 1.0; e2e_sql_facts gold_in_answer 1.0, verifier V1–V6 1.0; claim_analysis all gated metrics 1.0 (unchanged). New, report-only:
  - guardrails slice (re-run after the fixes, fast_20261009T014429Z): not_refused, s15_cited, mandated_wording, conflict_rendered 1.0; V1–V6 1.0; V7 1.0 (2 judged; GRD001 is a template answer)
  - claim_analysis.v7_pass_rate 0.5 → 0.7 after verify_groundedness.md v0.3.0 (fast_20261009T014151Z). The remaining 3 items (CA006, CA008, CA009) are llama3.1:8b false positives: verbatim next_best_actions, "Untracked documents: none." and list headings, all in the evidence JSON. invented_findings stays 0. Not gated
- [ ] Issue: V7 judge false positives on llama3.1:8b (claim_analysis 0.7); calibrate with judge_calibration.jsonl (spec 11, M7b) and re-measure on api-lite when a key exists
- [ ] Issue: conflict concepts sum insured and co-pay deferred (3-day scope); waiting period only
- [x] AC-08-02, AC-08-03 met on the baseline full run (2026-10-09): adversarial handled 15 of 15, access refusals 7 of 7, guarantee 2 of 2; suite.false_refusal 0 of 44
- [ ] Issue: AC-08-05 (zero orphan numbers): claim_analysis narratives are now V3-scored (`orphan_numbers`, target max 0): 0 of 10 on the 2026-10-10 slice run. Tick after the next full run confirms zero across every slice
- [~] deferred: 3-day scope. LLM injection confirmation (input rule 2); a marker hit still blocks
- [x] M7b, spec 11 (2026-10-09): `--suite full` (adds policy_clauses_e2e, comparisons, adversarial, suite.false_refusal, judge calibration); `.md` report next to every JSON with counts and 95% Wilson intervals and an Open gates section; `make eval-baseline` (insurai.eval.baseline); gate against the baseline (drop > max(0.02, 1/n) for n < 30, or below a target the baseline met; `{max: x}` targets); correctness judge (judge_correctness.md, ≥ 4) on clause, comparison and claim-analysis slices (claim gold built from the labels); faithfulness from V7 in eval mode; refusal_correct, guarantee_handled, false_refusal; guard_interventions (reported). Per-pair §15 FAQ labels (AC-03-10). V7 verbatim pre-check (AC-08-15). AC-11-09–18
  - Datasets signed off (Ram, 2026-10-09), tags `signed_off_2026-10-09`: adversarial.jsonl ADV001–015 (3-day scope: 15 of 25), comparisons.jsonl CMP001–005 (5 of 10; CMP002 gold_sources gained Maternity Protect §4), harder clause items EVAL036–041 (EVAL037 expected_route changed to coverage_compare at sign-off). EVAL029/030 gold relabelled to `All products §15 Training FAQ Q1`
  - Live smoke 2026-10-09 (local, qwen3:8b, adversarial slice while still draft, report slice-adversarial_20261009T043913Z): handled 15 of 15 (0.80–1.00), refusal_correct 7 of 7 (0.65–1.00), guarantee_handled 2 of 2, faithfulness 21 of 22 claims (0.78–0.99), 15 of 22 claims settled by the verbatim pre-check
- [x] Full run on the local profile (qwen3:8b, judge llama3.1:8b; git 6e6bb10, 0 draft items; report full_20261009T060120Z), promoted to eval/reports/baseline.json/.md with `make eval-baseline` on 2026-10-09. It built eval/datasets/judge_calibration.md (Part A 10 answers, Part B 7 of 7 V7 verdicts). Gate against itself: no failures. Open gates (target missed, so only regressions fail from now on):
  - analytics.exec_accuracy 10 of 15 (0.42–0.85), target 0.90 (AC-02-07, known)
  - claim_analysis.correctness 3 of 10 (0.11–0.60), target 0.90, while rule_status/docs/consistency/needs_review are 10 of 10: see the issue below
  - policy_clauses_e2e.correctness 31 of 36 (0.71–0.94), faithfulness 42 of 47 claims (0.77–0.95), citation_accuracy 33 of 36 (0.78–0.97); wrong EVAL002, EVAL004, EVAL010, EVAL021, EVAL036
  - comparisons.faithfulness 11 of 12 claims (0.65–0.99); 1 V7 error
  - Met: policy_clauses recall@5 36 of 36 (0.90–1.00), mrr 0.9236; sql_facts 20 of 20; routing intent 93 of 96 (0.91–0.99; misses EVAL021, EVAL034, EVAL036), entity 96 of 96; e2e_sql_facts 19 of 19; claim_analysis gated label metrics 10 of 10, faithfulness 65 of 65 (64 settled verbatim), guard_interventions 1 of 10; comparisons correctness 5 of 5, citation 5 of 5; adversarial handled 15 of 15 (every category), refusal_correct 7 of 7, faithfulness 21 of 22; suite.false_refusal 0 of 44 (0.00–0.08)
- [ ] Issue: claim_analysis.correctness 5 of 10 on llama3.1:8b (2026-10-10), advisory while the judge is uncalibrated. The narratives are fixed (templated opening, verbatim review line, no repeats, rupees only); the judge's reasons contradict the reference (CA001: "needs human review" marked wrong, the reference says the same). Re-measure on api-lite; human-verified correctness on the calibration sample is 8 of 10
- [x] EVAL036 no longer asks "Which claim do you mean?" (AC-06-23, 2026-10-10)
- [x] ~~Issue: EVAL036 now asks "Which product do you mean?": the rule-2 probe's confident top hit is product-specific although the gold is the common §7 Cashless section (judge 1)~~ Fixed 2026-10-10, prompted by EVAL036 (AC-06-26): rule 2 answers from the common sections when a confident common (ALL) chunk is anywhere in the unfiltered probe's top 3 (`agent.common_probe_top_k`); product-specific chunks are dropped from that evidence. On the real index the EVAL036 wording probes common (§7 in the top 3) and "What is the waiting period?" still asks which product. Not re-measured (no eval run)
- [x] The guardrails slice reports V7 faithfulness as "k of n" (AC-11-20)
- [x] Judge calibration filled in (2026-10-10): agreement 6 of 10 (0.31–0.83), V7 precision 3 of 7 (0.16–0.75): judge uncalibrated, so correctness and faithfulness are advisory, not gated (AC-11-21). Human-verified correctness on the sample 8 of 10 (0.49–0.94). After the splitter fix 3 of the 7 flags (table header, precedence sentence, specialist-review sentence) no longer reach the judge; precision over the rest 3 of 4 (0.30–0.95)
- [ ] Issue: AC-11-06 needs ≥ 80% judge agreement; llama3.1:8b is at 6 of 10. Re-calibrate on api-lite when a key exists
- [x] M7 fixes (2026-10-10): EVAL036 routing (AC-06-23), invented-product drop (AC-06-24), confidence gate (AC-06-25), templated narrative opening and verbatim reviewer line (AC-07-10, AC-07-11), currency check (AC-08-17), fixed sentences only on their trigger (AC-08-18), V7 splitter non-claims (AC-08-19), idempotent blocks (AC-08-20), qualifier rule (AC-08-21), judge robustness (AC-11-19), guardrails k of n (AC-11-20), advisory gate and calibration tables (AC-11-21), repeatable `--slice` (AC-11-22). Slice re-run (local, report slice-claim_analysis+policy_clauses_e2e+comparisons+guardrails_20261010T011212Z, gate passes with judge metrics advisory):
  - claim_analysis: correctness 3 → 5 of 10 (advisory); faithfulness 70 of 70; orphan_numbers 0 of 10; guard_interventions 1 → 3 of 10 (the templated opening no longer counts, so findings the model left out now show); label metrics 10 of 10
  - policy_clauses_e2e: correctness 31 → 33 of 36 (0.78–0.97); probes_abstained 1 → 5 of 5; v7_pass_rate 34 of 38 → 36 of 37; faithfulness 42 of 47 → 9 of 11 claims; citation_accuracy 33 of 36 (unchanged); wrong EVAL010, EVAL021, EVAL036
  - comparisons: correctness 5 of 5; faithfulness 11 of 12 → 13 of 14; v7_errors 1 → 0
  - guardrails: V7 pass rate and faithfulness 2 of 2 (now with counts)
- [x] ~~Issue: V7 faithfulness counts only the claims the judge returns; llama3.1:8b returns an empty list on most policy_clauses_e2e answers (47 claims in the baseline, 11 on 2026-10-10 over 37 judged answers)~~ Fixed 2026-10-10 (AC-08-22, AC-11-23): V7 sends the code-split claims left after the verbatim pre-check as numbered lists in batches of 8 (`guardrails.v7.batch_size`) and asks for one verdict per number (verify_groundedness.md v0.5.0); an empty or incomplete list is retried once, then that batch's claims are excluded and counted (`v7_excluded`); a judge failing on every batch is a `v7_judge_error`. Two numbers: `faithfulness` (headline, target) = (verbatim + supported) / (verbatim + judged) and `faithfulness_judged` = supported / judged. Not re-measured (no eval run)
- [ ] Re-baseline faithfulness at the next full run: the definition changed (AC-11-23), so the baseline's faithfulness counts (judge-returned claims) are not comparable; `v7_errors` is now `v7_judge_errors`
- [ ] Issue: the abstention template's wording was V7-flagged on EVAL032 in the 2026-10-10 run; it is now a fixed sentence (AC-08-19), not yet re-measured
- **Gate:** AC-08-*, AC-11-*; all spec 00 targets met; baseline committed
- [x] Eval follow-up (done in M7b: ADV014, ADV015): false-premise adversarial items, e.g. "Why is CLM300210 pending?" (it is Approved); the agent should correct the premise from tool facts. Seen 2026-10-06 on qwen3:8b: the planner routed it to claim_analysis and paused for review instead. Claim-analysis turns now correct it deterministically and explain without pausing (spec 07, AC-06-17); claim_status turns now correct it too (template answers, AC-06-22, 2026-10-07)
- [x] Eval follow-ups (done in M7b: EVAL036–041, AC-03-10): harder clause items (no product named, no shared words, multi-section); distinct labels per §15 FAQ pair (guarantee answers read labels from the chunks, so they keep working); ~~guarantee questions answered with the §15 citation rather than refused (EVAL029/030, spec 08)~~ done in M7a

## M8 API, UI, demo — specs 09, 10
- [x] API with SSE and resume, /health, /coverage-matrix, /claims/{id}/dossier (narrate=false, provisional assessment), /eval/reports (spec 09, 2026-10-05)
- [ ] Issue: AC-09-04 deferred (3-day scope): `/audit/summary` and `/audit/claims` need `portfolio_audit` (spec 07, M5)
- [ ] Issue: AC-09-06 deferred (3-day scope): `POST /eval/run` and `--via-api` (eval threads with source=eval, deleted after the run) need the spec 11 runner (M7)
- [x] `/claims/{id}/dossier?narrate=true` returns clauses, narrative and the customer message draft (spec 07, 2026-10-06). (`token` SSE events: resolved by the streaming synthesis pass, 2026-10-06)
- [x] Eval scorer (2026-10-06): `e2e_sql_facts` gold "no missing documents" now accepts a clear statement ("not missing", "no documents are missing", "nothing is missing", "all required documents are present", "missing: none") and fails any answer that also says a document is missing (negative tests in tests/eval). Note: the previous `gold_in_answer` 1.0 (2026-10-05) included a SQL009 hit from the abstain fallback's "missing: none", not from a synthesized answer; the old word list also accepted a bare "none" or "nothing" anywhere in the text
- [ ] Routing follow-up (2026-10-06, after the streaming pass): MT006 lost policy_id POL218917 on the customer's "What is my waiting period?" (entity_exact 0.9853, same as the 2026-10-05 measurement in spec 06). routing.intent_accuracy 0.9118 is unchanged and still below the 0.95 gate
- [x] Streaming synthesis pass (specs 06, 09, 10; 2026-10-06): plain-markdown synthesize with regex citations; `token`, `draft_hidden`, `heartbeat` and `tool_start` SSE events; never streams a promise or `<think>`; verified badge; status line from `config/ui_status.yaml` with tone; prompt hygiene over every prompt file (fixed golden-ID leaks in synthesize.md and templates.md, a golden phrase in planner.md)
- Recorded 2026-10-05: the busy lock is in-process, so `make api` must run a single uvicorn worker; production needs a database- or Redis-level lock (spec 09 Behaviour)
- [~] Streamlit pages (M8-lite, 2026-10-10): Chat, Claim Dossier (AC-10-10) and Eval Dashboard (AC-10-11) done, shown per persona; full trace panel (AC-10-02, AC-10-12); review card (AC-10-13)
- [ ] Issue: deferred (3-day scope): Coverage Matrix and Leakage Radar pages (AC-10-01, AC-10-04; Leakage Radar also needs /audit/*, AC-09-04); citation chips with clause expanders on the Chat page (the trace lists the retrieved clauses; the Dossier page expands its cited clauses)
- [x] `make demo-check` (AC-10-15) and `make demo` (AC-10-16); run-of-show in docs/DEMO.md. 14 of 14 twice on the local profile, 2026-10-10: core path 183 s and 163 s of model time, all steps 270 s and 249 s (AC-10-05). Still to do: a live rehearsal with the audience timing (AC-10-06, api-lite)
- [ ] Claude Desktop manual check with the README config (AC-05-09, moved from M3). The README now has the config for this machine; the check itself is manual
- [x] Thread list, rename and delete endpoints (spec 09, 2026-10-05)
- [x] Conversations sidebar (spec 10, 2026-10-06)

### M8 polish list
- [x] Greeting fast path: deterministic answers to hello and thanks, with no LLM call (spec 06 rule 1b, AC-06-27)
- [x] UI: "Answered by: template (no LLM)" unless a model wrote the answer (`llm_written` on the total trace event; AC-10-12)
- [x] Client-friendly trace view with plain labels (`trace_labels` in config/ui_status.yaml); raw events and JSON in an "Engineer details" expander (AC-10-12)
- [x] Named verifier checks, with the detail shown on failure: V1 Citations are real, V2 Facts are cited, V3 Numbers traced to data, V4 No promises, V5 No personal data leaked, V6 Hidden fields protected, V7 Grounded ("skipped (eval only)" on the local profile), CURRENCY Amounts in rupees (`check_names` in config/guardrails.yaml; AC-10-12)
- [x] Project `.streamlit/config.toml` that skips the first-run email prompt (`server.headless = true`) and turns off usage stats (`browser.gatherUsageStats = false`) (AC-10-14)
- [x] Demo-machine checklist (now in docs/DEMO.md; `make demo` runs the API without `--reload` and warms Ollama with `keep_alive: 30m`):
  - Run the API without `--reload`
  - Ollama `keep_alive` set, plus a warm-up request before the demo
  - Check the GPU/CPU split (`ollama ps`) at `num_ctx` 8192
  - Windows power mode Best performance, laptop plugged in
  - `powercfg` power-throttling exemptions for Python and Ollama
  - Port 8000 cleanup if a stale API holds it: `Get-NetTCPConnection -LocalPort 8000 -State Listen | Select-Object OwningProcess`, then `Stop-Process -Id <pid>` (Git Bash: `netstat -ano | findstr :8000`, then `taskkill /PID <pid> /F`)
- [ ] Skipped in M8-lite (3-day scope): try Ollama KV-cache quantization (`OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`), then re-measure the GPU/CPU split (`ollama ps`, 36%/64% CPU/GPU on 2026-10-06) and latency (TTFT 9.4 s, total 12.1 s, planner 7.7–8.4 tok/s on the maternity question)
- [x] Size the DraftGate hold-back to the longest possible guarantee match (max regex width over `no_guarantee.patterns`, plus a margin) instead of the fixed 64 characters; it costs about 1.7 s of TTFT on local qwen3:8b. Now 35 characters (AC-08-23); TTFT not re-measured
- [x] Review card: show the blockers and next best actions from the review summary, with the counts line (AC-10-13)
- [x] Deterministic guarantee answers (AC-08-24, 2026-10-10): a guarantee-only claim question skips the planner, the dossier narrative and the synthesizer (zero LLM calls); verify still runs. Mixed turns still synthesize. `make demo-check` 2026-10-10: 14 of 14, guarantee step S04 1.6 s (was 63 s and 49 s), core path 116 s, all steps 202 s
- [ ] Skipped in M8-lite (3-day scope): fix the pre-existing mypy errors (about 40 on 2026-10-06 across agent, api and eval), then add mypy to `make lint`

- **Gate:** AC-09-*, AC-10-*, AC-09-10, AC-09-11, AC-10-07, AC-11-08; demo-check passes twice
  - M8-lite status 2026-10-10: demo-check passed twice (AC-10-05); AC-09-17 and AC-10-02, 10–16 met; AC-10-01 and AC-10-04 deferred (pages not built); AC-10-06 (timed rehearsal on api-lite) and AC-05-09 (Claude Desktop) are manual and open. No eval run in this milestone; the agent change (greeting fast path, AC-06-27) is covered by unit and graph tests. MT009 ("Thanks!") now routes to greeting without the planner

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
