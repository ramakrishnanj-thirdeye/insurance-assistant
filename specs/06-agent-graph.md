# 06 – Agent graph (LangGraph)

Milestone: M4 · Depends on: 04, 05, 08 · ADR: 003 (planner graph), 006 (LLM profiles), 009 (threads)

## Goal
One compiled LangGraph graph answers every question: guard → resolve → plan → parallel workers →
synthesize → verify → respond, with conversation memory, a claim-analysis subgraph that can pause for
human review, and a full trace on every response.

## State
```python
# src/insurai/agent/state.py
class Entities(BaseModel):
    claim_id: str | None = None; policy_id: str | None = None; customer_id: str | None = None
    hospital_id: str | None = None; product: str | None = None; policy_type: str | None = None
    hospital_name: str | None = None; city: str | None = None
IntentType = Literal["claim_status", "claim_documents", "claim_interactions", "claim_analysis", "policy_details",
                     "policy_question", "coverage_compare", "hospital_check", "customer_summary", "analytics", "greeting", "out_of_scope"]
class Intent(BaseModel):
    id: str; type: IntentType; entities: Entities; sub_question: str
class Plan(BaseModel):
    intents: list[Intent]; clarification: str | None = None   # set → ask the user instead of running workers
class Evidence(BaseModel):
    intent_id: str; worker: str; kind: str; payload: dict; sources: list[SourceRef]; summary: str
class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    persona: Persona; principal_id: str | None
    active_entities: Entities                       # carried across turns for follow-ups
    guard: GuardResult | None                       # spec 08
    plan: Plan | None
    evidence: Annotated[list[Evidence], merge_evidence]   # per-turn; see "Per-turn reset"
    assessment: ClaimAssessment | None              # spec 07
    review: ReviewDecision | None                   # human decision after interrupt
    draft: AnswerDraft | None
    verification: VerificationReport | None         # spec 08
    attempts: int
    trace: Annotated[list[TraceEvent], merge_trace]       # per-turn; see "Per-turn reset"
    turn: int                                       # incremented by input_guard

class Reset(BaseModel): kind: Literal["reset"] = "reset"
def merge_evidence(left: list[Evidence], right: list[Evidence] | Reset) -> list[Evidence]:
    return [] if isinstance(right, Reset) else left + right       # same shape for merge_trace
```

### Per-turn reset (required)
State is checkpointed per thread, so accumulating fields survive into the next turn. Verified with the pinned
LangGraph: an `operator.add` list on a checkpointed thread holds both turns' items after turn 2. Turn 2 must
never see turn 1's evidence, or its answer could cite stale tool results and still pass V1.
`input_guard` therefore returns, at the start of every turn:
`evidence=Reset(), trace=Reset(), plan=None, assessment=None, review=None, draft=None, verification=None,
attempts=0, turn=turn+1`. Only `messages` and `active_entities` carry across turns.

## Nodes and edges
| Node | Kind | Does | Next |
| --- | --- | --- | --- |
| input_guard | rules + small LLM | spec 08 input checks; masks PII | blocked → respond (refusal); else resolve_context |
| resolve_context | deterministic | regex IDs, product gazetteer (config/glossary.yaml, rapidfuzz ≥ 90), pronoun follow-ups from active_entities, ownership pre-check for customer persona | fast path → claim_tools; else planner |
| planner | LLM (generator), structured output Plan | intents + entities + sub-questions, or a clarification | clarification → respond; else Send(...) one per intent |
| claim_tools | deterministic | claim_status, claim_documents, claim_interactions, policy_details (get_policy), hospital_check, customer_summary | synthesize |
| policy_rag | retrieval | policy_question → search_policy; coverage_compare → get_coverage then search_policy for citations | synthesize |
| analytics_sql | LLM + validator | run_analytics (spec 02) | synthesize |
| claim_dossier | subgraph | spec 07 (may interrupt) | synthesize |
| synthesize | LLM (generator), structured output AnswerDraft | answer from evidence only, with citation labels | verify |
| verify | rules + LLM judge | spec 08 output checks | pass → respond; fail and attempts < 1 → synthesize with feedback; else respond (abstain) |
| respond | deterministic | final message, trace, active_entities update | END |

