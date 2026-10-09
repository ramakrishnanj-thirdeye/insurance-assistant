# Harder policy_clauses items sign-off (spec 11, M7b)

6 items appended to policy_clauses.jsonl: two naming no product, two sharing no content word with their
clause (checked by a test, product name and stop words aside), two whose answer spans two sections.

Changes at sign-off (Ram, 2026-10-09): EVAL037 expected_route is coverage_compare (it asks which product has
a feature); a policy_question naming no product would correctly ask "Which product?" (spec 06 rule 2).

## EVAL036 · hard_no_product

**Question:** Is a cashless approval at a network hospital the same as a final settlement?

**Gold answer:** No. Cashless authorization is not a guarantee of final claim settlement; it is subject to provider network availability and insurer authorization.

Wording:

- [All products §7 Cashless / Network Process] Cashless service is subject to provider network availability and insurer authorization. Authorization is not a guarantee of final claim settlement.

- [x] signed off (Ram, 2026-10-09)

## EVAL037 · hard_no_product

**Question:** Which plan pays for newborn benefits along with delivery expenses?

**Gold answer:** Maternity Protect: it covers eligible delivery expenses, a medically necessary C-section and defined newborn benefits, subject to sub-limits.

Wording:

- [Maternity Protect §5 Maternity] Covers eligible delivery expenses, medically necessary C-section, and defined newborn benefits subject to sub-limits.

- [x] signed off (Ram, 2026-10-09)

## EVAL038 · hard_no_overlap

**Question:** Under Car Shield Plus, if my car just stops working on its own without a crash, am I paid?

**Gold answer:** No. Breakdown unrelated to accident is excluded.

Wording:

- [Car Shield Plus §9 Exclusions] Depreciation unless zero-dep add-on active, illegal use, racing, breakdown unrelated to accident.

- [x] signed off (Ram, 2026-10-09)

## EVAL039 · hard_no_overlap

**Question:** Under Student Travel Protect, am I covered for something I already knew about when I bought it?

**Gold answer:** No. Events known before policy inception are excluded.

Wording:

- [Student Travel Protect §9 Exclusions] Elective treatment, undocumented baggage claims, events known before policy inception.

- [x] signed off (Ram, 2026-10-09)

## EVAL040 · hard_multi_section

**Question:** Under Health Secure Plus, what is the maternity waiting period, and how soon after discharge must a reimbursement claim be filed?

**Gold answer:** Maternity is covered after a 24-month waiting period; reimbursement claims should normally be submitted within 30 days of discharge.

Wording:

- [Health Secure Plus §5 Maternity] Covered after a 24-month waiting period, subject to plan variant and sub-limits.
- [Health Secure Plus §10 Claim Procedure] Cashless claims require pre-authorization at network hospitals. Reimbursement claims should normally be submitted within 30 days of discharge.

- [x] signed off (Ram, 2026-10-09)

## EVAL041 · hard_multi_section

**Question:** For Global Travel Secure, what are the coverage limits and which papers may be needed to claim?

**Gold answer:** Limits of ₹5,00,000 or ₹10,00,000 equivalent; travel documents, bills, incident reports and carrier certificates may be required.

Wording:

- [Global Travel Secure §2 Sum Insured] Available coverage limits: ₹5,00,000 / ₹10,00,000 equivalent limits.
- [Global Travel Secure §10 Claim Procedure] Travel documents, bills, incident reports, and carrier certificates may be required.

- [x] signed off (Ram, 2026-10-09)
