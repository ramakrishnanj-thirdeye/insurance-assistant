# 09 – API (FastAPI)

Milestone: M8 (a minimal /chat and the thread store land in M4) · Depends on: 06, 07, 11 · ADR: 009 (threads)

## Goal
A thin, typed, streaming API over the graph and tools, so the UI is swappable and evals can run through it.

## Endpoints
| Method | Path | Body / query | Returns |
| --- | --- | --- | --- |
| POST | /chat | ChatRequest {message, thread_id?, persona, principal_id?} | SSE stream (below) |
| POST | /chat/resume | ResumeRequest {thread_id, action: approve|override|request_info, note} | SSE stream |
| GET | /threads | ?limit=20&offset=0 | ThreadSummary list for the caller's persona and principal, newest first |
| GET | /threads/{thread_id} | — | ThreadDetail: status, user and assistant messages, last trace, pending review summary |
| PATCH | /threads/{thread_id} | {title} | ThreadSummary |
| DELETE | /threads/{thread_id} | — | 204; removes the thread record and its checkpoints |
| GET | /claims/{claim_id}/dossier | ?narrate=false&persona=&principal_id= | ClaimAssessment (narrate=true adds clauses, narrative and customer message draft; no interrupt on this path) |
| GET | /coverage-matrix | ?product=&attribute= | CoverageCells |
| GET | /audit/summary | persona must be supervisor | PortfolioReport counts by rule, flag, product |
| GET | /audit/claims | ?flag=C1&product=&limit=50 | sample claims for drill-down |
| POST | /eval/run | {suite: fast|full|ablation} | {run_id} (background task) |
| GET | /eval/reports | — (claims_agent, supervisor) | list of runs with headline metrics |
| GET | /eval/reports/{run_id} | — (claims_agent, supervisor) | full report JSON |
| GET | /health | — | {warehouse, qdrant, llm_profile, as_of, coverage_status, versions} |

Identity travels as headers on every endpoint: `X-Persona` (required) and `X-Principal-Id` (required for
customer; optional operator name for staff personas, default `staff`). PoC only; production maps SSO claims
to the same two values. Exception: `/health` needs no identity. `/eval/reports*` allow only personas with
`can_read_eval_reports` in config/personas.yaml (claims_agent, supervisor); a customer gets 403 `ACCESS_DENIED`.

## Thread management (ADR-009)
```python
# src/insurai/agent/threads.py
ThreadStatus = Literal["active", "running", "awaiting_review"]
class ThreadRecord(BaseModel):
    thread_id: str                  # uuid4 hex, created server-side only
    persona: Persona; principal_id: str
    title: str                      # first user message, PII-masked, <= 60 chars + "…"
    status: ThreadStatus; source: Literal["ui", "api", "eval", "demo"]
    turn_count: int; last_entities: Entities | None
    created_at: datetime; updated_at: datetime   # wall-clock UTC metadata, not business dates (CLAUDE.md rule 5 is about business logic)
class ThreadStore:                  # table `threads` in the same SQLite file as the checkpointer
    async def create(self, persona, principal_id, first_message, source) -> ThreadRecord: ...
    async def authorize(self, thread_id, persona, principal_id) -> ThreadRecord: ...  # ThreadNotFound -> 404, ThreadForbidden -> 403
    async def list(self, persona, principal_id, limit=20, offset=0) -> list[ThreadRecord]: ...
    async def set_status(self, thread_id, status) -> None: ...
    async def touch(self, thread_id, entities: Entities | None) -> None: ...  # turn_count += 1, updated_at, last_entities
    async def rename(self, thread_id, title) -> None: ...
    async def delete(self, thread_id) -> None: ...   # also checkpointer.adelete_thread(thread_id)
    async def recover(self) -> int: ...              # at startup: running -> active; returns count
```
Rules:
1. **Ownership.** A thread is bound to the persona and principal that created it. Any request whose identity
   differs gets 403 `THREAD_FORBIDDEN`, including reads. Unknown IDs get 404 `THREAD_NOT_FOUND`.
   Clients never invent thread IDs; `/chat` without `thread_id` creates one.
2. **Status machine.** active → running (a `/chat` or `/chat/resume` starts) → active (final) or
   awaiting_review (interrupt) → running (resume) → active.
3. **Busy.** A per-thread `asyncio.Lock` plus the persisted status: a second `/chat` or `/chat/resume` while
   running → 409 `THREAD_BUSY`. The running status is a lease (`running_since`, `run_token`, taken by
   `ThreadStore.start_run` before the stream opens and ended by `finish_run`). A lease older than
   `agent.turn_timeout_s` (300 s) is stale: it is logged and the new request takes over, which covers streams
   that never start and hung turns; a late `finish_run` with the old token changes nothing.
4. **Pending review.** `/chat` on an awaiting_review thread → 409 `REVIEW_PENDING` (body includes the review
   summary so the UI can show the card). `/chat/resume` on a thread that is not awaiting_review → 409 `NO_PENDING_REVIEW`.
5. **Errors before streaming.** 403, 404 and 409 are returned as problem+json before the SSE stream opens.
6. **Recovery.** On startup, `recover()` resets threads left in running (crash or reload): a thread whose
   checkpoint holds a pending interrupt goes to awaiting_review, every other one to active.
7. **Title.** Set once from the first user message after PII masking; rename via PATCH.
8. **Cleanup.** `make reset-threads` deletes `paths.checkpoints` (stop the API first; CLAUDE.md Windows note).

