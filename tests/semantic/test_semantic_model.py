import pytest
from insurai.semantic.model import SemanticModel

pytestmark = pytest.mark.unit


def test_verified_queries_load_for_sql_examples() -> None:
    model = SemanticModel.load()
    assert len(model.verified_queries) == 14
    assert len({q.name for q in model.verified_queries}) == 14
    assert all(q.question and q.sql.lstrip().upper().startswith("SELECT") for q in model.verified_queries)
