"""`make demo-check` (spec 10, AC-10-15): per-step pass/fail with reasons and timings, exit code, cleanup.

A scripted fake API replays the response shapes of each run-of-show step; no server, no LLM.
"""

from collections.abc import Iterator
from typing import Any

import pytest
from trace_fixtures import POLICY_TRACE

from insurai.agent.prompts import template
from insurai.api.client import ApiProblem, Event, Identity
from insurai.eval import demo_check
from insurai.tools.messages import guardrails, refusal

pytestmark = pytest.mark.unit

MANDATED = guardrails()["no_guarantee"]["mandated_wording"]


def _total(answered_by: str = "draft", llm_written: bool = True) -> dict[str, Any]:
    return {"kind": "total", "name": "turn", "data": {"answered_by": answered_by, "llm_written": llm_written}}


def _final(answer: str, citations: list[str], trace: list[dict[str, Any]], **extra: Any) -> list[Event]:
    return [
        ("final", {"answer_markdown": answer, "citations": citations, "trace": trace, **extra}),
        ("done", {}),
    ]


GOOD: dict[str, list[Event]] = {
    "Hello": _final(template("greeting"), [], [_total("template", False)]),
    "What is the status of my claim CLM300210?": _final(
        "Claim CLM300210 is Approved. [claims:CLM300210]", ["[claims:CLM300210]"], [_total("draft", False)]
    ),
    "What is the status of claim CLM327142?": _final(
        refusal("ACCESS_DENIED"), [], [_total("refusal", False)]
    ),
    "Can you guarantee my claim CLM311320 will be approved?": _final(
        f"I can't promise an outcome. The claim still needs the Claim Form. {MANDATED} "
        "[All products §15 Training FAQ Q1]",
        ["[All products §15 Training FAQ Q1]"],
        [_total()],
    ),
    "What is the maternity waiting period under Health Secure Plus?": [
        ("token", {"text": "The maternity ", "attempt": 1}),
        *_final(
            "The maternity waiting period is 9 months. [Health Secure Plus §5 Maternity]",
            ["[Health Secure Plus §5 Maternity]"],
            POLICY_TRACE,
        ),
    ],
    "Is drunk driving covered under Motor Protect Comprehensive?": _final(
        "No: intoxication is excluded. [Motor Protect Comprehensive §9 Exclusions]",
        ["[Motor Protect Comprehensive §9 Exclusions]"],
        [_total()],
    ),
    "Analyze claim CLM300210": [
        (
            "interrupt",
            {"assessment_summary": {"claim_id": "CLM300210", "blockers": ["Outside the policy period"]}},
        ),
        ("done", {}),
    ],
    "Why is CLM300210 pending?": _final("CLM300210 is Approved, not pending.", [], [_total()]),
    "Give me a summary of claim CLM300423": _final("Claim CLM300423 is clean.", [], [_total()]),
    "Are vet bills for my pet dog covered?": _final(
        refusal("LOW_CONFIDENCE") + "\n\nClosest clause:", [], [_total("draft", False)]
    ),
    "Show the approval rate by line of business as a chart": _final(
        "Health leads. [sql:1a2b3c4d]",
        [],
        [_total()],
        analytics={"rows": [["Health", 0.6], ["Motor", 0.5]], "chart": {"type": "bar", "x": "a", "y": "b"}},
    ),
    "How many claims were paid in full despite a co-pay?": _final(
        "20,903 claims. [sql:5e6f7a8b]", [], [_total()], analytics={"rows": [[20903]], "chart": None}
    ),
}


class FakeApi:
    def __init__(self, script: dict[str, list[Event]]) -> None:
        self.script = script
        self.deleted: list[str] = []
        self.calls: list[tuple[Any, ...]] = []

    def chat(
        self, message: str, thread_id: str | None, ident: Identity, source: str = "ui"
    ) -> Iterator[Event]:
        self.calls.append(("chat", message, ident.persona, source))
        yield "thread", {"thread_id": f"t-{len(self.calls)}"}
        yield from self.script[message]

    def resume(self, thread_id: str, action: str, note: str, ident: Identity) -> Iterator[Event]:
        self.calls.append(("resume", thread_id, action))
        yield from _final(f"Reviewer decision: **{action}**. Reviewer note: {note}", [], [_total()])

    def delete_thread(self, thread_id: str, ident: Identity) -> None:
        self.deleted.append(thread_id)

    def dossier(self, claim_id: str, ident: Identity, narrate: bool = False) -> dict[str, Any]:
        if claim_id == "CLM311320":
            return {"checklist": {"missing": ["Claim Form"], "pending": []}}
        missing = ["Claim Form", "Discharge Summary", "ID Proof", "Prescription"]
        return {"rules": [{"id": "R01"}], "checklist": {"missing": missing}, "next_best_actions": ["Request"]}

    def eval_reports(self, ident: Identity) -> list[dict[str, Any]]:
        return [
            {"run_id": "slice-x_20261010T011212Z", "suite": "slice-x"},
            {"run_id": "a", "suite": "ablation"},
        ]

    def eval_report(self, run_id: str, ident: Identity) -> dict[str, Any]:
        return {"calibration": {"part_a": {"status": "scored"}}}


