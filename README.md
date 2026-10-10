# Insurance Claims & Policy Intelligence Assistant (PoC)

A local-first, glass-box assistant for insurance operations. It answers each question from its system of
record, never from model memory:
- **SQL** for claim, policy, customer and hospital facts (DuckDB warehouse).
- **Hybrid RAG** for policy clauses (BM25 + dense, product filter, cross-encoder rerank, Qdrant embedded).
- A **deterministic rules engine** for claim judgments (R01–R12, consistency flags C1–C4, document checklist).

Every answer carries citations and a trace of how it was produced. A verifier checks it before it is shown:
citations real, facts cited, numbers traced to data, no promises, no personal data, hidden fields protected,
groundedness. An evaluation suite with a baseline gate measures all of this.

Three personas: **customer** (own records only, enforced in code), **claims_agent** and **supervisor**
(analytics, consistency flags). The as-of date is fixed at 2026-10-01.

## Quickstart (Windows, PowerShell or Git Bash)
Prerequisites:
- Python 3.12 and [uv](https://docs.astral.sh/uv/).
- `make` on PATH (`winget install ezwinports.make`).
- [Ollama](https://ollama.com) with `qwen3:8b` and `llama3.1:8b` (the judge) for the `local` profile, or an
  Anthropic API key for `api-lite`.
- About 3 GB of disk for models and indexes.

```bash
# 1. The dataset goes into data/raw/ (layout in data/raw/README.md); it is never modified.
cp .env.example .env          # set INSURAI__LLM__PROFILE=local until an ANTHROPIC_API_KEY exists
make setup                    # uv sync
make data                     # CSVs -> data/warehouse.duckdb, data-quality report, rule results
make index                    # policy chunks + SQL examples -> Qdrant (data/qdrant)
make demo                     # warm the model, API on :8000 (no --reload), UI on :8501
make demo-check               # in a second terminal: the run-of-show, headless (14 steps)
```

The run-of-show, with the persona, the expected outcome and a fallback for each step, is in
[docs/DEMO.md](docs/DEMO.md). Stop `make demo` (Ctrl+C) before `make data` or `make index`: Windows locks the
DuckDB file and the Qdrant store.

Other targets: `make test` (no LLM calls), `make lint`, `make eval-fast` (milestone gate), `make eval`
(full suite), `make eval-ablation`, `make mcp`, `make phoenix` (tracing UI). The full list is in CLAUDE.md.

## Architecture
Full architecture doc: https://claude.ai/code/artifact/5d204a71-2acf-420b-8022-a759e17ddeec

In short:
- **Agent.** A LangGraph planner routes each question (ADR-003):
  - A fast path for claim status and greetings, with no LLM call.
  - Otherwise a planner LLM splits the question into intents, handled in parallel by:
    - **claim_tools:** parameterised SQL tools behind persona checks.
    - **policy_rag:** hybrid search with a product filter.
    - **analytics_sql:** text-to-SQL over a semantic model, through a validator, read-only.
    - **claim_dossier:** the rules engine, with a human-review interrupt.
- **Answering.** `synthesize` drafts a cited answer and streams it through a gate that never streams a promise;
  `verify` runs V1–V7 and retries once, then abstains.
- **Interfaces.** FastAPI with SSE and resumable threads (spec 09), Streamlit (spec 10), and an MCP server
  exposing the same 11 tools (spec 05).
- **Config over code.** Rules, thresholds, coverage, required documents, glossary, prompts, refusals and UI
  labels all live in `config/`. Decisions are in `decisions/ADR-001…009`; specs in `specs/00…11` are the
  contract.

UI pages:
- **Chat** (everyone). Streamed answers with citations and a trace in plain language: steps, named answer
  checks, clauses, rules, SQL and model calls, with the raw events under "Engineer details". The review card
  shows blockers and next best actions.
- **Claim Dossier** (staff). The rule checklist with severity colours, documents, interactions, next best
  actions and consistency flags (supervisor), and an optional narrative with the customer message draft.
- **Eval Dashboard** (staff). Metrics against targets, open gates, judge calibration, retrieval ablation,
  history and failed items.

## Results
Baseline: the full suite on the local profile (qwen3:8b; judge llama3.1:8b), git 6e6bb10, 2026-10-09
(`eval/reports/baseline.md`). Counts are "k of n" with 95% Wilson intervals.

| Area | Metric | Result | Target |
| --- | --- | --- | --- |
| Policy clauses | recall@5 | 36 of 36 (0.90–1.00), MRR 0.92 | ≥ 0.95 |
| Retrieval latency | p95 | 144 ms | ≤ 800 ms |
| SQL facts | accuracy | 20 of 20 (0.84–1.00) | 1.0 |
| Routing | intent accuracy | 93 of 96 (0.91–0.99); entities 96 of 96 | ≥ 0.95 |
| End to end, SQL facts | gold in answer | 19 of 19 (0.83–1.00) | — |
| Claim analysis | rule status, documents, consistency, review pause | 10 of 10 each | 1.0 |
| Claim analysis | blocker mentioned | 36 of 36 | 1.0 |
| Adversarial | handled | 15 of 15 (0.80–1.00), every category | ≥ 0.95 |
| Adversarial | refusal correct / guarantee handled | 7 of 7 / 2 of 2 | 1.0 |
| Whole suite | false refusals | 0 of 44 (0.00–0.08) | ≤ 0.05 |
| Analytics | execution accuracy | 10 of 15 (0.42–0.85) | ≥ 0.90 (**open**) |
| Policy answers | correctness (judge) | 31 of 36 (0.71–0.94) | ≥ 0.90 (advisory) |
| Policy answers | citation accuracy | 33 of 36 (0.78–0.97) | ≥ 0.95 (**open**) |

Retrieval ablation (`make eval-ablation`): product precision@5 rises from 0.69 (dense only) and 0.75 (hybrid)
to 1.0 once the product filter is on (configs D and E); recall@5 is 1.0 throughout.

## Open gates, stated honestly
- **Analytics execution accuracy is 10 of 15 on qwen3:8b**, below 0.90 (AC-02-07). The misses are extra columns
  and filters the question did not ask for. Re-measure on api-lite when a key exists.
- **The judge is uncalibrated.** llama3.1:8b agrees with a human on 6 of 10 answers, below the 80% bar
  (AC-11-06). Correctness and faithfulness are therefore reported as **advisory**, not gated.
  Human-verified correctness on the calibration sample is 8 of 10.
- **Faithfulness must be re-baselined.** The V7 definition changed on 2026-10-10 (AC-11-23), so the baseline's
  faithfulness counts are not comparable with new runs.
- **Policy-answer citation accuracy is 33 of 36**, below 0.95.
- **Deferred under the 3-day scope:**
  - the Leakage Radar and Coverage Matrix pages and `/audit/*`
  - the LLM query rewrite and ablation config F
  - LLM injection confirmation
  - the sum-insured and co-pay conflict concepts
  - growing several datasets to their spec sizes

  The full list is in tasks.md.
- **Data is synthetic.** Counts such as 20,903 claims paid in full despite a co-pay demonstrate the capability,
  not findings about a real portfolio.

## MCP server and Claude Desktop
`make mcp` serves the tools over streamable HTTP on `http://127.0.0.1:8765/mcp`; `make mcp-smoke` checks the
stdio server against the in-process tools. The persona is fixed per server process: `INSURAI_PERSONA`
(`claims_agent` by default, `supervisor`, or `customer` with `INSURAI_PRINCIPAL_ID=CUST######`).

Claude Desktop on this machine: add the following to `%APPDATA%\Claude\claude_desktop_config.json`, then
restart Claude Desktop. Use forward slashes; the space in the path is fine inside the JSON string.
```json
{
  "mcpServers": {
    "insurai": {
      "command": "uv",
      "args": [
        "run", "--directory", "C:/Users/ramak/Documents/LearnBay Project/insurance-assistant",
        "python", "-m", "insurai.mcp_server", "--transport", "stdio"
      ],
      "env": {"INSURAI_PERSONA": "claims_agent", "INSURAI__LLM__PROFILE": "local", "PYTHONUTF8": "1"}
    }
  }
}
```
Then ask Claude Desktop "What is the status of CLM300210?"; it should call `get_claim` and answer "Approved"
(AC-05-09, a manual check). If `uv` is not found, put the full path to `uv.exe` in `command`.

## Working with Claude Code
`CLAUDE.md` holds the standing instructions: commands, hard rules, conventions and data traps. Implement or
change a spec with `/implement-spec specs/<file>`. Specs are authoritative: change the spec first, then the
code. Progress and open issues are tracked in `tasks.md`.
