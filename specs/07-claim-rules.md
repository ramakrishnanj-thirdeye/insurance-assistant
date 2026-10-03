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
def compile_rules(rules, thresholds) -> str: ...            # one SELECT producing <id> status columns
def evaluate_claim(claim_id: str, persona: Persona) -> ClaimAssessment: ...   # no LLM
def materialise_portfolio(con) -> PortfolioReport: ...      # gold.rule_results (make rules)
```

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

## Acceptance criteria
- [ ] AC-07-01 `load_rules` rejects an expression that references an unknown column, with the rule ID in the error.
- [ ] AC-07-02 Rule statuses, missing and pending document lists for CA001–CA003 (eval/datasets/claim_analysis_seed.jsonl) match exactly.
- [ ] AC-07-03 Portfolio fail counts at as-of 2026-10-01 (regression fixture): R01 98,375 · R02 3,589 · R03 16,346 · R04 4,798 · R05 2,753 · R06 107,729 · R07 13,942 · R08 17,992 · R09 35,124 · R10 1,164 · R11 6,000 · R12 28,279.
- [ ] AC-07-04 Consistency counts: C1 59,627 · C2 514 · C3 241 · C4 1,412; maternity claims paid on products whose wording excludes maternity: 1,390.
- [ ] AC-07-05 Every rendered message for the three demo claims has no `{` characters and uses ₹ grouping.
- [ ] AC-07-06 Customer view of CLM300210 (principal CUST139920) contains no R10/R12 results, no fraud score, no consistency flags.
- [ ] AC-07-07 Narrative for CA001–CA003 mentions every blocker (deterministic check on `labels.must_mention`) and the judge finds zero invented findings.
- [ ] AC-07-08 `evaluate_claim` < 300 ms; `make rules` < 30 s.
- [ ] AC-07-09 Changing `thresholds.fraud_review_score` in settings changes R10 counts without code changes.

## Eval hooks
claim_analysis slice (25): blocker mention recall, invented findings, review-interrupt correctness.

## Notes for the demo
Because the data was generated column by column, rules fire on most claims (R01 fails on 82%). The leakage
radar presents these as a capability demonstration, with that caveat on screen (spec 10).
