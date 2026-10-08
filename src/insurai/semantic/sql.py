"""Governed text-to-SQL (spec 02): generate against the semantic model, validate by AST, execute read-only.

`validate` runs its checks in a fixed order and returns the first failure: parse, one statement, SELECT root,
forbidden functions, tables, joins (declared relationships only), columns (unknown, hidden, blocked), persona
row scope; then it applies the row limit and masks `mask_columns_in_analytics` to initials.
"""

import fnmatch
import re
import threading
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import duckdb
import sqlglot
from langchain_core.messages import HumanMessage
from sqlglot import exp
from sqlglot.errors import OptimizeError, SqlglotError
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import Scope, traverse_scope

from insurai import db
from insurai.agent.prompts import load_prompt
from insurai.llm.structured import structured_call
from insurai.observability import get_logger
from insurai.semantic.model import SemanticModel, load_semantic_model
from insurai.semantic.schemas import QueryResult, SqlDraft, SqlRejection, ValidatedSql, VerifiedQuery
from insurai.settings import get_settings
from insurai.tools.access import load_personas
from insurai.tools.schemas import Persona

log = get_logger(__name__)

DIALECT = "duckdb"
# Rejections worth one repair call with the error text (spec 02 Behaviour 6).
REPAIRABLE = frozenset({"parse", "unknown_table", "unknown_column", "forbidden_join", "runtime"})
_SQL_TYPES = {"varchar": "VARCHAR", "number": "DOUBLE", "date": "DATE", "boolean": "BOOLEAN"}
_INITIALS = (  # 'Arjun Sharma' -> 'A. S.'
    "array_to_string(list_transform(string_split_regex(trim(_x_), '\\s+'), "
    "w -> upper(left(w, 1)) || '.'), ' ')"
)


# --- generation -----------------------------------------------------------------------------------------


def generate_sql(
    question: str, persona: Persona, examples: list[VerifiedQuery], *, error: str | None = None
) -> SqlDraft:
    """One generator call; `error` carries the previous rejection for the repair attempt."""
    settings = get_settings()
    prompt = load_prompt("text_to_sql")
    text = prompt.render(
        as_of_date=settings.as_of_date.isoformat(),
        row_limit=settings.sql.row_limit,
        semantic_model_context=load_semantic_model().prompt_context(persona),
        verified_query_examples="\n".join(f"Q: {q.question}\nSQL: {q.sql}" for q in examples) or "(none)",
        error=error or "(none)",
        question=question,
    )
    draft, _ = structured_call("sql", SqlDraft, [HumanMessage(content=text)], prompt.id, prompt.version)
    return draft


# --- validation -----------------------------------------------------------------------------------------


def validate(sql: str, persona: Persona, model: SemanticModel) -> ValidatedSql | SqlRejection:
    try:
        statements = [s for s in sqlglot.parse(sql, dialect=DIALECT) if s is not None]
    except SqlglotError as e:
        return SqlRejection(reason="parse", detail=_first_line(e))
    if not statements:
        return SqlRejection(reason="parse", detail="no SQL statement")
    if len(statements) > 1:
        return SqlRejection(
            reason="multi_statement", detail=f"{len(statements)} statements; send exactly one"
        )
    root = statements[0]
    if not isinstance(root, exp.Select | exp.SetOperation):
        return SqlRejection(reason="not_select", detail=f"{root.key.upper()} statements are not allowed")

    if bad := _forbidden_function(root):
        return SqlRejection(reason="forbidden_function", detail=f"function {bad}() is not allowed")

    by_qualified = {v.lower(): k for k, v in model.allowed_tables().items()}
    persona_tables = model.tables_for(persona)
    ctes = {c.alias_or_name.lower() for c in root.find_all(exp.CTE)}
    tables: list[str] = []
    for t in root.find_all(exp.Table):
        if not isinstance(t.this, exp.Identifier):
            return SqlRejection(
                reason="unknown_table", detail=f"{t.sql(DIALECT)} is not a table in the model"
            )
        if not t.db and t.name.lower() in ctes:
            continue
        name = f"{t.db}.{t.name}".lower()
        if t.catalog or name not in by_qualified:
            return SqlRejection(
                reason="unknown_table", detail=f"{t.sql(DIALECT)} is not an allowed table; use schema.table"
            )
        if by_qualified[name] not in persona_tables:
            return SqlRejection(reason="persona", detail=f"{name} is not available to the {persona} persona")
        if name not in tables:
            tables.append(name)

    try:
        qualified = qualify(
            root.copy(), schema=_schema(model), dialect=DIALECT, validate_qualify_columns=True, identify=False
        )
    except OptimizeError as e:
        return SqlRejection(reason="unknown_column", detail=_column_detail(_first_line(e), tables, model))
    except SqlglotError as e:
        return SqlRejection(reason="parse", detail=_first_line(e))

    scopes = traverse_scope(qualified)
    if rejection := _check_joins(scopes, model, by_qualified):  # before columns: a join on a blocked column
        return rejection  # is a forbidden join first
    if rejection := _check_columns(scopes, persona, model, by_qualified):
        return rejection
    if load_personas()[persona].row_scope != "all":
        return SqlRejection(reason="persona", detail=f"analytics is not available to the {persona} persona")

    mask = {c.lower() for c in load_personas()[persona].mask_columns_in_analytics}
    has_star = any(
        isinstance(p, exp.Star) or p.is_star for s in root.find_all(exp.Select) for p in s.expressions
    )
    needs_mask = bool(mask) and any(c.name.lower() in mask for c in qualified.find_all(exp.Column))
    # The qualified tree expands stars and GROUP BY ordinals, so masking cannot be bypassed and masked
    # projections still group by the raw value; otherwise keep the SQL as written (readable column names).
    out = qualified if (has_star or needs_mask) else root.copy()
    if needs_mask:
        _mask_projections(out, mask)
    limit_applied, imposed = _apply_limit(out, get_settings().sql.row_limit)
    return ValidatedSql(
        sql=out.sql(DIALECT), tables=tables, limit_applied=limit_applied, limit_imposed=imposed
    )


