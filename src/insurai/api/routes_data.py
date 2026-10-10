"""Health, coverage matrix, claim dossier and eval reports (spec 09 Endpoints)."""

import json
import re
from importlib.metadata import PackageNotFoundError, version
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from insurai import db
from insurai.agent.prompts import PROMPTS_DIR, load_prompt
from insurai.api.identity import Identity, ensure_matches, identity
from insurai.api.problems import ApiError
from insurai.api.schemas import EvalReportSummary, Health
from insurai.eval.datasets import question_index
from insurai.knowledge import coverage
from insurai.observability import get_logger
from insurai.retrieval import search
from insurai.rules.schemas import ClaimAssessment
from insurai.settings import get_settings
from insurai.tools.access import load_personas
from insurai.tools.knowledge import CoverageCells
from insurai.tools.registry import TOOLS
from insurai.tools.schemas import AccessDenied, NotFound, ToolContext

log = get_logger(__name__)

router = APIRouter(tags=["data"])
Ident = Annotated[Identity, Depends(identity)]

# write_report names: <suite>_<UTC stamp> or slice-<a+b>_<UTC stamp>; plus baseline.json (make eval-baseline)
RUN_ID = re.compile(r"^(?:[a-z]+|slice-[a-z0-9_+]+)_\d{8}T\d{6}Z$|^baseline$")
PACKAGES = ("insurai", "langgraph", "langchain-core", "fastapi", "qdrant-client", "duckdb")


def _ctx(ident: Identity, trace_id: str) -> ToolContext:
    return ToolContext(
        persona=ident.persona,
        principal_id=ident.tool_principal,
        as_of=get_settings().as_of_date,
        trace_id=trace_id,
    )


def _raise_for(result: Any) -> None:
    if isinstance(result, NotFound):
        raise ApiError(404, "NOT_FOUND", result.message)
    if isinstance(result, AccessDenied):
        raise ApiError(403, "ACCESS_DENIED", result.message)


# --- health -----------------------------------------------------------------------------------------------


def _warehouse() -> str:
    try:
        with db.connect(read_only=True) as con:
            con.execute("SELECT count(*) FROM gold.claim_facts").fetchone()
        return "ok"
    except Exception as exc:
        return f"error: {exc}"


def _qdrant() -> str:
    try:
        n = search.collection_count(get_settings().retrieval.collection_policies)
        return "ok" if n > 0 else "error: policy collection is empty (run make index)"
    except Exception as exc:
        return f"error: {exc}"


def _versions() -> dict[str, Any]:
    packages: dict[str, str] = {}
    for name in PACKAGES:
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = "unknown"
    prompts = {}
    for path in sorted(PROMPTS_DIR.glob("*.md")):
        try:
            prompts[path.stem] = load_prompt(path.stem).version
        except ValueError:
            continue
    return {"packages": packages, "prompts": prompts}


@router.get("/health", response_model=Health)
def health() -> Health:
    settings = get_settings()
    warehouse, qdrant = _warehouse(), _qdrant()
    return Health(
        status="ok" if warehouse == qdrant == "ok" else "degraded",
        warehouse=warehouse,
        qdrant=qdrant,
        llm_profile=settings.llm.profile,
        as_of=settings.as_of_date,
        coverage_status=coverage.load_coverage(coverage.COVERAGE_FILE).status,
        versions=_versions(),
    )


# --- coverage and dossier ---------------------------------------------------------------------------------


@router.get("/coverage-matrix", response_model=CoverageCells)
def coverage_matrix(ident: Ident, product: str | None = None, attribute: str | None = None) -> CoverageCells:
    result = TOOLS["get_coverage"](_ctx(ident, "api-coverage"), product=product, attribute=attribute)
    _raise_for(result)
    return result  # type: ignore[no-any-return]


@router.get("/claims/{claim_id}/dossier", response_model=ClaimAssessment)
def claim_dossier(
    claim_id: str,
    ident: Ident,
    narrate: bool = False,
    persona: Annotated[str | None, Query()] = None,
    principal_id: Annotated[str | None, Query()] = None,
) -> ClaimAssessment:
    ensure_matches(ident, persona, principal_id)
    result = TOOLS["analyze_claim"](
        _ctx(ident, f"api-dossier-{claim_id}"), claim_id=claim_id, narrate=narrate
    )
    _raise_for(result)
    return result  # type: ignore[return-value]


# --- eval reports -----------------------------------------------------------------------------------------


def eval_reader(ident: Ident) -> Identity:
    """Eval reports are staff-only (config/personas.yaml can_read_eval_reports); a customer gets 403."""
    if not load_personas()[ident.persona].can_read_eval_reports:
        raise ApiError(403, "ACCESS_DENIED", f"Persona {ident.persona} cannot read eval reports.")
    return ident


EvalReader = Annotated[Identity, Depends(eval_reader)]


def _headline(report: dict[str, Any]) -> dict[str, dict[str, float | int]]:
    """Scalar metrics per slice (fast/full) or per retrieval config (ablation)."""
    out: dict[str, dict[str, float | int]] = {}
    for section in ("slices", "configs"):
        for name, body in (report.get(section) or {}).items():
            metrics = body.get("metrics", body) if isinstance(body, dict) else {}
            out[name] = {
                k: v for k, v in metrics.items() if isinstance(v, int | float) and not isinstance(v, bool)
            }
    return out


def _load_report(run_id: str) -> dict[str, Any]:
    path = get_settings().paths.eval_reports / f"{run_id}.json"
    if not RUN_ID.fullmatch(run_id) or not path.is_file():
        raise ApiError(404, "NOT_FOUND", f"No eval report {run_id}.")
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


@router.get("/eval/reports", response_model=list[EvalReportSummary])
def eval_reports(ident: EvalReader) -> list[EvalReportSummary]:
    reports = []
    for path in sorted(get_settings().paths.eval_reports.glob("*.json"), reverse=True):
        if not RUN_ID.fullmatch(path.stem):
            continue
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            log.warning("skipping unreadable eval report %s", path.name)
            continue
        reports.append(
            EvalReportSummary(
                run_id=path.stem,
                suite=str(report.get("suite", path.stem.split("_")[0])),
                created_at=report.get("created_at"),
                git_sha=report.get("git_sha"),
                baseline_of=report.get("baseline_of"),
                headline=_headline(report),
            )
        )
    return sorted(reports, key=lambda r: r.created_at or "", reverse=True)


@router.get("/eval/reports/{run_id}")
def eval_report(run_id: str, ident: EvalReader) -> dict[str, Any]:
    """The raw report plus `questions` (item id -> question text) for the dashboard's failed-items table."""
    report = _load_report(run_id)
    ids = {
        str(item["id"])
        for body in (report.get("slices") or {}).values()
        if isinstance(body, dict)
        for item in body.get("items", [])
        if isinstance(item, dict) and "id" in item
    }
    index = question_index()
    return report | {"questions": {i: index[i] for i in sorted(ids) if i in index}}
