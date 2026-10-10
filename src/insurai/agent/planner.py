"""Planner (spec 06): one structured LLM call for the Plan, then deterministic finalisation.

`finalize_plan` promotes summary and why questions to claim_analysis (rule 10), prunes intents whose
trigger words are absent (rule 9), fills IDs from the message and active_entities, resolves products
(rule 2), caps the intent count (rule 6), sets explain vs assess on claim_analysis intents, turns
unresolvable gaps into clarifications and, on a guarantee request, adds the §14/§15 wording and the claim's
needs (spec 08). It never invents an ID.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from insurai.agent import guarantee, routing
from insurai.agent.prompts import load_prompt, template
from insurai.agent.resolve import canonical_product, has_claim_reference, match_product, product_names
from insurai.agent.schemas import NO_WORKER, Entities, Intent, Plan
from insurai.rules.narrative import question_mode
from insurai.tools.schemas import Persona

# Routing rule 2 probe (an unfiltered search_policy): a confident common (ALL) top hit needs no product;
# a confident product-specific top hit needs one; no confident hit anywhere is answered with the abstention.
ProbeOutcome = Literal["common", "product", "none"]

CLAIM_INTENTS = frozenset({"claim_status", "claim_documents", "claim_interactions", "claim_analysis"})
PRODUCT_INTENTS = frozenset({"policy_question"})


@dataclass
class PlanContext:
    """What finalisation may consult, injected so the function stays testable without the warehouse."""

    persona: Persona
    principal_id: str | None
    message: str
    resolved: Entities
    active: Entities
    max_intents: int
    own_products: Callable[[], list[str]] = list  # customer persona: in-force products
    own_claims: Callable[[], list[str]] = list  # customer persona: claim IDs for a clarification
    product_of: Callable[[Entities], str | None] = lambda e: None  # product behind a claim or policy ID
    product_probe: Callable[[str], ProbeOutcome] = lambda q: "product"  # unfiltered search: see ProbeOutcome
    notes: list[str] = field(default_factory=list)
    pruned: list[str] = field(default_factory=list)  # intent types dropped by rule 9 (trace)
    promoted: int = 0  # claim_status intents turned into claim_analysis by rule 10 (trace)
    guarantee_request: bool = False  # spec 08: §14/§15 pinned, the claim's needs, explain mode
    guarantee_added: list[str] = field(default_factory=list)  # intent types the guarantee rule added (trace)


def planner_messages(
    message: str, history: list[BaseMessage], resolved: Entities, active: Entities, persona: Persona
) -> list[BaseMessage]:
    prompt = load_prompt("planner")
    system = prompt.render(
        resolved_entities=json.dumps(resolved.set_fields()),
        active_entities=json.dumps(active.set_fields()),
        product_names=", ".join(product_names()),
        persona=persona,
    )
    return [SystemMessage(system), *history, HumanMessage(message)]


def finalize_plan(plan: Plan, ctx: PlanContext) -> Plan:
    if plan.clarification and not plan.intents:
        return plan
    promoted_all, flags = routing.promote(plan.intents, ctx.message)
    keep = routing.prune(promoted_all, ctx.message)
    ctx.pruned = [i.type for k, i in enumerate(promoted_all) if k not in keep]
    ctx.promoted = sum(flags[k] for k in keep)
    pairs = [(promoted_all[k], flags[k]) for k in keep]
    if len(pairs) > ctx.max_intents:
        ctx.notes.append(template("intents_truncated", count=len(pairs), max=ctx.max_intents))
        pairs = pairs[: ctx.max_intents]

    out: list[Intent] = []
    for intent, promoted in pairs:
        entities = _fill(intent, ctx)
        needs_claim = intent.type in CLAIM_INTENTS and entities.claim_id is None
        needs_policy = (
            intent.type == "policy_details" and entities.policy_id is None and entities.claim_id is None
        )
        if needs_claim or needs_policy:
            product = entities.product or ctx.resolved.product
            if product is None and needs_claim and has_claim_reference(ctx.message):
                claims = ctx.own_claims()
                return Plan(
                    clarification=template("clarification_claim", claim_list=", ".join(claims)).strip()
                )
            if product is None and needs_policy:
                return Plan(clarification=template("clarification_policy"))
            # No claim or policy anywhere and none referred to: a question about the wording (spec 06 rule 2),
            # with the product named, or resolved below by rule 2 when none is.
            if any(i.type == "policy_question" for i in out):
                continue
            intent = intent.model_copy(update={"type": "policy_question"})
            entities = Entities(product=product)
        if intent.type in PRODUCT_INTENTS and entities.product is None:
            product, clarification = _resolve_product(intent, entities, ctx)
            if clarification:
                return Plan(clarification=clarification)
            entities = entities.model_copy(update={"product": product})
        update: dict[str, object] = {"entities": entities, "mode": None, "question": None}
        if intent.type == "claim_analysis":  # explain vs assess (deterministic, from the user's words)
            mode = "explain" if promoted else question_mode(ctx.message)
            update |= {"mode": mode, "question": ctx.message}
        out.append(intent.model_copy(update=update))
    out = routing.dedupe(out)
    if ctx.guarantee_request:
        out = _guarantee(out, ctx)
    return Plan(intents=[i.model_copy(update={"id": f"i{n}"}) for n, i in enumerate(out, start=1)])


def _guarantee(intents: list[Intent], ctx: PlanContext) -> list[Intent]:
    claim_id = ctx.resolved.claim_id or ctx.active.claim_id
    product = canonical_product(ctx.resolved.product) or (
        ctx.product_of(Entities(claim_id=claim_id)) if claim_id else None
    )
    out = guarantee.augment(intents, ctx.message, claim_id, product)
    ctx.guarantee_added = [i.type for i in out[len(intents) :]]
    return out


def _fill(intent: Intent, ctx: PlanContext) -> Entities:
    """Planner entities, with IDs not present in the message or context dropped, then gaps filled."""
    known_ids = {v for v in (*ctx.resolved.set_fields().values(), *ctx.active.set_fields().values())}
    e = intent.entities
    for id_field in ("claim_id", "policy_id", "customer_id", "hospital_id"):
        value = getattr(e, id_field)
        if value is not None and value not in known_ids and value not in ctx.message:
            e = e.model_copy(update={id_field: None})  # an invented ID; never trust it
    e = e.model_copy(update={"product": _trusted_product(e.product, ctx)})
    if intent.type in NO_WORKER or intent.type in ("analytics", "coverage_compare"):
        return e
    fill: dict[str, str | None] = {}
    if intent.type in CLAIM_INTENTS or (
        intent.type == "hospital_check" and not (e.hospital_id or e.hospital_name)
    ):
        fill["claim_id"] = e.claim_id or ctx.resolved.claim_id or ctx.active.claim_id
    if intent.type == "policy_details":
        fill["policy_id"] = e.policy_id or ctx.resolved.policy_id or ctx.active.policy_id
        if fill["policy_id"] is None:
            fill["claim_id"] = e.claim_id or ctx.resolved.claim_id or ctx.active.claim_id
    if intent.type == "customer_summary" and not e.customer_id:
        principal = ctx.principal_id if ctx.persona == "customer" else None
        fill["customer_id"] = ctx.resolved.customer_id or ctx.active.customer_id or principal
    if intent.type == "policy_question":
        fill["product"] = e.product or ctx.resolved.product
    return e.model_copy(update={k: v for k, v in fill.items() if v is not None})


def _trusted_product(name: str | None, ctx: PlanContext) -> str | None:
    """The planner's product only when the message names it (gazetteer) or the context carries it (the active
    product, or the product behind a claim or policy in the message or context); an invented product is
    dropped, so rule 2 treats the question as product-less."""
    product = canonical_product(name)
    if product is None:
        return None
    if product in (match_product(ctx.message), ctx.resolved.product, ctx.active.product):
        return product
    for source in (ctx.resolved, ctx.active):
        ids = Entities(claim_id=source.claim_id, policy_id=source.policy_id)
        if (ids.claim_id or ids.policy_id) and ctx.product_of(ids) == product:
            return product
    return None


def _resolve_product(intent: Intent, e: Entities, ctx: PlanContext) -> tuple[str | None, str | None]:
    """Routing rule 2 → (product, clarification). Generic and unanswerable questions run unfiltered (product
    None): common chunks answer the first, the abstention template the second."""
    ids_here = Entities(claim_id=ctx.resolved.claim_id, policy_id=ctx.resolved.policy_id)
    if (ids_here.claim_id or ids_here.policy_id) and (product := ctx.product_of(ids_here)):
        return product, None
    if ctx.active.product:
        return ctx.active.product, None
    products = ctx.own_products() if ctx.persona == "customer" else []
    if len(products) == 1:
        return products[0], None
    if e.policy_type is not None or ctx.product_probe(intent.sub_question) != "product":
        return None, None
    return None, template("clarification_product", product_list=", ".join(products or product_names()))
