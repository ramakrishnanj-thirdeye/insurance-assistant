# Eval report: full (2026-10-09T06:01:20+00:00)

- git 6e6bb10 · profile local · coverage matrix reviewed
- Judge agreement: awaiting human scores (0 of 10 scored)
- V7 precision: awaiting marks (0 of 7 marked)

## Open gates

| Metric | Value | Target |
| --- | --- | --- |
| analytics.exec_accuracy | 10 of 15, 0.42–0.85 | min 0.9 |
| claim_analysis.correctness | 3 of 10, 0.11–0.60 | min 0.9 |
| policy_clauses_e2e.correctness | 0.8611 (31 of 36, 0.71–0.94) | min 0.9 |
| policy_clauses_e2e.faithfulness | 0.8936 (42 of 47, 0.77–0.95) | min 0.95 |
| policy_clauses_e2e.citation_accuracy | 0.9167 (33 of 36, 0.78–0.97) | min 0.95 |
| comparisons.faithfulness | 11 of 12, 0.65–0.99 | min 0.95 |

## Gate

- FAIL analytics.exec_accuracy = 0.6667 misses target min 0.9 (no baseline value)
- FAIL claim_analysis.correctness = 0.3 misses target min 0.9 (no baseline value)
- FAIL policy_clauses_e2e.correctness = 0.8611 misses target min 0.9 (no baseline value)
- FAIL policy_clauses_e2e.faithfulness = 0.8936 misses target min 0.95 (no baseline value)
- FAIL policy_clauses_e2e.citation_accuracy = 0.9167 misses target min 0.95 (no baseline value)
- FAIL comparisons.faithfulness = 0.9167 misses target min 0.95 (no baseline value)

Tolerance: a regression from the baseline fails above 2 points, or above one item (1/n) for a proportion with n < 30; a target the baseline met must still be met.

## policy_clauses

| Metric | Value |
| --- | --- |
| items | 36 |
| probes | 5 |
| recall_at_5 | 1.0000 (36 of 36, 0.90–1.00) |
| product_precision_at_5 | 1.0 |
| mrr | 0.9236 |
| latency_p50_ms | 101.7 |
| latency_p95_ms | 143.9 |
| probes_not_confident | 5 |
| answerable_not_confident | 0 |
| misses | none |
| suggested_rerank_threshold | -5.0798 |
| suggested_threshold_f1 | 1.0 |

## sql_facts

| Metric | Value |
| --- | --- |
| items | 20 |
| accuracy | 20 of 20, 0.84–1.00 |
| tool_errors | 0 |
| wrong | none |

## routing

| Metric | Value |
| --- | --- |
| items | 96 |
| intent_accuracy | 0.9688 (93 of 96, 0.91–0.99) |
| entity_exact | 1.0000 (96 of 96, 0.96–1.00) |
| by_slice | {"analytics": {"items": 15, "intent_accuracy": 1.0, "entity_exact": 1.0}, "claim_analysis": {"items": 10, "intent_accuracy": 1.0, "entity_exact": 1.0}, "multi_turn": {"items": 10, "intent_accuracy": 1.0, "entity_exact": 1.0}, "policy_clauses": {"items": 41, "intent_accuracy": 0.9268, "entity_exact": 1.0}, "sql_facts": {"items": 20, "intent_accuracy": 1.0, "entity_exact": 1.0}} |
| wrong | 3: EVAL021, EVAL034, EVAL036 |

## e2e_sql_facts

| Metric | Value |
| --- | --- |
| items | 20 |
| scored | 19 |
| gold_in_answer | 19 of 19, 0.83–1.00 |
| misses | none |
| verifier_pass | {"V1": 1.0, "V2": 1.0, "V3": 1.0, "V4": 1.0, "V5": 1.0, "V6": 1.0} |

## claim_analysis

| Metric | Value |
| --- | --- |
| items | 10 |
| draft_items | 0 |
| rule_status_exact | 10 of 10, 0.72–1.00 |
| docs_exact | 10 of 10, 0.72–1.00 |
| consistency_exact | 10 of 10, 0.72–1.00 |
| needs_review_exact | 10 of 10, 0.72–1.00 |
| review_interrupt | 10 of 10, 0.72–1.00 |
| blocker_mention | 1.0000 (36 of 36, 0.90–1.00) |
| invented_findings | 0 |
| invented_findings_free | 10 of 10, 0.72–1.00 |
| v7_judged | 10 |
| v7_pass_rate | 10 of 10, 0.72–1.00 |
| faithfulness | 1.0000 (65 of 65, 0.94–1.00) |
| v7_verbatim_share | 0.9846 (64 of 65, 0.92–1.00) |
| v7_claims_total | 65 |
| v7_verbatim_total | 64 |
| v7_unsupported_total | 0 |
| v7_errors | 0 |
| correctness | 3 of 10, 0.11–0.60 |
| judge_errors | 0 |
| guard_interventions | 1 of 10, 0.02–0.40 |
| wrong | none |

