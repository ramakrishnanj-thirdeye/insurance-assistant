"""Citation labels for tool results, built from the formats in config/guardrails.yaml."""

import re
from functools import lru_cache

from insurai.tools.messages import guardrails
from insurai.tools.schemas import SourceRef


def sql_source(table: str, key: str) -> SourceRef:
    """`[claims:CLM300210]`: one row (or a claim's rows) of a warehouse table."""
    label = guardrails()["sql_citation_format"].format(table=table, key=key)
    return SourceRef(kind="sql", label=label, table=table, key=key)


@lru_cache(maxsize=1)
def label_regexes() -> tuple[re.Pattern[str], re.Pattern[str]]:
    """(sql, policy) label patterns derived from the guardrails format strings."""
    g = guardrails()
    sql = _to_regex(
        g["sql_citation_format"], {"table": r"[a-z_]+", "key": r"[A-Z]+\d+|[0-9a-f]{8}"}
    )  # a row | a query
    policy = _to_regex(
        g["citation_format"], {"product": r"[A-Za-z][\w ]*?", "section_no": r"\d+", "section_name": r".+?"}
    )
    return sql, policy


def _to_regex(fmt: str, fields: dict[str, str]) -> re.Pattern[str]:
    parts = re.split(r"\{(\w+)\}", fmt)  # literal, field, literal, field, ...
    pattern = "".join(re.escape(p) if i % 2 == 0 else f"(?:{fields[p]})" for i, p in enumerate(parts))
    return re.compile(pattern)
