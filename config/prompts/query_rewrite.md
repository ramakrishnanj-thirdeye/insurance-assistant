---
id: query_rewrite
version: 0.1.0
role: small
output: {"rewritten_query": str, "extra_section_hints": [int], "product_mentions": [str]}
---
Rewrite the user's insurance question into a retrieval query for policy wordings.
- Keep the user's meaning; add the insurer's terms (e.g. "drunk driving" → also "intoxication"; "PED" → "pre-existing disease").
- Sections: 2 Sum Insured, 3 Eligibility, 4 Waiting Period, 5 Maternity, 6 Hospitalization / Loss Coverage,
  7 Cashless / Network Process, 8 Reimbursement Process, 9 Exclusions, 10 Claim Procedure, 11 Fraud / Misrepresentation,
  12 Privacy, 13 Human Review, 14 Disclaimer, 15 Training FAQ. Return the most likely 1–2 section numbers.
- product_mentions: canonical names from {product_names} that the question names; empty if none.
Question: {question}
Glossary expansion already applied: {glossary_terms}
