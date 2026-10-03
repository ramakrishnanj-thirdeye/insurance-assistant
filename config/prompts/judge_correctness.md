---
id: judge_correctness
version: 0.1.0
role: judge
output: {"score": 1-5, "reason": str}
---
Score how well the answer matches the reference for the question.
5 = fully correct and complete; 4 = correct with minor omissions; 3 = partly correct; 2 = mostly wrong; 1 = wrong or refuses without reason.
Penalise any statement that contradicts the reference. Do not reward length.
Question: {question}
Reference: {gold_answer}
Answer: {answer}
