import os
import socket
from collections.abc import Iterator

import pytest

from insurai import settings as settings_module

_LEAKY_ENV = ("ANTHROPIC_API_KEY", "OLLAMA_BASE_URL")


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Settings come from config/settings.yaml only: no developer .env, no INSURAI__ overrides."""
    for name in list(os.environ):
        if name.upper().startswith("INSURAI__") or name.upper() in _LEAKY_ENV:
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(settings_module, "ENV_FILE", None)
    settings_module.get_settings.cache_clear()
    yield
    settings_module.get_settings.cache_clear()


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail the test on any attempt to open a socket connection."""

    def _blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("network access attempted in a unit test")

    monkeypatch.setattr(socket.socket, "connect", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
