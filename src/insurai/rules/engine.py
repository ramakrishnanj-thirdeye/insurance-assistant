"""Claim rules engine (spec 07): config/rules.yaml compiled to ONE DuckDB SELECT over gold.claim_facts.

The same SQL serves a single claim (`evaluate_claim`, WHERE claim_id = ?) and the whole portfolio
(`materialise_portfolio` → gold.rule_results, `make rules`). No LLM is involved anywhere in this module.
"""

import re
import time
from collections.abc import Iterable, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import duckdb
import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from insurai.knowledge.coverage import section_name
from insurai.knowledge.parse import citation_label
from insurai.rules.actions import ActionDef, network_alternatives, next_best_actions
from insurai.rules.render import Formats, RenderError, jsonable, placeholders, render
from insurai.rules.schemas import ClaimAssessment, ConsistencyFlag, PortfolioReport, RuleResult, Severity
from insurai.settings import ROOT, get_settings
from insurai.tools import access
from insurai.tools.base import fetch_one, one_connection
from insurai.tools.claims import get_claim_documents, get_claim_interactions
from insurai.tools.schemas import (
    AccessDenied,
    DocumentChecklist,
    InteractionHistory,
    NotFound,
    Persona,
    SourceRef,
    ToolContext,
)
from insurai.tools.sources import sql_source

RULES_FILE = ROOT / "config" / "rules.yaml"
FACTS_TABLE = "gold.claim_facts"
ANY_BLOCKER_FAIL = "<any blocker fail>"
DERIVED_VALUES = frozenset({"network_alternatives", "untracked"})  # filled by the engine, not by SQL
Cite = Literal["schedule", "coverage", "reimbursement", "human_review", "none"]
_THRESHOLD = re.compile(r"\{(\w+)\}")


class RulesConfigError(ValueError):
    """config/rules.yaml is invalid; the message names the rule (or flag) and the field."""


