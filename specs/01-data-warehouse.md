# 01 – Data warehouse

Milestone: M1 · Depends on: config/settings.yaml, config/required_documents.yaml, config/coverage_matrix.yaml
ADRs: 001 (DuckDB), 007 (keep and flag anomalies), 008 (interactions join on claim_id)
Reference implementation: specs/reference/warehouse.sql, specs/reference/prototype_build_and_rules.py

## Goal
`make data` turns the delivered CSVs into `data/warehouse.duckdb` with bronze, silver, gold and ref
schemas, derived business columns at the as-of date, and a data-quality report. Deterministic and
rebuildable in under a minute.

## In scope / Out of scope
In: CSV load with explicit types, derived columns, reference tables from YAML, gold tables for tools and
rules, DQ report, read-only connection helper.
Out: fixing anomalies (we flag, never repair), incremental loads, PII encryption.

## Interfaces
```python
# src/insurai/db.py
def connect(read_only: bool = True) -> duckdb.DuckDBPyConnection: ...
    # sets SET VARIABLE as_of / high_value on every connection; read_only=True for all runtime use

# src/insurai/ingest/ref_tables.py
def load_ref_tables(con, config_dir: Path) -> RefTablesReport: ...      # ref.required_documents, ref.diagnosis_coverage
def coverage_grid(matrix: CoverageMatrix) -> list[CoverageGridRow]: ...  # shared with spec 03

# src/insurai/ingest/build_warehouse.py   (python -m insurai.ingest.build_warehouse)
def build(settings: Settings) -> WarehouseReport: ...                   # writes paths.warehouse, paths.dq_report

# src/insurai/ingest/quality.py
def run_checks(con) -> DataQualityReport: ...                           # integrity checks + anomaly metrics
```
Settings consumed: `as_of_date`, `paths.raw_dir`, `paths.warehouse`, `paths.dq_report`, `thresholds.high_value_inr`.

## Behaviour
1. Raw files live in `data/raw/` exactly as delivered (CSV names from the zip; `policy_documents/` subfolder). Never modified.
2. Build into a temp file, then atomically replace `data/warehouse.duckdb`.
3. Before running SQL, set variables `as_of`, `high_value`, `raw_dir`, then load ref tables (below).
4. Run specs/reference/warehouse.sql (or its equivalent split into numbered files under `src/insurai/ingest/sql/`).
5. Run DQ checks; write `data/data_quality_report.json`; exit non-zero if any **integrity** check fails.
   **Anomaly** metrics never fail the build; they are reported and feed the leakage radar.
6. After the warehouse, `make rules` (spec 07) materialises gold.rule_results; `make data` calls it.

### Schemas and objects
| Object | Grain | Notes |
| --- | --- | --- |
| bronze.* (6 tables) | as delivered | explicit column types, see reference SQL |
| silver.customers, silver.hospitals, silver.claim_documents | as bronze | |
| silver.policies | policy | + continuous_cover_start, effective_status, days_to_expiry, status_conflict |
| silver.claims | claim | + product_name, in_policy_period, days_since_policy_start, days_since_cover_start, within_schedule_waiting, expected_payable, high_value |
| silver.customer_interactions | interaction | claim_owner_id (from claim), logged_customer_id (raw, blocked), before_claim_date |
| ref.required_documents | policy_type × document_type (+ condition) | from required_documents.yaml |
| ref.diagnosis_coverage | product × diagnosis (85 rows) | from coverage_matrix.yaml via coverage_grid() |
| gold.claim_doc_checklist | claim × document_type | required vs present vs verified; status Verified / Pending verification / Rejected / Missing / No record |
| gold.claim_facts | claim | every rule input (spec 07) |
| gold.v_claim_360 | claim | claim_facts + customer attributes |
| gold.v_customer_360 | customer | policy and claim counts |
| gold.rule_results | claim | written by spec 07 |

