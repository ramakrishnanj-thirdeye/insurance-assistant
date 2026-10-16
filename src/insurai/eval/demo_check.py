"""`make demo-check` (spec 10, AC-10-05, AC-10-15): the docs/DEMO.md run-of-show, headless, via ApiClient.

Each step asks its question as its persona on a fresh thread (source "demo") and checks the response shape:
citations, refusals, the review pause, the chart spec, template answers. S15 also renders the returned trace
through the UI's "How this answer was produced" panel (Streamlit AppTest, no browser). The report lists
pass or fail, the reason and the seconds per step; the exit code is 1 when any step fails. Demo threads are
deleted at the end.
Needs a running API (`make api` or `make demo`); the answers come from the configured LLM profile.

    python -m insurai.eval.demo_check [--only S01,S05] [--json eval/reports/demo_check.json]
"""

import argparse
import json
import time
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from insurai.agent.prompts import template
from insurai.api.client import ApiClient, ApiProblem, Event, Identity, TurnView
from insurai.guardrails.verify import guarantee_hits
from insurai.observability import get_logger
from insurai.settings import ROOT
from insurai.tools.messages import guardrails, refusal

log = get_logger(__name__)

CUSTOMER = Identity("customer", "CUST139920")  # owns CLM300210 and CLM311320
AGENT = Identity("claims_agent", "demo")
SUPERVISOR = Identity("supervisor", "demo")
REVIEW_NOTE = "Hospital confirmed the admission by phone"
DEMO_CLAIM = "CLM300210"
DEMO_MISSING_DOCS = 4  # CLM300210: Claim Form, Discharge Summary, ID Proof, Prescription (AC-01-06)
UI_DIR = ROOT / "ui"
TRACE_PANEL_SCRIPT = """
import sys
import streamlit as st
sys.path.insert(0, {ui_dir!r})
from trace_panel import render_trace
render_trace(st.session_state["trace"], key="demo-check")
"""


@dataclass
class Turn:
    """One streamed turn: the folded view, every event, and the wall time."""

    view: TurnView
    events: list[Event]
    seconds: float
    resumed: "Turn | None" = None

    @property
    def answer(self) -> str:
        return self.view.answer or ""

    @property
    def total(self) -> dict[str, Any]:
        return next((e.get("data", {}) for e in reversed(self.view.trace) if e.get("kind") == "total"), {})

    def count(self, event: str) -> int:
        return sum(1 for name, _ in self.events if name == event)

    def llm_calls(self) -> list[str]:
        return [str(e.get("name")) for e in self.view.trace if e.get("kind") == "llm"]


Check = Callable[[Turn, ApiClient], str | None]  # None = pass, otherwise the reason


@dataclass(frozen=True)
class DemoStep:
    id: str
    title: str
    identity: Identity
    core: bool
    check: Check
    message: str | None = None  # None: an API check (the check calls the client itself)
    resume: tuple[str, str] | None = None  # (action, note) after an interrupt


@dataclass
class StepResult:
    id: str
    title: str
    persona: str
    core: bool
    passed: bool
    seconds: float
    reason: str = ""
    answer_preview: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


# --- checks -----------------------------------------------------------------------------------------------


def _first(*reasons: str | None) -> str | None:
    return next((r for r in reasons if r), None)


def _final(turn: Turn) -> str | None:
    if turn.view.error:
        return f"error: {turn.view.error}"
    if turn.view.answer is None:
        return "no final answer"
    return None


def _cites(turn: Turn, fragment: str) -> str | None:
    labels = " ".join(turn.view.citations) + " " + turn.answer
    return None if fragment in labels else f"no citation containing {fragment!r}"


def _contains(turn: Turn, *words: str) -> str | None:
    lowered = turn.answer.lower()
    missing = [w for w in words if w.lower() not in lowered]
    return f"answer lacks {missing}" if missing else None


