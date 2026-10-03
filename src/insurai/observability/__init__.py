"""Logging for the package: stdlib ``logging`` under the ``insurai`` namespace."""

import logging
import sys

_ROOT_LOGGER = "insurai"
_HANDLER_NAME = "insurai-stderr"
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def get_logger(name: str) -> logging.Logger:
    """A logger under ``insurai``; configures the namespace's single stderr handler on first use."""
    _configure()
    if name != _ROOT_LOGGER and not name.startswith(f"{_ROOT_LOGGER}."):
        name = f"{_ROOT_LOGGER}.{name}"
    return logging.getLogger(name)


def _configure() -> None:
    root = logging.getLogger(_ROOT_LOGGER)
    if any(h.get_name() == _HANDLER_NAME for h in root.handlers):
        return
    from insurai.settings import get_settings  # lazy: settings must stay importable without logging

    handler = logging.StreamHandler(sys.stderr)
    handler.set_name(_HANDLER_NAME)
    handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(handler)
    root.setLevel(get_settings().logging.level.upper())
    root.propagate = False
