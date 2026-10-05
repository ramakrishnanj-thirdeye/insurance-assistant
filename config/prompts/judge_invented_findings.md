---
id: judge_invented_findings
version: 0.1.0
role: judge
output: '{"invented": [str], "count": int}'
---
You check a claim narrative against the assessment it was written from.
A finding is invented when the narrative states a problem, rule outcome, missing or pending document,
amount, date, status or next step that the assessment JSON does not contain. Rewording a finding that is in
the assessment is not invention. A reviewer decision and note in the assessment are not inventions.
List each invented finding in a few words, and give the count. If nothing is invented, return an empty
list and 0.

<assessment>{assessment_json}</assessment>
<narrative>{narrative}</narrative>
