"""`make rules`: materialise gold.rule_results (spec 07).

Placeholder until spec 07 lands in M5 (see tasks.md) so that `make data`, which calls `make rules`, succeeds.
"""

import sys

from insurai.observability import get_logger

log = get_logger("rules.materialise")


def main() -> int:
    log.warning("rules engine not implemented yet (spec 07, M5): gold.rule_results not materialised")
    return 0


if __name__ == "__main__":
    sys.exit(main())
