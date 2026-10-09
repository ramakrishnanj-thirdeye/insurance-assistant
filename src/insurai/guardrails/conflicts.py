"""Conflict rendering (spec 08): when evidence holds a policy schedule value and the product wording's value
for the same concept and they differ, the answer must show both with the precedence sentence.

The synthesizer prompt carries the rule (synthesize.md rule 5) and V7 checks it; `ensure_conflicts_rendered`
is the deterministic completion for a draft that left it out. Concepts come from config/guardrails.yaml
`conflict_rendering` (waiting period only; sum insured and co-pay deferred, 3-day scope). A conflict counts
only when the wording's section label is in the evidence, so both numbers and both citations are evidence.
"""

from typing import Any

from pydantic import BaseModel

from insurai.agent.prompts import template
from insurai.agent.schemas import AnswerDraft, Evidence
from insurai.guardrails.verify import labels_in
from insurai.knowledge.coverage import get_coverage
from insurai.tools.messages import guardrails

SCHEDULE_KINDS = frozenset({"PolicyView", "ClaimView"})


class Conflict(BaseModel):
    concept: str
    name: str
    unit: str
    schedule_value: Any
    schedule_label: str
    wording_value: Any
    wording_label: str

    def line(self) -> str:
        return template(
            "conflict_line",
            concept_name=self.name,
            unit=self.unit,
            schedule_value=self.schedule_value,
            schedule_label=self.schedule_label,
            wording_value=self.wording_value,
            wording_label=self.wording_label,
        )


def precedence_sentence() -> str:
    return str(guardrails()["conflict_rendering"]["precedence_sentence"])


def find_conflicts(evidence: list[Evidence]) -> list[Conflict]:
    concepts: dict[str, dict[str, str]] = guardrails()["conflict_rendering"]["concepts"]
    labels = {ref.label for ev in evidence for ref in ev.sources}
    found: dict[tuple[str, str], Conflict] = {}
    for ev in evidence:
        product = ev.payload.get("product_name")
        if ev.kind not in SCHEDULE_KINDS or not product or not ev.sources:
            continue
        for concept, cfg in concepts.items():
            schedule = ev.payload.get(cfg["schedule_field"])
            if schedule is None:
                continue
            for cell in get_coverage(product, cfg["coverage_attribute"]):
                wording = getattr(cell, cfg["coverage_field"], None)
                cell_labels = [ref.label for ref in cell.sources if ref.label in labels]
                if wording is None or wording == schedule or not cell_labels:
                    continue
                found[(concept, ev.sources[0].label)] = Conflict(
                    concept=concept,
                    name=cfg["name"],
                    unit=cfg["unit"],
                    schedule_value=schedule,
                    schedule_label=ev.sources[0].label,
                    wording_value=wording,
                    wording_label=cell_labels[0],
                )
    return list(found.values())


def is_rendered(text: str, conflict: Conflict) -> bool:
    return (
        precedence_sentence() in text
        and f"{conflict.schedule_value} {conflict.unit}" in text
        and f"{conflict.wording_value} {conflict.unit}" in text
    )


def ensure_conflicts_rendered(draft: AnswerDraft, evidence: list[Evidence]) -> AnswerDraft:
    """The draft plus one cited line per unrendered conflict and the precedence sentence."""
    missing = [c for c in find_conflicts(evidence) if not is_rendered(draft.answer_markdown, c)]
    if not missing:
        return draft
    lines = [c.line() for c in missing]
    if precedence_sentence() not in draft.answer_markdown:
        lines.append(precedence_sentence())
    text = draft.answer_markdown.rstrip() + "\n\n" + " ".join(lines)
    return draft.model_copy(update={"answer_markdown": text, "citations": labels_in(text)})
