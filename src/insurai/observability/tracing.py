"""Tool-call spans on the OpenTelemetry API. A no-op until a tracer provider (Phoenix) is registered."""

from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import trace
from opentelemetry.util.types import AttributeValue


def _tracer() -> trace.Tracer:
    return trace.get_tracer("insurai.tools")


@contextmanager
def tool_span(name: str, attributes: dict[str, AttributeValue]) -> Iterator[trace.Span]:
    with _tracer().start_as_current_span(f"tool.{name}", attributes=attributes) as span:
        yield span
