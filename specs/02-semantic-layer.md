# 02 – Semantic layer and governed text-to-SQL

Milestone: M6 · Depends on: 01, 04 (sql_examples collection), 08 (personas) · ADR: 004

## Goal
Answer ad-hoc analytics questions ("approval rate by line of business", "monthly claims in 2025") with
SQL that is generated against `config/semantic_model.yaml`, validated by AST, executed read-only, and
shown to the user. Known question shapes never come here; they use deterministic tools (spec 05).

## In scope / Out of scope
In: semantic model loader, few-shot retrieval, SQL generation, sqlglot validation, execution with limits and
timeout, one repair attempt, chart spec, `run_analytics` tool.
Out: customer persona analytics (denied), writes, cross-database queries, natural-language-to-chart styling.

## Interfaces
```python
# src/insurai/semantic/model.py
class SemanticModel(BaseModel):                 # mirrors the YAML (Cortex Analyst shape)
    @classmethod
    def load(cls, path: Path) -> "SemanticModel": ...
    def allowed_tables(self) -> dict[str, str]: ...          # logical name -> "schema.table"
    def allowed_columns(self, persona: Persona) -> dict[str, set[str]]: ...
    def allowed_joins(self) -> set[frozenset[tuple[str, str]]]: ...  # {(table, col), (table, col)}
    def prompt_context(self) -> str: ...                     # compact text: tables, columns, enums, synonyms, filters, metrics

# src/insurai/semantic/sql.py
class SqlDraft(BaseModel): sql: str; rationale: str
class ValidatedSql(BaseModel): sql: str; tables: list[str]; limit_applied: int
class SqlRejection(BaseModel): reason: Literal["parse", "not_select", "multi_statement", "forbidden_function",
                               "unknown_table", "unknown_column", "forbidden_join", "hidden_column", "persona", "timeout", "runtime"]; detail: str
def generate_sql(question: str, persona: Persona, examples: list[VerifiedQuery]) -> SqlDraft: ...   # LLM role: generator
def validate(sql: str, persona: Persona, model: SemanticModel) -> ValidatedSql | SqlRejection: ...
def execute(v: ValidatedSql, timeout_s: int) -> QueryResult | SqlRejection: ...

# src/insurai/tools/analytics.py
def run_analytics(ctx: ToolContext, question: str) -> AnalyticsResult: ...
class AnalyticsResult(BaseModel):
    sql: str; columns: list[str]; rows: list[list[Any]]; row_count: int; truncated: bool
    chart: ChartSpec | None; sources: list[SourceRef]; attempts: int
```

## Behaviour
1. Persona `customer` → return ACCESS_DENIED immediately (no LLM call).
2. Retrieve the 3 most similar verified queries from Qdrant collection `sql_examples` (spec 04).
3. Prompt (`config/prompts/text_to_sql.md`) = semantic model context + examples + question + rules:
   DuckDB dialect; only listed tables (fully qualified `schema.table`); use named filters and metric
   expressions where they fit; dates relative to the as-of date literal `DATE '2026-10-01'`; never select
   `customer_name` unless asked; output JSON `{sql, rationale}`.
4. Validate with sqlglot (dialect duckdb):
   - exactly one statement; root is SELECT (CTEs allowed);
   - every table reference resolves to an allowed `schema.table`; no table functions (`read_csv*`, `read_parquet`, `read_json*`, `glob`), no `COPY`, `ATTACH`, `INSTALL`, `LOAD`, `PRAGMA`, `SET`, `CALL`, `getvariable`;
   - every column resolves to an allowed column for the persona (hidden columns from personas.yaml);
     `logged_customer_id` is never allowed;
   - every JOIN condition matches a declared relationship (either direction); any other join → forbidden_join;
   - add `LIMIT {row_limit}` if absent; cap a larger LIMIT at row_limit.
   - for `claims_agent`, if `customer_name` is selected, wrap output so it is masked to initials.
5. Execute on `db.connect(read_only=True)`; a timer thread calls `con.interrupt()` at `sql.timeout_s`.
6. On SqlRejection(parse|unknown_*|forbidden_join|runtime): one repair call with the error text; a second failure returns the rejection to the agent, which tells the user the question could not be answered safely.
7. Chart spec: 1 categorical + 1 numeric column with ≤ 30 rows → bar; a date/month column + numeric → line; otherwise none (table only).
8. Sources: `SourceRef(kind="sql", label="[sql:<sha8 of sql>]", table=<first table>)`; the SQL itself goes to the trace and the UI.

## Acceptance criteria
- [x] AC-02-01 `SemanticModel.load` validates the YAML; a test introspects DuckDB and confirms every table and column expression exists (the committed model passes).
- [x] AC-02-02 All 17 committed verified queries pass `validate` and return ≥ 1 row (14 until 2026-10-08, when three supervisor queries were added: approved claims outside their policy period, maternity paid where the wording excludes it, approved claims paid in full despite a co-pay = 20,903).
- [x] AC-02-03 Validator rejects (≥ 15 negative tests): INSERT/UPDATE/DELETE/CREATE/DROP, two statements, `read_csv('...')`, `COPY ... TO`, `ATTACH`, `PRAGMA`, unknown table, unknown column, join `interactions.logged_customer_id = customers.customer_id`, join customers to hospitals on city, selecting `fraud_risk_score` as customer persona, `getvariable('as_of')`.
- [x] AC-02-04 LIMIT is injected when absent and capped at 200 when larger.
- [x] AC-02-05 Customer persona `run_analytics` → ACCESS_DENIED with no LLM call.
- [x] AC-02-06 A cross join of claims × claim_documents is interrupted at timeout_s and returns reason "timeout".
- [ ] AC-02-07 (open gate: 0.80 on qwen3:8b with 30 verified queries, 2026-10-08; 0.6667 with 17) Analytics slice (20 items; 15 under the 3-day scope, decided 2026-10-08): execution accuracy ≥ 90%; unsafe SQL blocked 100%.
- [x] AC-02-08 `customer_name` in a claims_agent analytics result is masked (e.g. "A. S.").

## Eval hooks
Slice `analytics` (spec 11): execution accuracy, validator block rate, repair rate, latency.

## Open questions
- ~~Add `gold.rule_results` to the model for supervisor analytics?~~ Done 2026-10-08: table `rule_results` (supervisor only via
  personas.yaml `analytics_hidden_tables`), joined to claims on claim_id; every rule and flag column described with synonyms.

## Decisions (2026-10-08)
- A second failure returns `AnalyticsRejected` (reason, detail, last SQL, attempts); the agent answers with the
  `analytics_rejected` template, without an LLM call.
- `validate` check order: parse, one statement, SELECT root, forbidden functions (settings `sql.forbidden_functions`),
  tables, joins, columns, persona row scope; then LIMIT and masking. A join on a blocked column reports forbidden_join.
- `generate_sql` uses the optional `sql` LLM role (falls back to generator; ADR-006 amendment 2026-10-08). verified_queries: 30.
- `ValidatedSql.limit_imposed` (additive) drives `truncated`; `generate_sql(..., error=None)` carries the repair error.
- Chart: exactly one non-numeric column is x, the first numeric column is y; temporal → line, text with ≤ 30 rows → bar.
- Execution runs with `enable_external_access = false` set on the read-only connection.
- Citation label `[sql:<sha8>]`; the guardrails sql label regex accepts an 8-hex key.
- If verification fails twice on an analytics turn, the answer is the result table with its citation (not the abstain text).
