# ADR-007 Keep and flag data anomalies; fixed as-of date
Status: accepted (open decisions #4 and #5 defaulted)

**Context.** The dataset was generated column by column: 82% of claims fall outside their policy period, 50,811 Active policies have ended, document status ignores claim status, the fraud score carries no signal.
**Decision.** Never repair raw data. Derive explicit flags in silver/gold, report them in the DQ report, surface them in answers and the leakage radar with a synthetic-data caveat. All date logic uses `as_of_date = 2026-10-01` (latest claim date), never the system clock.
**Consequences.** Answers are honest and evals reproducible; most claims show blockers in the dossier, which the demo explains up front.
**Alternatives.** Curate a repaired demo cohort (cleaner story, but hides exactly what the assistant is good at); use today's date (non-reproducible evals).
