# ADR-009 Thread management
Status: accepted

**Context.** Spec 06 checkpoints conversation state per thread, but nothing listed conversations, bound
them to an identity, capped the history sent to the LLM, handled concurrent or review-pending requests, or
kept eval runs out of the demo database. A verification run also showed that `operator.add` state fields
accumulate across turns on a checkpointed thread, so turn 2 could cite turn 1's evidence.

**Decision.**
- A `threads` table (ThreadStore) lives in the same SQLite file as the LangGraph checkpointer and holds
  ownership (persona, principal), title, status, source, turn count and timestamps.
- Every thread request is authorized against the creating identity; mismatches return 403, reads included.
- Status machine active → running → active | awaiting_review, with a per-thread lock (409 THREAD_BUSY),
  409 REVIEW_PENDING / NO_PENDING_REVIEW, and startup recovery of stale running threads.
- Per-turn reset of evidence, trace and derived fields; only messages and active_entities carry over.
- The planner and synthesizer see the last 6 turns plus active_entities; full history stays for display.
- Evals use InMemorySaver in-process, or tagged threads deleted after `--via-api` runs.

**Consequences.** Conversations survive page refreshes and can be reopened from the sidebar; one identity
can never read another's history; prompt size stays flat in long conversations. Cost: one table, four
endpoints and a sidebar component (M4 for the store and rules, M8 for list, rename, delete and the UI).

**Alternatives.** Rely on the checkpointer alone (no listing, no ownership); keep threads only in
Streamlit session state (lost on refresh, no API access); summarise old turns with an LLM (unnecessary at
6-turn windows for this PoC).