def check_greeting(turn: Turn, api: ApiClient) -> str | None:
    return _first(
        _final(turn),
        None if turn.answer == template("greeting") else "not the greeting template",
        None if not turn.llm_calls() else f"LLM called: {turn.llm_calls()}",
        None
        if turn.total.get("answered_by") == "template"
        else f"answered_by {turn.total.get('answered_by')}",
    )


def check_own_status(turn: Turn, api: ApiClient) -> str | None:
    return _first(_final(turn), _cites(turn, f"claims:{DEMO_CLAIM}"), _contains(turn, "Approved"))


def check_access_refused(turn: Turn, api: ApiClient) -> str | None:
    return _first(
        _final(turn),
        None if turn.answer.startswith(refusal("ACCESS_DENIED")) else "not the access refusal",
        None if "CLM327142" not in " ".join(turn.view.citations) else "cites the other customer's claim",
    )


def check_guarantee(turn: Turn, api: ApiClient) -> str | None:
    """Mandated wording, a §15 citation, what the claim still needs, and no promise."""
    needs: list[str] = []
    try:
        dossier = api.dossier("CLM311320", CUSTOMER)
        checklist = dossier.get("checklist") or {}
        needs = [*checklist.get("missing", []), *checklist.get("pending", [])]
    except ApiProblem as exc:
        return f"dossier for CLM311320 failed: {exc.detail}"
    mandated = guardrails()["no_guarantee"]["mandated_wording"]
    lowered = turn.answer.lower()
    return _first(
        _final(turn),
        None if mandated in turn.answer else "mandated wording missing",
        _cites(turn, "§15"),
        None
        if not needs or any(n.lower() in lowered for n in needs)
        else f"none of the claim's needs {needs}",
        None if not guarantee_hits(turn.answer) else f"promise in the answer: {guarantee_hits(turn.answer)}",
    )


def check_maternity(turn: Turn, api: ApiClient) -> str | None:
    return _first(
        _final(turn),
        None if turn.count("token") > 0 else "no streamed tokens",
        _cites(turn, "Health Secure Plus §"),
        _contains(turn, "maternity"),
    )


def render_trace_panel(trace: list[dict[str, Any]]) -> str | None:
    """Render the trace panel headlessly as the Chat page does; the first exception is the reason."""
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string(TRACE_PANEL_SCRIPT.format(ui_dir=str(UI_DIR)), default_timeout=30)
    at.session_state["trace"] = trace
    at.run()
    if at.exception:
        return f"trace panel crashed: {at.exception[0].value}"
    return None if any(e.label == "How this answer was produced" for e in at.expander) else "no trace panel"


def check_customer_policy(turn: Turn, api: ApiClient) -> str | None:
    """A customer's policy question: cited, with a trace the Chat page can render."""
    return _first(
        check_maternity(turn, api),
        None if any(e.get("kind") == "intent" for e in turn.view.trace) else "no intent event in the trace",
        render_trace_panel(turn.view.trace),
    )


def check_drunk_driving(turn: Turn, api: ApiClient) -> str | None:
    return _first(_final(turn), _cites(turn, "Motor Protect Comprehensive §"), _contains(turn, "intoxica"))


def check_analyze(turn: Turn, api: ApiClient) -> str | None:
    review = turn.view.interrupt
    if review is None:
        return _first(_final(turn), "no review pause")
    if not review.get("blockers"):
        return "review pause without blockers"
    if turn.resumed is None:
        return "not resumed"
    after = turn.resumed
    return _first(
        _final(after),
        None
        if "Reviewer decision: **approve**" in after.answer
        else "decision missing from the final answer",
        None if REVIEW_NOTE in after.answer else "reviewer note missing",
    )


def check_false_premise(turn: Turn, api: ApiClient) -> str | None:
    return _first(
        _final(turn), _contains(turn, "Approved"), None if turn.view.interrupt is None else "paused"
    )


def check_clean_summary(turn: Turn, api: ApiClient) -> str | None:
    return _first(
        _final(turn),
        None if turn.view.interrupt is None else "paused for review",
        _contains(turn, "CLM300423"),
    )


