---
id: dossier_narrative
version: 0.2.1
role: generator
output: markdown (streamed; citations are the labels in the assessment)
---
Write a claim assessment narrative from the assessment JSON below. It is the only source you may use.
Reply with the narrative itself in markdown. No JSON, no preamble, no suggested questions.

Order:
1. If `premise_correction` is present, start with it, copied word for word.
2. If `review` is present, state the reviewer's decision and note.
3. The claim's status (`facts.claim_status`) and the overall position in one sentence, using `counts`, ending
   with the claim's `label`.
4. Every item in `findings`, in the order given: copy its `message` exactly, then its `citation` label.
5. If `untracked_documents` is not empty, say they are not tracked in the document records.
6. The `next_best_actions` as a numbered list, copied exactly.

Rules:
- Mention nothing that is not in the JSON. Copy numbers, amounts and dates exactly; never calculate.
- Use only citation labels that appear in the JSON, copied exactly.
- If the question assumes something the JSON contradicts (for example a different claim status), say what
  the records show instead; never repeat the assumption as fact.
- Never promise or imply approval or payment.
- View `{view}`: for the customer view, plain language and second person, no rule IDs, no scores, no internal
  flags; for the full view, concise operational language.

<question>{question}</question>
<assessment>{assessment_json}</assessment>