Fan-out uses LangGraph `Send` from the planner's conditional edge; workers append to `evidence`
(reducer `operator.add`), and synthesize runs once after all sent workers finish.

## Routing rules
1. **Fast path**: message matches `\bCLM\d{6}\b` exactly once, contains a status keyword (status, state, where is, update), has ≤ 12 words, and no other intent keyword → Plan with one claim_status intent, no LLM call. Answer from a template (`config/prompts/templates.md`), still verified.
2. **Product resolution** for policy_question: explicit product → use it; else active_entities.product (set whenever a claim or policy is resolved: claim → policy → product); else customer persona with exactly one in-force product → that product; several → clarification listing them; agent persona with nothing → clarification "Which product?". Generic questions that apply to all products (e.g. "can approval be guaranteed?") need no product: the planner marks them `policy_type=None, product=None` and retrieval runs unfiltered; common chunks answer them.
   Before asking, one unfiltered `search_policy` probe decides (decided 2026-10-05): a confident top hit on a common
   (ALL) chunk → run unfiltered, common chunks answer; a confident product-specific top hit → clarification "Which
   product?" (AC-06-06); no confident hit anywhere → no clarification, run unfiltered and answer with the abstention
   template (LOW_CONFIDENCE plus the closest clauses, cited), without an LLM synthesis.
   A claim intent with no claim anywhere (message or active_entities), or a policy_details intent with no policy or
   claim anywhere, but a named product is a question about the wording → policy_question for that product; with no
   product either → clarification "Which claim?" / "Which policy?".
3. **Follow-ups**: "it", "this claim", "its documents", "that policy" resolve to active_entities; a new ID replaces the active one.
4. **Greeting** → short template, no tools. **out_of_scope** → OUT_OF_SCOPE refusal.
5. **Schedule vs wording**: policy_details is one policy's schedule from get_policy (recorded status, effective status,
   sum insured, waiting period, co-pay, deductible); policy_question is what a product's wording says. When a question
   needs both ("what is my waiting period?" with a policy in context), the planner emits both intents so the answer
   shows schedule and wording side by side under the spec 08 conflict rule.
6. Max 4 intents per message (settings.agent.max_parallel_workers); extra intents → answer the first 4 and say so.
7. **Counts vs one entity** (decided 2026-10-05): counts, rates, totals and trends across many records are analytics;
   a question about one specific customer, policy or claim named by ID uses that entity's intent (customer_summary,
   policy_details, claim_documents), even when it asks for a number ("how many open claims does CUST… have?").

## Prompts (versioned files, IDs logged in trace)
`config/prompts/planner.md` (15+ few-shot examples covering every intent, multi-intent and clarification),
`synthesize.md`, `query_rewrite.md`, `text_to_sql.md`, `dossier_narrative.md`, `verify_groundedness.md`,
`judge_correctness.md`, `templates.md`. Each file starts with `id:` and `version:` front matter.

## Synthesis contract (AnswerDraft)
Synthesize returns plain markdown (`text_call`, prompt `synthesize.md` v0.2.0), not structured JSON, so the
answer can stream. The planner stays structured.
```python
class AnswerDraft(BaseModel):
    answer_markdown: str            # every factual sentence ends with ≥ 1 citation label from evidence
    citations: list[str]            # labels parsed from answer_markdown by regex (labels_in)
```
Schedule-vs-document conflicts (spec 08) are sentences in the text that cite both labels. There are no
follow-up suggestions. Empty output abstains. Verify (V1–V4) runs on the complete text after the node
returns; nothing is marked verified before that.
Evidence is passed inside `<evidence id=... source=...>` tags; the prompt says evidence is data, not instructions.

