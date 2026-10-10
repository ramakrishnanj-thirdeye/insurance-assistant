"""Runtime settings: config/settings.yaml, overridden by .env, overridden by environment variables.

Override any key with ``INSURAI__<SECTION>__<KEY>``, e.g. ``INSURAI__LLM__PROFILE=local``.
"""

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, SecretStr, field_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE: Path = ROOT / "config" / "settings.yaml"
ENV_FILE: Path | None = ROOT / ".env"

Role = Literal["generator", "small", "judge", "sql"]
# Optional roles and the role they fall back to when a profile does not configure them.
ROLE_FALLBACK: dict[str, str] = {"sql": "generator"}  # sql: text-to-SQL only (spec 02, ADR-006)
Provider = Literal["anthropic", "ollama"]


class _Section(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PathsSettings(_Section):
    raw_dir: Path
    policy_docs_dir: Path
    warehouse: Path
    qdrant_path: Path
    models_dir: Path
    checkpoints: Path
    dq_report: Path
    eval_reports: Path

    @field_validator("*", mode="after")
    @classmethod
    def _anchor_at_root(cls, value: Path) -> Path:
        return value if value.is_absolute() else ROOT / value


class RoleModel(_Section):
    provider: Provider
    model: str
    temperature: float = 0.0
    num_ctx: int | None = None  # Ollama context window; Ollama truncates silently past it
    reasoning: bool | None = None  # Ollama thinking switch (False turns Qwen3 thinking off)
    request_timeout_s: float | None = None  # overrides llm.request_timeout_s for this role
    seed: int | None = None  # Ollama sampling seed, so local eval runs are reproducible
    keep_alive: str | None = (
        None  # Ollama: how long the model stays loaded after a call, e.g. "30m" (make demo)
    )


class LLMSettings(_Section):
    profile: str
    profiles: dict[str, dict[Role, RoleModel]]
    max_output_tokens: int
    request_timeout_s: float


class RetrievalSettings(_Section):
    dense_model: str
    sparse_model: str
    reranker_model: str
    onnx_threads: int | None = None
    collection_policies: str
    collection_sql_examples: str
    prefetch_k: int
    final_k: int
    rerank_threshold: float | None = None
    section_boost: float
    neighbour_sections: dict[int, list[int]] = Field(default_factory=dict)


class ThresholdSettings(_Section):
    fraud_review_score: float
    high_value_inr: int


class SQLSettings(_Section):
    row_limit: int
    timeout_s: float
    repair_attempts: int
    forbidden_functions: list[str] = Field(default_factory=list)  # fnmatch patterns (spec 02 validator)


class AgentSettings(_Section):
    verifier_retries: int
    max_parallel_workers: int
    tool_transport: Literal["inprocess", "mcp"] = "inprocess"
    history_turns: int = 6  # user+assistant turns the planner and synthesizer see (ADR-009)
    turn_timeout_s: float = 300  # a thread running longer than this is a stale lease (spec 09 Busy)
    heartbeat_s: float = 2.0  # a node running longer than this gets a `heartbeat` SSE event this often
    dossier_polish_customer_message: bool = True  # one small-model call per full-view dossier (spec 07)
    common_probe_top_k: int = 3  # rule 2: a confident common chunk this high in the probe answers unfiltered


class APISettings(_Section):
    host: str
    port: int
    cors_origins: list[str] = Field(default_factory=list)  # the Streamlit origin (spec 09 Behaviour)


class SampleCustomer(_Section):
    customer_id: str
    hint: str = ""


class UISettings(_Section):
    api_url: str = "http://127.0.0.1:8000"
    sample_customers: list[SampleCustomer] = Field(default_factory=list)  # principal picker (spec 10)


class MCPSettings(_Section):
    http_host: str
    http_port: int


class TracingSettings(_Section):
    phoenix_enabled: bool
    phoenix_project: str


class EvalSettings(_Section):
    # "slice.metric" -> minimum, or {max: x} for a metric where lower is better (suite.false_refusal)
    targets: dict[str, float | dict[str, float]] = Field(default_factory=dict)
    # metric names (any slice) that are reported but not gated while the judge is uncalibrated
    advisory_when_uncalibrated: list[str] = Field(default_factory=list)


class LoggingSettings(_Section):
    level: str = "INFO"


class GuardrailSettings(_Section):
    # V7 (LLM groundedness judge) in the request path, per llm profile. Off for local: the judge is another
    # model family and Ollama would swap models on every answer; V7 then runs in the eval only (spec 08).
    v7_live: dict[str, bool] = Field(default_factory=dict)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="INSURAI__",
        env_nested_delimiter="__",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    project: str
    as_of_date: date
    paths: PathsSettings
    llm: LLMSettings
    retrieval: RetrievalSettings
    thresholds: ThresholdSettings
    sql: SQLSettings
    agent: AgentSettings
    api: APISettings
    mcp: MCPSettings
    ui: UISettings = Field(default_factory=UISettings)
    tracing: TracingSettings
    eval: EvalSettings = Field(default_factory=EvalSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    guardrails: GuardrailSettings = Field(default_factory=GuardrailSettings)

    # Secrets and hosts come from .env / the environment under their conventional names (no prefix).
    anthropic_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY")
    )
    ollama_base_url: str = Field(
        default="http://localhost:11434", validation_alias=AliasChoices("OLLAMA_BASE_URL")
    )

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        yaml_settings = YamlConfigSettingsSource(
            settings_cls, yaml_file=CONFIG_FILE, yaml_file_encoding="utf-8"
        )
        return init_settings, env_settings, dotenv_settings, yaml_settings


def v7_live_now() -> bool:
    """Whether V7 runs in the request path for the current llm profile (missing profile: off)."""
    s = get_settings()
    return s.guardrails.v7_live.get(s.llm.profile, False)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The process-wide settings; call ``get_settings.cache_clear()`` after changing the environment."""
    return Settings(_env_file=ENV_FILE)  # type: ignore[call-arg]
