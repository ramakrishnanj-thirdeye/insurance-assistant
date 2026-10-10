"""The compiled agent graph (spec 06 Nodes and edges, ADR-003).

python -m insurai.agent.graph --mermaid     # write specs/reference/agent_graph.mmd
"""

import argparse
from typing import Any, Literal

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send

from insurai.agent import planner as planner_mod
from insurai.agent import routing
from insurai.agent.dossier import build_dossier_graph
from insurai.agent.history import window
from insurai.agent.prompts import load_prompt, template
from insurai.agent.resolve import fast_path_plan, greeting_plan, is_fast_path, is_greeting, resolve_entities
from insurai.agent.respond import guard_event, respond
from insurai.agent.schemas import NO_WORKER, AnswerDraft, Entities, Evidence, Plan, Reset, TraceEvent
from insurai.agent.state import AgentState, worker_payload
from insurai.agent.synthesize import abstain_draft, analytics_draft, last_question, synthesize
from insurai.agent.trace import event, instant, llm_events, now_ms
from insurai.agent.workers import WORKER_FOR, analytics_sql, claim_tools, policy_rag
from insurai.guardrails.groundedness import V7_INTENTS, judge_groundedness
from insurai.guardrails.hidden import lookup_hidden
from insurai.guardrails.input import check_input
from insurai.guardrails.schemas import GroundednessVerdict, VerificationReport
from insurai.guardrails.verify import Judge, labels_in, rewrite_guarantees, v7_skipped, verify
from insurai.llm.structured import StructuredOutputError, structured_call
from insurai.observability import get_logger
from insurai.rules.narrative import premise_correction, render_assessment
from insurai.settings import ROOT, get_settings, v7_live_now
from insurai.tools.customers import own_claims, own_products
from insurai.tools.messages import refusal
from insurai.tools.registry import TOOLS
from insurai.tools.schemas import AccessDenied, ClaimView, PolicyView, ToolContext

log = get_logger(__name__)

MERMAID_FILE = ROOT / "specs" / "reference" / "agent_graph.mmd"
NODES = (
    "input_guard",
    "resolve_context",
    "planner",
    "claim_tools",
    "policy_rag",
    "analytics_sql",
    "claim_dossier",
    "synthesize",
    "verify",
    "respond",
)  # spec 06 node table, in order
WORKERS = ("claim_tools", "policy_rag", "analytics_sql", "claim_dossier")


def _trace_id(state: AgentState, config: RunnableConfig) -> str:
    thread = (config.get("configurable") or {}).get("thread_id", "local")
    return f"{thread}-t{state.get('turn', 0)}"


def _ctx(state: AgentState, config: RunnableConfig) -> ToolContext:
    return ToolContext(
        persona=state["persona"],
        principal_id=state.get("principal_id"),
        as_of=get_settings().as_of_date,
        trace_id=_trace_id(state, config),
    )


# --- nodes ------------------------------------------------------------------------------------------------


def input_guard(state: AgentState) -> dict[str, Any]:
    """Per-turn reset (required), then spec 08 input checks on the new message; masks PII in state."""
    start = now_ms()
    turn = state.get("turn", 0) + 1
    last = state["messages"][-1]
    guard = check_input(str(last.content), state["persona"])
    update: dict[str, Any] = {
        "evidence": Reset(),
        "trace": Reset(),
        "plan": None,
        "assessment": None,
        "review": None,
        "draft": None,
        "verification": None,
        "attempts": 0,
        "turn": turn,
        "guard": guard,
        "resolved": None,
        "fast_path": False,
        "refusal": None,
        "notes": [],
        "turn_started_ms": start,
        "verdict": None,
    }
    if state.get("active_entities") is None:
        principal = state.get("principal_id") if state["persona"] == "customer" else None
        update["active_entities"] = Entities(customer_id=principal)
    if guard.pii_found:
        update["messages"] = [HumanMessage(content=guard.masked_text, id=last.id)]
    update["guard_end_ms"] = (
        now_ms()
    )  # the guard span is traced by the next node: trace must stay a Reset here
    return update


