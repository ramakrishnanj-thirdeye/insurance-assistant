# Insurance assistant — every workflow is one make target (see CLAUDE.md)
# Python UTF-8 mode: on Windows the default text encoding is cp1252
export PYTHONUTF8 := 1

.PHONY: setup data rules index coverage-draft mcp mcp-smoke api ui phoenix test test-llm test-all lint fmt \
        eval-fast eval eval-ablation eval-baseline demo-check all

setup:
	uv sync

data:
	uv run python -m insurai.ingest.build_warehouse
	$(MAKE) rules

rules:
	uv run python -m insurai.rules.materialise

index:
	uv run python -m insurai.retrieval.index

coverage-draft:
	uv run python -m insurai.knowledge.coverage --draft

mcp:
	uv run python -m insurai.mcp_server --transport streamable-http

mcp-smoke:
	uv run python -m insurai.mcp_server.smoke

api:
	uv run uvicorn insurai.api.main:app --host 127.0.0.1 --port 8000 --reload

ui:
	uv run streamlit run ui/app.py

phoenix:
	uv run phoenix serve

test:
	uv run pytest -m "not llm and not slow" -q

test-llm:
	uv run pytest -m llm -q

test-all:
	uv run pytest -q

lint:
	uv run ruff check .
	uv run ruff format --check .

fmt:
	uv run ruff format .
	uv run ruff check --fix .

eval-fast:
	uv run python -m insurai.eval.run --suite fast --gate

eval:
	uv run python -m insurai.eval.run --suite full

eval-ablation:
	uv run python -m insurai.eval.run --suite ablation

eval-baseline:
	uv run python -m insurai.eval.baseline --promote-latest

demo-check:
	uv run python -m insurai.eval.demo_check

all: setup data index
