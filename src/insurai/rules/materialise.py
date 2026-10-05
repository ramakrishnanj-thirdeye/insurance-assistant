"""`make rules`: materialise gold.rule_results from config/rules.yaml and log the portfolio counts (spec 07).

Run after `make data` (which calls it). Stop `make api`, `make mcp` and `make ui` first: Windows cannot write
a DuckDB file another process holds open.
"""

import json
import sys

from insurai import db
from insurai.observability import get_logger
from insurai.rules.engine import materialise_portfolio

log = get_logger("rules.materialise")


def main() -> int:
    with db.connect(read_only=False) as con:
        report = materialise_portfolio(con)
    log.info("gold.rule_results: %d claims in %.0f ms", report.claims, report.elapsed_ms or 0)
    log.info("fails: %s", json.dumps(report.fail_counts))
    log.info(
        "consistency: %s · insights: %s",
        json.dumps(report.consistency_counts),
        json.dumps(report.insight_counts),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