def _first_line(e: Exception) -> str:
    return str(e).strip().splitlines()[0][:300] if str(e).strip() else type(e).__name__


def _column_detail(message: str, tables: list[str], model: SemanticModel) -> str:
    """A repair hint for sqlglot's "could not be resolved": an unqualified column two joined tables share is
    ambiguous; a known column under the wrong alias names the table that has it."""
    match = re.search(r"Column '([^']+)' could not be resolved|Unknown column: (\S+)", message)
    if not match:
        return message
    written = match.group(1) or match.group(2)
    name = written.lower().rsplit(".", 1)[-1]
    holders = [t.base_table.qualified for t in model.tables if name in {c.name.lower() for c in t.columns}]
    owners = [h for h in holders if h in tables]
    if len(owners) > 1 and match.group(1) and "." not in written:
        return (
            f"Column '{name}' is ambiguous: it exists in {' and '.join(owners)}; prefix it with a table alias"
        )
    if holders:
        return f"{message}. '{name}' is a column of {', '.join(holders)}; use that table's alias"
    return message


def _function_name(f: exp.Func) -> str:
    return (f.name if isinstance(f, exp.Anonymous) else f.sql_name()).lower()


def _forbidden_function(root: exp.Expression) -> str | None:
    patterns = get_settings().sql.forbidden_functions
    for f in root.find_all(exp.Func):
        name = _function_name(f)
        if any(fnmatch.fnmatchcase(name, p) for p in patterns):
            return name
    return None


def _schema(model: SemanticModel) -> dict[str, dict[str, dict[str, str]]]:
    """sqlglot schema {schema: {table: {column: type}}}; blocked columns are included so they are reported
    as blocked rather than unknown."""
    out: dict[str, dict[str, dict[str, str]]] = {}
    for t in model.tables:
        cols = {c.name: _SQL_TYPES.get(c.data_type, "VARCHAR") for c in t.columns}
        cols |= {b: "VARCHAR" for b in t.blocked_columns}
        out.setdefault(t.base_table.schema_, {})[t.base_table.table] = cols
    return out


def _check_columns(
    scopes: list[Scope], persona: Persona, model: SemanticModel, by_qualified: dict[str, str]
) -> SqlRejection | None:
    allowed = {k: {c.lower() for c in v} for k, v in model.allowed_columns(persona).items()}
    for scope in scopes:
        for col in scope.columns:
            source = scope.sources.get(col.table)
            if not isinstance(source, exp.Table):
                continue  # a CTE, subquery or output alias: checked where it is defined
            logical = by_qualified[f"{source.db}.{source.name}".lower()]
            table = model.table(logical)
            name = col.name.lower()
            if name in {b.lower() for b in table.blocked_columns}:
                return SqlRejection(reason="hidden_column", detail=f"{logical}.{col.name} is never queryable")
            if name not in allowed[logical]:
                if name in {c.name.lower() for c in table.columns}:
                    return SqlRejection(
                        reason="hidden_column",
                        detail=f"{logical}.{col.name} is hidden for the {persona} persona",
                    )
                return SqlRejection(
                    reason="unknown_column", detail=f"{logical}.{col.name} is not in the model"
                )
    return None