## SSE events (`event:` name, `data:` JSON)
`thread` {thread_id} → interleaved, repeated:
- `node` {name, status: start|end, ms, interrupted}; an end event may add `outcome` (verify: pass | retry |
  abstain) or `plan` (planner, and resolve_context on the fast path: {intents, product, claim_ids, policy_ids},
  never customer data or typed free text)
- `tool_start` {name, args_redacted} (well-formed IDs and canonical product names only) and `tool` {name,
  args_redacted, ms, ok}
- `heartbeat` {node, elapsed_ms, beat}: every `agent.heartbeat_s` (2 s) while a node runs longer than that
- `token` {text, attempt} (synthesize only; attempt 2 follows a verify retry) and `draft_hidden` {attempt,
  reason: guarantee | reasoning}

→ `interrupt` {assessment_summary} **or** `final` {answer_markdown, citations, trace, assessment?, verified}
→ `done`. Errors: `error` {code, message} then `done`.

**Never stream a promise.** Each attempt's accumulated draft is checked against the V4 no-guarantee
patterns; text is released only `no_guarantee.stream_holdback_chars` (64) behind the newest token, on a
word boundary, so a phrase split across chunks is never partly sent. On a hit the attempt stops streaming
and one `draft_hidden` is sent; `<think>` text never streams (an unclosed block hides the attempt). The
`final` answer is the verified text (V4 rewrite applied).

## Behaviour
- **Single API worker.** The per-thread lock is in-process, so `make api` runs one uvicorn worker. Production
  (several workers or hosts) needs the lock at the database level (e.g. a conditional UPDATE on a shared
  database) or in Redis.
- **Identity.** The headers are authoritative. `persona` / `principal_id` in a request body or query are
  optional and must equal the headers, else 400 `IDENTITY_MISMATCH`; missing headers → 400 `IDENTITY_REQUIRED`.
- **Streaming.** `node` events come from LangGraph stream mode `tasks`, `tool` events from the workers' tool
  trace events in `updates` (args already redacted; `ok` = result is not not_found/access_denied),
  `tool_start` from `custom`, `token` from `messages` filtered to the synthesize node and passed through the
  draft gate (`agent/progress.py`). Heartbeats come from `with_heartbeats` in `api/streaming.py`: a pump task
  feeds a queue so waiting for the next beat never cancels the graph iterator.
- **Connections.** Qdrant uses the process's cached reader; DuckDB stays per call (read-only), as decided
  2026-10-04 in tasks.md, so `make data` can replace the warehouse without stopping the API.
- Pydantic v2 schemas in `src/insurai/api/schemas.py`; OpenAPI at /docs.
- CORS allows the Streamlit origin from settings.
- Graph compiled once at startup; DuckDB and Qdrant clients opened once (read-only DuckDB).
- Errors as RFC 7807 problem+json for non-streaming endpoints.

## Acceptance criteria
- [x] AC-09-01 `make api` serves /docs; /health reports ok for warehouse and qdrant.
- [x] AC-09-02 TestClient streaming test: /chat emits thread → node… → final → done for "status of CLM300210".
- [x] AC-09-03 Interrupt flow over HTTP: /chat (agent, analyze CLM300210) ends with `interrupt`; /chat/resume approve ends with `final` containing the decision.
- [~] deferred: 3-day scope (needs portfolio_audit, spec 07, M5). AC-09-04 /audit/* with persona customer or claims_agent → 403.
- [x] AC-09-05 /claims/{id}/dossier without narrate returns in < 500 ms.
- [x] AC-09-07 Ownership: customer B reading or continuing customer A's thread → 403; a claims_agent using a customer's thread → 403; an unknown ID → 404.
- [x] AC-09-08 Two concurrent `/chat` calls on one thread: exactly one streams, the other gets 409 THREAD_BUSY.
- [x] AC-09-09 `/chat` on an awaiting_review thread → 409 REVIEW_PENDING with the summary; `/chat/resume` on an active thread → 409 NO_PENDING_REVIEW.
- [x] AC-09-10 `GET /threads` returns only the caller's threads, newest first, with titles PII-masked and at most 60 characters plus an ellipsis.
- [x] AC-09-11 `DELETE /threads/{id}` removes the record and its checkpoints; a later GET returns 404.
- [x] AC-09-12 A thread left in running when the API stops is active after restart.
- [x] AC-09-13 /chat event order is thread → node… → token… → final → done, with every token inside a synthesize start/end window; a verify retry streams attempt-2 tokens after `outcome: retry`; a draft containing "will definitely be approved" emits no token with the phrase, one `draft_hidden`, and a final with the mandated wording; a `<think>` block never streams.
- [x] AC-09-14 A node running longer than `heartbeat_s` gets a `heartbeat` every `heartbeat_s` (beats 1, 2, …, elapsed ≥ beat × interval); a shorter node gets none.
- [x] AC-09-15 The planner end event carries {intents, product, claim_ids, policy_ids} only; no customer name or customer ID appears in any event before `final`.
- [x] AC-09-16 `tool_start` precedes its `tool` event and carries only status-safe args; outside a graph run (MCP, scripts) nothing is emitted.
- [~] deferred: 3-day scope (needs the spec 11 runner, M7). AC-09-06 `python -m insurai.eval.run --via-api` produces the same metrics as in-process (± judge noise) on the fast suite.
