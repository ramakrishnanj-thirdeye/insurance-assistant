import pytest
from langchain_anthropic import ChatAnthropic
from langchain_ollama import ChatOllama

from insurai.llm import get_model, role_spec
from insurai.settings import get_settings

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("no_network")]

PROFILES = ["local", "api-lite", "api-quality"]
ROLES = ["generator", "small", "judge"]


@pytest.mark.parametrize("profile", PROFILES)
@pytest.mark.parametrize("role", ROLES)
def test_M0_get_model_resolves_each_profile_offline(
    monkeypatch: pytest.MonkeyPatch, profile: str, role: str
) -> None:
    monkeypatch.setenv("INSURAI__LLM__PROFILE", profile)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    settings = get_settings()
    spec = settings.llm.profiles[profile][role]

    model = get_model(role)  # type: ignore[arg-type]

    assert model.temperature == spec.temperature
    if spec.provider == "anthropic":
        assert isinstance(model, ChatAnthropic)
        assert model.model == spec.model
        assert model.max_tokens == settings.llm.max_output_tokens
        assert model.anthropic_api_key.get_secret_value() == "sk-test"
    else:
        assert isinstance(model, ChatOllama)
        assert model.model == spec.model
        assert model.num_predict == settings.llm.max_output_tokens
        assert model.base_url == settings.ollama_base_url


def test_M0_ollama_base_url_comes_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INSURAI__LLM__PROFILE", "local")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://ollama.test:11434")
    model = get_model("generator")
    assert isinstance(model, ChatOllama)
    assert model.base_url == "http://ollama.test:11434"


@pytest.mark.parametrize("profile", PROFILES)
def test_M0_judge_differs_from_generator_in_every_profile(profile: str) -> None:
    roles = get_settings().llm.profiles[profile]
    assert roles["judge"].model != roles["generator"].model


def test_M0_unknown_role_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown LLM role"):
        get_model("writer")  # type: ignore[arg-type]


def test_M0_unknown_profile_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INSURAI__LLM__PROFILE", "gpu-cluster")
    with pytest.raises(ValueError, match="Unknown LLM profile"):
        get_model("generator")


def test_local_profile_sets_num_ctx_reasoning_off_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INSURAI__LLM__PROFILE", "local")
    for role in ROLES:
        model = get_model(role)  # type: ignore[arg-type]
        assert isinstance(model, ChatOllama)
        assert model.num_ctx == 8192
        assert model.reasoning is (False if role != "judge" else None)  # Qwen3 thinking off; Llama has none
        assert model.client_kwargs == {"timeout": 180.0}


def test_local_judge_is_another_model_family(monkeypatch: pytest.MonkeyPatch) -> None:
    """ADR-006 amendment 2026-10-06: the judge does not share the generator's model family."""
    monkeypatch.setenv("INSURAI__LLM__PROFILE", "local")
    family = {role: get_model(role).model.split(":")[0].rstrip("0123456789.") for role in ROLES}  # type: ignore[arg-type,union-attr,attr-defined]
    assert family["judge"] != family["generator"]


def test_local_profile_sets_seed_for_reproducible_evals(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INSURAI__LLM__PROFILE", "local")
    for role in ROLES:
        model = get_model(role)  # type: ignore[arg-type]
        assert isinstance(model, ChatOllama) and model.seed == 42


def test_AC_10_16_local_generator_stays_loaded_between_demo_turns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INSURAI__LLM__PROFILE", "local")
    for role in ("generator", "small"):
        model = get_model(role)
        assert isinstance(model, ChatOllama) and model.keep_alive == "30m"


def test_api_profile_keeps_global_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    model = get_model("generator")
    assert isinstance(model, ChatAnthropic)
    assert model.default_request_timeout == get_settings().llm.request_timeout_s


@pytest.mark.parametrize("profile", ["api-lite", "api-quality"])
def test_sql_role_falls_back_to_the_generator(monkeypatch: pytest.MonkeyPatch, profile: str) -> None:
    """ADR-006 amendment 2026-10-08: `sql` is optional; a profile without it uses its generator."""
    monkeypatch.setenv("INSURAI__LLM__PROFILE", profile)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    settings = get_settings()
    assert "sql" not in settings.llm.profiles[profile]
    assert role_spec("sql") == settings.llm.profiles[profile]["generator"]
    assert get_model("sql").model == get_model("generator").model  # type: ignore[attr-defined]


def test_configured_sql_role_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INSURAI__LLM__PROFILE", "local")
    monkeypatch.setenv("INSURAI__LLM__PROFILES__LOCAL__SQL__PROVIDER", "ollama")
    monkeypatch.setenv("INSURAI__LLM__PROFILES__LOCAL__SQL__MODEL", "sql-model:1b")
    assert get_model("sql").model == "sql-model:1b"  # type: ignore[attr-defined]
    assert get_model("generator").model != "sql-model:1b"  # type: ignore[attr-defined]


def test_local_judge_differs_from_the_sql_model_family(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INSURAI__LLM__PROFILE", "local")
    family = {r: get_model(r).model.split(":")[0].rstrip("0123456789.") for r in ("sql", "judge")}  # type: ignore[arg-type,attr-defined]
    assert family["judge"] != family["sql"]


def test_unknown_role_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown LLM role"):
        get_model("planner")  # type: ignore[arg-type]
