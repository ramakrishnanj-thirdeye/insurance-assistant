# Insurance Claims & Policy Intelligence Assistant (PoC)

A local-first, glass-box assistant for insurance operations. It answers each question from its system of
record — SQL for claim and policy facts, hybrid RAG for policy clauses, a deterministic rules engine for
claim judgments — and proves its accuracy with an evaluation suite.

Architecture doc: https://claude.ai/code/artifact/5d204a71-2acf-420b-8022-a759e17ddeec

## Status
Spec pack only. Code is generated milestone by milestone with Claude Code (see "Working with Claude Code").

## Windows notes
Developed on native Windows with PowerShell. Set `PYTHONUTF8=1` for your user once, keep `make` on PATH
(`winget install ezwinports.make`), and stop the API, MCP server and UI before `make data` or `make index`.

## Prerequisites
- Python 3.12 and [uv](https://docs.astral.sh/uv/)
- An Anthropic API key for the default `api-lite` profile, or [Ollama](https://ollama.com) with `qwen3:8b` and `qwen3:14b` for the `local` profile
- ~3 GB disk for models and indexes

## Quick start (once M1–M4 are implemented)
```bash
unzip insurance_genai_cdataset.zip -d data/raw     # see data/raw/README.md for the expected layout
cp .env.example .env                                # add ANTHROPIC_API_KEY
make setup data index
make phoenix &                                      # tracing UI
make api &                                          # http://127.0.0.1:8000/docs
make ui                                             # Streamlit
```

## What is already here
| Path | Contents |
| --- | --- |
| `CLAUDE.md` | Standing instructions for Claude Code: commands, hard rules, conventions, data traps |
| `specs/00…11` | One spec per component: goal, interfaces, behaviour, acceptance criteria, eval hooks |
| `specs/reference/warehouse.sql` | Bronze → silver → gold SQL, tested on the dataset (DuckDB 1.5) |
| `specs/reference/prototype_build_and_rules.py` | Throwaway prototype proving the configs and rules end to end |
| `decisions/ADR-001…008` | Architecture decisions and the defaults taken for the open decisions |
| `tasks.md` | Milestones M0–M8 with exit gates |
| `config/` | Settings, semantic model (14 verified queries, tested), rules R01–R12, coverage matrix (draft, from the 10 wordings), required documents, glossary, guardrails, personas, prompt drafts |
| `eval/datasets/` | The 5 seed questions (header fixed, gold sections added) and 3 hand-checked demo claims |
| `.claude/` | `/implement-spec` command and a ruff post-edit hook |

Check the prototype yourself (needs `duckdb` and `pyyaml`):
```bash
python specs/reference/prototype_build_and_rules.py data/raw CLM300210 CLM300500 CLM300101
```

## Working with Claude Code
1. Open the repo in Claude Code. It reads `CLAUDE.md` automatically.
2. Start with M0 in `tasks.md`, then run `/implement-spec specs/01-data-warehouse.md`.
3. Review the plan it proposes (files, AC-to-test map, ambiguities) before it writes code.
4. Each milestone ends with its gate in `tasks.md`; from M2 on, `make eval-fast` is part of the gate.
5. Keep specs authoritative: if behaviour must change, edit the spec first, then implement.

Verify `.claude/settings.json` (permission rule syntax, hook format) against the current Claude Code docs
before relying on it: https://docs.claude.com/en/docs/claude-code/overview

## Claude Desktop (after M3)
Add to `claude_desktop_config.json`:
```json
{"mcpServers": {"insurai": {"command": "uv",
  "args": ["run", "--directory", "/ABSOLUTE/PATH/insurance-assistant", "python", "-m", "insurai.mcp_server", "--transport", "stdio"],
  "env": {"INSURAI_PERSONA": "claims_agent"}}}}
```

## Proposed defaults to confirm
LLM profile api-lite · interactions joined on claim_id · required-documents matrix · keep and flag anomalies ·
as-of date 2026-10-01 · Critical Care Elite covers Cardiac Procedure only · deductible before co-pay ·
three personas · Qdrant embedded (pending spike). See `tasks.md` → Open decisions.
