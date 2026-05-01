"""
Model Router

This module provides per-task model routing for different LLM use cases.
Routes tasks to appropriate models based on task requirements.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Type

from pydantic import BaseModel


class TaskType(Enum):
    """Types of LLM tasks requiring different models."""
    INTENT_PARSING = "intent_parsing"
    WORLD_SIMULATION = "world_simulation"
    NPC_DECISION = "npc_decision"
    CONFLICT_RESOLUTION = "conflict_resolution"
    NARRATION = "narration"
    SUMMARY = "summary"
    MEMORY_EXTRACTION = "memory_extraction"
    LORE_RETRIEVAL = "lore_retrieval"
    VALIDATION_REPAIR = "validation_repair"


class ModelCapability(Enum):
    """Capabilities that models may have."""
    FAST = "fast"
    ACCURATE = "accurate"
    CHEAP = "cheap"
    LARGE_CONTEXT = "large_context"
    JSON_MODE = "json_mode"
    STREAMING = "streaming"


@dataclass
class ModelConfig:
    """Configuration for an LLM model."""
    model_id: str
    provider: str
    display_name: str
    max_tokens: int
    context_window: int
    capabilities: List[ModelCapability] = field(default_factory=list)
    cost_per_1k_input: float = 0.0
    cost_per_1k_output: float = 0.0
    temperature_default: float = 0.7
    supports_json_mode: bool = False
    supports_function_calling: bool = False
    fallback_models: List[str] = field(default_factory=list)


@dataclass
class RoutingDecision:
    """Result of a routing decision."""
    task_type: TaskType
    selected_model: str
    provider: str
    temperature: float
    max_tokens: int
    reasoning: str
    fallback_chain: List[str] = field(default_factory=list)
    estimated_cost: float = 0.0


class RoutingRule(ABC):
    """Abstract base class for routing rules."""
    
    @abstractmethod
    def evaluate(
        self,
        task_type: TaskType,
        available_models: Dict[str, ModelConfig],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """
        Evaluate this rule and return model ID if matched.
        
        Returns:
            Model ID if rule matches, None otherwise
        """
        pass


class TaskTypeRule(RoutingRule):
    """Route based on task type preferences."""
    
    TASK_PREFERENCES: Dict[TaskType, Dict[str, Any]] = {
        TaskType.INTENT_PARSING: {
            "needs": [ModelCapability.FAST, ModelCapability.JSON_MODE],
            "preferred": "gpt-3.5-turbo",
            "fallback": ["gpt-4o-mini", "gpt-4o"],
        },
        TaskType.WORLD_SIMULATION: {
            "needs": [ModelCapability.ACCURATE, ModelCapability.LARGE_CONTEXT],
            "preferred": "gpt-4o",
            "fallback": ["gpt-4", "claude-3-opus"],
        },
        TaskType.NPC_DECISION: {
            "needs": [ModelCapability.ACCURATE, ModelCapability.JSON_MODE],
            "preferred": "gpt-4o",
            "fallback": ["gpt-4", "gpt-3.5-turbo"],
        },
        TaskType.CONFLICT_RESOLUTION: {
            "needs": [ModelCapability.ACCURATE, ModelCapability.JSON_MODE],
            "preferred": "gpt-4o",
            "fallback": ["gpt-4", "claude-3-sonnet"],
        },
        TaskType.NARRATION: {
            "needs": [ModelCapability.ACCURATE],
            "preferred": "gpt-4o",
            "fallback": ["gpt-4", "claude-3-sonnet"],
        },
        TaskType.SUMMARY: {
            "needs": [ModelCapability.LARGE_CONTEXT],
            "preferred": "gpt-4o",
            "fallback": ["gpt-3.5-turbo-16k", "gpt-4"],
        },
        TaskType.MEMORY_EXTRACTION: {
            "needs": [ModelCapability.ACCURATE, ModelCapability.JSON_MODE],
            "preferred": "gpt-4o",
            "fallback": ["gpt-4", "gpt-3.5-turbo"],
        },
        TaskType.LORE_RETRIEVAL: {
            "needs": [ModelCapability.ACCURATE],
            "preferred": "gpt-4o",
            "fallback": ["gpt-4", "claude-3-sonnet"],
        },
        TaskType.VALIDATION_REPAIR: {
            "needs": [ModelCapability.ACCURATE, ModelCapability.JSON_MODE],
            "preferred": "gpt-4o",
            "fallback": ["gpt-4", "gpt-3.5-turbo"],
        },
    }
    
    def evaluate(
        self,
        task_type: TaskType,
        available_models: Dict[str, ModelConfig],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Evaluate task type preference rule."""
        prefs = self.TASK_PREFERENCES.get(task_type)
        if not prefs:
            return None
        
        preferred = prefs["preferred"]
        if preferred in available_models:
            return preferred
        
        for fallback in prefs.get("fallback", []):
            if fallback in available_models:
                return fallback
        
        return None