def _check_joins(
    scopes: list[Scope], model: SemanticModel, by_qualified: dict[str, str]
) -> SqlRejection | None:
    declared = {frozenset((t, c.lower()) for t, c in pair) for pair in model.allowed_joins()}
    for scope in scopes:
        if not isinstance(scope.expression, exp.Select):
            continue
        for join in scope.expression.args.get("joins") or []:
            on = join.args.get("on")
            if on is None:
                return SqlRejection(
                    reason="forbidden_join",
                    detail=f"join to {join.this.sql(DIALECT)} has no ON condition; use a declared join",
                )
            has_declared = False
            for cond in on.flatten() if isinstance(on, exp.And) else [on]:
                if len({c.table for c in cond.find_all(exp.Column)}) <= 1:
                    continue  # a filter on one table
                if not (
                    isinstance(cond, exp.EQ)
                    and isinstance(cond.this, exp.Column)
                    and isinstance(cond.expression, exp.Column)
                ):
                    return SqlRejection(reason="forbidden_join", detail=f"join condition {cond.sql(DIALECT)}")
                left = _origin(scope, cond.this, by_qualified)
                right = _origin(scope, cond.expression, by_qualified)
                if left is None or right is None or frozenset({left, right}) not in declared:
                    return SqlRejection(
                        reason="forbidden_join",
                        detail=f"{cond.sql(DIALECT)} is not a declared relationship",
                    )
                has_declared = True
            if not has_declared:
                return SqlRejection(
                    reason="forbidden_join",
                    detail=f"join on {on.sql(DIALECT)} does not use a declared relationship",
                )
    return None


def _origin(scope: Scope, col: exp.Column, by_qualified: dict[str, str]) -> tuple[str, str] | None:
    """(logical table, column) a column comes from, followed through CTEs and subqueries that pass it
    through unchanged; None when it is computed."""
    source = scope.sources.get(col.table)
    if isinstance(source, exp.Table):
        return by_qualified[f"{source.db}.{source.name}".lower()], col.name.lower()
    if isinstance(source, Scope) and isinstance(source.expression, exp.Select):
        for projection in source.expression.selects:
            if projection.alias_or_name.lower() != col.name.lower():
                continue
            inner = projection.this if isinstance(projection, exp.Alias) else projection
            return _origin(source, inner, by_qualified) if isinstance(inner, exp.Column) else None
    return None


def initials_expr(column: exp.Expression) -> exp.Expression:
    """'Arjun Sharma' -> 'A. S.'"""
    expr = sqlglot.parse_one(_INITIALS, dialect=DIALECT)
    placeholder = next(c for c in expr.find_all(exp.Column) if c.name == "_x_")
    placeholder.replace(column)
    return expr


def _mask_projections(tree: exp.Expression, mask: set[str]) -> None:
    for select in list(tree.find_all(exp.Select)):
        for projection in list(select.expressions):
            if isinstance(projection, exp.Column) and projection.name.lower() in mask:
                projection.replace(exp.alias_(initials_expr(projection.copy()), projection.name))
                continue
            for col in [c for c in projection.find_all(exp.Column) if c.name.lower() in mask]:
                col.replace(initials_expr(col.copy()))


def _apply_limit(tree: exp.Expression, row_limit: int) -> tuple[int, bool]:
    """Add LIMIT row_limit when absent, cap a larger one; (limit applied, whether we imposed it)."""
    assert isinstance(tree, exp.Query)
    limit = tree.args.get("limit")
    value = limit.expression if isinstance(limit, exp.Limit) else None
    if isinstance(value, exp.Literal) and value.is_int and int(value.this) <= row_limit:
        return int(value.this), False
    tree.limit(row_limit, copy=False)
    return row_limit, True


# --- execution ------------------------------------------------------------------------------------------


def execute(v: ValidatedSql, timeout_s: float) -> QueryResult | SqlRejection:
    """Run on a read-only connection with external access off; a timer interrupts it at `timeout_s`."""
    con = db.connect(read_only=True)
    timer = threading.Timer(timeout_s, con.interrupt)
    try:
        con.execute("SET enable_external_access = false")  # defence in depth behind the validator
        timer.start()
        cursor = con.execute(v.sql)
        rows = cursor.fetchall()
        description = cursor.description or []
    except duckdb.InterruptException:
        return SqlRejection(reason="timeout", detail=f"query exceeded {timeout_s:g} s and was stopped")
    except duckdb.Error as e:
        return SqlRejection(reason="runtime", detail=_first_line(e))
    finally:
        timer.cancel()
        con.close()
    return QueryResult(
        columns=[d[0] for d in description],
        rows=[[_json_safe(x) for x in row] for row in rows],
        row_count=len(rows),
        truncated=v.limit_imposed and len(rows) >= v.limit_applied,
        column_kinds=[_kind(str(d[1])) for d in description],
    )


def _kind(duck_type: str) -> str:
    t = duck_type.upper()
    if t.startswith(("DATE", "TIMESTAMP", "TIME")):
        return "temporal"
    if t.startswith(
        (
            "TINYINT",
            "SMALLINT",
            "INTEGER",
            "BIGINT",
            "HUGEINT",
            "UTINYINT",
            "USMALLINT",
            "UINTEGER",
            "UBIGINT",
            "UHUGEINT",
            "FLOAT",
            "DOUBLE",
            "DECIMAL",
            "REAL",
        )
    ):
        return "numeric"
    if t.startswith("VARCHAR"):
        return "text"
    return "other"


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, timedelta | UUID):
        return str(value)
    if isinstance(value, list | tuple):
        return [_json_safe(x) for x in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(x) for k, x in value.items()}
    return value
