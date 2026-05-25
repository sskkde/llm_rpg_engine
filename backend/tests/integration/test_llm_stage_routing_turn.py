"""
Integration tests for stage-level LLM routing.

Tests:
- Default routing with config_source verification
- Stage env override with config_source and fallback_used verification
- Global env fallback with config_source verification
- use_mock=True override behavior
- Debug endpoint response structure
"""

import pytest

from llm_rpg.llm.stage_provider_resolver import resolve_stage_llm_config
from llm_rpg.models.llm_stage_routing import (
    GLOBAL_ENV_VAR_MAP,
    STAGE_ENV_VAR_MAP,
)


def _clear_all_llm_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Delete all LLM-related env vars to ensure clean test state."""
    for stage_map in STAGE_ENV_VAR_MAP.values():
        for var in stage_map.values():
            monkeypatch.delenv(var, raising=False)
    for var in GLOBAL_ENV_VAR_MAP.values():
        monkeypatch.delenv(var, raising=False)


# =============================================================================
# Test 1: Default Routing (No Env Vars)
# =============================================================================

class TestDefaultRouting:
    """Test default routing when no env vars are set."""

    def test_input_intent_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """input_intent stage uses correct defaults with stage_default config_source."""
        _clear_all_llm_env_vars(monkeypatch)

        config = resolve_stage_llm_config("input_intent", {}, use_mock=False)

        # Verify default values
        assert config.timeout_seconds == 15.0
        assert config.max_tokens == 200
        assert config.temperature == 0.3

        # Verify config_source indicates stage_default
        assert config.config_source == "stage_default"
        assert config.fallback_used is True

    def test_world_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """world stage uses correct defaults with stage_default config_source."""
        _clear_all_llm_env_vars(monkeypatch)

        config = resolve_stage_llm_config("world", {}, use_mock=False)

        # Verify default values (different from input_intent)
        assert config.timeout_seconds == 30.0
        assert config.max_tokens == 500
        assert config.temperature == 0.8

        # Verify config_source indicates stage_default
        assert config.config_source == "stage_default"
        assert config.fallback_used is True

    def test_input_intent_differs_from_other_stages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """input_intent defaults differ from world/scene/npc/narration stages."""
        _clear_all_llm_env_vars(monkeypatch)

        input_intent_config = resolve_stage_llm_config("input_intent", {}, use_mock=False)
        world_config = resolve_stage_llm_config("world", {}, use_mock=False)

        # input_intent has lower timeout, fewer tokens, lower temperature
        assert input_intent_config.timeout_seconds < world_config.timeout_seconds
        assert input_intent_config.max_tokens < world_config.max_tokens
        assert input_intent_config.temperature < world_config.temperature


# =============================================================================
# Test 2: Stage Env Override
# =============================================================================

class TestStageEnvOverride:
    """Test stage-specific env var override."""

    def test_stage_env_temperature_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Stage env var overrides default, config_source contains stage_env."""
        _clear_all_llm_env_vars(monkeypatch)
        monkeypatch.setenv("LLM_INPUT_INTENT_TEMPERATURE", "0.5")

        config = resolve_stage_llm_config("input_intent", {}, use_mock=False)

        # Verify override value
        assert config.temperature == 0.5

        # Verify config_source indicates stage_env (or mixed with stage_env)
        assert "stage_env" in config.config_source

        # fallback_used should be True because only temperature came from stage_env
        # (other params still use defaults)
        assert config.fallback_used is True

    def test_partial_stage_env_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Partial stage env override (only temperature) results in mixed config_source."""
        _clear_all_llm_env_vars(monkeypatch)
        monkeypatch.setenv("LLM_INPUT_INTENT_TEMPERATURE", "0.5")

        config = resolve_stage_llm_config("input_intent", {}, use_mock=False)

        # Temperature from stage_env
        assert config.temperature == 0.5

        # Other params from defaults
        assert config.timeout_seconds == 15.0
        assert config.max_tokens == 200

        # config_source should be mixed (stage_env + stage_default)
        assert "stage_env" in config.config_source
        assert "stage_default" in config.config_source


# =============================================================================
# Test 3: Global Env Fallback
# =============================================================================

class TestGlobalEnvFallback:
    """Test global env var fallback when no stage env vars are set."""

    def test_global_env_temperature_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Global env var used when stage env var not set, config_source contains global_env."""
        _clear_all_llm_env_vars(monkeypatch)
        monkeypatch.setenv("LLM_TEMPERATURE", "0.6")

        config = resolve_stage_llm_config("input_intent", {}, use_mock=False)

        # Verify global env value
        assert config.temperature == 0.6

        # Verify config_source contains global_env
        assert "global_env" in config.config_source

        # fallback_used should be True
        assert config.fallback_used is True

    def test_global_env_applies_to_all_stages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Global env var applies to all stages when no stage-specific override."""
        _clear_all_llm_env_vars(monkeypatch)
        monkeypatch.setenv("LLM_TEMPERATURE", "0.6")

        input_intent_config = resolve_stage_llm_config("input_intent", {}, use_mock=False)
        world_config = resolve_stage_llm_config("world", {}, use_mock=False)

        # Both stages use global env temperature
        assert input_intent_config.temperature == 0.6
        assert world_config.temperature == 0.6

        # Both have global_env in config_source
        assert "global_env" in input_intent_config.config_source
        assert "global_env" in world_config.config_source


# =============================================================================
# Test 4: use_mock=True Override
# =============================================================================

class TestMockOverride:
    """Test use_mock=True forces mock provider."""

    def test_mock_override_forces_mock_provider(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """use_mock=True forces provider_mode='mock' regardless of env vars."""
        _clear_all_llm_env_vars(monkeypatch)
        monkeypatch.setenv("LLM_PROVIDER_MODE", "openai")

        config = resolve_stage_llm_config("input_intent", {}, use_mock=True)

        # Verify mock provider is forced
        assert config.provider_mode == "mock"

        # Verify config_source is mock_override
        assert config.config_source == "mock_override"

        # fallback_used should be False for mock override
        assert config.fallback_used is False

    def test_mock_override_ignores_stage_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """use_mock=True ignores stage-specific env vars."""
        _clear_all_llm_env_vars(monkeypatch)
        monkeypatch.setenv("LLM_INPUT_INTENT_PROVIDER_MODE", "openai")
        monkeypatch.setenv("LLM_INPUT_INTENT_TEMPERATURE", "0.9")

        config = resolve_stage_llm_config("input_intent", {}, use_mock=True)

        # Mock is forced, env vars ignored
        assert config.provider_mode == "mock"
        assert config.config_source == "mock_override"

        # Temperature should come from stage defaults (not env var)
        assert config.temperature == 0.3


# =============================================================================
# Test 5: Debug Endpoint via TestClient
# =============================================================================

class TestDebugEndpoint:
    """Test debug endpoint response structure."""

    def test_debug_endpoint_structure(self, client, monkeypatch: pytest.MonkeyPatch) -> None:
        """Debug endpoint returns correct structure with all 5 stages."""
        _clear_all_llm_env_vars(monkeypatch)

        from llm_rpg.storage.models import UserModel
        from llm_rpg.api.auth import get_current_active_user
        from llm_rpg.main import app

        mock_admin = UserModel(
            id="test_admin_id",
            username="test_admin",
            email="admin@test.com",
            password_hash="test_hash",
            is_admin=True,
        )

        def override_get_current_active_user():
            return mock_admin

        app.dependency_overrides[get_current_active_user] = override_get_current_active_user

        try:
            response = client.get("/debug/llm/stage-routing/resolved")

            assert response.status_code == 200

            data = response.json()

            assert "stages" in data
            stages = data["stages"]
            assert "input_intent" in stages
            assert "world" in stages
            assert "scene" in stages
            assert "npc" in stages
            assert "narration" in stages

            for stage_name in ["input_intent", "world", "scene", "npc", "narration"]:
                stage = stages[stage_name]
                assert "config_source" in stage
                assert "fallback_used" in stage
                assert "provider_mode" in stage
                assert "temperature" in stage
                assert "max_tokens" in stage
                assert "timeout_seconds" in stage

            assert "global_env_vars" in data
            assert "global_settings" in data

        finally:
            app.dependency_overrides.pop(get_current_active_user, None)

    def test_debug_endpoint_with_env_vars(
        self, client, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Debug endpoint reflects env var status correctly."""
        _clear_all_llm_env_vars(monkeypatch)
        monkeypatch.setenv("LLM_TEMPERATURE", "0.7")

        from llm_rpg.storage.models import UserModel
        from llm_rpg.api.auth import get_current_active_user
        from llm_rpg.main import app

        mock_admin = UserModel(
            id="test_admin_id",
            username="test_admin",
            email="admin@test.com",
            password_hash="test_hash",
            is_admin=True,
        )

        def override_get_current_active_user():
            return mock_admin

        app.dependency_overrides[get_current_active_user] = override_get_current_active_user

        try:
            response = client.get("/debug/llm/stage-routing/resolved")
            assert response.status_code == 200

            data = response.json()

            global_env_vars = data["global_env_vars"]
            assert global_env_vars.get("LLM_TEMPERATURE") == "set"

            for stage_name in ["input_intent", "world"]:
                stage = data["stages"][stage_name]
                assert stage["temperature"] == 0.7
                assert "global_env" in stage["config_source"]

        finally:
            app.dependency_overrides.pop(get_current_active_user, None)
