"""Chart spec for an analytics result (spec 02 Behaviour 7).

Exactly one non-numeric column is the x axis and the first numeric column the y axis: a date or month column
gives a line, a categorical column with at most MAX_BAR_ROWS rows gives a bar; anything else is a table only.
"""

from insurai.semantic.schemas import ChartSpec, QueryResult

MAX_BAR_ROWS = 30


def chart_spec(result: QueryResult) -> ChartSpec | None:
    kinds = result.column_kinds
    if result.row_count == 0 or len(kinds) != len(result.columns):
        return None
    dims = [i for i, k in enumerate(kinds) if k in ("text", "temporal")]
    nums = [i for i, k in enumerate(kinds) if k == "numeric"]
    if len(dims) != 1 or len(dims) + len(nums) != len(kinds) or not nums:
        return None
    x, y = result.columns[dims[0]], result.columns[nums[0]]
    if kinds[dims[0]] == "temporal":
        return ChartSpec(type="line", x=x, y=y)
    if result.row_count <= MAX_BAR_ROWS:
        return ChartSpec(type="bar", x=x, y=y)
    return None
