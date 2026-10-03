# Insurance Claims & Policy Intelligence Assistant

Local-first PoC: answers claim and policy questions from the right system of record — SQL for facts,
hybrid RAG for policy clauses, a rules engine for claim judgments — with a glass-box trace and an eval gate.
Specs in `specs/` are the contract; decisions in `decisions/`; progress in `tasks.md`.

## Commands
| Command | Does |
| --- | --- |
| `make setup` | `uv sync` (Python 3.12) |
| `make data` | CSVs → `data/warehouse.duckdb` + DQ report, then `make rules` |
| `make index` | Policy chunks + SQL examples → Qdrant (`data/qdrant`) |
| `make test` | Unit + integration tests, no LLM calls |
| `make test-llm` | Tests marked `llm` (needs ANTHROPIC_API_KEY or Ollama) |
| `make lint` / `make fmt` | ruff check / ruff format + fix |
| `make eval-fast` | Milestone gate (spec 11) |
| `make eval` / `make eval-ablation` | Full suite / retrieval ablation |
| `make api` / `make ui` / `make mcp` / `make phoenix` | FastAPI :8000 / Streamlit / MCP over HTTP / tracing UI |
| `make demo-check` | Headless run-of-show (spec 10) |

## Repository map
`config/` settings, semantic model, rules, coverage matrix, required documents, glossary, guardrails, personas, prompts ·
`src/insurai/` `ingest/ db.py knowledge/ retrieval/ semantic/ tools/ rules/ agent/ guardrails/ llm/ mcp_server/ api/ eval/ observability/` ·
`ui/` Streamlit · `eval/` datasets and reports · `tests/` mirrors `src/insurai/` · `specs/reference/` tested reference SQL and a throwaway prototype.

## Hard rules
1. **Facts come from tools, never from model memory.** Any claim, policy, customer or hospital value in an answer must come from a tool result in the current turn.
2. **SQL safety.** Generated SQL goes through `semantic.sql.validate`; runtime DuckDB connections are read-only; tool SQL is parameterised, never string-built from user input.
3. **Access control lives in code** (`config/personas.yaml` enforced in `tools/`), never in prompts. Interactions are owned via their claim (`claim_owner_id`), never `logged_customer_id`.
4. **Every tool result has `sources`**, and the synthesizer may only cite labels present in evidence.
5. **Time is `settings.as_of_date` (2026-10-01).** Never call `date.today()` or `datetime.now()` in business logic.
6. **Config over code.** Thresholds, rules, required documents, coverage, glossary, prompts and refusal texts live in `config/`.
7. **Never modify `data/raw/`, never repair anomalies.** Flag them (ADR-007).
8. **All LLM calls go through `insurai.llm.get_model(role)`** with role generator, small or judge. No direct provider clients.
9. **No secrets in code or config.** Keys come from `.env` (see `.env.example`).
10. **Tests ship with every change.** Name tests after acceptance criteria: `test_AC_04_05_drunk_driving_hits_mpc_exclusions`.

## Conventions
Python 3.12 · type hints everywhere · Pydantic v2 models in each package's `schemas.py` · stdlib `logging` via `insurai.observability.get_logger`, no `print` ·
ruff (line length 110) · pytest markers `unit`, `integration` (needs warehouse/index), `llm`, `slow` · small modules, pure functions where possible ·
Indian rupee formatting via `insurai.formatting.inr()` (₹5,00,000) · citation labels only via `insurai.tools.schemas.SourceRef`.

## Windows development machine
- The developer runs native Windows (PowerShell, Git Bash inside Claude Code). Paths may contain spaces: never build shell commands by string-concatenating paths.
- Always pass `encoding="utf-8"` when reading or writing text files; the Makefile also sets `PYTHONUTF8=1`.
- Stop `make api`, `make mcp` and `make ui` before `make data` or `make index`: Windows cannot replace a DuckDB file that is open, and Qdrant local storage is locked by one process (spec 04, `get_qdrant`).
- Use `pathlib.Path` everywhere; no hard-coded `/` separators in file paths.

## Workflow for a spec (use `/implement-spec specs/<file>`)
1. Read the spec, the ADRs it names, and the configs it consumes. Ask before changing an interface another spec depends on.
2. Plan: files to create, tests mapped to AC IDs, risks. Wait for approval.
3. Write failing tests from the acceptance criteria, then implement until green.
4. `make lint test`; if the spec has eval hooks, `make eval-fast`.
5. Tick the ACs in the spec, update `tasks.md`, commit as `feat(spec-NN): <summary>`.

## Definition of done
Lint clean · `make test` green · `make eval-fast` holds or improves · spec ACs ticked · no TODOs without an issue line in `tasks.md`.

## Data traps (read before touching data or rules code)
- Only 21,625 of 120,000 claims fall inside their policy period; most rules fire on most claims. This is expected.
- `policy_status` is stale: 50,811 "Active" policies have ended. Use `effective_status`.
- `customer_interactions.customer_id` ≠ claim owner on 179,999 of 180,000 rows (ADR-008).
- Document status is independent of claim status; never infer one from the other.
- 10 of 15 policy sections are identical across products: retrieval without a product filter returns the wrong product.
- Two Wheeler Secure says "drunk driving"; Motor Protect Comprehensive says "intoxication".
- 300 customer names cover 50,000 customers: never resolve a customer by name alone.
- Every policy lasts 365 days; 730-day waiting periods can never be completed within one policy.