def test_AC_10_15_every_step_passes_on_the_expected_shapes_and_threads_are_deleted() -> None:
    fake = FakeApi(GOOD)
    results = demo_check.run(fake)  # type: ignore[arg-type]
    assert [r.id for r in results] == [s.id for s in demo_check.STEPS]
    assert all(r.passed for r in results), [(r.id, r.reason) for r in results if not r.passed]
    assert ("resume", "t-7", "approve") in fake.calls
    assert all(c[3] == "demo" for c in fake.calls if c[0] == "chat")
    assert len(fake.deleted) == 13  # one thread per chat step
    assert "15 of 15 steps passed" in demo_check.summary(results)


def test_AC_10_15_a_failing_step_reports_its_reason_and_the_exit_code_is_1(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    script = GOOD | {
        "Hello": _final("Hi!", [], [{"kind": "llm", "name": "planner"}, _total("template", False)]),
        "Analyze claim CLM300210": _final("No pause.", [], [_total()]),
    }
    fake = FakeApi(script)
    fake.health = lambda: {"status": "ok"}  # type: ignore[attr-defined]
    monkeypatch.setattr(demo_check.ApiClient, "from_settings", classmethod(lambda cls: fake))
    assert demo_check.main([]) == 1
    results = {r.id: r for r in demo_check.run(fake)}  # type: ignore[arg-type]
    assert results["S01"].reason == "not the greeting template"
    assert results["S07"].reason == "no review pause"
    assert results["S02"].passed and results["S01"].seconds >= 0


def test_AC_10_15_promise_or_missing_mandated_wording_fails_the_guarantee_step() -> None:
    question = "Can you guarantee my claim CLM311320 will be approved?"
    promise = _final(
        "Your claim will definitely be approved. [All products §15 Training FAQ Q1]", [], [_total()]
    )
    results = demo_check.run(FakeApi(GOOD | {question: promise}), (demo_check.STEPS[3],))  # type: ignore[arg-type]
    assert results[0].reason == "mandated wording missing"


def test_AC_10_15_api_error_is_a_failed_step_not_a_crash() -> None:
    class Down(FakeApi):
        def chat(self, *args: Any, **kwargs: Any) -> Iterator[Event]:
            raise ApiProblem(503, "API_UNAVAILABLE", "Cannot reach the API")

    results = demo_check.run(Down(GOOD), demo_check.STEPS[:1])  # type: ignore[arg-type]
    assert not results[0].passed and results[0].reason == "API_UNAVAILABLE: Cannot reach the API"


def test_AC_10_15_only_selects_steps(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeApi(GOOD)
    fake.health = lambda: {"status": "ok"}  # type: ignore[attr-defined]
    monkeypatch.setattr(demo_check.ApiClient, "from_settings", classmethod(lambda cls: fake))
    assert demo_check.main(["--only", "s01,S13"]) == 0
    assert [c[1] for c in fake.calls if c[0] == "chat"] == ["Hello"]


def _s15() -> demo_check.DemoStep:
    return next(s for s in demo_check.STEPS if s.id == "S15")


def test_AC_10_17_customer_policy_question_step_renders_the_trace_panel() -> None:
    fake = FakeApi(GOOD)
    results = demo_check.run(fake, (_s15(),))  # type: ignore[arg-type]
    assert results[0].passed, results[0].reason
    assert fake.calls[0][2] == "customer"


def test_AC_10_17_a_trace_the_panel_cannot_render_fails_the_step() -> None:
    question = "What is the maternity waiting period under Health Secure Plus?"
    broken = [{"kind": "intent", "name": "plan", "start_ms": 0, "end_ms": 0, "data": ["not", "a", "dict"]}]
    script = GOOD | {
        question: [
            ("token", {"text": "The maternity ", "attempt": 1}),
            *_final(
                "The maternity waiting period is 9 months. [Health Secure Plus §5 Maternity]",
                ["[Health Secure Plus §5 Maternity]"],
                [*broken, _total()],
            ),
        ]
    }
    results = demo_check.run(FakeApi(script), (_s15(),))  # type: ignore[arg-type]
    assert results[0].reason.startswith("trace panel crashed: ")
