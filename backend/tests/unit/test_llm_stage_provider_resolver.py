"""Unit tests for stage_provider_resolver — env var fallback chain for per-stage LLM config."""

import pytest

from llm_rpg.llm.stage_provider_resolver import resolve_stage_llm_config
from llm_rpg.models.llm_stage_routing import (
    GLOBAL_ENV_VAR_MAP,
    STAGE_DEFAULTS,
    STAGE_ENV_VAR_MAP,
)


def _clear_all_llm_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Delete all LLM-related env vars to ensure clean test state."""
    for stage_map in STAGE_ENV_VAR_MAP.values():
        for var in stage_map.values():
            monkeypatch.delenv(var, raising=False)
    for var in GLOBAL_ENV_VAR_MAP.values():
        monkeypatch.delenv(var, raising=False)


class TestAllStageEnvVars:
    """Set all stage env vars for input_intent → each matches, config_source=stage_env, fallback_used=False."""

    def test_all_stage_env_vars_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_all_llm_env_vars(monkeypatch)
        monkeypatch.setenv("LLM_INPUT_INTENT_PROVIDER_MODE", "openai")
        monkeypatch.setenv("LLM_INPUT_INTENT_DEFAULT_MODEL", "gpt-4-turbo")
        monkeypatch.setenv("LLM_INPUT_INTENT_TEMPERATURE", "0.5")
        monkeypatch.setenv("LLM_INPUT_INTENT_MAX_TOKENS", "300")
        monkeypatch.setenv("LLM_INPUT_INTENT_TIMEOUT", "20.0")

        config = resolve_stage_llm_config("input_intent", {})

        assert config.provider_mode == "openai"
        assert config.default_model == "gpt-4-turbo"
        assert config.temperature == 0.5
        assert config.max_tokens == 300
        assert config.timeout_seconds == 20.0
        assert config.fallback_used is False


class TestGlobalEnvFallback:
    """No stage env vars, set global env vars → all from global, config_source=global_env, fallback_used=True."""

    def test_global_env_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_all_llm_env_vars(monkeypatch)
        monkeypatch.setenv("LLM_PROVIDER_MODE", "openai")
        monkeypatch.setenv("LLM_DEFAULT_MODEL", "gpt-4")
        monkeypatch.setenv("LLM_TEMPERATURE", "0.7")
        monkeypatch.setenv("LLM_MAX_TOKENS", "400")
        monkeypatch.setenv("LLM_TIMEOUT", "25.0")

        config = resolve_stage_llm_config("input_intent", {})

        assert config.provider_mode == "openai"
        assert config.default_model == "gpt-4"
        assert config.temperature == 0.7
        assert config.max_tokens == 400
        assert config.timeout_seconds == 25.0
        assert config.fallback_used is True


class TestGlobalSettingsFallback:
    """No env vars, pass global_provider_config → config_source=global_settings."""

    def test_global_settings_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_all_llm_env_vars(monkeypatch)
        global_config = {
            "provider_mode": "auto",
            "default_model": "gpt-4",
            "temperature": 0.7,
        }

        config = resolve_stage_llm_config("input_intent", global_config)

        assert config.provider_mode == "auto"
        assert config.default_model == "gpt-4"
        assert config.temperature == 0.7
        assert config.fallback_used is True


class TestStageDefault:
    """No env vars, empty global config → values match STAGE_DEFAULTS, config_source=stage_default."""

    def test_stage_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_all_llm_env_vars(monkeypatch)

        config = resolve_stage_llm_config("input_intent", {})

        defaults = STAGE_DEFAULTS["input_intent"]
        assert config.timeout_seconds == defaults["timeout_seconds"]
        assert config.max_tokens == defaults["max_tokens"]
        assert config.temperature == defaults["temperature"]
        assert config.fallback_used is True


class TestMockOverride:
    """Set LLM_PROVIDER_MODE=openai, call with use_mock=True → provider_mode="mock"."""

    def test_mock_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_all_llm_env_vars(monkeypatch)
        monkeypatch.setenv("LLM_PROVIDER_MODE", "openai")

        config = resolve_stage_llm_config("input_intent", {}, use_mock=True)

        assert config.provider_mode == "mock"
        assert config.config_source == "mock_override"
        assert config.fallback_used is False


class TestInputIntentDefaults:
    """No overrides → input_intent has 15.0/200/0.3."""

    def test_input_intent_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_all_llm_env_vars(monkeypatch)

        config = resolve_stage_llm_config("input_intent", {})

        assert config.timeout_seconds == 15.0
        assert config.max_tokens == 200
        assert config.temperature == 0.3


class TestWorldDefaults:
    """No overrides → world has 30.0/500/0.8."""

    def test_world_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_all_llm_env_vars(monkeypatch)

        config = resolve_stage_llm_config("world", {})

        assert config.timeout_seconds == 30.0
        assert config.max_tokens == 500
        assert config.temperature == 0.8


class TestInvalidEnvVar:
    """Set LLM_INPUT_INTENT_TEMPERATURE="not_a_number" → graceful fallback to 0.3, no crash."""

    def test_invalid_env_var_fallback(self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
        _clear_all_llm_env_vars(monkeypatch)
        monkeypatch.setenv("LLM_INPUT_INTENT_TEMPERATURE", "not_a_number")

        with caplog.at_level("WARNING"):
            config = resolve_stage_llm_config("input_intent", {})

        assert config.temperature == 0.3
        assert config.fallback_used is True


class TestPartialOverride:
    """Only set LLM_INPUT_INTENT_TEMPERATURE=0.1 → temperature from stage_env, rest from defaults, fallback_used=True."""

    def test_partial_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_all_llm_env_vars(monkeypatch)
        monkeypatch.setenv("LLM_INPUT_INTENT_TEMPERATURE", "0.1")

        config = resolve_stage_llm_config("input_intent", {})

        assert config.temperature == 0.1
        assert config.timeout_seconds == 15.0
        assert config.max_tokens == 200
        assert config.fallback_used is True


class TestFallbackUsedFalse:
    """All stage env vars set → fallback_used=False."""

    def test_fallback_used_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_all_llm_env_vars(monkeypatch)
        for param, env_var in STAGE_ENV_VAR_MAP["input_intent"].items():
            if param in ("temperature", "timeout_seconds"):
                monkeypatch.setenv(env_var, "0.5")
            elif param == "max_tokens":
                monkeypatch.setenv(env_var, "300")
            else:
                monkeypatch.setenv(env_var, "openai")

        config = resolve_stage_llm_config("input_intent", {})

        assert config.fallback_used is False


class TestFallbackChainPriority:
    """Stage env var takes priority over global env var and global_provider_config."""

    def test_stage_env_over_global_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_all_llm_env_vars(monkeypatch)
        monkeypatch.setenv("LLM_INPUT_INTENT_TEMPERATURE", "0.1")
        monkeypatch.setenv("LLM_TEMPERATURE", "0.9")

        config = resolve_stage_llm_config("input_intent", {})

        assert config.temperature == 0.1

    def test_global_env_over_global_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_all_llm_env_vars(monkeypatch)
        monkeypatch.setenv("LLM_TEMPERATURE", "0.6")

        config = resolve_stage_llm_config("input_intent", {"temperature": 0.9})

        assert config.temperature == 0.6

    def test_global_settings_over_stage_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _clear_all_llm_env_vars(monkeypatch)

        config = resolve_stage_llm_config("input_intent", {"temperature": 0.9})

        assert config.temperature == 0.9
