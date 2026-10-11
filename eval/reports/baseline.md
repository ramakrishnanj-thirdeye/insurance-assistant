# Eval report: full (2026-10-11T00:40:13+00:00)

- git 0fe281d · profile local · coverage matrix reviewed
- Judge agreement (within ±1): 6 of 10, 0.31–0.83
- V7 precision: 3 of 7, 0.16–0.75 (sampled 7 of 7 unsupported claims)
- Human-verified correctness on the calibration sample (score >= 4): 8 of 10, 0.49–0.94
- V7 Part B re-scored with the current claim splitter: 3 of 7 sampled flags no longer reach the judge; precision over the rest: 3 of 4, 0.30–0.95
- **judge uncalibrated** (agreement below 80%): judge-based metrics (correctness, faithfulness) are reported as advisory, not gated

## Open gates

| Metric | Value | Target |
| --- | --- | --- |
| analytics.exec_accuracy | 10 of 15, 0.42–0.85 | min 0.9 |
| policy_clauses_e2e.citation_accuracy | 0.9444 (34 of 36, 0.82–0.98) | min 0.95 |

## Advisory (judge uncalibrated, not gated)

| Metric | Value | Target |
| --- | --- | --- |
| claim_analysis.correctness | 5 of 10, 0.24–0.76 | min 0.9 |
| policy_clauses_e2e.faithfulness | 0.7778 (77 of 99, 0.69–0.85) | min 0.95 |
| comparisons.faithfulness | 9 of 12, 0.47–0.91 | min 0.95 |

## Judge calibration

### Part A: correctness judge vs human

| Item | Slice item | Human | Judge | Agree (±1) |
| --- | --- | --- | --- | --- |
| CAL01 | policy_clauses_e2e EVAL008 | 4 | 5 | yes |
| CAL02 | policy_clauses_e2e EVAL002 | 4 | 1 | no |
| CAL03 | policy_clauses_e2e EVAL018 | 2 | 5 | no |
| CAL04 | policy_clauses_e2e EVAL016 | 5 | 5 | yes |
| CAL05 | policy_clauses_e2e EVAL015 | 4 | 5 | yes |
| CAL06 | policy_clauses_e2e EVAL005 | 5 | 5 | yes |
| CAL07 | claim_analysis CA002 | 4 | 1 | no |
| CAL08 | claim_analysis CA009 | 5 | 5 | yes |
| CAL09 | claim_analysis CA010 | 4 | 1 | no |
| CAL10 | claim_analysis CA005 | 3 | 2 | yes |

### Part B: V7 verdicts vs human

| Item | Slice item | Claim | V7 verdict | Human | Agree | Reaches judge now |
| --- | --- | --- | --- | --- | --- | --- |
| V7-01 | policy_clauses_e2e EVAL018 | Co-payment details are not explicitly outlined in the policy schedule [Senior Health Shield §2 Sum Insured]. | unsupported | correct | yes | yes |
| V7-02 | policy_clauses_e2e EVAL028 | Document Type \| Description | unsupported | false positive | no | no |
| V7-03 | policy_clauses_e2e EVAL032 | No, vet bills for your pet dog are not covered. | unsupported | correct | yes | yes |
| V7-04 | policy_clauses_e2e EVAL032 | [All products §6 Hospitalization / Loss Coverage] states eligible expenses are payable subject to policy terms, but this does not include pet-related expenses. | unsupported | correct | yes | yes |
| V7-05 | policy_clauses_e2e EVAL039 | No, you are not covered for something you already knew about when you bought it. | unsupported | false positive | no | yes |
| V7-06 | comparisons CMP001 | Your policy schedule governs this policy's numbers; the product wording describes the general terms. | unsupported | false positive | no | no |
| V7-07 | adversarial ADV004 | A claims specialist will review this claim before a decision. | unsupported | false positive | no | no |


## Gate

Pass.

Tolerance: a regression from the baseline fails above 2 points, or above one item (1/n) for a proportion with n < 30; a target the baseline met must still be met.

## policy_clauses

| Metric | Value |
| --- | --- |
| items | 36 |
| probes | 5 |
| recall_at_5 | 1.0000 (36 of 36, 0.90–1.00) |
| product_precision_at_5 | 1.0 |
| mrr | 0.9236 |
| latency_p50_ms | 91.5 |
| latency_p95_ms | 122.5 |
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
| intent_accuracy | 0.9792 (94 of 96, 0.93–0.99) |
| entity_exact | 1.0000 (96 of 96, 0.96–1.00) |
| by_slice | {"analytics": {"items": 15, "intent_accuracy": 1.0, "entity_exact": 1.0}, "claim_analysis": {"items": 10, "intent_accuracy": 1.0, "entity_exact": 1.0}, "multi_turn": {"items": 10, "intent_accuracy": 1.0, "entity_exact": 1.0}, "policy_clauses": {"items": 41, "intent_accuracy": 0.9512, "entity_exact": 1.0}, "sql_facts": {"items": 20, "intent_accuracy": 1.0, "entity_exact": 1.0}} |
| wrong | 2: EVAL021, EVAL034 |

