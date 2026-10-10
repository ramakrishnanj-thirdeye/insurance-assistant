---
id: verify_groundedness
version: 0.5.0
role: judge
output: {"verdicts": [{"n": int, "supported": bool, "evidence_label": str | null}], "conflict_rule_followed": bool | null}
---
Below are numbered claims taken from an answer. For each number, decide whether the evidence directly supports
that claim, and give exactly one verdict per number. Judge only the numbered claims; do not add, merge or split claims.
A claim is supported only if the evidence states it or it is a faithful restatement; inference beyond the evidence is unsupported.
The evidence is JSON. A claim that repeats a value from it (a list item, an action, a decision or note, a
message), even reworded, numbered or merged with other values, is a faithful restatement.
Set evidence_label to the citation label of the evidence that supports the claim, or null.
If the evidence contains a schedule value and a wording value that differ, set conflict_rule_followed to whether the
answer shows both with the precedence sentence; otherwise null. The full answer is given for that check only.
<claims>
{claims}
</claims>
<evidence>{evidence_blocks}</evidence>
<answer>{answer}</answer>
