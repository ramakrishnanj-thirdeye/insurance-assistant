"""Logging for the package: stdlib ``logging`` under the ``insurai`` namespace."""

import logging
import sys

_ROOT_LOGGER = "insurai"
_HANDLER_NAME = "insurai-stderr"
_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


class PiiRedactingFilter(logging.Filter):
    """Masks PII (config/guardrails.yaml pii_patterns) in the formatted message before any handler sees
    the record, test capture handlers included (spec 08 Logging)."""

    def filter(self, record: logging.LogRecord) -> bool:
        from insurai.guardrails.pii import mask  # lazy: guardrails imports this package

        message = record.getMessage()
        masked, found = mask(message)
        if found:
            record.msg, record.args = masked, None
        return True


_PII_FILTER = PiiRedactingFilter()


def get_logger(name: str) -> logging.Logger:
    """A logger under ``insurai`` with the PII filter; configures the namespace's single stderr handler on
    first use."""
    _configure()
    if name != _ROOT_LOGGER and not name.startswith(f"{_ROOT_LOGGER}."):
        name = f"{_ROOT_LOGGER}.{name}"
    logger = logging.getLogger(name)
    if _PII_FILTER not in logger.filters:
        logger.addFilter(_PII_FILTER)
    return logger


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
