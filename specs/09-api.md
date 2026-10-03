# 09 – API (FastAPI)

Milestone: M8 (a minimal /chat lands in M4 for manual testing) · Depends on: 06, 07, 11

## Goal
A thin, typed, streaming API over the graph and tools, so the UI is swappable and evals can run through it.

## Endpoints
| Method | Path | Body / query | Returns |
| --- | --- | --- | --- |
| POST | /chat | ChatRequest {message, thread_id?, persona, principal_id?} | SSE stream (below) |
| POST | /chat/resume | ResumeRequest {thread_id, action: approve|override|request_info, note} | SSE stream |
| GET | /threads/{thread_id} | — | message history + last trace |
| GET | /claims/{claim_id}/dossier | ?narrate=false&persona=&principal_id= | ClaimAssessment |
| GET | /coverage-matrix | ?product=&attribute= | CoverageCells |
| GET | /audit/summary | persona must be supervisor | PortfolioReport counts by rule, flag, product |
| GET | /audit/claims | ?flag=C1&product=&limit=50 | sample claims for drill-down |
| POST | /eval/run | {suite: fast|full|ablation} | {run_id} (background task) |
| GET | /eval/reports | — | list of runs with headline metrics |
| GET | /eval/reports/{run_id} | — | full report JSON |
| GET | /health | — | {warehouse, qdrant, llm_profile, as_of, coverage_status, versions} |

Persona travels as body fields for /chat and as headers `X-Persona`, `X-Principal-Id` elsewhere (PoC only; documented).

## SSE events (`event:` name, `data:` JSON)
`thread` {thread_id} → `node` {name, status: start|end, ms} (repeated) → `tool` {name, args_redacted, ms, ok} →
`token` {text} (synthesize only, optional) → `interrupt` {assessment_summary} **or** `final` {answer_markdown,
citations, trace, assessment?} → `done`. Errors: `error` {code, message} then `done`.

## Behaviour
- Pydantic v2 schemas in `src/insurai/api/schemas.py`; OpenAPI at /docs.
- CORS allows the Streamlit origin from settings.
- Graph compiled once at startup; DuckDB and Qdrant clients opened once (read-only DuckDB).
- Errors as RFC 7807 problem+json for non-streaming endpoints.

## Acceptance criteria
- [ ] AC-09-01 `make api` serves /docs; /health reports ok for warehouse and qdrant.
- [ ] AC-09-02 TestClient streaming test: /chat emits thread → node… → final → done for "status of CLM300210".
- [ ] AC-09-03 Interrupt flow over HTTP: /chat (agent, analyze CLM300210) ends with `interrupt`; /chat/resume approve ends with `final` containing the decision.
- [ ] AC-09-04 /audit/* with persona customer or claims_agent → 403.
- [ ] AC-09-05 /claims/{id}/dossier without narrate returns in < 500 ms.
- [ ] AC-09-06 `python -m insurai.eval.run --via-api` produces the same metrics as in-process (± judge noise) on the fast suite.