## analytics

| Metric | Value |
| --- | --- |
| items | 15 |
| exec_accuracy | 10 of 15, 0.42–0.85 |
| unsafe_blocked | 1.0000 (31 of 31, 0.89–1.00) |
| unsafe_probes | 31 |
| repair_rate | 0.0667 |
| rejected_rate | 0.0 |
| latency_p50_ms | 9997.9 |
| latency_p95_ms | 26258.1 |
| wrong | 5: ANA002, ANA003, ANA006, ANA009, ANA014 |
| leaked_probes | none |

## guardrails

| Metric | Value |
| --- | --- |
| items | 3 |
| not_refused | 3 of 3, 0.44–1.00 |
| s15_cited | 2 of 2, 0.34–1.00 |
| mandated_wording | 2 of 2, 0.34–1.00 |
| conflict_rendered | 1 of 1, 0.21–1.00 |
| verifier_pass | {"V1": 1.0, "V2": 1.0, "V3": 1.0, "V4": 1.0, "V5": 1.0, "V6": 1.0} |
| v7_judged | 2 |
| v7_pass_rate | 1.0 |
| faithfulness | 1.0 |
| v7_verbatim_share | 1.0 |
| v7_claims_total | 2 |
| v7_verbatim_total | 2 |
| v7_unsupported_total | 0 |
| v7_errors | 0 |
| errors | none |

## policy_clauses_e2e

| Metric | Value |
| --- | --- |
| items | 41 |
| draft_items | 0 |
| correctness | 0.8611 (31 of 36, 0.71–0.94) |
| judge_errors | 0 |
| citation_accuracy | 0.9167 (33 of 36, 0.78–0.97) |
| refused | 0.0000 (0 of 36, 0.00–0.10) |
| probes_abstained | 1 of 5, 0.04–0.62 |
| v7_judged | 38 |
| v7_pass_rate | 0.8947 (34 of 38, 0.76–0.96) |
| faithfulness | 0.8936 (42 of 47, 0.77–0.95) |
| v7_verbatim_share | 0.0426 (2 of 47, 0.01–0.14) |
| v7_claims_total | 47 |
| v7_verbatim_total | 2 |
| v7_unsupported_total | 5 |
| v7_errors | 0 |
| verifier_pass | {"V1": 1.0, "V2": 1.0, "V3": 1.0, "V4": 1.0, "V5": 1.0, "V6": 1.0} |
| wrong | 5: EVAL002, EVAL004, EVAL010, EVAL021, EVAL036 |
| errors | none |

## comparisons

| Metric | Value |
| --- | --- |
| items | 5 |
| draft_items | 0 |
| correctness | 5 of 5, 0.57–1.00 |
| judge_errors | 0 |
| citation_accuracy | 5 of 5, 0.57–1.00 |
| refused | 0 of 5, 0.00–0.43 |
| v7_judged | 4 |
| v7_pass_rate | 3 of 4, 0.30–0.95 |
| faithfulness | 11 of 12, 0.65–0.99 |
| v7_verbatim_share | 2 of 12, 0.05–0.45 |
| v7_claims_total | 12 |
| v7_verbatim_total | 2 |
| v7_unsupported_total | 1 |
| v7_errors | 1 |
| verifier_pass | {"V1": 1.0, "V2": 1.0, "V3": 1.0, "V4": 1.0, "V5": 1.0, "V6": 1.0} |
| wrong | none |
| errors | none |

## adversarial

| Metric | Value |
| --- | --- |
| items | 15 |
| draft_items | 0 |
| handled | 15 of 15, 0.80–1.00 |
| refusal_correct | 7 of 7, 0.65–1.00 |
| guarantee_handled | 2 of 2, 0.34–1.00 |
| handled_cross_customer | 2 of 2, 0.34–1.00 |
| handled_false_premise | 2 of 2, 0.34–1.00 |
| handled_guarantee | 2 of 2, 0.34–1.00 |
| handled_injection | 2 of 2, 0.34–1.00 |
| handled_invented_clause | 2 of 2, 0.34–1.00 |
| handled_out_of_scope | 1 of 1, 0.21–1.00 |
| handled_pii | 2 of 2, 0.34–1.00 |
| handled_unknown_id | 2 of 2, 0.34–1.00 |
| v7_judged | 6 |
| v7_pass_rate | 5 of 6, 0.44–0.97 |
| faithfulness | 21 of 22, 0.78–0.99 |
| v7_verbatim_share | 15 of 22, 0.47–0.84 |
| v7_claims_total | 22 |
| v7_verbatim_total | 15 |
| v7_unsupported_total | 1 |
| v7_errors | 0 |
| verifier_pass | {"V1": 1.0, "V2": 1.0, "V3": 1.0, "V4": 1.0, "V5": 1.0, "V6": 1.0} |
| not_handled | none |
| errors | none |

## suite

| Metric | Value |
| --- | --- |
| false_refusal | 0.0000 (0 of 44, 0.00–0.08) |
| refused_items | none |
