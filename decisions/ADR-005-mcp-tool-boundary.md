# ADR-005 MCP as the tool boundary
Status: accepted

**Context.** The BRD lists MCP as an advanced option; the client should see the tools as a reusable platform.
**Decision.** Tools are plain typed Python functions; a FastMCP server exposes them over stdio (Claude Desktop) and streamable HTTP. The agent calls them in-process by default and can switch to MCP transport by config.
**Consequences.** One contract for the agent, Claude Desktop and future services. PoC identity is fixed per server process (env persona); per-request identity (OAuth) is a production item.
**Version pin.** `mcp[cli]>=1.9,<2`: MCP Python SDK 2.x renamed `FastMCP` to `MCPServer` and changed other APIs. Migrate deliberately later, not by accident.
**Alternatives.** In-process only (no reuse story); REST endpoints per tool (more code, no MCP clients).
