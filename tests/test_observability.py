import logging

import pytest

from insurai.observability import get_logger

pytestmark = pytest.mark.unit


def test_M0_get_logger_uses_insurai_namespace() -> None:
    assert get_logger("insurai.tools").name == "insurai.tools"
    assert get_logger("tools").name == "insurai.tools"
    assert get_logger("insurai").name == "insurai"


def test_M0_get_logger_configures_one_handler() -> None:
    get_logger("a")
    get_logger("b")
    root = logging.getLogger("insurai")
    ours = [h for h in root.handlers if h.get_name() == "insurai-stderr"]
    assert len(ours) == 1
    assert root.level == logging.INFO
    assert root.propagate is False
