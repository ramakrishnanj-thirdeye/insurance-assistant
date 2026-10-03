---
id: dossier_narrative
version: 0.1.0
role: generator
output: markdown
---
Write a claim assessment narrative from the ClaimAssessment JSON below. It is the only source you may use.
- First line: the overall position in one sentence (e.g. "This claim has 3 blockers and needs human review.").
- Then the blockers, then warnings and items needing review, each with its citation label from the JSON.
- Mention every rule with status fail and severity blocker or escalate, and every review item. Mention nothing that is not in the JSON.
- End with the next best actions as a short numbered list.
- If a reviewer decision is present, state it and the note first.
- View `{view}`: for customer view, plain language, no rule IDs, no scores, no internal flags.
- Never promise approval. Copy numbers exactly.
<assessment>{assessment_json}</assessment>
