"""Provider factory for summarization."""
from __future__ import annotations

from typing import Callable, Protocol, runtime_checkable

from ..utils.api_keys import LITELLM_KEY_MAP as _LITELLM_KEY_MAP, resolve_api_key as _resolve_key


@runtime_checkable
class SummarizationProvider(Protocol):
    def summarize(
        self,
        transcript: str,
        on_status: Callable[[str], None] | None = None,
    ) -> str: ...


def create_summarization_provider(config: dict) -> SummarizationProvider:
    """Factory: return the configured summarization provider."""
    provider = config.get("summarization_provider", "litellm")

    if provider == "claude_code":
        from .providers.claude_code import ClaudeCodeProvider
        return ClaudeCodeProvider(
            timeout=config.get("llm_request_timeout_minutes", 5) * 60,
        )

    if provider == "litellm":
        from .providers.litellm_provider import LiteLLMSummarizationProvider
        model = config.get("litellm_summarization_model", "gemini/gemini-2.5-flash")
        prefix = model.split("/")[0] if "/" in model else ""
        key_name = _LITELLM_KEY_MAP.get(prefix, "")
        api_key = _resolve_key(config, key_name) if key_name else None
        return LiteLLMSummarizationProvider(
            model=model,
            api_key=api_key,
            summarization_prompt=config.get("summarization_prompt", ""),
            timeout_minutes=config.get("llm_request_timeout_minutes", 5),
        )

    raise ValueError(f"Unknown summarization provider: {provider!r}")