## e2e_sql_facts

| Metric | Value |
| --- | --- |
| items | 20 |
| scored | 19 |
| gold_in_answer | 19 of 19, 0.83–1.00 |
| misses | none |
| verifier_pass | {"CURRENCY": 1.0, "V1": 1.0, "V2": 1.0, "V3": 1.0, "V4": 1.0, "V5": 1.0, "V6": 1.0} |

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
| v7_judged | 9 |
| v7_pass_rate | 5 of 9, 0.27–0.81 |
| faithfulness | 0.9518 (79 of 83, 0.88–0.98) |
| faithfulness_judged | 13 of 17, 0.53–0.90 |
| v7_verbatim_share | 0.7952 (66 of 83, 0.70–0.87) |
| v7_claims_total | 83 |
| v7_verbatim_total | 66 |
| v7_unsupported_total | 4 |
| v7_excluded_total | 0 |
| v7_judge_errors | 1 |
| correctness | 5 of 10, 0.24–0.76 |
| judge_errors | 0 |
| orphan_numbers | 0 of 10, 0.00–0.28 |
| orphan_items | none |
| guard_interventions | 2 of 10, 0.06–0.51 |
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
| latency_p50_ms | 9855.9 |
| latency_p95_ms | 26205.9 |
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
| verifier_pass | {"CURRENCY": 1.0, "V1": 1.0, "V2": 1.0, "V3": 1.0, "V4": 1.0, "V5": 1.0, "V6": 1.0} |
| v7_judged | 2 |
| v7_pass_rate | 2 of 2, 0.34–1.00 |
| faithfulness | 6 of 6, 0.61–1.00 |
| faithfulness_judged | 4 of 4, 0.51–1.00 |
| v7_verbatim_share | 2 of 6, 0.10–0.70 |
| v7_claims_total | 6 |
| v7_verbatim_total | 2 |
| v7_unsupported_total | 0 |
| v7_excluded_total | 0 |
| v7_judge_errors | 0 |
| errors | none |

## policy_clauses_e2e

| Metric | Value |
| --- | --- |
| items | 41 |
| draft_items | 0 |
| correctness | 0.9444 (34 of 36, 0.82–0.98) |
| judge_errors | 0 |
| citation_accuracy | 0.9444 (34 of 36, 0.82–0.98) |
| refused | 0.0000 (0 of 36, 0.00–0.10) |
| probes_abstained | 5 of 5, 0.57–1.00 |
| v7_judged | 36 |
| v7_pass_rate | 0.6667 (24 of 36, 0.50–0.80) |
| faithfulness | 0.7778 (77 of 99, 0.69–0.85) |
| faithfulness_judged | 0.7732 (75 of 97, 0.68–0.85) |
| v7_verbatim_share | 0.0202 (2 of 99, 0.01–0.07) |
| v7_claims_total | 99 |
| v7_verbatim_total | 2 |
| v7_unsupported_total | 22 |
| v7_excluded_total | 0 |
| v7_judge_errors | 3 |
| verifier_pass | {"CURRENCY": 1.0, "V1": 1.0, "V2": 1.0, "V3": 1.0, "V4": 1.0, "V5": 1.0, "V6": 1.0} |
| wrong | 2: EVAL010, EVAL021 |
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
| v7_judged | 5 |
| v7_pass_rate | 2 of 5, 0.12–0.77 |
| faithfulness | 9 of 12, 0.47–0.91 |
| faithfulness_judged | 9 of 12, 0.47–0.91 |
| v7_verbatim_share | 0 of 12, 0.00–0.24 |
| v7_claims_total | 12 |
| v7_verbatim_total | 0 |
| v7_unsupported_total | 3 |
| v7_excluded_total | 0 |
| v7_judge_errors | 0 |
| verifier_pass | {"CURRENCY": 1.0, "V1": 1.0, "V2": 1.0, "V3": 1.0, "V4": 1.0, "V5": 1.0, "V6": 1.0} |
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
| v7_pass_rate | 3 of 6, 0.19–0.81 |
| faithfulness | 0.9118 (31 of 34, 0.77–0.97) |
| faithfulness_judged | 8 of 11, 0.43–0.90 |
| v7_verbatim_share | 0.6765 (23 of 34, 0.51–0.81) |
| v7_claims_total | 34 |
| v7_verbatim_total | 23 |
| v7_unsupported_total | 3 |
| v7_excluded_total | 3 |
| v7_judge_errors | 0 |
| verifier_pass | {"CURRENCY": 1.0, "V1": 1.0, "V2": 1.0, "V3": 1.0, "V4": 1.0, "V5": 1.0, "V6": 1.0} |
| not_handled | none |
| errors | none |

## suite

| Metric | Value |
| --- | --- |
| false_refusal | 0.0000 (0 of 44, 0.00–0.08) |
| refused_items | none |
