# ADR-004 Semantic layer in the Cortex Analyst shape
Status: accepted

**Context.** Text-to-SQL over raw schemas invents joins; this data has a join that looks valid but is wrong (interactions.customer_id).
**Decision.** `config/semantic_model.yaml` declares tables, dimensions, facts, metrics, named filters, allowed relationships and verified queries, in the Snowflake Cortex Analyst shape. Generated SQL is validated by sqlglot against it; verified queries double as retrieved few-shot examples.
**Consequences.** Governed analytics now; on Snowflake the same model can be served by Cortex Analyst. The model must be maintained alongside schema changes (AC-02-01 test catches drift).
**Alternatives.** Raw schema prompting; a full semantic layer product (dbt Semantic Layer, Cube) — too heavy for a PoC.
