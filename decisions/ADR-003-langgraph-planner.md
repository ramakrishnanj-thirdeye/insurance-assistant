# ADR-003 LangGraph planner with parallel workers
Status: accepted

**Context.** Questions often mix sources ("status of CLM300500 and is drunk driving covered?"); claim analysis needs a pause for human review; follow-ups need memory.
**Decision.** One LangGraph graph: guard → resolve → planner (structured Plan) → `Send` fan-out to workers → synthesize → verify, with a SQLite checkpointer and `interrupt()` in the dossier subgraph. A regex fast path skips the planner for bare status questions.
**Consequences.** Explicit, testable state; parallel workers; resumable threads. More code than a single ReAct agent, but every step is traceable and evaluable.
**Alternatives.** Single ReAct tool-calling agent (opaque routing, no parallel plan), CrewAI (heavier abstraction, weaker interrupt story).
