"""Stage-level LLM provider resolver with env var fallback chain.

Resolves per-stage LLM configuration (provider_mode, default_model,
temperature, max_tokens, timeout_seconds) via a four-tier fallback chain:
    stage-specific env var → global env var → global_settings dict → stage defaults
"""

import logging
import os
from typing import Any

from llm_rpg.models.llm_stage_routing import (
    GLOBAL_ENV_VAR_MAP,
    LLMStageName,
    STAGE_DEFAULTS,
    STAGE_ENV_VAR_MAP,
    StageLLMConfig,
)

logger = logging.getLogger(__name__)

_NUMERIC_PARAMS: dict[str, type] = {"temperature": float, "max_tokens": int, "timeout_seconds": float}


def resolve_stage_llm_config(
    stage_name: LLMStageName,
    global_provider_config: dict[str, Any],
    use_mock: bool = False,
) -> StageLLMConfig:
    """Resolve LLM configuration for a single stage via fallback chain.

    Resolution order per parameter:
      1. If use_mock=True → provider_mode="mock", others from STAGE_DEFAULTS,
         config_source="mock_override"
      2. Stage-specific env var (STAGE_ENV_VAR_MAP[stage_name][param])
         → config_source="stage_env"
      3. Global env var (GLOBAL_ENV_VAR_MAP[param])
         → config_source="global_env"
      4. global_provider_config dict key
         → config_source="global_settings"
      5. STAGE_DEFAULTS[stage_name][param]
         → config_source="stage_default"

    Args:
        stage_name: The stage to resolve config for.
        global_provider_config: Dict with global LLM settings (e.g. from DB).
        use_mock: If True, force provider_mode="mock" and ignore env vars.

    Returns:
        A fully-resolved StageLLMConfig instance.
    """
    stage_defaults = STAGE_DEFAULTS[stage_name]
    stage_env_map = STAGE_ENV_VAR_MAP[stage_name]

    if use_mock:
        return StageLLMConfig(
            stage_name=stage_name,
            provider_mode="mock",
            default_model=stage_defaults.get("default_model", ""),
            temperature=stage_defaults.get("temperature", 0.5),
            max_tokens=stage_defaults.get("max_tokens", 200),
            timeout_seconds=stage_defaults.get("timeout_seconds", 15.0),
            config_source="mock_override",
            fallback_used=False,
        )

    resolved: dict[str, Any] = {}
    sources: dict[str, str] = {}
    fallback_used = False

    for param in ["provider_mode", "default_model", "temperature", "max_tokens", "timeout_seconds"]:
        value, source = _resolve_param(
            param, stage_name, stage_env_map, global_provider_config, stage_defaults
        )
        resolved[param] = value
        sources[param] = source

        if source in ("global_env", "global_settings", "stage_default"):
            fallback_used = True

    source_priority = {"stage_env": 0, "global_env": 1, "global_settings": 2, "stage_default": 3}
    aggregate_source = min(sources.values(), key=lambda s: source_priority.get(s, 99))
    unique_sources = set(sources.values())
    if len(unique_sources) > 1:
        aggregate_source = "mixed:" + ",".join(
            sorted(unique_sources, key=lambda s: source_priority.get(s, 99))
        )

    logger.info(
        "Resolved LLM config for stage '%s': source=%s, fallback_used=%s",
        stage_name,
        aggregate_source,
        fallback_used,
    )

    return StageLLMConfig(
        stage_name=stage_name,
        provider_mode=resolved["provider_mode"],
        default_model=resolved["default_model"],
        temperature=resolved["temperature"],
        max_tokens=resolved["max_tokens"],
        timeout_seconds=resolved["timeout_seconds"],
        config_source=aggregate_source,
        fallback_used=fallback_used,
    )


def _resolve_param(
    param: str,
    stage_name: LLMStageName,
    stage_env_map: dict[str, str],
    global_provider_config: dict[str, Any],
    stage_defaults: dict[str, Any],
) -> tuple[Any, str]:
    """Resolve a single parameter through the fallback chain.

    Returns:
        A tuple of (resolved_value, config_source).
    """
    # Step 2: Check stage-specific env var
    stage_env_var = stage_env_map.get(param)
    if stage_env_var:
        env_val = os.getenv(stage_env_var)
        if env_val is not None and env_val != "":
            coerced = _coerce_param(param, env_val, stage_env_var, stage_defaults)
            if coerced is not None:
                logger.info(
                    "Stage '%s' param '%s' from stage env var %s=%s",
                    stage_name,
                    param,
                    stage_env_var,
                    env_val,
                )
                return coerced, "stage_env"

    # Step 3: Check global env var
    global_env_var = GLOBAL_ENV_VAR_MAP.get(param)
    if global_env_var:
        env_val = os.getenv(global_env_var)
        if env_val is not None and env_val != "":
            coerced = _coerce_param(param, env_val, global_env_var, stage_defaults)
            if coerced is not None:
                logger.debug(
                    "Stage '%s' param '%s' from global env var %s=%s",
                    stage_name,
                    param,
                    global_env_var,
                    env_val,
                )
                return coerced, "global_env"

    # Step 4: Check global_provider_config dict
    if param in global_provider_config:
        value = global_provider_config[param]
        if isinstance(value, str) and param in _NUMERIC_PARAMS:
            try:
                value = _NUMERIC_PARAMS[param](value)
            except (ValueError, TypeError):
                logger.warning(
                    "Invalid value '%s' for param '%s' in global_provider_config, "
                    + "falling back to stage default",
                    value,
                    param,
                )
                return stage_defaults.get(param, _default_for_param(param)), "stage_default"
        logger.debug(
            "Stage '%s' param '%s' from global_provider_config",
            stage_name,
            param,
        )
        return value, "global_settings"

    # Step 5: Fallback to STAGE_DEFAULTS
    default_val = stage_defaults.get(param, _default_for_param(param))
    logger.debug(
        "Stage '%s' param '%s' from STAGE_DEFAULTS",
        stage_name,
        param,
    )
    return default_val, "stage_default"


def _coerce_param(
    param: str, raw_value: str, env_var_name: str, stage_defaults: dict[str, Any]
) -> Any:
    """Coerce an env var string to the correct type.

    Returns None (and logs warning) if coercion fails.
    """
    if param in _NUMERIC_PARAMS:
        coerce_fn = _NUMERIC_PARAMS[param]
        try:
            return coerce_fn(raw_value)
        except (ValueError, TypeError):
            logger.warning(
                "Invalid value '%s' for %s (env var %s), "
                + "falling back to stage default %s",
                raw_value,
                param,
                env_var_name,
                stage_defaults.get(param),
            )
            return None
    return raw_value


def _default_for_param(param: str) -> Any:
    _hardcoded_defaults: dict[str, Any] = {
        "provider_mode": "auto",
        "default_model": "gpt-4",
        "temperature": 0.5,
        "max_tokens": 200,
        "timeout_seconds": 15.0,
    }
    return _hardcoded_defaults.get(param)
