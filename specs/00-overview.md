# 00 – Overview

Status: agreed · Owner: Ram · Architecture doc: https://claude.ai/code/artifact/5d204a71-2acf-420b-8022-a759e17ddeec

## Goal
A local-first, glass-box assistant that answers insurance claim and policy questions from the right
system of record: SQL for facts, hybrid RAG for policy clauses, a deterministic rules engine for claim
judgments. The LLM plans, picks tools and explains; it never decides a fact.

## Users
| Persona | Example need |
| --- | --- |
| customer | "Why is my claim pending?", "Is maternity covered on my plan?" |
| claims_agent | "Analyze CLM300210 and tell me if documents are missing" |
| supervisor | "Rejection rate by product in 2025", portfolio leakage audit |

## Question taxonomy → mechanism
| Intent | Example | Mechanism | Spec |
| --- | --- | --- | --- |
| claim_status | What is the status of claim CLM300210? | Deterministic tool (fast path, no LLM) | 05, 06 |
| claim_documents | Which documents are missing for CLM300500? | Tool over gold.claim_doc_checklist | 01, 05 |
| claim_interactions | Has this customer contacted us about CLM300101? | Tool, joined by claim_id only | 05 |
| policy_details | Is POL218917 in force, and what is its sum insured? | Tool over silver.policies (schedule) | 05, 06 |
| policy_question | Maternity waiting period under Health Secure Plus? | Hybrid RAG, product filter, rerank | 03, 04 |
| coverage_compare | Which health plans cover maternity, after how long? | Coverage matrix + RAG citations | 03, 04 |
| hospital_check | Is HOSP1257 in network? | Tool | 05 |
| customer_summary | Summarise customer CUST139920 | Tool over gold.v_customer_360 | 05 |
| claim_analysis | Analyze claim CLM300101 | Claim Dossier subgraph (rules + RAG + HITL) | 07 |
| analytics | Approval rate by line of business | Semantic-layer text-to-SQL | 02 |
| out_of_scope / unsafe | Guarantee my claim will be approved | Guardrail refusal | 08 |

## In scope
Everything in specs 01–11, running on one laptop: DuckDB, Qdrant embedded, fastembed models, LangGraph,
FastMCP, FastAPI, Streamlit, Arize Phoenix, an eval harness.

## Out of scope (non-goals)
Deployment, real authentication (personas are a dropdown), write-back of decisions to any system,
OCR of real claim documents, any ML fraud model (the score carries no signal, see 01), multilingual UI.

## Success criteria (PoC targets; enforced by spec 11)
| Layer | Target |
| --- | --- |
| Routing | intent accuracy ≥ 95%, entity exact match ≥ 98% |
| Retrieval | recall@5 ≥ 0.95, product precision@5 ≥ 0.90, MRR ≥ 0.85 |
| SQL | analytics execution accuracy ≥ 90%, unsafe SQL blocked 100% |
| Answers | correctness ≥ 90%, faithfulness ≥ 0.95, citation accuracy ≥ 95% |
| Claim analysis | blockers mentioned 100%, invented findings 0 |
| Guardrails | access/guarantee refusals 100%, false refusals ≤ 5% |
| Hallucination | answers with orphan numbers = 0 |
| System | p95 latency ≤ 8 s on api-lite; tokens per query reported |

## Key terms
- **as-of date**: fixed "today" = 2026-10-01 (settings.as_of_date). Never use the system clock.
- **effective_status**: In Force / Lapsed / Cancelled / Not Started, derived from dates at the as-of date.
- **evidence**: a tool result plus its `sources`; the only material the synthesizer may use.
- **SourceRef / citation label**: `[Health Secure Plus §5 Maternity]` or `[claims:CLM300210]`.
- **coverage grid**: product × diagnosis table (85 rows) derived from config/coverage_matrix.yaml.
- **dossier**: the ClaimAssessment produced by spec 07, rendered in the UI.

## Demo run-of-show (spec 10 automates it as `make demo-check`)
1. Customer persona asks for claim status; disambiguates between their claims; follow-up "which documents are missing?"
2. "What is the maternity waiting period under Health Secure Plus?" → cites §5; open trace.
3. "Is drunk driving covered under Motor Protect Comprehensive?" → cites the intoxication exclusion (§9).
4. Agent persona: "Analyze claim CLM300210" → dossier, interrupt, approve with note.
5. Customer asks for someone else's claim, then asks for a guaranteed approval → both refused.
6. Supervisor: "Rejection rate by product in 2025, as a chart" → SQL shown with chart.
7. Leakage radar, then coverage matrix.
8. Claude Desktop answers a claim question through the MCP server.
9. Eval dashboard.

## Milestones → specs
M0 scaffold · M1 → 01 · M2 → 03, 04 · M3 → 05 · M4 → 06 · M5 → 07 · M6 → 02 · M7 → 08, 11 · M8 → 09, 10.
See tasks.md for the checklist and exit gates.
