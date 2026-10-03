import logging

import pytest
from insurai.rules import materialise

pytestmark = pytest.mark.unit


def test_M1_rules_stub_exits_zero_and_warns(caplog: pytest.LogCaptureFixture) -> None:
    # Placeholder until spec 07 (M5) so `make data` can call `make rules`; see tasks.md.
    logging.getLogger("insurai").propagate = True
    try:
        with caplog.at_level(logging.WARNING, logger="insurai"):
            assert materialise.main() == 0
    finally:
        logging.getLogger("insurai").propagate = False
    assert "spec 07" in caplog.text
