"""fastembed models (ONNX, CPU), cached under paths.models_dir.

At runtime the models load from their cached snapshot directory only (no network); `make index` calls
`allow_downloads()` first, so a service or a test never downloads models. Loading from the snapshot path,
not `local_files_only`, because huggingface_hub rejects fastembed's partial snapshots (e.g. Qdrant/bm25
fetches a subset of the repo's stopword files) as incomplete when offline.
"""

from functools import lru_cache
from pathlib import Path
from typing import Any

from fastembed import SparseTextEmbedding, TextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder

from insurai.observability import get_logger
from insurai.settings import get_settings

log = get_logger(__name__)

_downloads_allowed = False


def allow_downloads() -> None:
    global _downloads_allowed
    _downloads_allowed = True


@lru_cache(maxsize=1)
def dense_model() -> TextEmbedding:
    return TextEmbedding(**_load_args(TextEmbedding, get_settings().retrieval.dense_model))


@lru_cache(maxsize=1)
def sparse_model() -> SparseTextEmbedding:
    return SparseTextEmbedding(**_load_args(SparseTextEmbedding, get_settings().retrieval.sparse_model))


@lru_cache(maxsize=1)
def reranker() -> TextCrossEncoder:
    return TextCrossEncoder(**_load_args(TextCrossEncoder, get_settings().retrieval.reranker_model))


def _load_args(cls: Any, model_name: str) -> dict[str, Any]:
    settings = get_settings()
    cache_dir = settings.paths.models_dir
    args: dict[str, Any] = {
        "model_name": model_name,
        "cache_dir": str(cache_dir),
        "threads": settings.retrieval.onnx_threads,
    }
    if not _downloads_allowed:
        args["specific_model_path"] = str(snapshot_dir(cls, model_name, cache_dir))
    return args


def snapshot_dir(cls: Any, model_name: str, cache_dir: Path) -> Path:
    """The cached snapshot of a fastembed model; FileNotFoundError when `make index` has not fetched it."""
    sources = [m["sources"] for m in cls.list_supported_models() if m["model"] == model_name]
    if not sources or not sources[0].get("hf"):
        raise ValueError(f"{model_name!r} is not a Hugging Face-hosted {cls.__name__} model")
    repo_dir = cache_dir / f"models--{sources[0]['hf'].replace('/', '--')}"
    ref = repo_dir / "refs" / "main"
    if not ref.exists():
        raise FileNotFoundError(f"{model_name} is not cached in {cache_dir}: run make index first")
    path = repo_dir / "snapshots" / ref.read_text(encoding="utf-8").strip()
    if not path.is_dir():
        raise FileNotFoundError(f"{model_name} snapshot missing at {path}: run make index first")
    return path


def models_cached() -> bool:
    """True when all three configured models load from the local cache (loading them as a side effect)."""
    try:
        dense_model()
        sparse_model()
        reranker()
    except Exception as exc:  # fastembed raises various errors for a missing local model
        log.info("fastembed models not cached in %s: %s", get_settings().paths.models_dir, exc)
        return False
    return True
