---
id: verify_groundedness
version: 0.3.0
role: judge
output: {"claims": [{"text": str, "supported": bool, "evidence_label": str | null}], "conflict_rule_followed": bool | null}
---
Split the answer into atomic factual claims. For each, decide whether the evidence directly supports it.
A claim is supported only if the evidence states it or it is a faithful restatement; inference beyond the evidence is unsupported.
The evidence is JSON. A sentence that repeats a value from it (a list item, an action, a decision or note, a
message), even reworded, numbered or merged with other values, is a faithful restatement.
Citation labels in square brackets are not claims. These fixed sentences are policy rules, not claims; skip them:
{fixed_sentences}
If the evidence contains a schedule value and a wording value that differ, set conflict_rule_followed to whether the
answer shows both with the precedence sentence; otherwise null.
<evidence>{evidence_blocks}</evidence>
<answer>{answer}</answer>
