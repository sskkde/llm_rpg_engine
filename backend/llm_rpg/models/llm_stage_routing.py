"""
LLM Stage Routing Configuration.

This module defines the stage routing configuration for LLM-enabled turn stages,
including stage names, configuration defaults, environment variable mappings,
and the configuration dataclass.
"""

from dataclasses import dataclass
from typing import Any, Dict, Literal

LLMStageName = Literal["input_intent", "world", "scene", "npc", "narration"]


@dataclass
class StageLLMConfig:
    """
    Configuration for a single LLM-enabled turn stage.
    
    Fields:
        stage_name: The stage identifier (input_intent, world, scene, npc, narration)
        provider_mode: The LLM provider mode (auto, openai, mock, custom)
        default_model: The default model identifier for this stage
        temperature: Sampling temperature for LLM calls (0.0-2.0)
        max_tokens: Maximum tokens for LLM response
        timeout_seconds: Timeout for LLM API calls in seconds
        config_source: Where the config was loaded from (defaults, env, db)
        fallback_used: Whether fallback defaults were used due to missing config
    """
    stage_name: LLMStageName
    provider_mode: str
    default_model: str
    temperature: float
    max_tokens: int
    timeout_seconds: float
    config_source: str
    fallback_used: bool


STAGE_DEFAULTS: Dict[LLMStageName, Dict[str, Any]] = {
    "input_intent": {
        "timeout_seconds": 15.0,
        "max_tokens": 200,
        "temperature": 0.3,
    },
    "world": {
        "timeout_seconds": 30.0,
        "max_tokens": 500,
        "temperature": 0.8,
    },
    "scene": {
        "timeout_seconds": 30.0,
        "max_tokens": 500,
        "temperature": 0.8,
    },
    "npc": {
        "timeout_seconds": 30.0,
        "max_tokens": 500,
        "temperature": 0.8,
    },
    "narration": {
        "timeout_seconds": 30.0,
        "max_tokens": 500,
        "temperature": 0.8,
    },
}


STAGE_ENV_VAR_MAP: Dict[LLMStageName, Dict[str, str]] = {
    "input_intent": {
        "provider_mode": "LLM_INPUT_INTENT_PROVIDER_MODE",
        "default_model": "LLM_INPUT_INTENT_DEFAULT_MODEL",
        "temperature": "LLM_INPUT_INTENT_TEMPERATURE",
        "max_tokens": "LLM_INPUT_INTENT_MAX_TOKENS",
        "timeout_seconds": "LLM_INPUT_INTENT_TIMEOUT",
    },
    "world": {
        "provider_mode": "LLM_WORLD_PROVIDER_MODE",
        "default_model": "LLM_WORLD_DEFAULT_MODEL",
        "temperature": "LLM_WORLD_TEMPERATURE",
        "max_tokens": "LLM_WORLD_MAX_TOKENS",
        "timeout_seconds": "LLM_WORLD_TIMEOUT",
    },
    "scene": {
        "provider_mode": "LLM_SCENE_PROVIDER_MODE",
        "default_model": "LLM_SCENE_DEFAULT_MODEL",
        "temperature": "LLM_SCENE_TEMPERATURE",
        "max_tokens": "LLM_SCENE_MAX_TOKENS",
        "timeout_seconds": "LLM_SCENE_TIMEOUT",
    },
    "npc": {
        "provider_mode": "LLM_NPC_PROVIDER_MODE",
        "default_model": "LLM_NPC_DEFAULT_MODEL",
        "temperature": "LLM_NPC_TEMPERATURE",
        "max_tokens": "LLM_NPC_MAX_TOKENS",
        "timeout_seconds": "LLM_NPC_TIMEOUT",
    },
    "narration": {
        "provider_mode": "LLM_NARRATION_PROVIDER_MODE",
        "default_model": "LLM_NARRATION_DEFAULT_MODEL",
        "temperature": "LLM_NARRATION_TEMPERATURE",
        "max_tokens": "LLM_NARRATION_MAX_TOKENS",
        "timeout_seconds": "LLM_NARRATION_TIMEOUT",
    },
}

GLOBAL_ENV_VAR_MAP: Dict[str, str] = {
    "provider_mode": "LLM_PROVIDER_MODE",
    "default_model": "LLM_DEFAULT_MODEL",
    "temperature": "LLM_TEMPERATURE",
    "max_tokens": "LLM_MAX_TOKENS",
    "timeout_seconds": "LLM_TIMEOUT",
}
