import pytest

from insurai.semantic.chart import chart_spec
from insurai.semantic.schemas import QueryResult

pytestmark = pytest.mark.unit


def _result(columns: list[str], kinds: list[str], n: int) -> QueryResult:
    rows = [[f"v{i}" if k != "numeric" else i for k in kinds] for i in range(n)]
    return QueryResult(columns=columns, rows=rows, row_count=n, truncated=False, column_kinds=kinds)  # type: ignore[arg-type]


def test_categorical_and_numeric_is_a_bar() -> None:
    spec = chart_spec(_result(["product", "claims"], ["text", "numeric"], 10))
    assert spec is not None and (spec.type, spec.x, spec.y) == ("bar", "product", "claims")


def test_first_numeric_column_is_the_y_axis() -> None:
    spec = chart_spec(_result(["product", "claims", "rate"], ["text", "numeric", "numeric"], 3))
    assert spec is not None and spec.y == "claims"


def test_date_and_numeric_is_a_line_at_any_length() -> None:
    spec = chart_spec(_result(["month", "claims"], ["temporal", "numeric"], 46))
    assert spec is not None and spec.type == "line" and spec.x == "month"


def test_more_than_30_categories_is_table_only() -> None:
    assert chart_spec(_result(["hospital", "claims"], ["text", "numeric"], 31)) is None


@pytest.mark.parametrize(
    ("columns", "kinds"),
    [
        (["claims"], ["numeric"]),  # a single value
        (["city", "product", "claims"], ["text", "text", "numeric"]),  # two dimensions
        (["city", "state"], ["text", "text"]),  # nothing to plot
        (["flag", "claims"], ["other", "numeric"]),
    ],
)
def test_other_shapes_are_table_only(columns: list[str], kinds: list[str]) -> None:
    assert chart_spec(_result(columns, kinds, 3)) is None


def test_empty_result_has_no_chart() -> None:
    assert chart_spec(_result(["product", "claims"], ["text", "numeric"], 0)) is None
