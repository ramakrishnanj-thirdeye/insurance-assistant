import pytest
from langchain_anthropic import ChatAnthropic
from langchain_ollama import ChatOllama

from insurai.llm import get_model
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