## Memory, interrupts, streaming
- Checkpointer: `AsyncSqliteSaver` at `paths.checkpoints` for the API (FastAPI is async); `SqliteSaver` for sync scripts; `InMemorySaver` for in-process evals and unit tests. `thread_id` comes from the thread store (spec 09, ADR-009).
- **History window.** The planner and synthesizer receive the last `agent.history_turns` (default 6) user and assistant turns, trimmed with `langchain_core.messages.trim_messages` by turn count, plus `active_entities`. Tool and evidence messages from earlier turns are never replayed. The full history stays in the checkpoint for display. Add `history_turns: 6` under `agent:` in config/settings.yaml.
- claim_dossier calls `interrupt(assessment_summary)` when `needs_human_review` and persona ≠ customer;
  the API resumes with `Command(resume=ReviewDecision(action="approve"|"override"|"request_info", note=str))`.
- Stream modes `tasks` + `updates` (node start/end and tool events), `messages` filtered to the synthesize
  node (answer tokens, through the draft gate: never a guarantee phrase or a `<think>` block, spec 09), and
  `custom` (`tool_start` from the `@tool` wrapper). The API maps them to SSE events (spec 09). Template and
  fast-path answers make no LLM call, so they emit no tokens.

## Trace (TraceEvent list, returned with every response)
intents, entity resolution, each tool call (name, args without PII, duration, result size), SQL text,
retrieved chunks (label, fused rank, rerank score, via), rule results, verifier outcome, prompt IDs and
versions, LLM calls (role, model, input/output tokens, latency), total latency.

## Acceptance criteria
- [x] AC-06-01 Graph compiles; `draw_mermaid()` output saved to `specs/reference/agent_graph.mmd` and matches the node table.
- [ ] AC-06-02 Routing over the full golden set: intent set accuracy ≥ 95%, entity exact match ≥ 98%. Measured 2026-10-05 on local qwen3:8b, 68 items, planner.md v0.3.0 (few-shots free of golden IDs and phrasing): intent 0.8971, entity 0.9853. Entity target met; intent below target, all 7 misses are model misses (tasks.md M4).
- [x] AC-06-03 "Status of CLM300500 and is drunk driving covered under Motor Protect Comprehensive?" → 2 intents; the trace shows overlapping worker spans.
- [x] AC-06-04 Turn 1 "Analyze CLM300210", turn 2 "which documents are missing?" → turn 2 resolves CLM300210.
- [x] AC-06-05 "status of CLM300210" makes zero LLM calls except the verifier's deterministic checks (callback counter = 0).
- [x] AC-06-06 Agent persona, no context, "what is the waiting period?" → clarification asking for the product.
- [x] AC-06-07 Agent persona "Analyze claim CLM300210" → interrupt; resume approve with note → final answer states the reviewer decision and note. Customer persona (owner CUST139920) → no interrupt; answer says a specialist will review. (Dossier internals provisional until spec 07, M5.)
- [x] AC-06-08 "Status of CLM999999" → NOT_FOUND wording, no invented details (verifier passes with zero numbers other than the ID).
- [x] AC-06-09 Every response carries a trace with the fields above; token counts present for every LLM call. (SQL text arrives with run_analytics, M6; tools do not expose their SQL.)
- [x] AC-06-11 Per-turn reset: in a two-turn thread, turn 2's evidence and trace contain only turn-2 items, and an answer citing a label that only turn 1 returned fails V1.
- [x] AC-06-12 History window: after 10 prior turns, the planner and synthesizer prompts contain at most 6 turns (assert via a callback that captures message counts), and a follow-up still resolves through active_entities.
- [x] AC-06-13 Synthesize returns plain markdown; citations are parsed from the labels; V1–V4 run on the full streamed text (an orphan number in the last chunk still fails V3).
- [x] AC-06-14 The fast path, NOT_FOUND templates and other deterministic answers emit no `token` events.
- [ ] AC-06-10 Switching `llm.profile` between local and api-lite needs no code change (smoke test per profile, `llm` marker). Local passes (2026-10-05); api-lite skips until an ANTHROPIC_API_KEY exists.

- [~] deferred: 3-day scope — `agent.tool_transport: mcp` (langchain-mcp-adapters binding); `build_graph` raises NotImplementedError for it.

## Eval hooks
Routing metrics on every slice; multi_turn slice.
