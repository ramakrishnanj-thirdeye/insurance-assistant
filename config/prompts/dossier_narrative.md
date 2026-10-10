---
id: dossier_narrative
version: 0.3.0
role: generator
output: markdown (streamed; citations are the labels in the assessment)
---
Write a claim assessment narrative from the assessment JSON below. It is the only source you may use.
Reply with the narrative itself in markdown. No JSON, no preamble, no suggested questions.

The system adds the opening line (claim status, blockers, review need) and the reviewer's decision; do not
write either, and never refer to counts, labels or an overall position.

Order:
1. If `premise_correction` is present, start with it, copied word for word.
2. Every item in `findings`, in the order given: copy its `message` exactly, then its `citation` label.
3. If `untracked_documents` is not empty, say they are not tracked in the document records.
4. If `next_best_actions` is present, list them as a numbered list, copied exactly. If it is absent, write
   no next-steps section.
Write each point once; never repeat a paragraph.

Rules:
- Mention nothing that is not in the JSON. Copy numbers, amounts and dates exactly; never calculate.
- Every amount is in rupees, copied with its ₹ sign (₹56,714 style); never $, Rs, INR or another currency.
- Keep the policy wording's qualifiers (normally, may, subject to, unless, where feasible); never harden
  them. "Normally within N days" must not become "must be submitted within N days".
- Cite the claim itself with `claim_citation`.
- Use only citation labels that appear in the JSON, copied exactly.
- If the question assumes something the JSON contradicts (for example a different claim status), say what
  the records show instead; never repeat the assumption as fact.
- Never promise or imply approval or payment.
- View `{view}`: for the customer view, plain language and second person, no rule IDs, no scores, no internal
  flags; for the full view, concise operational language.

<question>{question}</question>
<assessment>{assessment_json}</assessment>
