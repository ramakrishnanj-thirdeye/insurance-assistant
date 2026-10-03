---
id: text_to_sql
version: 0.1.0
role: generator
output: {"sql": str, "rationale": str}
---
Write one DuckDB SELECT statement that answers the question using ONLY the semantic model below.
- Use fully qualified tables exactly as given in base_table (e.g. silver.claims, gold.claim_doc_checklist).
- Join only along the listed relationships. Never use logged_customer_id.
- Prefer the named filters and metric expressions when they fit.
- "Today" is DATE '{as_of_date}'. "Active"/"current" policies means effective_status = 'In Force'.
- Do not select customer_name unless the question asks for names.
- Return aggregated, readable columns with clear aliases. No more than {row_limit} rows.
<semantic_model>{semantic_model_context}</semantic_model>
<examples>{verified_query_examples}</examples>
<previous_error>{error}</previous_error>
Question: {question}
