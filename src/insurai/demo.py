"""`make demo` (spec 10, AC-10-16): warm the local models, start the API without --reload, then the UI.

1. When the active profile uses Ollama, load each demo model once with `keep_alive`, so the first demo
   question does not pay the cold load (an empty prompt only loads the model).
2. Start uvicorn without `--reload` (single worker, ADR-009) and wait for /health.
3. Start Streamlit (`.streamlit/config.toml` keeps it headless) and open the browser.
Ctrl+C stops both. Commands are argument lists, never shell strings: the repo path contains spaces.
"""

import argparse
import subprocess
import sys
import time
import webbrowser
from collections.abc import Callable
from urllib.parse import urlsplit

import httpx

from insurai.observability import get_logger
from insurai.settings import ROOT, Settings, get_settings, v7_live_now

log = get_logger(__name__)

DEMO_ROLES = ("generator", "small", "sql")  # the judge only runs live when V7 is on (guardrails.v7_live)
UI_PORT = 8501
HEALTH_TIMEOUT_S = 120.0
WARMUP_TIMEOUT_S = 600.0
STALE_API_HINT = (
    "Something already answers on {url}. Stop the stale API first: PowerShell "
    "`Get-NetTCPConnection -LocalPort {port} -State Listen | Select-Object OwningProcess`, then "
    "`Stop-Process -Id <pid>`; Git Bash `netstat -ano | findstr :{port}`, then `taskkill /PID <pid> /F`."
)


def demo_models(settings: Settings, v7_live: bool) -> list[tuple[str, str | None]]:
    """Distinct (model, keep_alive) pairs of the Ollama roles the demo calls, in role order."""
    roles = settings.llm.profiles[settings.llm.profile]
    wanted = [*DEMO_ROLES, "judge"] if v7_live else list(DEMO_ROLES)
    out: dict[str, str | None] = {}
    for role in wanted:
        spec = roles.get(role)  # type: ignore[call-overload]
        if spec is not None and spec.provider == "ollama":
            out.setdefault(spec.model, spec.keep_alive)
    return list(out.items())


def warm_up(http: httpx.Client, base_url: str, models: list[tuple[str, str | None]]) -> list[str]:
    """Load each model with an empty prompt; returns the models that failed to load."""
    failed = []
    for model, keep_alive in models:
        body: dict[str, object] = {"model": model, "prompt": "", "stream": False}
        if keep_alive:
            body["keep_alive"] = keep_alive
        started = time.perf_counter()
        try:
            http.post(
                f"{base_url.rstrip('/')}/api/generate", json=body, timeout=WARMUP_TIMEOUT_S
            ).raise_for_status()
            log.info("warmed %s in %.1f s (keep_alive %s)", model, time.perf_counter() - started, keep_alive)
        except httpx.HTTPError as exc:
            log.warning("could not warm %s: %s", model, exc)
            failed.append(model)
    return failed


def api_command(api_url: str) -> list[str]:
    parts = urlsplit(api_url)
    host, port = parts.hostname or "127.0.0.1", str(parts.port or 8000)
    return [sys.executable, "-m", "uvicorn", "insurai.api.main:app", "--host", host, "--port", port]


def ui_command(port: int = UI_PORT) -> list[str]:
    return [sys.executable, "-m", "streamlit", "run", str(ROOT / "ui" / "app.py"), "--server.port", str(port)]


def healthy(http: httpx.Client, api_url: str) -> bool:
    try:
        return http.get(f"{api_url.rstrip('/')}/health", timeout=5.0).status_code == 200
    except httpx.HTTPError:
        return False


def wait_for(check: Callable[[], bool], timeout_s: float, interval_s: float = 1.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if check():
            return True
        time.sleep(interval_s)
    return check()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--skip-warmup", action="store_true", help="do not load the Ollama models first")
    parser.add_argument("--no-browser", action="store_true", help="do not open the UI in a browser")
    args = parser.parse_args(argv)
    settings = get_settings()
    api_url = settings.ui.api_url
    with httpx.Client() as http:
        if healthy(http, api_url):
            port = urlsplit(api_url).port or 8000
            log.error(STALE_API_HINT.format(url=api_url, port=port))
            return 1
        models = demo_models(settings, v7_live_now())
        failed = warm_up(http, settings.ollama_base_url, models) if models and not args.skip_warmup else []
        if failed:
            log.warning("not warmed: %s; is Ollama running? The first answer will be slow", ", ".join(failed))
        api = subprocess.Popen(api_command(api_url), cwd=ROOT)
        procs = [api]
        try:
            if not wait_for(lambda: healthy(http, api_url), HEALTH_TIMEOUT_S):
                log.error("the API did not report healthy within %.0f s", HEALTH_TIMEOUT_S)
                return 1
            log.info("API ready on %s (no --reload)", api_url)
            procs.append(subprocess.Popen(ui_command(), cwd=ROOT))
            ui_url = f"http://localhost:{UI_PORT}"
            if not args.no_browser and wait_for(lambda: _answers(http, ui_url), 60.0):
                webbrowser.open(ui_url)
            log.info("UI on %s; Ctrl+C stops the demo", ui_url)
            return api.wait()
        except KeyboardInterrupt:
            log.info("stopping the demo")
            return 0
        finally:
            for proc in reversed(procs):
                if proc.poll() is None:
                    proc.terminate()
            for proc in procs:
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()


def _answers(http: httpx.Client, url: str) -> bool:
    try:
        return http.get(url, timeout=2.0).status_code < 500
    except httpx.HTTPError:
        return False


if __name__ == "__main__":
    raise SystemExit(main())
