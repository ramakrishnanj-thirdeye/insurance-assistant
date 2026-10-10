# 07 – Claim rules engine and Claim Dossier

Milestone: M5 · Depends on: 01, 03, 04, 05, 06 · Config: config/rules.yaml · Reference: specs/reference/prototype_build_and_rules.py

## Goal
Deterministic claim judgments with evidence and citations, one definition for single claims and the whole
portfolio, wrapped in a subgraph that gathers facts, cites clauses, pauses for human review and narrates.

## Interfaces
```python
# src/insurai/rules/engine.py
class RuleDef(BaseModel): id: str; name: str; severity: Severity; severity_if: list[SeverityIf] = []
    applies_if: str = "TRUE"; pass_if: str; review_if: str = "FALSE"; evidence: list[str]; message: str
    cite: Literal["schedule", "coverage", "reimbursement", "human_review", "none"]; hidden_from: list[Persona] = []
class RuleResult(BaseModel):
    id: str; name: str; status: Literal["pass", "fail", "review", "not_applicable"]; severity: Severity
    message: str | None; evidence: dict[str, Any]; citation: SourceRef | None
class ClaimAssessment(BaseModel):
    claim_id: str; as_of: date; view: Literal["full", "customer"]
    facts: dict[str, Any]; rules: list[RuleResult]; checklist: DocumentChecklist
    consistency: list[ConsistencyFlag]          # C1..C4
    needs_human_review: bool; escalation_reasons: list[str]
    next_best_actions: list[str]; interactions: InteractionHistory | None
    clauses: list[RetrievedChunk]; narrative: str | None; customer_message_draft: str | None
    review: ReviewDecision | None; sources: list[SourceRef]
def load_rules(path: Path, con) -> list[RuleDef]: ...        # validates every expression against gold.claim_facts columns
def compile_rules(rules, thresholds, *, consistency=(), insights=()) -> str: ...  # one SELECT producing <id> status columns
def evaluate_claim(claim_id: str, persona: Persona, *, principal_id=None, trace_id=None
                   ) -> ClaimAssessment | NotFound | AccessDenied: ...   # no LLM
def materialise_portfolio(con) -> PortfolioReport: ...      # gold.rule_results (make rules)
```
Implementation notes (2026-10-06): `RuleDef` also takes `message_if: list[{when, message}]` (first match wins,
like `severity_if`). `evaluate_claim` takes the principal as a keyword (ownership is checked by the claim tools)
and returns NotFound or AccessDenied like every tool. `compile_rules` takes the consistency flags and portfolio
insights (P1) as keywords. `PortfolioReport` (rules/schemas.py): as_of, claims, fail_counts, review_counts,
consistency_counts, insight_counts, by_product, elapsed_ms. The dossier pipeline without the graph is
`insurai.agent.dossier.analyze(ctx, claim_id, narrate, question)` (analyze_claim tool, GET /claims/{id}/dossier).

## Behaviour
1. Status per rule: not_applicable if NOT applies_if; pass if pass_if; review if review_if; else fail. NULL → false. `{fraud_review_score}`-style placeholders come from settings.thresholds.
2. Severity: the rule's severity unless a `severity_if` condition holds (e.g. R04 with an assumption-based wait → warning).
3. Messages render with evidence values: rupees with Indian grouping (₹58,119; ₹5,00,000), ISO dates, lists joined with commas. No unresolved `{placeholders}`.
4. Citations: `schedule` → `[policies:<policy_id>]`; `coverage` → the product's section from ref.diagnosis_coverage.section_no; `reimbursement` → `[All products §8 Reimbursement Process]`; `human_review` → `[All products §13 Human Review]`.
5. needs_human_review = any fail with severity blocker or escalate, or any review.
6. Consistency flags C1–C4 from rules.yaml; C1 uses "any blocker fail".
7. Next best actions (deterministic, ordered by severity):
   R06 fail → "Request {missing_doc_types} from the customer"; R07 review → "Verify {pending_doc_types}";
   R07 fail → "Ask for replacements of {rejected_doc_types}"; R01 fail → "Confirm the policy period; the claim date falls outside it";
   R05 review → "Confirm whether {diagnosis} is covered under {product}"; R08 fail → "Advise the reimbursement path; network alternatives: …";
   R10/R11/R12 fail → "Route to the manual review queue"; untracked documents → "Collect {untracked} outside the system".
