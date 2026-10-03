---
id: verify_groundedness
version: 0.1.0
role: judge
output: {"claims": [{"text": str, "supported": bool, "evidence_label": str | null}], "conflict_rule_followed": bool | null}
---
Split the answer into atomic factual claims. For each, decide whether the evidence directly supports it.
A claim is supported only if the evidence states it or it is a faithful restatement; inference beyond the evidence is unsupported.
If the evidence contains a schedule value and a wording value that differ, set conflict_rule_followed to whether the
answer shows both with the precedence sentence; otherwise null.
<evidence>{evidence_blocks}</evidence>
<answer>{answer}</answer>
