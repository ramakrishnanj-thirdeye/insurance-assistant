from datetime import date

import pytest
from pydantic import ValidationError

from insurai.tools.schemas import AccessDenied, NotFound, SourceRef, ToolContext

pytestmark = pytest.mark.unit


def test_M0_error_results_carry_their_kind() -> None:
    assert NotFound(entity="claim", message="No claim CLM999999").kind == "not_found"
    assert AccessDenied(message="Not your claim").kind == "access_denied"


def test_M0_tool_context_rejects_unknown_persona() -> None:
    ctx = ToolContext(persona="customer", principal_id="CUST000001", as_of=date(2026, 10, 1), trace_id="t1")
    assert ctx.as_of == date(2026, 10, 1)
    with pytest.raises(ValidationError):
        ToolContext(persona="admin", as_of=date(2026, 10, 1), trace_id="t1")  # type: ignore[arg-type]


def test_M0_source_ref_optional_fields_default_to_none() -> None:
    ref = SourceRef(kind="sql", label="[claims:CLM300210]", table="claims", key="CLM300210")
    assert ref.product is None and ref.section_no is None
    with pytest.raises(ValidationError):
        SourceRef(kind="memory", label="[x]")  # type: ignore[arg-type]