class CostOptimizationRule(RoutingRule):
    """Route to cheapest model that meets requirements."""
    
    def __init__(self, cost_threshold: float = 0.01):
        self.cost_threshold = cost_threshold
    
    def evaluate(
        self,
        task_type: TaskType,
        available_models: Dict[str, ModelConfig],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Evaluate cost optimization rule."""
        context_data = context or {}
        optimize_cost = context_data.get("optimize_cost", False)
        
        if not optimize_cost:
            return None
        
        task_prefs = TaskTypeRule.TASK_PREFERENCES.get(task_type, {})
        needed_caps = set(task_prefs.get("needs", []))
        
        candidates = []
        for model_id, config in available_models.items():
            model_caps = set(config.capabilities)
            if needed_caps.issubset(model_caps):
                total_cost = config.cost_per_1k_input + config.cost_per_1k_output
                candidates.append((model_id, total_cost))
        
        if candidates:
            candidates.sort(key=lambda x: x[1])
            if candidates[0][1] <= self.cost_threshold:
                return candidates[0][0]
        
        return None


class SpeedPriorityRule(RoutingRule):
    """Route to fastest model when speed is prioritized."""
    
    def evaluate(
        self,
        task_type: TaskType,
        available_models: Dict[str, ModelConfig],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Evaluate speed priority rule."""
        context_data = context or {}
        prioritize_speed = context_data.get("prioritize_speed", False)
        
        if not prioritize_speed:
            return None
        
        task_prefs = TaskTypeRule.TASK_PREFERENCES.get(task_type, {})
        needed_caps = set(task_prefs.get("needs", []))
        needed_caps.add(ModelCapability.FAST)
        
        for model_id, config in available_models.items():
            model_caps = set(config.capabilities)
            if needed_caps.issubset(model_caps):
                return model_id
        
        return None


class ContextSizeRule(RoutingRule):
    """Route based on required context window size."""
    
    def evaluate(
        self,
        task_type: TaskType,
        available_models: Dict[str, ModelConfig],
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Evaluate context size requirement rule."""
        context_data = context or {}
        required_context = context_data.get("required_context_tokens", 0)
        
        if not required_context:
            return None
        
        task_prefs = TaskTypeRule.TASK_PREFERENCES.get(task_type, {})
        needed_caps = set(task_prefs.get("needs", []))
        
        candidates = []
        for model_id, config in available_models.items():
            model_caps = set(config.capabilities)
            if needed_caps.issubset(model_caps):
                if config.context_window >= required_context:
                    candidates.append((model_id, config.context_window))
        
        if candidates:
            candidates.sort(key=lambda x: x[1])
            return candidates[0][0]
        
        return None


class ModelRouter:
    """
    Routes LLM tasks to appropriate models based on task requirements.
    
    The router:
    1. Evaluates task type and requirements
    2. Applies routing rules in priority order
    3. Builds fallback chain for resilience
    4. Estimates costs for the routing decision
    5. Provides detailed routing reasoning
    """
    
    DEFAULT_MODELS: Dict[str, ModelConfig] = {
        "gpt-4o": ModelConfig(
            model_id="gpt-4o",
            provider="openai",
            display_name="GPT-4o",
            max_tokens=4096,
            context_window=128000,
            capabilities=[
                ModelCapability.ACCURATE,
                ModelCapability.LARGE_CONTEXT,
                ModelCapability.JSON_MODE,
                ModelCapability.STREAMING,
            ],
            cost_per_1k_input=0.005,
            cost_per_1k_output=0.015,
            temperature_default=0.7,
            supports_json_mode=True,
            supports_function_calling=True,
            fallback_models=["gpt-4", "gpt-3.5-turbo"],
        ),
        "gpt-4": ModelConfig(
            model_id="gpt-4",
            provider="openai",
            display_name="GPT-4",
            max_tokens=4096,
            context_window=8192,
            capabilities=[
                ModelCapability.ACCURATE,
                ModelCapability.JSON_MODE,
                ModelCapability.STREAMING,
            ],
            cost_per_1k_input=0.03,
            cost_per_1k_output=0.06,
            temperature_default=0.7,
            supports_json_mode=True,
            supports_function_calling=True,
            fallback_models=["gpt-3.5-turbo"],
        ),
        "gpt-3.5-turbo": ModelConfig(
            model_id="gpt-3.5-turbo",
            provider="openai",
            display_name="GPT-3.5 Turbo",
            max_tokens=4096,
            context_window=16385,
            capabilities=[
                ModelCapability.FAST,
                ModelCapability.CHEAP,
                ModelCapability.JSON_MODE,
                ModelCapability.STREAMING,
            ],
            cost_per_1k_input=0.0015,
            cost_per_1k_output=0.002,
            temperature_default=0.7,
            supports_json_mode=True,
            supports_function_calling=True,
            fallback_models=[],
        ),
        "gpt-4o-mini": ModelConfig(
            model_id="gpt-4o-mini",
            provider="openai",
            display_name="GPT-4o Mini",
            max_tokens=4096,
            context_window=128000,
            capabilities=[
                ModelCapability.FAST,
                ModelCapability.CHEAP,
                ModelCapability.JSON_MODE,
                ModelCapability.STREAMING,
            ],
            cost_per_1k_input=0.00015,
            cost_per_1k_output=0.0006,
            temperature_default=0.7,
            supports_json_mode=True,
            supports_function_calling=True,
            fallback_models=["gpt-3.5-turbo"],
        ),
    }
    
    def __init__(
        self,
        models: Optional[Dict[str, ModelConfig]] = None,
        rules: Optional[List[RoutingRule]] = None,
        default_model: str = "gpt-4o",
    ):
        self.models = models or self.DEFAULT_MODELS.copy()
        self.default_model = default_model
        self._routing_history: List[RoutingDecision] = []
        
        self.rules = rules or [
            SpeedPriorityRule(),
            CostOptimizationRule(),
            ContextSizeRule(),
            TaskTypeRule(),
        ]
    
    def register_model(self, config: ModelConfig):
        """Register a new model configuration."""
        self.models[config.model_id] = config
    
    def unregister_model(self, model_id: str):
        """Unregister a model configuration."""
        if model_id in self.models:
            del self.models[model_id]
    
    def route(
        self,
        task_type: TaskType,
        context: Optional[Dict[str, Any]] = None,
    ) -> RoutingDecision:
        """
        Route a task to the appropriate model.
        
        Args:
            task_type: Type of task to route
            context: Optional routing context (speed priority, cost optimization, etc.)
            
        Returns:
            RoutingDecision with selected model and configuration
        """
        context = context or {}
        
        selected_model_id = None
        matched_rule = None
        
        for rule in self.rules:
            result = rule.evaluate(task_type, self.models, context)
            if result:
                selected_model_id = result
                matched_rule = type(rule).__name__
                break
        
        if not selected_model_id:
            selected_model_id = self.default_model
            matched_rule = "default_fallback"
        
        model_config = self.models.get(selected_model_id)
        if not model_config:
            selected_model_id = self.default_model
            model_config = self.models[self.default_model]
        
        fallback_chain = self._build_fallback_chain(selected_model_id, task_type)
        
        estimated_cost = self._estimate_cost(model_config, context)
        
        reasoning = self._build_reasoning(
            task_type, matched_rule, model_config, context
        )
        
        decision = RoutingDecision(
            task_type=task_type,
            selected_model=selected_model_id,
            provider=model_config.provider,
            temperature=context.get("temperature", model_config.temperature_default),
            max_tokens=min(
                context.get("max_tokens", model_config.max_tokens),
                model_config.max_tokens,
            ),
            reasoning=reasoning,
            fallback_chain=fallback_chain,
            estimated_cost=estimated_cost,
        )
        
        self._routing_history.append(decision)
        return decision
    
    def _build_fallback_chain(
        self,
        primary_model_id: str,
        task_type: TaskType,
    ) -> List[str]:
        """Build a chain of fallback models."""
        chain = []
        visited = {primary_model_id}
        
        model_config = self.models.get(primary_model_id)
        if not model_config:
            return chain
        
        for fallback_id in model_config.fallback_models:
            if fallback_id not in visited and fallback_id in self.models:
                chain.append(fallback_id)
                visited.add(fallback_id)
        
        task_prefs = TaskTypeRule.TASK_PREFERENCES.get(task_type, {})
        for fallback_id in task_prefs.get("fallback", []):
            if fallback_id not in visited and fallback_id in self.models:
                chain.append(fallback_id)
                visited.add(fallback_id)
        
        return chain
    
    def _estimate_cost(
        self,
        model_config: ModelConfig,
        context: Dict[str, Any],
    ) -> float:
        """Estimate the cost of the routing decision."""
        estimated_input_tokens = context.get("estimated_input_tokens", 1000)
        estimated_output_tokens = context.get("estimated_output_tokens", 500)
        
        input_cost = (estimated_input_tokens / 1000) * model_config.cost_per_1k_input
        output_cost = (estimated_output_tokens / 1000) * model_config.cost_per_1k_output
        
        return round(input_cost + output_cost, 6)
    
    def _build_reasoning(
        self,
        task_type: TaskType,
        matched_rule: str,
        model_config: ModelConfig,
        context: Dict[str, Any],
    ) -> str:
        """Build human-readable reasoning for the routing decision."""
        reasons = []
        
        reasons.append(f"Task type: {task_type.value}")
        reasons.append(f"Routing rule: {matched_rule}")
        reasons.append(f"Selected model: {model_config.display_name}")
        
        if context.get("prioritize_speed"):
            reasons.append("Speed prioritized")
        
        if context.get("optimize_cost"):
            reasons.append("Cost optimized")
        
        if context.get("required_context_tokens"):
            reasons.append(
                f"Context requirement: {context['required_context_tokens']} tokens"
            )
        
        return "; ".join(reasons)
    
    def get_next_fallback(self, current_model_id: str, chain: List[str]) -> Optional[str]:
        """Get the next model in the fallback chain."""
        if current_model_id not in chain:
            return chain[0] if chain else None
        
        try:
            idx = chain.index(current_model_id)
            if idx + 1 < len(chain):
                return chain[idx + 1]
        except ValueError:
            pass
        
        return None
    
    def get_routing_history(self) -> List[RoutingDecision]:
        """Get all routing decision history."""
        return self._routing_history.copy()
    
    def clear_history(self):
        """Clear routing history."""
        self._routing_history.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get routing statistics."""
        total = len(self._routing_history)
        
        by_task: Dict[str, int] = {}
        by_model: Dict[str, int] = {}
        total_cost = 0.0
        
        for decision in self._routing_history:
            task = decision.task_type.value
            by_task[task] = by_task.get(task, 0) + 1
            
            by_model[decision.selected_model] = by_model.get(decision.selected_model, 0) + 1
            
            total_cost += decision.estimated_cost
        
        return {
            "total_routes": total,
            "by_task_type": by_task,
            "by_model": by_model,
            "total_estimated_cost": round(total_cost, 6),
            "average_cost_per_route": round(total_cost / total, 6) if total > 0 else 0,
        }
    
    def get_model_info(self, model_id: str) -> Optional[ModelConfig]:
        """Get information about a registered model."""
        return self.models.get(model_id)
    
    def list_models(self) -> List[str]:
        """List all registered model IDs."""
        return list(self.models.keys())
    
    def list_models_by_capability(self, capability: ModelCapability) -> List[str]:
        """List models that have a specific capability."""
        return [
            model_id
            for model_id, config in self.models.items()
            if capability in config.capabilities
        ]
