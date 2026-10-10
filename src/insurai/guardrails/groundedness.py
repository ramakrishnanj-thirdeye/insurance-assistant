"""V7 groundedness (spec 08 Output layer): the judge role with verify_groundedness.md splits the answer into
atomic claims and marks each supported or not; it also says whether a schedule/wording conflict was
rendered with the precedence sentence.

A verbatim pre-check runs first: a sentence of the answer (citation labels, markdown and list markers
removed) whose normalised text appears in the evidence is supported without a judge call. The judge sees the
settled sentences as "already checked" and judges the rest; when every sentence settles, no judge call is
made. The verdict carries both kinds of claim (`settled_by`).

Runs only on model-written answers to policy_question, coverage_compare and claim_analysis turns. In the
request path only when `guardrails.v7_live` is on for the llm profile; otherwise in the eval (phase 2).
"""

import re
from functools import lru_cache
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from insurai.agent.prompts import load_prompt, template
from insurai.agent.schemas import Evidence
from insurai.agent.synthesize import evidence_blocks
from insurai.guardrails.schemas import GroundedClaim, GroundednessVerdict
from insurai.guardrails.verify import MODEL_WRITTEN_KEYS, strip_labels
from insurai.llm.structured import LLMCall, structured_call
from insurai.tools.messages import guardrails

V7_INTENTS = frozenset({"policy_question", "coverage_compare", "claim_analysis"})
JUDGE_INSTRUCTION = "Check the answer against the evidence."

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_LINE_MARKER = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_MARKDOWN = re.compile(r"[*_`#>]+")
_TRAILING = " .:;,!?"
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([.,;:!?])")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")
_HEADING_LINE = re.compile(r"^\s*[^|\n]{1,60}:\s*$")  # "Also noted:", "Next steps:"
_REVIEW_LINE = re.compile(r"^\s*Reviewer decision:\s", re.IGNORECASE)  # templates.md review_decision


def _is_table_header(lines: list[str], k: int) -> bool:
    """A table row directly followed by a separator row."""
    nxt = next((ln for ln in lines[k + 1 :] if ln.strip()), "")
    return lines[k].lstrip().startswith("|") and bool(_TABLE_SEPARATOR.match(nxt))


def normalise(text: str) -> str:
    """Casefold, markdown and citation labels removed, whitespace collapsed, trailing punctuation stripped."""
    plain = _MARKDOWN.sub(" ", strip_labels(text)).casefold()
    return " ".join(plain.split()).strip(_TRAILING)


def claim_key(text: str) -> str:
    """`normalise` with table pipes tightened, so "| A | B |" and "A | B" compare equal."""
    return re.sub(r"\s*\|\s*", "|", normalise(text)).strip("|")


def _split(answer: str) -> tuple[list[str], set[str]]:
    """(claims, keys of the lines and sentences that are not claims)."""
    fixed = {claim_key(part) for s in fixed_sentences() for part in [s, *_SENTENCE_END.split(s)]}
    skipped = set(fixed)
    lines = answer.splitlines()
    claims: list[str] = []
    for k, line in enumerate(lines):
        if (
            _TABLE_SEPARATOR.match(line)
            or _is_table_header(lines, k)
            or _HEADING_LINE.match(line)
            or _REVIEW_LINE.match(line)
        ):
            skipped.add(claim_key(_LINE_MARKER.sub("", line)))
            continue
        body = _LINE_MARKER.sub("", line)
        for sentence in _SENTENCE_END.split(body):
            text = _SPACE_BEFORE_PUNCT.sub(r"\1", " ".join(strip_labels(sentence).split()))
            if normalise(text) and claim_key(text) not in fixed:
                claims.append(text)
    return list(dict.fromkeys(claims)), skipped


def atomic_claims(answer: str) -> list[str]:
    """The answer's sentences and bullet lines (labels and list markers removed). Not claims (spec 08): fixed
    system sentences (guarantee lead, mandated wording, precedence sentence, specialist-review block), the
    reviewer's decision line, block headings ("Next steps:"), and a markdown table's header and separator
    rows."""
    return _split(answer)[0]


def non_claims(answer: str) -> set[str]:
    """`claim_key`s of what the splitter skips in `answer`; a judge claim matching one is dropped."""
    return _split(answer)[1]


def evidence_text(evidence: list[Evidence]) -> str:
    """Every string in the evidence (summaries, payload values, labels), normalised and joined; model-written
    payload text is not evidence."""
    parts: list[str] = []
    for ev in evidence:
        parts.append(ev.summary)
        parts += _strings({k: v for k, v in ev.payload.items() if k not in MODEL_WRITTEN_KEYS})
    return "\n".join(normalise(p) for p in parts if p)


def verbatim_settled(claims: list[str], evidence: list[Evidence]) -> list[str]:
    """Claims of at least `v7.verbatim_min_words` words whose normalised text is verbatim in the evidence."""
    haystack = evidence_text(evidence)
    min_words = int(guardrails()["v7"]["verbatim_min_words"])
    out = []
    for claim in claims:
        norm = normalise(claim)
        if len(norm.split()) >= min_words and norm in haystack:
            out.append(claim)
    return out


def judge_groundedness(
    answer: str, evidence: list[Evidence], config: RunnableConfig | None = None
) -> tuple[GroundednessVerdict, LLMCall | None]:
    """The pre-check, then one structured judge call on what it left (none when it settled everything).
    Model-written payload text (the dossier narrative) is not evidence."""
    claims = atomic_claims(answer)
    settled = verbatim_settled(claims, evidence)
    verbatim = [GroundedClaim(text=c, supported=True, settled_by="verbatim") for c in settled]
    if claims and len(settled) == len(claims):
        return GroundednessVerdict(claims=verbatim), None
    prompt = load_prompt("verify_groundedness")
    cleaned = [
        ev.model_copy(
            update={"payload": {k: v for k, v in ev.payload.items() if k not in MODEL_WRITTEN_KEYS}}
        )
        for ev in evidence
    ]
    system = prompt.render(
        fixed_sentences="\n".join(f"- {s}" for s in fixed_sentences()),
        settled_sentences="\n".join(f"- {s}" for s in settled) or "- (none)",
        evidence_blocks=evidence_blocks(cleaned),
        answer=answer,
    )
    messages = [SystemMessage(system), HumanMessage(JUDGE_INSTRUCTION)]
    verdict, call = structured_call("judge", GroundednessVerdict, messages, prompt.id, prompt.version, config)
    done = {normalise(c) for c in settled}
    skip = non_claims(
        answer
    )  # the judge splits on its own: a header or system sentence it returns is dropped
    judged = [c for c in verdict.claims if normalise(c.text) not in done and claim_key(c.text) not in skip]
    return verdict.model_copy(update={"claims": verbatim + judged}), call


@lru_cache(maxsize=1)
def fixed_sentences() -> tuple[str, ...]:
    """System sentences that are not claims: the guarantee lead, the mandated wording, the precedence
    sentence, the customer specialist-review block and the abstention template's wording."""
    g = guardrails()
    lead = template("guarantee_lead", label="").strip()  # "I can't promise an outcome. Final decision …"
    return (
        lead,
        g["no_guarantee"]["mandated_wording"],
        g["conflict_rendering"]["precedence_sentence"],
        template("specialist_review_customer"),
        g["refusals"]["LOW_CONFIDENCE"],
        template("abstain_heading"),
    )


def _strings(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list | tuple):
        return [s for v in value for s in _strings(v)]
    return [value] if isinstance(value, str) else []
