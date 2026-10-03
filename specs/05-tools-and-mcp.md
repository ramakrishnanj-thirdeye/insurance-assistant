# 05 – Tools and MCP server

Milestone: M3 · Depends on: 01, 03, 04, 08 (personas) · ADR: 005 (MCP tool boundary)

## Goal
A small set of deterministic, typed, access-controlled tools that answer the known question shapes,
exposed in-process to the agent and through a FastMCP server to Claude Desktop and other MCP clients.

## Common types
```python
# src/insurai/tools/schemas.py
Persona = Literal["customer", "claims_agent", "supervisor"]
class ToolContext(BaseModel):
    persona: Persona; principal_id: str | None = None      # customer_id for persona=customer
    as_of: date; trace_id: str
class SourceRef(BaseModel):
    kind: Literal["sql", "policy", "config"]
    label: str                                              # "[claims:CLM300210]", "[Health Secure Plus §5 Maternity]"
    table: str | None = None; key: str | None = None
    product: str | None = None; section_no: int | None = None; section_name: str | None = None
class NotFound(BaseModel): kind: Literal["not_found"] = "not_found"; entity: str; message: str
class AccessDenied(BaseModel): kind: Literal["access_denied"] = "access_denied"; message: str
# Every tool returns   <ResultModel> | NotFound | AccessDenied   and every ResultModel has sources: list[SourceRef] (≥ 1).
```

## Tools
| Tool | Signature | Returns | Backing objects |
| --- | --- | --- | --- |
| get_claim | (ctx, claim_id) | ClaimView: claim fields, product, policy period, effective_status, derived flags, hospital summary | gold.claim_facts |
| get_claim_documents | (ctx, claim_id) | DocumentChecklist: rows (type, required, checklist_status, file_type), untracked requirements, counts | gold.claim_doc_checklist, required_documents.yaml |
| get_policy | (ctx, policy_id) | PolicyView: schedule, effective_status, status_conflict, continuous_cover_start | silver.policies |
| get_customer_summary | (ctx, customer_id=None, name=None, city=None) | CustomerSummary or Disambiguation (≤ 10 matches: id, city, age, policies) | gold.v_customer_360 |
| check_hospital | (ctx, hospital_id=None, name=None, city=None) | HospitalCheck: network_status, specialty, city, ≤ 3 network alternatives (same city and specialty) | silver.hospitals |
| get_claim_interactions | (ctx, claim_id) | InteractionHistory: rows, counts by intent, latest sentiment, open escalations, before_claim_date flags | silver.customer_interactions |
| search_policy | (ctx, query, product?, policy_type?, section_hints?) | RetrievalResult | spec 04 |
| get_coverage | (ctx, product?, attribute?) | CoverageCells | spec 03 |
| analyze_claim | (ctx, claim_id, narrate=False) | ClaimAssessment | spec 07 |
| run_analytics | (ctx, question) | AnalyticsResult | spec 02 |
| portfolio_audit | (ctx, flag?, product?, limit=50) | PortfolioAudit: counts per rule and consistency flag, sample claims | gold.rule_results |

## Behaviour
1. IDs are validated by regex (`CLM\d{6}`, `POL\d{6}`, `CUST\d{6}`, `HOSP\d{4}`) before any query; bad format → NotFound with a hint.
2. All SQL is parameterised; tools use `db.connect(read_only=True)`.
3. Access (config/personas.yaml), checked in code before returning data:
   - customer: claim/policy/documents/interactions only when the owning claim/policy has `customer_id = principal_id`; otherwise AccessDenied. Ownership of interactions comes from `claim_owner_id`, never `logged_customer_id`.
   - hidden columns are removed from results (customer: fraud_risk_score, manual_review_flag, risk_segment).
   - tools not listed for the persona → AccessDenied.
4. Names: `customer_name` is returned only to agent and supervisor personas; analytics masking is spec 02.
5. Name lookups never pick one customer: ≥ 2 matches → Disambiguation.
6. Every result carries `sources`: `[claims:CLM300210]`, `[policies:POL218917]`, `[claim_documents:CLM300210]`, `[hospitals:HOSP1257]`, `[interactions:CLM300210]`, `[customers:CUST139920]`.
7. Tool calls are traced (Phoenix span with name, args minus PII, duration, result size).

## MCP server
- `src/insurai/mcp_server/server.py` builds a FastMCP server (`mcp.server.fastmcp.FastMCP("insurai")`) that registers every tool above with its Pydantic input/output schema.
- Transports: `python -m insurai.mcp_server --transport stdio` (Claude Desktop) and `--transport streamable-http` on `mcp.http_host:http_port` (`make mcp`).
- Persona for the MCP server is fixed at start from env `INSURAI_PERSONA` (default `claims_agent`) and `INSURAI_PRINCIPAL_ID`. Per-request identity is a production concern (remote MCP with OAuth, see the scale-up path).
- The MCP server opens the index through `get_qdrant()` (spec 04), so it runs alongside the API.
- The agent binds the same Python functions in-process by default (`agent.tool_transport: inprocess`); `mcp` mode connects through langchain-mcp-adapters to the HTTP server. Both must produce identical results.
- Claude Desktop config (README):
  ```json
  {"mcpServers": {"insurai": {"command": "uv",
     "args": ["run", "--directory", "/ABSOLUTE/PATH/insurance-assistant", "python", "-m", "insurai.mcp_server", "--transport", "stdio"],
     "env": {"INSURAI_PERSONA": "claims_agent"}}}}
  ```

## Acceptance criteria
- [ ] AC-05-01 Each tool has unit tests for found, not found, bad ID format and access denied.
- [ ] AC-05-02 sql_facts slice (40 items) answered 100% correctly by tools alone (exact match).
- [ ] AC-05-03 Every successful result has ≥ 1 SourceRef whose label matches the formats in config/guardrails.yaml.
- [ ] AC-05-04 Customer persona: another customer's claim → AccessDenied; `fraud_risk_score` absent from every customer result (property test over 100 random owned claims).
- [ ] AC-05-05 Interactions: for a customer whose ID appears only as `logged_customer_id` on another customer's claim, get_claim_interactions returns AccessDenied.
- [ ] AC-05-06 check_hospital alternatives are Network, same city, same specialty, and exclude the hospital itself.
- [ ] AC-05-07 `get_customer_summary(name="Arjun Sharma")` returns a Disambiguation, never a single customer.
- [ ] AC-05-08 `make mcp-smoke`: an MCP client lists all tools with schemas and `get_claim("CLM300210")` over MCP equals the in-process result.
- [ ] AC-05-09 Manual: Claude Desktop with the README config answers "What is the status of CLM300210?" through the server.

## Eval hooks
sql_facts slice; tool errors counted in every slice.
