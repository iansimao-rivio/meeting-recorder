"""Shared API key validation utilities."""
from __future__ import annotations

import os

LITELLM_KEY_MAP = {
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "deepgram": "DEEPGRAM_API_KEY",
}


def has_api_key(cfg: dict, env_name: str) -> bool:
    """Check if API key is available in config or environment."""
    return bool(cfg.get("api_keys", {}).get(env_name) or os.environ.get(env_name))


def resolve_api_key(cfg: dict, env_name: str) -> str:
    """Get API key value from config api_keys dict, falling back to os.environ."""
    return cfg.get("api_keys", {}).get(env_name, "") or os.environ.get(env_name, "")


def check_api_keys(cfg: dict, ts: str, ss: str) -> str | None:
    """Validate API keys for the given transcription/summarization providers.

    Returns an error message string if a required key is missing, or None if all OK.
    """
    if ts == "gemini" and not has_api_key(cfg, "GEMINI_API_KEY"):
        return "Gemini API key not set (add in Settings \u2192 API Keys)"
    if ts == "elevenlabs" and not has_api_key(cfg, "ELEVENLABS_API_KEY"):
        return "ElevenLabs API key not set (add in Settings \u2192 API Keys)"
    for provider_type in ("transcription", "summarization"):
        prov = ts if provider_type == "transcription" else ss
        if prov != "litellm":
            continue
        model = cfg.get(f"litellm_{provider_type}_model", "")
        prefix = model.split("/")[0] if "/" in model else ""
        env_key = LITELLM_KEY_MAP.get(prefix)
        if env_key and not has_api_key(cfg, env_key):
            return f"{env_key} not set for {model} (add in Settings \u2192 API Keys)"
    return None
