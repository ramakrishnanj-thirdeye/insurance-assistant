"""Next best actions (spec 07 Behaviour 7): deterministic, from config/rules.yaml `next_best_actions`, ordered
by the triggering rule's severity (blocker, escalate, warning, info), then by config order, without repeats.
"""

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from insurai.rules.render import Formats, render
from insurai.rules.schemas import RuleResult
from insurai.tools.hospitals import alternatives as hospital_alternatives
from insurai.tools.schemas import HospitalSummary

SEVERITY_RANK = {"blocker": 0, "escalate": 1, "warning": 2, "info": 3}
UNTRACKED_RANK = len(SEVERITY_RANK)  # after every rule-driven action


class ActionDef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule: list[str] = Field(default_factory=list)
    status: Literal["fail", "review"] = "fail"
    untracked: bool = False  # triggered by documents the wordings require but the system does not track
    text: str
    customer_text: str


def next_best_actions(
    actions: Sequence[ActionDef],
    results: Sequence[RuleResult],
    values: Mapping[str, Any],
    fmt: Formats,
    *,
    customer: bool,
    has_untracked: bool,
) -> list[str]:
    """Rendered actions for the visible `results`; `values` holds facts, thresholds and derived values."""
    by_id = {r.id: r for r in results}
    ranked: list[tuple[int, int, str]] = []
    for order, action in enumerate(actions):
        if action.untracked:
            rank = UNTRACKED_RANK if has_untracked else None
        else:
            hits = [by_id[r] for r in action.rule if r in by_id and by_id[r].status == action.status]
            rank = min((SEVERITY_RANK[h.severity] for h in hits), default=None)
        if rank is None:
            continue
        text = render(action.customer_text if customer else action.text, values, fmt)
        ranked.append((rank, order, text))
    return list(dict.fromkeys(text for _, _, text in sorted(ranked)))


def network_alternatives(city: str, specialty: str, hospital_id: str) -> list[HospitalSummary]:
    """Network hospitals in the same city and specialty (as check_hospital), never the hospital itself."""
    return hospital_alternatives(city, specialty, hospital_id)
