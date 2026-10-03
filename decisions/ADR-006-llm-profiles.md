# ADR-006 Provider-agnostic LLM profiles, api-lite by default
Status: accepted (open decision #1 defaulted)

**Context.** Cost must stay minimal, demos must be reliable, and fully offline runs should be possible.
**Decision.** All LLM access goes through `insurai.llm.get_model(role)` with roles generator, small and judge, resolved from `settings.llm.profile`: `local` (Ollama Qwen3 8B/14B), `api-lite` (Claude Haiku 4.5, judge Claude Sonnet 5.5; default), `api-quality` (Claude Sonnet 5.5, judge Claude Opus 5.5).
**Consequences.** Swap models with one setting; the judge is always a different model from the generator. Structured-output and tool-calling quality on local models must be checked by the eval suite before demoing on them.
**Alternatives.** Hard-coded SDK calls; a single model for generation and judging (self-preference bias).