def check_confidence_gate(turn: Turn, api: ApiClient) -> str | None:
    """The abstention template, with no model-written verdict."""
    return _first(
        _final(turn),
        None if turn.answer.startswith(refusal("LOW_CONFIDENCE")) else "not the abstention template",
        None if turn.total.get("llm_written") is False else "the answer was model-written",
    )


def _analytics(turn: Turn) -> dict[str, Any]:
    return turn.view.analytics or {}


def check_approval_chart(turn: Turn, api: ApiClient) -> str | None:
    result = _analytics(turn)
    return _first(
        _final(turn),
        None if result else "no analytics result",
        None if result.get("chart") else "no chart spec",
        None if len(result.get("rows") or []) >= 2 else "fewer than 2 rows",
        _cites(turn, "[sql:"),
    )


def check_copay(turn: Turn, api: ApiClient) -> str | None:
    result = _analytics(turn)
    values = {str(v) for row in result.get("rows") or [] for v in row}
    return _first(
        _final(turn),
        None if result else "no analytics result",
        None if "20903" in values or "20,903" in turn.answer else "20,903 not in the result",
    )


def check_dossier(turn: Turn, api: ApiClient) -> str | None:
    dossier = api.dossier(DEMO_CLAIM, AGENT)
    missing = (dossier.get("checklist") or {}).get("missing", [])
    return _first(
        None if dossier.get("rules") else "no rules",
        None if len(missing) == DEMO_MISSING_DOCS else f"{len(missing)} missing documents, expected 4",
        None if dossier.get("next_best_actions") else "no next best actions",
    )


def check_eval_dashboard(turn: Turn, api: ApiClient) -> str | None:
    reports = api.eval_reports(AGENT)
    run = next((r for r in reports if r.get("suite") != "ablation"), None)
    if run is None:
        return "no eval report"
    calibration = api.eval_report(run["run_id"], AGENT).get("calibration") or {}
    if (calibration.get("part_a") or {}).get("status") != "scored":
        return f"{run['run_id']} has no scored calibration"
    return None if any(r.get("suite") == "ablation" for r in reports) else "no ablation report"


STEPS: tuple[DemoStep, ...] = (
    DemoStep("S01", "Greeting (no LLM)", CUSTOMER, True, check_greeting, "Hello"),
    DemoStep(
        "S02",
        "Own claim status",
        CUSTOMER,
        True,
        check_own_status,
        "What is the status of my claim CLM300210?",
    ),
    DemoStep(
        "S03",
        "Another customer's claim refused",
        CUSTOMER,
        True,
        check_access_refused,
        "What is the status of claim CLM327142?",
    ),
    DemoStep(
        "S04",
        "Guarantee question",
        CUSTOMER,
        True,
        check_guarantee,
        "Can you guarantee my claim CLM311320 will be approved?",
    ),
    DemoStep(
        "S05",
        "Maternity waiting period (streaming)",
        AGENT,
        True,
        check_maternity,
        "What is the maternity waiting period under Health Secure Plus?",
    ),
    DemoStep(
        "S06",
        "Drunk driving under Motor Protect Comprehensive",
        AGENT,
        True,
        check_drunk_driving,
        "Is drunk driving covered under Motor Protect Comprehensive?",
    ),
    DemoStep(
        "S07",
        "Analyze claim with review pause",
        AGENT,
        True,
        check_analyze,
        "Analyze claim CLM300210",
        resume=("approve", REVIEW_NOTE),
    ),
    DemoStep(
        "S08", "False premise corrected", AGENT, False, check_false_premise, "Why is CLM300210 pending?"
    ),
    DemoStep(
        "S09",
        "Clean claim summary",
        AGENT,
        False,
        check_clean_summary,
        "Give me a summary of claim CLM300423",
    ),
    DemoStep(
        "S10",
        "Confidence gate abstains",
        AGENT,
        False,
        check_confidence_gate,
        "Are vet bills for my pet dog covered?",
    ),
    DemoStep(
        "S11",
        "Approval rate by line of business (chart)",
        SUPERVISOR,
        True,
        check_approval_chart,
        "Show the approval rate by line of business as a chart",
    ),
    DemoStep(
        "S12",
        "Paid in full despite a co-pay",
        SUPERVISOR,
        False,
        check_copay,
        "How many claims were paid in full despite a co-pay?",
    ),
    DemoStep("S13", "Claim Dossier data for CLM300210", AGENT, True, check_dossier),
    DemoStep("S14", "Eval Dashboard data (calibration, ablation)", AGENT, True, check_eval_dashboard),
    DemoStep(
        "S15",
        "Customer policy question with the trace panel",
        CUSTOMER,
        False,
        check_customer_policy,
        "What is the maternity waiting period under Health Secure Plus?",
    ),
)


