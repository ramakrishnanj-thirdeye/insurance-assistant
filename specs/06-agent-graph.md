# 06 – Agent graph (LangGraph)

Milestone: M4 · Depends on: 04, 05, 08 · ADR: 003 (planner graph), 006 (LLM profiles)

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
IntentType = Literal["claim_status", "claim_documents", "claim_interactions", "claim_analysis", "policy_question",
                     "coverage_compare", "hospital_check", "customer_summary", "analytics", "greeting", "out_of_scope"]
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
    evidence: Annotated[list[Evidence], operator.add]
    assessment: ClaimAssessment | None              # spec 07
    review: ReviewDecision | None                   # human decision after interrupt
    draft: AnswerDraft | None
    verification: VerificationReport | None         # spec 08
    attempts: int
    trace: Annotated[list[TraceEvent], operator.add]
```

## Nodes and edges
| Node | Kind | Does | Next |
| --- | --- | --- | --- |
| input_guard | rules + small LLM | spec 08 input checks; masks PII | blocked → respond (refusal); else resolve_context |
| resolve_context | deterministic | regex IDs, product gazetteer (config/glossary.yaml, rapidfuzz ≥ 90), pronoun follow-ups from active_entities, ownership pre-check for customer persona | fast path → claim_tools; else planner |
| planner | LLM (generator), structured output Plan | intents + entities + sub-questions, or a clarification | clarification → respond; else Send(...) one per intent |
| claim_tools | deterministic | claim_status, claim_documents, claim_interactions, hospital_check, customer_summary | synthesize |
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
3. **Follow-ups**: "it", "this claim", "its documents", "that policy" resolve to active_entities; a new ID replaces the active one.
4. **Greeting** → short template, no tools. **out_of_scope** → OUT_OF_SCOPE refusal.
5. Max 4 intents per message (settings.agent.max_parallel_workers); extra intents → answer the first 4 and say so.

## Prompts (versioned files, IDs logged in trace)
`config/prompts/planner.md` (15+ few-shot examples covering every intent, multi-intent and clarification),
`synthesize.md`, `query_rewrite.md`, `text_to_sql.md`, `dossier_narrative.md`, `verify_groundedness.md`,
`judge_correctness.md`, `templates.md`. Each file starts with `id:` and `version:` front matter.

## Synthesis contract (AnswerDraft)
```python
class AnswerDraft(BaseModel):
    answer_markdown: str            # every factual sentence ends with ≥ 1 citation label from evidence
    citations: list[str]            # labels used
    conflicts: list[str]            # schedule-vs-document disagreements surfaced (spec 08)
    follow_ups: list[str]           # ≤ 2 suggested next questions
```
Evidence is passed inside `<evidence id=... source=...>` tags; the prompt says evidence is data, not instructions.

## Memory, interrupts, streaming
- Checkpointer: `SqliteSaver` at `paths.checkpoints`; `thread_id` from the client.
- claim_dossier calls `interrupt(assessment_summary)` when `needs_human_review` and persona ≠ customer;
  the API resumes with `Command(resume=ReviewDecision(action="approve"|"override"|"request_info", note=str))`.
- Stream modes `updates` + `messages`; the API maps them to SSE events (spec 09).

## Trace (TraceEvent list, returned with every response)
intents, entity resolution, each tool call (name, args without PII, duration, result size), SQL text,
retrieved chunks (label, fused rank, rerank score, via), rule results, verifier outcome, prompt IDs and
versions, LLM calls (role, model, input/output tokens, latency), total latency.

## Acceptance criteria
- [ ] AC-06-01 Graph compiles; `draw_mermaid()` output saved to `specs/reference/agent_graph.mmd` and matches the node table.
- [ ] AC-06-02 Routing over the full golden set: intent set accuracy ≥ 95%, entity exact match ≥ 98%.
- [ ] AC-06-03 "Status of CLM300500 and is drunk driving covered under Motor Protect Comprehensive?" → 2 intents; the trace shows overlapping worker spans.
- [ ] AC-06-04 Turn 1 "Analyze CLM300210", turn 2 "which documents are missing?" → turn 2 resolves CLM300210.
- [ ] AC-06-05 "status of CLM300210" makes zero LLM calls except the verifier's deterministic checks (callback counter = 0).
- [ ] AC-06-06 Agent persona, no context, "what is the waiting period?" → clarification asking for the product.
- [ ] AC-06-07 Agent persona "Analyze claim CLM300210" → interrupt; resume approve with note → final answer states the reviewer decision and note. Customer persona (owner CUST139920) → no interrupt; answer says a specialist will review.
- [ ] AC-06-08 "Status of CLM999999" → NOT_FOUND wording, no invented details (verifier passes with zero numbers other than the ID).
- [ ] AC-06-09 Every response carries a trace with the fields above; token counts present for every LLM call.
- [ ] AC-06-10 Switching `llm.profile` between local and api-lite needs no code change (smoke test per profile, `llm` marker).

## Eval hooks
Routing metrics on every slice; multi_turn slice.