### Derived column definitions (authoritative)
- `effective_status`: Cancelled if policy_status = Cancelled; Not Started if as_of < start; Lapsed if as_of > end; else In Force.
- `status_conflict`: (Active and not In Force) or (Expired and In Force).
- `continuous_cover_start`: earliest start in the chain of the same customer and product where each policy starts no later than the day after the previous one ends.
- `expected_payable = max(0, min(claim_amount, sum_insured) − deductible) × (1 − co_pay_pct/100)`, rounded to rupees. Deductible first (open decision #7).
- `high_value`: claim_amount > thresholds.high_value_inr (p95 = 236,053; log the recomputed p95 at build).

### Reference tables
- `ref.required_documents(policy_type, document_type, condition_field, condition_values[])`: one row per `always` doc (no condition) and per conditional doc.
- `ref.diagnosis_coverage(product_name, diagnosis, coverage_status, required_waiting_days, waiting_basis, waiting_reason, section_no, coverage_basis, reason)`.
  Expansion rules (implemented once in `coverage_grid`, reused by spec 03):
  1. Every product gets every diagnosis of its policy_type, status = default_status.
  2. Waits considered: product initial_days (document); specified_disease_months × 365/12 for diagnoses in assumption A2 (assumption); condition waits from overrides (their basis).
  3. Overrides apply in file order; a specific diagnosis beats `*` because it is listed later.
  4. Diagnoses in assumption A1 (accident-exempt) get no wait.
  5. required_waiting_days = the largest applicable wait; waiting_basis/reason come from that wait.

## Known anomalies (report them; do not fix)
| Metric at as-of 2026-10-01 | Value |
| --- | --- |
| Claims inside policy period / before start / after end | 21,625 / 35,295 / 63,080 |
| Policies In Force / Lapsed / Cancelled (effective) | 9,647 / 63,107 / 2,246 |
| Recorded Active but not In Force | 50,811 |
| Interactions whose logged customer ≠ claim owner | 179,999 of 180,000 |
| Interactions dated before their claim | 66,401 |
| Policies in a multi-policy continuous chain | 2,110 (strictly back-to-back renewals: 12) |
| Schedule waiting 730 days on a 365-day policy | ≈ 20% of policies; such claims can never clear R03 |
| Approved claims with a Missing upload (raw) | 21,775 |
| Fraud score: manual-review rate per score band | 17.8–21.8%, i.e. no signal |

## Acceptance criteria
- [ ] AC-01-01 `make data` builds `data/warehouse.duckdb` from `data/raw/` in < 60 s on a laptop.
- [ ] AC-01-02 Row counts: customers 50,000; policies 75,000; claims 120,000; claim_documents 600,010; hospitals 1,200; customer_interactions 180,000.
- [ ] AC-01-03 Integrity: primary keys unique; zero orphan foreign keys for claims→policies, claims→customers, claims→hospitals, documents→claims, interactions→claims, interactions→customers, policies→customers. Build fails otherwise.
- [ ] AC-01-04 Derived counts equal the anomaly table above (as-of 2026-10-01).
- [ ] AC-01-05 `ref.diagnosis_coverage` has 85 rows, 32 with required_waiting_days > 0; Critical Care Elite/Maternity = not_covered; Senior Health Shield/Maternity = not_applicable; Family Care Gold/Maternity = conditional; Critical Care Elite/Cardiac Procedure = covered with 90 days; Health Secure Plus/Cataract = 730 days, basis assumption; Accidental Injury = 0 days everywhere.
- [ ] AC-01-06 Checklist for demo claims: CLM300210 missing [Claim Form, Discharge Summary, ID Proof, Prescription], pending [Diagnostic Report, Hospital Bill]; CLM300500 missing [Policy Copy]; CLM300101 missing [Prescription], pending [Claim Form].
- [ ] AC-01-07 expected_payable: CLM300210 = 58,119; CLM300500 = 34,184; CLM300101 = 57,091.
- [ ] AC-01-08 `data/data_quality_report.json` lists every integrity check (pass/fail) and every anomaly metric (value) with a description.
- [ ] AC-01-09 Two consecutive builds produce identical row counts and identical `SELECT md5(string_agg(...))` checksums per gold table.
- [ ] AC-01-10 Runtime connections are read-only; a write attempt raises.
- [ ] AC-01-11 Single-claim lookups on gold tables return in < 50 ms.

## Eval hooks
Feeds the sql_facts slice (spec 11) and every rule (spec 07). No eval gate of its own.

## Open questions
- Deductible-before-co-pay order (#7) and the required-documents matrix (#3) are proposed defaults.
