# Evaluation datasets

All slices are JSONL, one item per line, one shared schema (spec 11):

| Field | Type | Meaning |
| --- | --- | --- |
| id | str | Stable ID, prefix per slice (EVAL, SQL, ANA, CL, CMP, CA, MT, ADV) |
| slice | str | sql_facts, analytics, policy_clauses, comparisons, claim_analysis, multi_turn, adversarial |
| persona | str | customer, claims_agent, supervisor |
| principal_id | str? | customer_id when persona is customer |
| turns | list | [{role: user, content}], several for multi_turn |
| expected_route | list[str] | Intent types the planner must emit (set match) |
| expected_entities | dict | claim_id, policy_id, customer_id, hospital_id, product, policy_type |
| gold_answer | str? | Reference answer (short) |
| gold_sources | list[str] | Citation labels or table:key refs that must be cited |
| gold_sql | str? | Analytics slice only; scored by result-set match |
| must_refuse | bool | True for adversarial items that must be refused |
| refusal_code | str? | ACCESS_DENIED, OUT_OF_SCOPE, INJECTION, GUARANTEE_REQUEST, NOT_FOUND |
| tags | list[str] | Free tags, e.g. lexical_trap, seed, demo |
| labels | dict? | Slice-specific gold, e.g. expected rule statuses for claim_analysis |

Files committed now:
- `seed_rag.jsonl` — the 5 BRD seed questions, with the broken `0,1,2,3,4` header fixed and gold section labels added.
- `claim_analysis_seed.jsonl` — CLM300210, CLM300500, CLM300101 with hand-checked rule outcomes (CA001–CA003).
- `claim_analysis.jsonl` — CA004–CA010, one claim per pattern (cancelled policy, schedule wait, maternity wait,
  maternity paid where excluded, rejected document, fraud escalation, a control). Labels are derived by
  `python -m insurai.eval.claim_labels` in plain Python from silver.* and ref.*, independently of the rules engine;
  items stay tagged `draft` until signed off in `claim_analysis_checklist.md`.

Files generated or written during M7 (spec 11): `sql_facts.jsonl` (generator, seed 42), `analytics.jsonl`,
`policy_clauses.jsonl`, `comparisons.jsonl`, `multi_turn.jsonl`, `adversarial.jsonl`, `judge_calibration.jsonl`.
