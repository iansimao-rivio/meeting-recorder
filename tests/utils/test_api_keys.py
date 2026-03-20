import os
from unittest.mock import patch

import pytest

from meeting_recorder.utils.api_keys import (
    LITELLM_KEY_MAP,
    has_api_key,
    resolve_api_key,
    check_api_keys,
)


def test_litellm_key_map_has_known_providers():
    assert LITELLM_KEY_MAP["gemini"] == "GEMINI_API_KEY"
    assert LITELLM_KEY_MAP["openai"] == "OPENAI_API_KEY"
    assert LITELLM_KEY_MAP["anthropic"] == "ANTHROPIC_API_KEY"


def test_has_api_key_from_config():
    cfg = {"api_keys": {"GEMINI_API_KEY": "test-key"}}
    assert has_api_key(cfg, "GEMINI_API_KEY") is True


def test_has_api_key_from_env():
    cfg = {"api_keys": {}}
    with patch.dict(os.environ, {"GEMINI_API_KEY": "env-key"}):
        assert has_api_key(cfg, "GEMINI_API_KEY") is True


def test_has_api_key_missing():
    cfg = {"api_keys": {}}
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("GEMINI_API_KEY", None)
        assert has_api_key(cfg, "GEMINI_API_KEY") is False


def test_check_api_keys_gemini_missing():
    cfg = {"api_keys": {}}
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("GEMINI_API_KEY", None)
        result = check_api_keys(cfg, "gemini", "litellm")
        assert result is not None
        assert "Gemini" in result


def test_check_api_keys_litellm_summarization_missing():
    cfg = {
        "api_keys": {},
        "litellm_summarization_model": "openai/gpt-4o",
    }
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("OPENAI_API_KEY", None)
        result = check_api_keys(cfg, "whisper", "litellm")
        assert result is not None
        assert "OPENAI_API_KEY" in result


def test_check_api_keys_all_present():
    cfg = {
        "api_keys": {"GEMINI_API_KEY": "key"},
        "litellm_summarization_model": "gemini/gemini-2.5-flash",
    }
    result = check_api_keys(cfg, "gemini", "litellm")
    assert result is None


def test_resolve_api_key_from_config():
    cfg = {"api_keys": {"GEMINI_API_KEY": "cfg-key"}}
    assert resolve_api_key(cfg, "GEMINI_API_KEY") == "cfg-key"


def test_resolve_api_key_from_env():
    cfg = {"api_keys": {}}
    with patch.dict(os.environ, {"GEMINI_API_KEY": "env-key"}):
        assert resolve_api_key(cfg, "GEMINI_API_KEY") == "env-key"


def test_resolve_api_key_missing():
    cfg = {"api_keys": {}}
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("GEMINI_API_KEY", None)
        assert resolve_api_key(cfg, "GEMINI_API_KEY") == ""