def resolve_context(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    start = now_ms()
    turn = state["turn"]
    text = state["guard"].masked_text if state.get("guard") else last_question(state)
    resolved = resolve_entities(text)
    update: dict[str, Any] = {"resolved": resolved}
    if state["persona"] == "customer":
        ctx = _ctx(state, config)
        for tool_name, arg in (("get_claim", resolved.claim_id), ("get_policy", resolved.policy_id)):
            if arg and isinstance(TOOLS[tool_name](ctx, arg), AccessDenied):
                update["refusal"] = refusal("ACCESS_DENIED")
    guarantee = bool(state.get("guard") and state["guard"].guarantee_request)  # needs §15 and the dossier
    fast = "refusal" not in update and not guarantee and is_fast_path(text) and resolved.claim_id is not None
    greeting = "refusal" not in update and not guarantee and not fast and is_greeting(text)
    if fast:
        update |= {"fast_path": True, "plan": fast_path_plan(text, resolved.claim_id)}  # type: ignore[arg-type]
    elif greeting:  # routing rule 1b: the greeting template, no planner call
        update |= {"fast_path": True, "plan": greeting_plan(text)}
    update["trace"] = [
        guard_event(state),
        event(
            "entity",
            "resolve_context",
            turn,
            start,
            resolved=resolved.set_fields(),
            active=(state.get("active_entities") or Entities()).set_fields(),
            fast_path=fast or greeting,
            refused=bool(update.get("refusal")),
        ),
    ]
    if fast or greeting:
        intents = ["claim_status"] if fast else ["greeting"]
        update["trace"].append(instant("intent", "fast_path", turn, intents=intents))
    return update


def planner(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    turn = state["turn"]
    text = state["guard"].masked_text if state.get("guard") else last_question(state)
    resolved = state.get("resolved") or Entities()
    active = state.get("active_entities") or Entities()
    settings = get_settings()
    history = window(state.get("messages", []), settings.agent.history_turns)
    messages = planner_mod.planner_messages(text, history, resolved, active, state["persona"])
    prompt = load_prompt("planner")
    start = now_ms()
    trace = []
    try:
        plan, call = structured_call("generator", Plan, messages, prompt.id, prompt.version, config)
        trace += llm_events(call, turn, start)
    except StructuredOutputError:
        plan = Plan(clarification=template("planner_failure"))
    ctx = _ctx(state, config)
    pctx = planner_mod.PlanContext(
        persona=state["persona"],
        principal_id=state.get("principal_id"),
        message=text,
        resolved=resolved,
        active=active,
        max_intents=settings.agent.max_parallel_workers,
        own_products=lambda: own_products(ctx),
        own_claims=lambda: own_claims(ctx),
        product_of=lambda e: _product_of(ctx, e),
        product_probe=lambda q: _product_probe(ctx, q),
        guarantee_request=bool(state.get("guard") and state["guard"].guarantee_request),
    )
    final = planner_mod.finalize_plan(plan, pctx)
    trace.append(
        instant(
            "intent",
            "plan",
            turn,
            raw=[i.type for i in plan.intents],
            pruned=pctx.pruned,
            promoted=pctx.promoted,
            guarantee_request=pctx.guarantee_request,
            guarantee_added=pctx.guarantee_added,
            intents=[
                {"id": i.id, "type": i.type, "entities": i.entities.set_fields()} for i in final.intents
            ],
            clarification=final.clarification,
        )
    )
    return {"plan": final, "notes": pctx.notes, "trace": trace}


def _product_of(ctx: Any, e: Entities) -> str | None:
    if e.claim_id and isinstance(claim := TOOLS["get_claim"](ctx, e.claim_id), ClaimView):
        return claim.product_name
    if e.policy_id and isinstance(policy := TOOLS["get_policy"](ctx, e.policy_id), PolicyView):
        return policy.product_name
    return None


def _product_probe(ctx: Any, question: str) -> planner_mod.ProbeOutcome:
    """Routing rule 2: one unfiltered search decides if a product-less policy question needs a product."""
    result = TOOLS["search_policy"](ctx, question)
    s = get_settings()
    return routing.probe_outcome(result, s.retrieval.rerank_threshold, s.agent.common_probe_top_k)


def verify_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    start = now_ms()
    draft = state["draft"]
    evidence = state.get("evidence", [])
    question = last_question(state)
    if decision := state.get("review"):
        question += "\n" + decision.note  # the reviewer's note may carry numbers (V3), like the question
    as_of = get_settings().as_of_date
    persona, principal = state["persona"], state.get("principal_id")
    hidden = lookup_hidden(principal) if persona == "customer" and principal else None
    judge_trace: list[TraceEvent] = []
    judge, v7_note = _v7_judge(state, draft, config, judge_trace)  # type: ignore[arg-type]

    def run(d: AnswerDraft) -> VerificationReport:
        return verify(d, evidence, persona, question, as_of, hidden=hidden, judge=judge)

    report = run(draft)  # type: ignore[arg-type]
    rewritten = False
    if not report.passed and [c.check for c in report.checks if not c.passed] == ["V4"]:
        draft = draft.model_copy(update={"answer_markdown": rewrite_guarantees(draft.answer_markdown)})  # type: ignore[union-attr]
        report = run(draft)  # type: ignore[arg-type]
        rewritten = True
    if v7_note and report.passed:
        report = report.model_copy(update={"checks": [*report.checks, v7_skipped(v7_note)]})
    attempts = state.get("attempts", 0)
    update: dict[str, Any] = {"verification": report, "draft": draft}
    if report.passed:
        outcome = "pass"
    elif attempts < get_settings().agent.verifier_retries:
        outcome, update["attempts"] = "retry", attempts + 1
    else:
        outcome, update["draft"] = "abstain", fallback_draft(state, evidence)
    update["verdict"] = outcome
    update["trace"] = [
        event(
            "verify",
            "verify",
            state["turn"],
            start,
            outcome=outcome,
            attempts=attempts,
            v4_rewrite=rewritten,
            checks=[c.model_dump() for c in report.checks],
        ),
        *judge_trace,
    ]
    return update


V7_OFF_NOTE = "guardrails.v7_live is off for profile {profile}; V7 runs in the eval only"


def _v7_judge(
    state: AgentState, draft: AnswerDraft, config: RunnableConfig, trace: list[TraceEvent]
) -> tuple[Judge | None, str | None]:
    """(judge, note): the V7 judge when this answer needs one and v7_live is on; otherwise a trace note when
    V7 would have run. Judge calls land in `trace`; a judge error skips V7 (logged, and the check says so)."""
    plan = state.get("plan")
    if not draft.llm_written or not plan or not any(i.type in V7_INTENTS for i in plan.intents):
        return None, None
    if not v7_live_now():
        return None, V7_OFF_NOTE.format(profile=get_settings().llm.profile)
    turn = state["turn"]

    def judge(answer: str, evidence: list[Evidence]) -> GroundednessVerdict | None:
        start = now_ms()
        try:
            verdict, calls = judge_groundedness(answer, evidence, config)
        except StructuredOutputError:
            log.warning("V7 judge failed on turn %s; V7 skipped", turn)
            return None
        for call in calls:  # none: the verbatim pre-check settled every claim
            trace.extend(llm_events(call, turn, start))
        return verdict

    return judge, None


def fallback_draft(state: AgentState, evidence: list[Evidence]) -> AnswerDraft:
    """After the last failed attempt: for a claim-analysis turn, the assessment rendered without an LLM
    (findings, next steps, citations; respond appends the reviewer decision), never the policy-wording
    abstention; for a turn with an analytics result, the result table with its citation; otherwise the
    abstain draft."""
    if any(ev.kind == "AnalyticsResult" for ev in evidence):
        return analytics_draft(evidence)
    assessment = state.get("assessment")
    plan = state.get("plan")
    intent = next((i for i in plan.intents if i.type == "claim_analysis"), None) if plan else None
    if assessment is None or intent is None:
        return abstain_draft(evidence)
    status = assessment.facts.get("claim_status")
    text = render_assessment(assessment, premise_correction(intent.question, assessment.claim_id, status))
    return AnswerDraft(answer_markdown=text, citations=labels_in(text))


# --- routing ----------------------------------------------------------------------------------------------


def route_guard(state: AgentState) -> Literal["resolve_context", "respond"]:
    guard = state.get("guard")
    return "respond" if guard is not None and not guard.allowed else "resolve_context"


def route_resolved(state: AgentState, config: RunnableConfig) -> Any:
    if state.get("refusal"):
        return "respond"
    if state.get("fast_path") and state.get("plan"):
        if all(i.type in NO_WORKER for i in state["plan"].intents):
            return "respond"
        return [
            Send("claim_tools", worker_payload(state, i, _trace_id(state, config)))
            for i in state["plan"].intents
        ]
    return "planner"


def route_plan(state: AgentState, config: RunnableConfig) -> Any:
    plan = state.get("plan")
    if plan is None or plan.clarification:
        return "respond"
    sends = [
        Send(WORKER_FOR[i.type], worker_payload(state, i, _trace_id(state, config)))
        for i in plan.intents
        if i.type not in NO_WORKER
    ]
    return sends or "respond"


def route_verified(state: AgentState) -> Literal["synthesize", "respond"]:
    return "synthesize" if state.get("verdict") == "retry" else "respond"


# --- build ------------------------------------------------------------------------------------------------


def build_graph(checkpointer: BaseCheckpointSaver | None = None) -> CompiledStateGraph:
    if get_settings().agent.tool_transport != "inprocess":
        raise NotImplementedError("agent.tool_transport=mcp is deferred (3-day scope); use inprocess")
    g = StateGraph(AgentState)
    g.add_node("input_guard", input_guard)
    g.add_node("resolve_context", resolve_context)
    g.add_node("planner", planner)
    g.add_node("claim_tools", claim_tools)
    g.add_node("policy_rag", policy_rag)
    g.add_node("analytics_sql", analytics_sql)
    g.add_node("claim_dossier", build_dossier_graph())
    g.add_node("synthesize", synthesize)
    g.add_node("verify", verify_node)
    g.add_node("respond", respond)

    g.add_edge(START, "input_guard")
    g.add_conditional_edges("input_guard", route_guard, ["resolve_context", "respond"])
    g.add_conditional_edges("resolve_context", route_resolved, ["claim_tools", "planner", "respond"])
    g.add_conditional_edges("planner", route_plan, [*WORKERS, "respond"])
    for worker in WORKERS:
        g.add_edge(worker, "synthesize")
    g.add_edge("synthesize", "verify")
    g.add_conditional_edges("verify", route_verified, ["synthesize", "respond"])
    g.add_edge("respond", END)
    return g.compile(checkpointer=checkpointer)


def mermaid() -> str:
    return build_graph().get_graph().draw_mermaid()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="insurai.agent.graph")
    parser.add_argument("--mermaid", action="store_true", help=f"write {MERMAID_FILE.relative_to(ROOT)}")
    args = parser.parse_args(argv)
    if args.mermaid:
        MERMAID_FILE.write_text(mermaid(), encoding="utf-8", newline="\n")
        log.info("wrote %s", MERMAID_FILE)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
