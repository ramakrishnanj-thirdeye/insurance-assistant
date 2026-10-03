# ADR-001 DuckDB as the PoC warehouse
Status: accepted

**Context.** 1.03M rows across six CSVs; analytical queries (group-bys, windows) and point lookups; must run on a laptop with zero ops.
**Decision.** One DuckDB file (`data/warehouse.duckdb`) with bronze/silver/gold/ref schemas, built by `make data`, opened read-only at runtime.
**Consequences.** Columnar speed and native CSV reads; single-writer means the build swaps files atomically. SQL written in the DuckDB dialect; sqlglot can transpile to Snowflake or Postgres for the production path.
**Alternatives.** SQLite (row store, slow aggregates), Postgres (needs a service).
