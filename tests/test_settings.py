from datetime import date
from pathlib import Path

import pytest

from insurai import settings as settings_module
from insurai.settings import ROOT, get_settings

pytestmark = pytest.mark.unit


def test_M0_settings_load_from_yaml_with_fixed_as_of_date() -> None:
    settings = get_settings()
    assert settings.as_of_date == date(2026, 10, 1)
    assert settings.llm.profile == "api-lite"
    assert set(settings.llm.profiles) == {"local", "api-lite", "api-quality"}
    assert settings.retrieval.neighbour_sections == {5: [4], 4: [5]}
    assert isinstance(settings.retrieval.rerank_threshold, float)  # tuned in M2 (spec 04, ADR-002)


def test_M0_paths_are_absolute_and_anchored_at_repo_root() -> None:
    paths = get_settings().paths
    assert paths.warehouse.is_absolute()
    assert paths.warehouse == ROOT / "data" / "warehouse.duckdb"
    assert paths.policy_docs_dir == ROOT / "data" / "raw" / "policy_documents"


def test_M0_env_override_with_prefix_and_nesting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INSURAI__LLM__PROFILE", "local")
    monkeypatch.setenv("INSURAI__SQL__ROW_LIMIT", "50")
    settings = get_settings()
    assert settings.llm.profile == "local"
    assert settings.sql.row_limit == 50
    # Deep merge: overriding one key keeps its YAML siblings.
    assert set(settings.llm.profiles) == {"local", "api-lite", "api-quality"}
    assert settings.sql.timeout_s == 10


def test_M0_dotenv_is_loaded(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("INSURAI__LLM__PROFILE=api-quality\nANTHROPIC_API_KEY=sk-test\n", encoding="utf-8")
    monkeypatch.setattr(settings_module, "ENV_FILE", env_file)
    settings = get_settings()
    assert settings.llm.profile == "api-quality"
    assert settings.anthropic_api_key is not None
    assert settings.anthropic_api_key.get_secret_value() == "sk-test"


def test_M0_environment_beats_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("INSURAI__LLM__PROFILE=api-quality\n", encoding="utf-8")
    monkeypatch.setattr(settings_module, "ENV_FILE", env_file)
    monkeypatch.setenv("INSURAI__LLM__PROFILE", "local")
    assert get_settings().llm.profile == "local"


def test_M0_settings_are_cached_until_cleared(monkeypatch: pytest.MonkeyPatch) -> None:
    first = get_settings()
    assert get_settings() is first
    monkeypatch.setenv("INSURAI__LLM__PROFILE", "local")
    get_settings.cache_clear()
    assert get_settings().llm.profile == "local"
