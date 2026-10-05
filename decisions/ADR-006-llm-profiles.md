# ADR-006 Provider-agnostic LLM profiles, api-lite by default
Status: accepted (open decision #1 defaulted)

**Context.** Cost must stay minimal, demos must be reliable, and fully offline runs should be possible.
**Decision.** All LLM access goes through `insurai.llm.get_model(role)` with roles generator, small and judge, resolved from `settings.llm.profile`: `local` (Ollama: generator and small Qwen3 8B, judge Llama 3.1 8B), `api-lite` (Claude Haiku 4.5, judge Claude Sonnet 5.5; default), `api-quality` (Claude Sonnet 5.5, judge Claude Opus 5.5).
**Consequences.** Swap models with one setting; the judge is always a different model from the generator. Structured-output and tool-calling quality on local models must be checked by the eval suite before demoing on them.
**Alternatives.** Hard-coded SDK calls; a single model for generation and judging (self-preference bias).

**Amendment 2026-10-06 (local judge).** The local judge is `llama3.1:8b`, not `qwen3:14b`: the judge comes from a
different model family than the generator, which judges more independently than a bigger model of the same family,
and it runs at about the generator's speed (~4.9 GB). It will be calibrated against hand scores in M7
(judge_calibration.jsonl, spec 11). Eval runners make every judge call in a second phase after all answers are
generated, so Ollama does not swap models on every item.
