---
id: text_to_sql
version: 0.3.0
role: sql
output: {"sql": str, "rationale": str}
---
Write one DuckDB SELECT statement that answers the question using ONLY the semantic model below.
- Use fully qualified tables exactly as given after TABLE (e.g. silver.claims, gold.claim_doc_checklist).
- Use only the listed columns. Join only with the conditions listed under JOINS; never cross join.
- When you join tables, give each table an alias and prefix every column with it (several tables share column names).
- Never use logged_customer_id, file readers, getvariable or any statement other than SELECT (WITH is fine).
- Prefer the named filters and metric expressions when they fit. Filter values must match the listed values exactly.
- If a column's description or synonyms already capture the condition asked about, filter on that column directly instead of rebuilding it from other columns.
- Add only the filters the question states. Do not add conditions it does not mention (for example a line of business or `required`).
- Select only what answers the question: the grouping columns it names and the measure it asks for. No extra IDs, counts or totals.
- Questions about counts, totals, rates or averages need aggregation; questions asking to list or show individual records need one row per record.
- "Today" is DATE '{as_of_date}'; write dates as DATE 'YYYY-MM-DD' literals. "Active"/"current" policies means effective_status = 'In Force'.
- Do not select customer_name unless the question asks for names.
- Use clear aliases and a meaningful order. At most {row_limit} rows; use LIMIT for "top N".
- If an earlier attempt failed, the error is shown below: fix that problem and keep everything else.
Reply with only JSON: {"sql": "<the statement>", "rationale": "<one sentence>"}.
<semantic_model>
{semantic_model_context}
</semantic_model>
<examples>
{verified_query_examples}
</examples>
<previous_error>{error}</previous_error>
Question: {question}