class SeverityIf(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    when: str
    severity: Severity


class MessageIf(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    when: str
    message: str


class RuleDef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str
    severity: Severity
    severity_if: list[SeverityIf] = Field(default_factory=list)
    applies_if: str = "TRUE"
    pass_if: str
    review_if: str = "FALSE"
    evidence: list[str]
    message: str
    message_if: list[MessageIf] = Field(default_factory=list)
    cite: Cite
    hidden_from: list[Persona] = Field(default_factory=list)

    @field_validator("id")
    @classmethod
    def _id_is_column_safe(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Z]\d{2}", value):
            raise ValueError(f"rule id {value!r} must look like R01")
        return value


class ConsistencyDef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    name: str
    when: str


class CitationDef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    product: str
    section_no: int
    section_name: str


class DossierDef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    assess_keywords: list[str] = Field(default_factory=list)
    status_words: dict[str, list[str]] = Field(default_factory=dict)
    premise_ignore: list[str] = Field(default_factory=list)


class RuleSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: int
    citations: dict[str, CitationDef]
    formats: Formats = Field(default_factory=Formats)
    rules: list[RuleDef]
    escalation: dict[str, str] = Field(default_factory=dict)
    decision_consistency: list[ConsistencyDef] = Field(default_factory=list)
    insights: list[ConsistencyDef] = Field(default_factory=list)
    next_best_actions: list[ActionDef] = Field(default_factory=list)
    dossier: DossierDef = Field(default_factory=DossierDef)

    def rule(self, rule_id: str) -> RuleDef:
        return next(r for r in self.rules if r.id == rule_id)


# --- loading and validation ------------------------------------------------------------------------------


def read_ruleset(path: Path = RULES_FILE) -> RuleSet:
    """The parsed config without the warehouse checks (planner keywords, tests)."""
    try:
        return RuleSet.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    except ValidationError as exc:
        raise RulesConfigError(f"{path.name}: {exc}") from exc


@lru_cache(maxsize=1)
def dossier_config() -> DossierDef:
    """Explain/assess keywords and premise status words (config/rules.yaml `dossier`)."""
    return read_ruleset(RULES_FILE).dossier


def load_ruleset(path: Path, con: duckdb.DuckDBPyConnection) -> RuleSet:
    """Parse and validate config/rules.yaml: every expression binds against gold.claim_facts, every
    {placeholder} is a column, a threshold or a derived value. Errors name the rule or flag."""
    ruleset = read_ruleset(path)
    thresholds = _thresholds()
    columns = facts_columns(con)
    names = columns | set(thresholds) | DERIVED_VALUES
    seen: set[str] = set()
    for rule in ruleset.rules:
        if rule.id in seen:
            raise RulesConfigError(f"{rule.id}: duplicate rule id")
        seen.add(rule.id)
        expressions = {"applies_if": rule.applies_if, "pass_if": rule.pass_if, "review_if": rule.review_if}
        expressions |= {f"severity_if[{n}]": s.when for n, s in enumerate(rule.severity_if)}
        expressions |= {f"message_if[{n}]": m.when for n, m in enumerate(rule.message_if)}
        for field, expr in expressions.items():
            _check_expression(con, rule.id, field, expr, thresholds)
        for col in rule.evidence:
            if col not in columns:
                raise RulesConfigError(f"{rule.id}: evidence column {col!r} is not in {FACTS_TABLE}")
        for field, template in [("message", rule.message)] + [
            (f"message_if[{n}]", m.message) for n, m in enumerate(rule.message_if)
        ]:
            _check_placeholders(rule.id, field, template, names)
    for flag in [*ruleset.decision_consistency, *ruleset.insights]:
        _check_expression(con, flag.id, "when", flag.when.replace(ANY_BLOCKER_FAIL, "TRUE"), thresholds)
    for n, action in enumerate(ruleset.next_best_actions):
        unknown = [r for r in action.rule if r not in seen]
        if unknown:
            raise RulesConfigError(f"next_best_actions[{n}]: unknown rule {unknown}")
        for field, template in (("text", action.text), ("customer_text", action.customer_text)):
            _check_placeholders(f"next_best_actions[{n}]", field, template, names)
    for key in ("reimbursement", "human_review"):
        if key not in ruleset.citations:
            raise RulesConfigError(f"citations: {key!r} is required")
    return ruleset


def load_rules(path: Path, con: duckdb.DuckDBPyConnection) -> list[RuleDef]:
    """The validated rules (spec 07 Interfaces); see load_ruleset for the checks."""
    return load_ruleset(path, con).rules


def facts_columns(con: duckdb.DuckDBPyConnection) -> set[str]:
    rows = con.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_schema = 'gold' AND table_name = ?",
        ["claim_facts"],
    ).fetchall()
    return {r[0] for r in rows}


def _check_expression(
    con: duckdb.DuckDBPyConnection, owner: str, field: str, expr: str, thresholds: dict[str, float]
) -> None:
    try:
        sql = substitute_thresholds(expr, thresholds)
    except KeyError as exc:
        raise RulesConfigError(f"{owner}.{field}: unknown threshold {exc.args[0]!r} in {expr!r}") from exc
    try:
        con.execute(f"SELECT CAST(({sql}) AS BOOLEAN) FROM {FACTS_TABLE} LIMIT 0")
    except duckdb.Error as exc:
        first_line = str(exc).splitlines()[0]
        raise RulesConfigError(f"{owner}.{field}: {expr!r} does not bind: {first_line}") from exc


def _check_placeholders(owner: str, field: str, template: str, names: set[str]) -> None:
    unknown = [p for p in placeholders(template) if p not in names]
    if unknown:
        raise RulesConfigError(f"{owner}.{field}: unknown placeholder(s) {unknown} in {template!r}")


def substitute_thresholds(expr: str, thresholds: dict[str, float]) -> str:
    """`{fraud_review_score}` → its settings value (numbers only, so nothing user-typed reaches SQL)."""
    return _THRESHOLD.sub(lambda m: repr(float(thresholds[m.group(1)])), expr)


def _thresholds() -> dict[str, float]:
    return {k: float(v) for k, v in get_settings().thresholds.model_dump().items()}


# --- compilation -----------------------------------------------------------------------------------------


def compile_rules(
    rules: Sequence[RuleDef],
    thresholds: dict[str, float],
    *,
    consistency: Iterable[ConsistencyDef] = (),
    insights: Iterable[ConsistencyDef] = (),
) -> str:
    """One SELECT over gold.claim_facts: every fact column, a status column per rule (`R01`), the chosen
    severity_if / message_if index (`R04_severity`, `R01_message`; 0 = default) and a boolean per flag."""

    def sub(expr: str) -> str:
        return substitute_thresholds(expr, thresholds)

    cols: list[str] = []
    for r in rules:
        cols.append(
            f"CASE WHEN NOT coalesce(({sub(r.applies_if)}), FALSE) THEN 'not_applicable' "
            f"WHEN coalesce(({sub(r.pass_if)}), FALSE) THEN 'pass' "
            f"WHEN coalesce(({sub(r.review_if)}), FALSE) THEN 'review' ELSE 'fail' END AS {r.id}"
        )
        variants = (
            ("severity", [s.when for s in r.severity_if]),
            ("message", [m.when for m in r.message_if]),
        )
        for suffix, conditions in variants:
            if conditions:
                whens = " ".join(
                    f"WHEN coalesce(({sub(c)}), FALSE) THEN {n}" for n, c in enumerate(conditions, 1)
                )
                cols.append(f"CASE {whens} ELSE 0 END AS {r.id}_{suffix}")
    blockers = [r.id for r in rules if r.severity == "blocker"]
    any_blocker = "(" + (" OR ".join(f"{b} = 'fail'" for b in blockers) or "FALSE") + ")"
    flags = [
        f"coalesce(({sub(f.when.replace(ANY_BLOCKER_FAIL, any_blocker))}), FALSE) AS {f.id}"
        for f in [*consistency, *insights]
    ]
    inner = f"SELECT f.*, {', '.join(cols)} FROM {FACTS_TABLE} f"
    return f"SELECT s.*{''.join(', ' + f for f in flags)} FROM ({inner}) s"


@lru_cache(maxsize=4)
def _compiled(thresholds_key: tuple[tuple[str, float], ...], mtime: float) -> tuple[RuleSet, str]:
    with one_connection() as con:
        ruleset = load_ruleset(RULES_FILE, con)
    sql = compile_rules(
        ruleset.rules,
        dict(thresholds_key),
        consistency=ruleset.decision_consistency,
        insights=ruleset.insights,
    )
    return ruleset, sql


def compiled() -> tuple[RuleSet, str]:
    """The validated ruleset and its SQL for the current thresholds (recompiled when either changes)."""
    return _compiled(tuple(sorted(_thresholds().items())), RULES_FILE.stat().st_mtime)


# --- one claim -------------------------------------------------------------------------------------------


def evaluate_claim(
    claim_id: str, persona: Persona, *, principal_id: str | None = None, trace_id: str | None = None
) -> ClaimAssessment | NotFound | AccessDenied:
    """The deterministic dossier for one claim (no LLM): rules, checklist, flags, actions, citations.

    Ownership is checked by the claim tools (a customer sees only their own claims)."""
    ctx = ToolContext(
        persona=persona,
        principal_id=principal_id,
        as_of=get_settings().as_of_date,
        trace_id=trace_id or f"rules-{claim_id}",
    )
    with one_connection():
        docs = get_claim_documents(ctx, claim_id=claim_id)
        if not isinstance(docs, DocumentChecklist):
            return docs
        found = get_claim_interactions(ctx, claim_id=claim_id)
        interactions = found if isinstance(found, InteractionHistory) else None
        return assess(ctx, docs, interactions)


def assess(
    ctx: ToolContext, docs: DocumentChecklist, interactions: InteractionHistory | None
) -> ClaimAssessment | NotFound:
    """Evaluate the rules for `docs.claim_id` and assemble the assessment for the caller's persona.

    `docs` and `interactions` come from the claim tools, so access was checked before this runs."""
    ruleset, sql = compiled()
    row = fetch_one(f"SELECT * FROM ({sql}) WHERE claim_id = ?", [docs.claim_id])
    if row is None:
        return NotFound(entity="claim", message=f"Claim {docs.claim_id} has no facts row.")
    persona_cfg = access.load_personas()[ctx.persona]
    view: Literal["full", "customer"] = persona_cfg.analyze_claim_view
    hidden = frozenset(persona_cfg.hidden_columns)
    thresholds = _thresholds()

    all_results = [_result(rule, row, ruleset, thresholds, hidden) for rule in ruleset.rules]
    needs_review = any(_needs_review(r) for r in all_results)
    visible_ids = {r.id for r in ruleset.rules if ctx.persona not in r.hidden_from}
    results = [r for r in all_results if r.id in visible_ids]

    alternatives = []
    if any(r.id == "R08" and r.status == "fail" for r in results) and row.get("hospital_id"):
        alternatives = network_alternatives(
            row["hospital_city"], row["hospital_specialty"], row["hospital_id"]
        )
    derived = {
        "network_alternatives": [f"{h.hospital_name} ({h.hospital_id})" for h in alternatives],
        "untracked": docs.untracked,
    }
    actions = next_best_actions(
        ruleset.next_best_actions,
        results,
        {**row, **thresholds, **derived},
        ruleset.formats,
        customer=view == "customer",
        has_untracked=bool(docs.untracked),
    )
    consistency = (
        [ConsistencyFlag(id=f.id, name=f.name) for f in ruleset.decision_consistency if row.get(f.id)]
        if view == "full"
        else []
    )
    escalation = [r.message or r.name for r in results if _needs_review(r)] if view == "full" else []
    status_cols = {c for r in ruleset.rules for c in (r.id, f"{r.id}_severity", f"{r.id}_message")}
    flag_cols = {f.id for f in [*ruleset.decision_consistency, *ruleset.insights]}
    facts = {k: jsonable(v) for k, v in row.items() if k not in status_cols | flag_cols and k not in hidden}
    sources: dict[str, SourceRef] = {}
    for ref in [
        sql_source("claims", docs.claim_id),
        sql_source("policies", row["policy_id"]),
        *docs.sources,
        *(interactions.sources if interactions else []),
        *(r.citation for r in results if r.citation is not None),
        *(sql_source("hospitals", h.hospital_id) for h in alternatives),
    ]:
        sources.setdefault(ref.label, ref)
    return ClaimAssessment(
        claim_id=docs.claim_id,
        as_of=get_settings().as_of_date,
        view=view,
        facts=facts,
        rules=results,
        checklist=docs,
        consistency=consistency,
        needs_human_review=needs_review,
        escalation_reasons=escalation,
        next_best_actions=actions,
        interactions=interactions,
        sources=list(sources.values()),
    )


def _needs_review(r: RuleResult) -> bool:
    return r.status == "review" or (r.status == "fail" and r.severity in ("blocker", "escalate"))


def _result(
    rule: RuleDef,
    row: dict[str, Any],
    ruleset: RuleSet,
    thresholds: dict[str, float],
    hidden: frozenset[str],
) -> RuleResult:
    status = row[rule.id]
    severity = rule.severity
    if rule.severity_if and (n := row[f"{rule.id}_severity"]):
        severity = rule.severity_if[n - 1].severity
    message = None
    if status in ("fail", "review"):
        template = rule.message
        if rule.message_if and (n := row[f"{rule.id}_message"]):
            template = rule.message_if[n - 1].message
        try:
            message = render(template, {**row, **thresholds}, ruleset.formats)
        except RenderError as exc:
            raise RulesConfigError(f"{rule.id}: {exc}") from exc
    used = {p for p in placeholders(rule.message) if p in thresholds}
    evidence = {c: jsonable(row[c]) for c in rule.evidence if c not in hidden}
    evidence |= {t: thresholds[t] for t in used}
    return RuleResult(
        id=rule.id,
        name=rule.name,
        status=status,
        severity=severity,
        message=message,
        evidence=evidence,
        citation=citation(rule.cite, row, ruleset) if status in ("fail", "review") else None,
    )


def citation(cite: Cite, row: dict[str, Any], ruleset: RuleSet) -> SourceRef | None:
    """Spec 07 Behaviour 4: schedule → [policies:<id>]; coverage → the product's coverage section;
    reimbursement / human_review → the common (ALL) section; none → no citation."""
    match cite:
        case "schedule":
            return sql_source("policies", row["policy_id"])
        case "coverage":
            if row.get("coverage_section") is None:
                return None
            section = int(row["coverage_section"])
            name = section_name(row["product_name"], section)
            if name is None:
                return None
            return SourceRef(
                kind="policy",
                label=citation_label(row["product_name"], section, name),
                product=row["product_name"],
                section_no=section,
                section_name=name,
            )
        case "reimbursement" | "human_review":
            c = ruleset.citations[cite]
            return SourceRef(
                kind="policy",
                label=citation_label(c.product, c.section_no, c.section_name),
                product=c.product,
                section_no=c.section_no,
                section_name=c.section_name,
            )
    return None


# --- portfolio -------------------------------------------------------------------------------------------


def materialise_portfolio(con: duckdb.DuckDBPyConnection) -> PortfolioReport:
    """gold.rule_results (claim_id, product, status, one column per rule, flag and insight) and its counts.

    `con` must be writable (`make rules`); the expressions are validated on it first."""
    start = time.perf_counter()
    ruleset = load_ruleset(RULES_FILE, con)
    sql = compile_rules(
        ruleset.rules, _thresholds(), consistency=ruleset.decision_consistency, insights=ruleset.insights
    )
    rule_cols = [r.id for r in ruleset.rules]
    sev_cols = [f"{r.id}_severity" for r in ruleset.rules if r.severity_if]
    flag_cols = [f.id for f in [*ruleset.decision_consistency, *ruleset.insights]]
    keep = ", ".join(["claim_id", "product_name", "claim_status", *rule_cols, *sev_cols, *flag_cols])
    con.execute(f"CREATE OR REPLACE TABLE gold.rule_results AS SELECT {keep} FROM ({sql}) ORDER BY claim_id")
    report = portfolio_counts(con, ruleset)
    return report.model_copy(update={"elapsed_ms": round((time.perf_counter() - start) * 1000, 1)})


def portfolio_counts(
    con: duckdb.DuckDBPyConnection, ruleset: RuleSet, product: str | None = None
) -> PortfolioReport:
    """Counts from gold.rule_results (optionally for one product)."""
    rules = [r.id for r in ruleset.rules]
    flags = [f.id for f in ruleset.decision_consistency]
    insights = [f.id for f in ruleset.insights]
    where, params = ("WHERE product_name = ?", [product]) if product else ("", [])
    select = ", ".join(
        ["count(*) AS claims"]
        + [f"count(*) FILTER (WHERE {r} = 'fail') AS {r}_fail" for r in rules]
        + [f"count(*) FILTER (WHERE {r} = 'review') AS {r}_review" for r in rules]
        + [f"count(*) FILTER (WHERE {f}) AS {f}" for f in [*flags, *insights]]
    )
    cur = con.execute(f"SELECT {select} FROM gold.rule_results {where}", params)
    row = dict(zip([d[0] for d in cur.description], cur.fetchone() or (), strict=True))
    by_select = ", ".join(
        [f"count(*) FILTER (WHERE {r} = 'fail') AS {r}" for r in rules]
        + [f"count(*) FILTER (WHERE {f}) AS {f}" for f in flags]
    )
    cur = con.execute(
        f"SELECT product_name, {by_select} FROM gold.rule_results {where} GROUP BY product_name "
        "ORDER BY product_name",
        params,
    )
    names = [d[0] for d in cur.description]
    by_product = {r[0]: dict(zip(names[1:], r[1:], strict=True)) for r in cur.fetchall()}
    return PortfolioReport(
        as_of=get_settings().as_of_date,
        claims=row["claims"],
        fail_counts={r: row[f"{r}_fail"] for r in rules},
        review_counts={r: row[f"{r}_review"] for r in rules},
        consistency_counts={f: row[f] for f in flags},
        insight_counts={f: row[f] for f in insights},
        by_product=by_product,
    )
