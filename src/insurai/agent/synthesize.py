"""synthesize (spec 06): answer from evidence only. Deterministic templates when no judgment is needed
(fast path, a single SQL-fact intent, all-not-found, abstain); the dossier narrative as is for a
claim-analysis turn (it already streamed from the dossier's narrate node); otherwise one plain-markdown
generator call with synthesize.md, streamed to the client (spec 09 `token`). Citations are the labels
found in the text; verify checks the complete text after the node returns.
"""

import html
import json
from typing import Any

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from insurai.agent.answers import claim_status_text, template_draft
from insurai.agent.history import window
from insurai.agent.prompts import load_prompt, template
from insurai.agent.schemas import ALL_ROWS, AnswerDraft, Evidence, Plan
from insurai.agent.state import AgentState
from insurai.agent.trace import llm_events, now_ms
from insurai.guardrails.verify import NO_RESULT_KINDS, labels_in
from insurai.llm.structured import text_call
from insurai.rules.narrative import premise_correction
from insurai.settings import get_settings
from insurai.tools.messages import refusal


def synthesize(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    evidence = state.get("evidence", [])
    turn = state.get("turn", 0)
    if draft := deterministic_draft(state, evidence):
        return {"draft": draft}
    question = last_question(state)
    feedback = state["verification"].feedback if state.get("verification") and state.get("attempts") else ""
    messages = synth_messages(state, question, evidence, feedback)
    prompt = load_prompt("synthesize")
    start = now_ms()
    text, call = text_call("generator", messages, prompt.id, prompt.version, config)
    trace = llm_events(call, turn, start)
    if not text:
        return {"draft": abstain_draft(evidence), "trace": trace}
    text = with_premise_correction(text, state.get("plan"), evidence, question)
    return {"draft": AnswerDraft(answer_markdown=text, citations=labels_in(text)), "trace": trace}


def with_premise_correction(text: str, plan: Plan | None, evidence: list[Evidence], question: str) -> str:
    """A generated answer on a turn with a claim_status intent leads with the premise correction when the
    question assumes a status the claim does not have and the model left it out (spec 06 template answers)."""
    status_ids = {i.id for i in plan.intents if i.type == "claim_status"} if plan else set()
    for ev in evidence:
        if ev.intent_id in status_ids and ev.kind == "ClaimView":
            correction = premise_correction(question, ev.payload["claim_id"], ev.payload.get("claim_status"))
            if correction and correction not in text:
                return f"{correction}\n\n{text}"
    return text


def synth_messages(
    state: AgentState, question: str, evidence: list[Evidence], feedback: str
) -> list[BaseMessage]:
    system = load_prompt("synthesize").render(
        persona=state["persona"],
        question=question,
        evidence_blocks=evidence_blocks(evidence),
        feedback=feedback,
    )
    history = window(state.get("messages", []), get_settings().agent.history_turns)
    return [SystemMessage(system), *history, HumanMessage(question)]


def evidence_blocks(evidence: list[Evidence]) -> str:
    """`<evidence source=... kind=...>` blocks; the payload is escaped so evidence cannot close the tag.

    No block ids: the generator copied ids like [e2] as citations instead of the source labels (M4 manual
    test, post-override answer failed V2 twice)."""
    blocks = []
    for ev in evidence:
        labels = " ".join(s.label for s in ev.sources)
        payload = {k: v for k, v in ev.payload.items() if k != ALL_ROWS}
        body = html.escape(json.dumps(payload, ensure_ascii=False, default=str), quote=False)
        blocks.append(
            f'<evidence source="{html.escape(labels)}" kind="{ev.kind}">\n'
            f"summary: {html.escape(ev.summary, quote=False)}\n{body}\n</evidence>"
        )
    return "\n".join(blocks)


def deterministic_draft(state: AgentState, evidence: list[Evidence]) -> AnswerDraft | None:
    if evidence and all(ev.kind in NO_RESULT_KINDS for ev in evidence):
        lines = list(dict.fromkeys(ev.summary for ev in evidence))
        return AnswerDraft(answer_markdown="\n\n".join(lines))
    if state.get("fast_path") and len(evidence) == 1 and evidence[0].kind == "ClaimView":
        text = claim_status_text(evidence[0], last_question(state))
        return AnswerDraft(answer_markdown=text, citations=list(dict.fromkeys(labels_in(text))))
    assessment = state.get("assessment")
    if (
        not state.get("attempts")
        and narrative_is_answer(state.get("plan"))
        and assessment
        and assessment.narrative
    ):
        return AnswerDraft(answer_markdown=assessment.narrative, citations=labels_in(assessment.narrative))
    if evidence and all(_unanswered_unfiltered(ev) for ev in evidence):
        return abstain_draft(evidence)  # routing rule 2: no product and no confident clause anywhere
    if not state.get("attempts"):  # a verify retry goes to the generator with the feedback
        return template_draft(state.get("plan"), evidence, last_question(state))
    return None


CLAIM_TOOL_INTENTS = frozenset({"claim_status", "claim_documents", "claim_interactions"})


def narrative_is_answer(plan: Plan | None) -> bool:
    """A claim-analysis turn: exactly one claim_analysis intent, and any others are claim-tool intents on the
    same claim (the dossier covers them). Mixed turns (a policy question too) go through the generator."""
    if plan is None or plan.clarification:
        return False
    analyses = [i for i in plan.intents if i.type == "claim_analysis"]
    if len(analyses) != 1:
        return False
    claim_id = analyses[0].entities.claim_id
    return all(
        i.type == "claim_analysis" or (i.type in CLAIM_TOOL_INTENTS and i.entities.claim_id == claim_id)
        for i in plan.intents
    )


def _unanswered_unfiltered(ev: Evidence) -> bool:
    return ev.kind == "RetrievalResult" and ev.payload.get("unfiltered") and not ev.payload.get("confident")


def abstain_draft(evidence: list[Evidence]) -> AnswerDraft:
    """LOW_CONFIDENCE wording plus each evidence summary with its first citation (spec 08 abstain)."""
    lines = [refusal("LOW_CONFIDENCE"), "", template("abstain_heading")]
    cited: list[str] = []
    for ev in evidence:
        label = ev.sources[0].label if ev.sources else ""
        if label:
            cited.append(label)
        lines.append(f"- {ev.summary} {label}".rstrip())
    return AnswerDraft(answer_markdown="\n".join(lines), citations=list(dict.fromkeys(cited)))


def analytics_draft(evidence: list[Evidence], max_rows: int = 30) -> AnswerDraft:
    """An analytics answer without an LLM: each result as a markdown table with its [sql:…] citation, and the
    other evidence as cited summary lines. Used when the synthesized answer failed verification twice."""
    lines: list[str] = []
    for ev in evidence:
        label = ev.sources[0].label if ev.sources else ""
        if ev.kind != "AnalyticsResult":
            lines.append(f"- {ev.summary} {label}".rstrip())
            continue
        columns, rows = ev.payload["columns"], ev.payload.get(ALL_ROWS, ev.payload["rows"])
        lines += [template("analytics_table_heading", row_count=ev.payload["row_count"], label=label), ""]
        lines.append("| " + " | ".join(_cell(c) for c in columns) + " |")
        lines.append("|" + "---|" * len(columns))
        lines += ["| " + " | ".join(_cell(v) for v in row) + " |" for row in rows[:max_rows]]
        if len(rows) > max_rows:
            lines += ["", template("analytics_more_rows", more=len(rows) - max_rows)]
        lines.append("")
    text = "\n".join(lines).strip()
    return AnswerDraft(answer_markdown=text, citations=list(dict.fromkeys(labels_in(text))))


def _cell(value: Any) -> str:
    return "" if value is None else str(value).replace("|", r"\|")


def last_question(state: AgentState) -> str:
    for message in reversed(state.get("messages", [])):
        if isinstance(message, HumanMessage):
            return str(message.content)
    return ""
