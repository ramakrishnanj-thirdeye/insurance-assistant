"""Qdrant embedded client with the one-process lock handled (spec 04, ADR-002).

Local mode locks its storage folder to one process. Readers (API, MCP server, eval runner) fall back to a
private copy of the index, which is tiny and read-only at runtime; the writer (`make index`) never does.
"""

import atexit
import shutil
import tempfile
from pathlib import Path

from qdrant_client import QdrantClient

from insurai.observability import get_logger
from insurai.settings import get_settings

log = get_logger(__name__)

LOCKED = "already accessed by another instance"
STOP_SERVICES = "stop make api / make mcp / make ui, then rerun make index"


class IndexLockedError(RuntimeError):
    """The writer found the index open in another process."""


def get_qdrant(read_only: bool = True, path: Path | None = None) -> QdrantClient:
    """Open the embedded index at `path` (default `paths.qdrant_path`).

    read_only=True: if another process holds the folder, open a per-process copy instead.
    read_only=False: fail with the stop-the-services message instead.
    """
    path = path or get_settings().paths.qdrant_path
    if read_only and not path.exists():
        raise FileNotFoundError(f"No Qdrant index at {path}: run make index first")
    try:
        return QdrantClient(path=str(path))
    except RuntimeError as exc:
        if LOCKED not in str(exc):
            raise
        if not read_only:
            raise IndexLockedError(
                f"Qdrant index at {path} is open in another process: {STOP_SERVICES}"
            ) from exc
    return QdrantClient(path=str(_private_copy(path)))


def _private_copy(path: Path) -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="insurai-qdrant-"))
    # Windows may still hold handles on the copy at exit, so cleanup is best effort.
    atexit.register(shutil.rmtree, tmp, ignore_errors=True)
    copy = tmp / path.name
    shutil.copytree(path, copy, ignore=shutil.ignore_patterns(".lock"))
    log.warning("Qdrant index %s is locked by another process; reading a private copy at %s", path, copy)
    return copy
