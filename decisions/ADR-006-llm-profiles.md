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

**Amendment 2026-10-08 (sql role).** An optional fourth role, `sql`, is used only by `semantic.sql.generate_sql`
(text-to-SQL, spec 02). A profile that does not configure it falls back to its `generator` (`ROLE_FALLBACK` in
settings), so api-lite and api-quality are unchanged. Measured on the 15-item analytics slice with 30 verified
queries as few-shots (analytics slice run in its own phase): qwen3:8b exec_accuracy 0.80, repair_rate 0.067,
p50 9.9 s, p95 26.4 s; qwen2.5-coder:7b exec_accuracy 0.80, repair_rate 0.0, p50 6.7 s, p95 43.9 s (8.8 s once
loaded). Equal accuracy, so the local profile keeps qwen3:8b: a second local model would make Ollama swap models
inside every analytics turn (planner → sql → synthesize). The coder stays a commented option in settings.yaml.
