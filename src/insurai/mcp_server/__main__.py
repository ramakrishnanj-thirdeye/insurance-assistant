"""`python -m insurai.mcp_server --transport stdio|streamable-http` (spec 05)."""

import argparse

from insurai.mcp_server.server import build_server, ctx_factory_from_env
from insurai.observability import get_logger
from insurai.settings import get_settings

log = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="insurai.mcp_server")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio")
    args = parser.parse_args(argv)
    try:
        factory = ctx_factory_from_env()
    except ValueError as exc:
        log.error("%s", exc)
        return 2
    ctx = factory()
    s = get_settings().mcp
    where = f" on http://{s.http_host}:{s.http_port}/mcp" if args.transport == "streamable-http" else ""
    log.info("insurai MCP server: persona=%s transport=%s%s", ctx.persona, args.transport, where)
    build_server(factory).run(transport=args.transport)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