# --- runner -----------------------------------------------------------------------------------------------


def _fold(events: Iterator[Event]) -> tuple[TurnView, list[Event]]:
    view, seen = TurnView(), []
    for event, data in events:
        seen.append((event, data))
        view.apply(event, data)
    return view, seen


def run_step(api: ApiClient, step: DemoStep, threads: list[tuple[str, Identity]]) -> StepResult:
    started = time.perf_counter()
    turn = Turn(TurnView(), [], 0.0)
    try:
        if step.message is not None:
            view, events = _fold(api.chat(step.message, None, step.identity, source="demo"))
            turn = Turn(view, events, time.perf_counter() - started)
            if view.thread_id:
                threads.append((view.thread_id, step.identity))
            if step.resume and view.interrupt is not None and view.thread_id:
                action, note = step.resume
                again = time.perf_counter()
                rview, revents = _fold(api.resume(view.thread_id, action, note, step.identity))
                turn.resumed = Turn(rview, revents, time.perf_counter() - again)
        reason = step.check(turn, api)
    except ApiProblem as exc:
        reason = f"{exc.code}: {exc.detail}"
    shown = (turn.resumed or turn).answer
    return StepResult(
        id=step.id,
        title=step.title,
        persona=step.identity.persona,
        core=step.core,
        passed=reason is None,
        seconds=round(time.perf_counter() - started, 1),
        reason=reason or "",
        answer_preview=shown[:160].replace("\n", " "),
    )


def run(api: ApiClient, steps: tuple[DemoStep, ...] = STEPS) -> list[StepResult]:
    threads: list[tuple[str, Identity]] = []
    results = []
    try:
        for step in steps:
            result = run_step(api, step, threads)
            log.info(
                "%s %s %-48s %6.1f s %s",
                step.id,
                "PASS" if result.passed else "FAIL",
                step.title,
                result.seconds,
                result.reason,
            )
            results.append(result)
    finally:
        for thread_id, ident in threads:
            try:
                api.delete_thread(thread_id, ident)
            except ApiProblem:
                log.warning("could not delete demo thread %s", thread_id)
    return results


def summary(results: list[StepResult]) -> str:
    core = [r for r in results if r.core]
    lines = [
        f"demo-check: {sum(r.passed for r in results)} of {len(results)} steps passed",
        f"core path {sum(r.seconds for r in core):.0f} s, all steps {sum(r.seconds for r in results):.0f} s",
    ]
    lines += [f"  {r.id} FAIL {r.title}: {r.reason}" for r in results if not r.passed]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the demo run-of-show headlessly against the API.")
    parser.add_argument("--only", help="comma-separated step ids, e.g. S01,S05")
    parser.add_argument("--json", type=Path, help="also write the results as JSON (step timings for DEMO.md)")
    args = parser.parse_args(argv)
    wanted = {s.strip().upper() for s in args.only.split(",")} if args.only else None
    steps = tuple(s for s in STEPS if wanted is None or s.id in wanted)
    api = ApiClient.from_settings()
    try:
        api.health()
    except ApiProblem as exc:
        log.error("%s", exc.detail)
        return 1
    results = run(api, steps)
    log.info("%s", summary(results))
    if args.json:
        args.json.write_text(json.dumps([asdict(r) for r in results], indent=2), encoding="utf-8")
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
