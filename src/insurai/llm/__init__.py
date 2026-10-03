"""The only door to LLMs (ADR-006): ``get_model(role)`` for the active profile in settings."""

from typing import Any, get_args

from langchain.chat_models import init_chat_model
from langchain_core.language_models import BaseChatModel

from insurai.settings import Role, RoleModel, Settings, get_settings

__all__ = ["Role", "get_model"]


def get_model(role: Role) -> BaseChatModel:
    """Build the chat model for ``role`` in the active profile. Construction does no network I/O."""
    if role not in get_args(Role):
        raise ValueError(f"Unknown LLM role {role!r}; expected one of {get_args(Role)}")
    settings = get_settings()
    profile = settings.llm.profile
    roles = settings.llm.profiles.get(profile)
    if roles is None:
        raise ValueError(f"Unknown LLM profile {profile!r}; configured: {sorted(settings.llm.profiles)}")
    if role not in roles:
        raise ValueError(f"LLM profile {profile!r} has no {role!r} model")
    spec = roles[role]
    return init_chat_model(
        spec.model,
        model_provider=spec.provider,
        temperature=spec.temperature,
        **_provider_kwargs(spec, settings),
    )


def _provider_kwargs(spec: RoleModel, settings: Settings) -> dict[str, Any]:
    llm = settings.llm
    if spec.provider == "anthropic":
        kwargs: dict[str, Any] = {"max_tokens": llm.max_output_tokens, "timeout": llm.request_timeout_s}
        if settings.anthropic_api_key is not None:
            kwargs["api_key"] = settings.anthropic_api_key
        return kwargs
    return {
        "num_predict": llm.max_output_tokens,
        "base_url": settings.ollama_base_url,
        "client_kwargs": {"timeout": llm.request_timeout_s},
    }