8. Customer view: drop rules in `hidden_from`, drop consistency flags and escalation reasons, keep plain-language next steps.
9. Dossier subgraph: gather_facts (get_claim, get_claim_documents, get_claim_interactions in parallel) → evaluate_rules →
   fetch_clauses (for each fail/review rule with cite coverage: search_policy filtered to the product and section; for reimbursement/human_review: the ALL chunks) →
   assemble → interrupt if needs_human_review and persona ≠ customer → narrate (LLM, prompt dossier_narrative.md, input = assessment JSON only) →
   customer_message_draft (template + LLM polish, no-guarantee check).
10. `make rules` materialises gold.rule_results (claim_id, status per rule, consistency flags) for the audit and analytics.

Additions decided 2026-10-06:
11. Messages read as plain language: config `formats` (rupee columns, labels for raw codes) and per-status
    `message_if` variants (R05 per coverage status, R01 before the policy started, R07 pending only, R09 when the
    deductible or co-pay is zero, R12 by flag); no rendered message contains a snake_case token.
12. Next best actions live in config (`next_best_actions`, each with a plain-language `customer_text`).
13. False premise: status words in the question (`dossier.status_words`) that contradict the claim's status produce a
    cited correction that opens the narrative ("CLM300210 is Approved, not pending [claims:CLM300210].").
14. Completeness guard: after the narrative, any fail or review finding whose message is missing, and any missing
    next best action, is appended verbatim with its citation; the correction is moved to the front.
15. Every citation label in the assessment is in the dossier evidence's sources (V1), including clause labels.

## Acceptance criteria
- [x] AC-07-01 `load_rules` rejects an expression that references an unknown column, with the rule ID in the error.
- [x] AC-07-02 Rule statuses, missing and pending document lists for CA001–CA003 (eval/datasets/claim_analysis_seed.jsonl) match exactly. Also CA004–CA010 (draft, labels derived independently by `insurai.eval.claim_labels`), and the two implementations agree on all 120,000 claims.
- [x] AC-07-03 Portfolio fail counts at as-of 2026-10-01 (regression fixture): R01 98,375 · R02 3,589 · R03 16,346 · R04 4,798 · R05 2,753 · R06 107,729 · R07 13,942 · R08 17,992 · R09 35,124 · R10 1,164 · R11 6,000 · R12 28,279.
- [x] AC-07-04 Consistency counts: C1 59,627 · C2 514 · C3 241 · C4 1,412; maternity claims paid on products whose wording excludes maternity: 1,390.
- [x] AC-07-05 Every rendered message for the three demo claims has no `{` characters and uses ₹ grouping.
- [x] AC-07-06 Customer view of CLM300210 (principal CUST139920) contains no R10/R12 results, no fraud score, no consistency flags.
- [x] AC-07-07 Narrative for CA001–CA003 mentions every blocker (deterministic check on `labels.must_mention`) and the judge finds zero invented findings. Passed 2026-10-06 on the local profile (generator qwen3:8b, judge llama3.1:8b, ADR-006 amendment); the completeness guard makes the mention part model-independent (scripted-model tests over all 10 items); api-lite skips until an ANTHROPIC_API_KEY exists.
- [x] AC-07-08 `evaluate_claim` < 300 ms; `make rules` < 30 s. Measured 2026-10-06: warm 80–90 ms (first call ~2.7 s while the ruleset and section names load); `make rules` 0.8 s (3.6 s with process start).
- [x] AC-07-09 Changing `thresholds.fraud_review_score` in settings changes R10 counts without code changes.
- [x] AC-07-10 Narrative presentation: the first line is the `narrative_opening` template ("Claim X is <status>;
  N blockers; needs / doesn't need human review [claims:X]."), never a model sentence about counts, labels or an
  overall position; the model's own status opener is removed; `narrative_input` carries no counts and no review,
  gives amounts in rupees, and leaves out an empty next_best_actions list, so no empty next-steps section appears.
- [x] AC-07-11 The reviewer's decision and note are appended verbatim after the narrative (`review_decision`
  template), exactly once, never reworded by the model (tests/rules/test_narrative.py, tests/agent/test_dossier.py).

## Eval hooks
claim_analysis slice (25): blocker mention recall, invented findings, review-interrupt correctness.

## Notes for the demo
Because the data was generated column by column, rules fire on most claims (R01 fails on 82%). The leakage
radar presents these as a capability demonstration, with that caveat on screen (spec 10).
