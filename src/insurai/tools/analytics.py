"""run_analytics (spec 02): governed text-to-SQL for claims_agent and supervisor personas.

Few-shots from the sql_examples collection → generate → validate → execute, with one repair call carrying the
error text when the rejection is repairable. Customers are denied by the @tool persona gate before any
LLM call.
"""

import hashlib
import time
from typing import Any, Literal

from insurai.llm.structured import StructuredOutputError
from insurai.observability import get_logger
from insurai.retrieval.search import similar_sql_examples
from insurai.semantic.chart import chart_spec
from insurai.semantic.model import load_semantic_model
from insurai.semantic.schemas import (
    ChartSpec,
    QueryResult,
    RejectionReason,
    SqlRejection,
    ValidatedSql,
    VerifiedQuery,
)
from insurai.semantic.sql import REPAIRABLE, execute, generate_sql, validate
from insurai.settings import get_settings
from insurai.tools.base import tool
from insurai.tools.messages import guardrails
from insurai.tools.schemas import AccessDenied, Persona, SourceRef, ToolContext, ToolResult

log = get_logger(__name__)

EXAMPLES = 3


class AnalyticsResult(ToolResult):
    kind: Literal["analytics"] = "analytics"
    sql: str
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    truncated: bool
    chart: ChartSpec | None
    attempts: int


class AnalyticsRejected(ToolResult):
    """The question could not be answered with SQL that passed the validator and ran (spec 02 Behaviour 6)."""

    kind: Literal["analytics_rejected"] = "analytics_rejected"
    reason: RejectionReason
    detail: str
    sql: str | None
    attempts: int


def sql_query_source(sql: str, table: str | None) -> SourceRef:
    """`[sql:<sha8>]`: the result set of one validated query."""
    key = hashlib.sha256(sql.encode("utf-8")).hexdigest()[:8]
    label = guardrails()["sql_citation_format"].format(table="sql", key=key)
    return SourceRef(kind="sql", label=label, table=table, key=key)


@tool
def run_analytics(ctx: ToolContext, question: str) -> AnalyticsResult | AnalyticsRejected | AccessDenied:
    """Answer an aggregate question (counts, rates, totals, trends) with validated read-only SQL over the
    semantic model. Returns the SQL, the rows, a chart spec when one fits, and the [sql:…] citation."""
    settings = get_settings()
    examples = _examples(question, ctx.persona)
    error: str | None = None
    sql: str | None = None
    rejection = SqlRejection(reason="parse", detail="no attempt")
    attempt = 0
    for attempt in range(1, 2 + settings.sql.repair_attempts):
        start = time.perf_counter()
        sql, outcome, checked = _attempt(question, ctx.persona, examples, error)
        log.info(
            "analytics attempt=%d trace=%s outcome=%s ms=%.0f",
            attempt,
            ctx.trace_id,
            getattr(outcome, "reason", "ok"),
            (time.perf_counter() - start) * 1000,
        )
        if isinstance(outcome, QueryResult) and isinstance(checked, ValidatedSql):
            return AnalyticsResult(
                sql=checked.sql,
                columns=outcome.columns,
                rows=outcome.rows,
                row_count=outcome.row_count,
                truncated=outcome.truncated,
                chart=chart_spec(outcome),
                attempts=attempt,
                sources=[sql_query_source(checked.sql, checked.tables[0] if checked.tables else None)],
            )
        assert isinstance(outcome, SqlRejection)
        rejection = outcome
        if outcome.reason not in REPAIRABLE:
            break
        error = f"{outcome.reason}: {outcome.detail}\nPrevious SQL: {sql or '(none)'}"
    return AnalyticsRejected(
        reason=rejection.reason,
        detail=rejection.detail,
        sql=sql,
        attempts=attempt,
        sources=[sql_query_source(sql or "", None)],
    )


def _attempt(
    question: str, persona: Persona, examples: list[VerifiedQuery], error: str | None
) -> tuple[str | None, QueryResult | SqlRejection, ValidatedSql | SqlRejection | None]:
    """(SQL shown for this attempt, outcome, validation result) for one generate → validate → execute pass."""
    try:
        draft = generate_sql(question, persona, examples, error=error)
    except StructuredOutputError as e:
        return None, SqlRejection(reason="parse", detail=f"the model returned no valid JSON: {e}"), None
    checked = validate(draft.sql, persona, load_semantic_model())
    if isinstance(checked, SqlRejection):
        return draft.sql, checked, checked
    return checked.sql, execute(checked, get_settings().sql.timeout_s), checked


def _examples(question: str, persona: Persona) -> list[VerifiedQuery]:
    """The closest verified queries the persona may run (rule_results examples never reach claims_agent)."""
    model = load_semantic_model()
    found = similar_sql_examples(question, k=EXAMPLES + 3)
    return [q for q in found if isinstance(validate(q.sql, persona, model), ValidatedSql)][:EXAMPLES]
