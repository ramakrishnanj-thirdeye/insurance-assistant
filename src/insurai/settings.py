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

Role = Literal["generator", "small", "judge"]
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


class AgentSettings(_Section):
    verifier_retries: int
    max_parallel_workers: int


class APISettings(_Section):
    host: str
    port: int


class MCPSettings(_Section):
    http_host: str
    http_port: int


class TracingSettings(_Section):
    phoenix_enabled: bool
    phoenix_project: str


class LoggingSettings(_Section):
    level: str = "INFO"


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
    tracing: TracingSettings
    logging: LoggingSettings = Field(default_factory=LoggingSettings)

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The process-wide settings; call ``get_settings.cache_clear()`` after changing the environment."""
    return Settings(_env_file=ENV_FILE)  # type: ignore[call-arg]
