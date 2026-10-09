"""V7 groundedness (spec 08 Output layer): the judge role with verify_groundedness.md splits the answer into
atomic claims and marks each supported or not; it also says whether a schedule/wording conflict was
rendered with the precedence sentence.

Runs only on model-written answers to policy_question, coverage_compare and claim_analysis turns. In the
request path only when `guardrails.v7_live` is on for the llm profile; otherwise in the eval (phase 2).
"""

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from insurai.agent.prompts import load_prompt, template
from insurai.agent.schemas import Evidence
from insurai.agent.synthesize import evidence_blocks
from insurai.guardrails.schemas import GroundednessVerdict
from insurai.guardrails.verify import MODEL_WRITTEN_KEYS
from insurai.llm.structured import LLMCall, structured_call
from insurai.tools.messages import guardrails

V7_INTENTS = frozenset({"policy_question", "coverage_compare", "claim_analysis"})
JUDGE_INSTRUCTION = "Check the answer against the evidence."


def judge_groundedness(
    answer: str, evidence: list[Evidence], config: RunnableConfig | None = None
) -> tuple[GroundednessVerdict, LLMCall]:
    """One structured judge call. Model-written payload text (the dossier narrative) is not evidence."""
    prompt = load_prompt("verify_groundedness")
    g = guardrails()
    lead = template("guarantee_lead", label="").strip()  # "I can't promise an outcome. Final decision …"
    fixed = [lead, g["no_guarantee"]["mandated_wording"], g["conflict_rendering"]["precedence_sentence"]]
    cleaned = [
        ev.model_copy(
            update={"payload": {k: v for k, v in ev.payload.items() if k not in MODEL_WRITTEN_KEYS}}
        )
        for ev in evidence
    ]
    system = prompt.render(
        fixed_sentences="\n".join(f"- {s}" for s in fixed),
        evidence_blocks=evidence_blocks(cleaned),
        answer=answer,
    )
    messages = [SystemMessage(system), HumanMessage(JUDGE_INSTRUCTION)]
    return structured_call("judge", GroundednessVerdict, messages, prompt.id, prompt.version, config)
