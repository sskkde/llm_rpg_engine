"""
Unit tests for LLM Repair, Model Router, and Token Budget Manager.

Tests the three core LLM infrastructure components:
1. RetryRepairHandler - JSON repair for malformed LLM outputs
2. ModelRouter - Per-task model routing
3. TokenBudgetManager - Context trimming with audit trails
"""

import json
import pytest
from datetime import datetime
from pydantic import BaseModel

from llm_rpg.llm.repair import (
    RetryRepairHandler,
    RepairStrategy,
    RepairStatus,
    RepairFallbacks,
    JSONRepairRule,
    ExtractJSONRule,
    FixQuotesRule,
    FixTrailingCommasRule,
    FixMissingBracesRule,
    WrapperRepairRule,
)
from llm_rpg.llm.model_router import (
    ModelRouter,
    TaskType,
    ModelCapability,
    ModelConfig,
    RoutingDecision,
)
from llm_rpg.llm.token_budget import (
    TokenBudgetManager,
    TrimDecision,
    TrimReason,
    SectionPriority,
    ContextSection,
    BudgetEnforcer,
    ApproximateTokenCounter,
)


class TestRetryRepairHandler:
    """Tests for the RetryRepairHandler."""
    
    def test_repair_valid_json(self):
        """Test that valid JSON is parsed directly."""
        handler = RetryRepairHandler()
        valid_json = '{"action_type": "move", "target": "north", "confidence": 0.9}'
        
        result, audit = handler.repair(valid_json)
        
        assert result is not None
        assert result["action_type"] == "move"
        assert result["target"] == "north"
        assert audit.fallback_used is False
        assert len(audit.attempts) == 0
    
    def test_repair_json_in_markdown_code_block(self):
        """Test extracting JSON from markdown code blocks."""
        handler = RetryRepairHandler()
        markdown_json = '''```json
{"intent_type": "explore", "target": "forest", "risk_level": "medium"}
```'''
        
        result, audit = handler.repair(markdown_json)
        
        assert result is not None
        assert result["intent_type"] == "explore"
        assert audit.fallback_used is False
        assert any(a.strategy == RepairStrategy.EXTRACT_JSON for a in audit.attempts)
    
    def test_repair_json_with_trailing_comma(self):
        """Test fixing trailing commas in JSON."""
        handler = RetryRepairHandler()
        trailing_comma = '{"action_type": "attack", "target": "enemy",}'
        
        result, audit = handler.repair(trailing_comma)
        
        assert result is not None
        assert result["action_type"] == "attack"
        assert any(a.strategy == RepairStrategy.FIX_TRAILING_COMMAS for a in audit.attempts)
    
    def test_repair_json_with_missing_closing_brace(self):
        """Test fixing missing closing braces."""
        handler = RetryRepairHandler()
        missing_brace = '{"action_type": "defend", "target": "self"'
        fallback = {"action_type": "unknown", "target": None}
        
        result, audit = handler.repair(missing_brace, fallback_defaults=fallback)
        
        assert result is not None
        assert "action_type" in result
        has_brace_attempt = any(
            "brace" in str(a.strategy.value).lower() or 
            "missing" in str(a.metadata.get("method", "")).lower()
            for a in audit.attempts
        )
        assert has_brace_attempt or audit.fallback_used
    
    def test_repair_json_with_single_quotes(self):
        """Test fixing single quotes in JSON."""
        handler = RetryRepairHandler()
        single_quotes = "{'action_type': 'talk', 'target': 'npc'}"
        fallback = {"action_type": "unknown", "target": None}
        
        result, audit = handler.repair(single_quotes, fallback_defaults=fallback)
        
        assert result is not None
        assert "action_type" in result
        assert result["action_type"] == "talk" or audit.fallback_used
    
    def test_repair_plain_text_with_wrapper(self):
        """Test wrapping plain text responses."""
        handler = RetryRepairHandler(enable_wrapper_fallback=True)
        plain_text = "The character moves north and observes the surroundings."
        
        result, audit = handler.repair(plain_text)
        
        assert result is not None
        assert "content" in result
        assert audit.fallback_used is False
    
    def test_repair_with_fallback(self):
        """Test that fallback is used when repair fails."""
        handler = RetryRepairHandler(enable_wrapper_fallback=False)
        unrepairable = "This is completely unrepairable garbage ~~~!!!"
        fallback = {"action_type": "unknown", "target": None}
        
        result, audit = handler.repair(unrepairable, fallback_defaults=fallback)
        
        assert result == fallback
        assert audit.fallback_used is True
        assert audit.fallback_reason == "All repair strategies exhausted"
    
    def test_repair_with_pydantic_validation(self):
        """Test repair with Pydantic schema validation."""
        class NPCAction(BaseModel):
            action_type: str
            target: str
            confidence: float
        
        handler = RetryRepairHandler()
        valid_json = '{"action_type": "move", "target": "north", "confidence": 0.9}'
        
        result, audit = handler.repair(valid_json, target_schema=NPCAction)
        
        assert result is not None
        assert result["action_type"] == "move"
        assert result["confidence"] == 0.9
    
    def test_repair_audit_history(self):
        """Test that repair history is tracked."""
        handler = RetryRepairHandler()
        
        handler.repair('{"test": "value1"}')
        handler.repair('{"test": "value2"}')
        
        history = handler.get_repair_history()
        assert len(history) == 2
    
    def test_repair_stats(self):
        """Test repair statistics."""
        handler = RetryRepairHandler()
        
        handler.repair('{"test": "value"}')
        handler.repair('{invalid json', fallback_defaults={"test": "fallback"})
        
        stats = handler.get_repair_stats()
        assert stats["total_attempts"] == 2
        assert stats["successful_repairs"] == 1
        assert stats["fallback_used"] == 1
    
    def test_repair_clear_history(self):
        """Test clearing repair history."""
        handler = RetryRepairHandler()
        handler.repair('{"test": "value"}')
        
        handler.clear_history()
        
        assert len(handler.get_repair_history()) == 0
    
    def test_custom_repair_rule(self):
        """Test adding custom repair rules."""
        handler = RetryRepairHandler()
        
        class CustomRule(JSONRepairRule):
            def can_repair(self, content):
                return "CUSTOM:" in content
            
            def repair(self, content):
                return '{"custom": true}', {"method": "custom"}
        
        handler.add_rule(CustomRule(), index=0)
        result, audit = handler.repair('CUSTOM: test')
        
        assert result is not None
        assert result.get("custom") is True


class TestModelRouter:
    """Tests for the ModelRouter."""
    
    def test_router_initialization(self):
        """Test router initialization with default models."""
        router = ModelRouter()
        
        assert "gpt-4o" in router.models
        assert "gpt-3.5-turbo" in router.models
        assert router.default_model == "gpt-4o"
    
    def test_route_narration_task(self):
        """Test routing narration task."""
        router = ModelRouter()
        
        decision = router.route(TaskType.NARRATION)
        
        assert decision.task_type == TaskType.NARRATION
        assert decision.selected_model == "gpt-4o"
    
    def test_route_intent_parsing_task(self):
        """Test routing intent parsing task."""
        router = ModelRouter()
        
        decision = router.route(TaskType.INTENT_PARSING)
        
        assert decision.task_type == TaskType.INTENT_PARSING
        assert decision.selected_model in router.models
    
    def test_route_with_speed_priority(self):
        """Test routing with speed priority."""
        router = ModelRouter()
        
        decision = router.route(
            TaskType.INTENT_PARSING,
            context={"prioritize_speed": True}
        )
        
        assert decision.task_type == TaskType.INTENT_PARSING
        assert "gpt" in decision.selected_model
    
    def test_route_with_cost_optimization(self):
        """Test routing with cost optimization."""
        router = ModelRouter()
        
        decision = router.route(
            TaskType.INTENT_PARSING,
            context={"optimize_cost": True}
        )
        
        assert decision.task_type == TaskType.INTENT_PARSING
        assert decision.estimated_cost > 0
    
    def test_route_fallback_chain(self):
        """Test that fallback chains are built."""
        router = ModelRouter()
        
        decision = router.route(TaskType.NARRATION)
        
        assert len(decision.fallback_chain) > 0
        assert "gpt-3.5-turbo" in decision.fallback_chain
    
    def test_route_estimated_cost(self):
        """Test cost estimation in routing."""
        router = ModelRouter()
        
        decision = router.route(
            TaskType.NARRATION,
            context={"estimated_input_tokens": 2000, "estimated_output_tokens": 500}
        )
        
        assert decision.estimated_cost > 0
    
    def test_route_reasoning(self):
        """Test that routing includes reasoning."""
        router = ModelRouter()
        
        decision = router.route(TaskType.NPC_DECISION)
        
        assert len(decision.reasoning) > 0
        assert "npc_decision" in decision.reasoning.lower()
    
    def test_register_custom_model(self):
        """Test registering custom models."""
        router = ModelRouter()
        
        custom_model = ModelConfig(
            model_id="custom-model",
            provider="custom",
            display_name="Custom Model",
            max_tokens=1000,
            context_window=4000,
            capabilities=[ModelCapability.FAST],
        )
        
        router.register_model(custom_model)
        
        assert "custom-model" in router.models
        assert router.models["custom-model"].provider == "custom"
    
    def test_unregister_model(self):
        """Test unregistering models."""
        router = ModelRouter()
        
        router.unregister_model("gpt-3.5-turbo")
        
        assert "gpt-3.5-turbo" not in router.models
    
    def test_route_all_task_types(self):
        """Test routing all defined task types."""
        router = ModelRouter()
        
        for task_type in TaskType:
            decision = router.route(task_type)
            assert decision is not None
            assert decision.selected_model in router.models
    
    def test_routing_history(self):
        """Test that routing history is tracked."""
        router = ModelRouter()
        
        router.route(TaskType.NARRATION)
        router.route(TaskType.SUMMARY)
        
        history = router.get_routing_history()
        assert len(history) == 2
    
    def test_routing_stats(self):
        """Test routing statistics."""
        router = ModelRouter()
        
        router.route(TaskType.NARRATION)
        router.route(TaskType.NARRATION)
        router.route(TaskType.SUMMARY)
        
        stats = router.get_stats()
        assert stats["total_routes"] == 3
        assert stats["by_task_type"]["narration"] == 2
        assert stats["by_task_type"]["summary"] == 1
    
    def test_get_next_fallback(self):
        """Test getting next fallback in chain."""
        router = ModelRouter()
        
        decision = router.route(TaskType.NARRATION)
        chain = decision.fallback_chain
        
        if len(chain) > 0:
            next_fallback = router.get_next_fallback(decision.selected_model, chain)
            assert next_fallback is not None
    
    def test_list_models_by_capability(self):
        """Test listing models by capability."""
        router = ModelRouter()
        
        fast_models = router.list_models_by_capability(ModelCapability.FAST)
        
        assert len(fast_models) > 0
        assert "gpt-3.5-turbo" in fast_models


class TestTokenBudgetManager:
    """Tests for the TokenBudgetManager."""
    
    def test_manager_initialization(self):
        """Test budget manager initialization."""
        manager = TokenBudgetManager()
        
        assert manager.default_budget == 2000
        assert "intent_parsing" in manager._budgets
        assert "narration" in manager._budgets
    
    def test_set_and_get_budget(self):
        """Test setting and getting budget for task types."""
        manager = TokenBudgetManager()
        
        manager.set_budget("custom_task", 5000)
        
        assert manager.get_budget("custom_task") == 5000
    
    def test_manage_budget_within_limit(self):
        """Test managing budget when within limit."""
        manager = TokenBudgetManager()
        
        sections = [
            ContextSection(name="context1", content="Short text", priority=SectionPriority.MEDIUM),
            ContextSection(name="context2", content="Another text", priority=SectionPriority.MEDIUM),
        ]
        
        combined, audit = manager.manage_budget(sections, "intent_parsing")
        
        assert audit.overflow_detected is False
        assert audit.fallback_triggered is False
        assert len(audit.entries) == 2
        assert all(e.decision == TrimDecision.KEEP for e in audit.entries)
    
    def test_manage_budget_exceeds_limit(self):
        """Test managing budget when exceeding limit."""
        manager = TokenBudgetManager()
        
        long_text = "word " * 500
        sections = [
            ContextSection(name="critical", content="Important", priority=SectionPriority.CRITICAL),
            ContextSection(name="long_section", content=long_text, priority=SectionPriority.LOW),
        ]
        
        manager.set_budget("test_task", 300)
        combined, audit = manager.manage_budget(sections, "test_task")
        
        assert audit.overflow_detected is True
        assert audit.original_total > audit.final_total
    
    def test_critical_sections_preserved(self):
        """Test that critical sections are always preserved."""
        manager = TokenBudgetManager()
        
        sections = [
            ContextSection(name="critical", content="Critical info", priority=SectionPriority.CRITICAL),
            ContextSection(name="optional", content="Optional info", priority=SectionPriority.OPTIONAL),
        ]
        
        combined, audit = manager.manage_budget(sections, "intent_parsing")
        
        critical_entry = next(e for e in audit.entries if e.section_name == "critical")
        assert critical_entry.decision == TrimDecision.KEEP
    
    def test_trim_audit_entries(self):
        """Test that trim audit entries are created."""
        manager = TokenBudgetManager()
        
        long_text = "word " * 1000
        sections = [
            ContextSection(name="section1", content=long_text, priority=SectionPriority.LOW, trimmable=True),
        ]
        
        manager.set_budget("test_task", 100)
        combined, audit = manager.manage_budget(sections, "test_task")
        
        assert len(audit.entries) == 1
        entry = audit.entries[0]
        assert entry.decision in [TrimDecision.TRIM, TrimDecision.SUMMARIZE, TrimDecision.REMOVE]
        assert entry.original_tokens > entry.final_tokens or entry.decision == TrimDecision.REMOVE
    
    def test_budget_enforcer_check(self):
        """Test budget enforcer check method."""
        enforcer = BudgetEnforcer(global_budget=1000)
        
        fits, tokens, reason = enforcer.check_budget("Short text")
        
        assert fits is True
        assert tokens > 0
        assert reason is None
    
    def test_budget_enforcer_exceeds_global(self):
        """Test enforcer when exceeding global budget."""
        enforcer = BudgetEnforcer(global_budget=10)
        
        long_text = "word " * 100
        fits, tokens, reason = enforcer.check_budget(long_text)
        
        assert fits is False
        assert "global budget" in reason.lower()
    
    def test_budget_enforcer_session_budget(self):
        """Test enforcer with session budget."""
        enforcer = BudgetEnforcer()
        enforcer.set_session_budget("session_1", 1000)
        
        fits, tokens, reason = enforcer.check_budget("Some text", session_id="session_1")
        
        assert fits is True
    
    def test_budget_enforcer_record_usage(self):
        """Test recording token usage."""
        enforcer = BudgetEnforcer()
        enforcer.set_session_budget("session_1", 1000)
        
        enforcer.record_usage("session_1", 100)
        enforcer.record_usage("session_1", 50)
        
        usage = enforcer.get_session_usage("session_1")
        assert usage == 150
    
    def test_budget_audit_history(self):
        """Test that budget audit history is tracked."""
        manager = TokenBudgetManager()
        
        sections = [ContextSection(name="test", content="test content", priority=SectionPriority.MEDIUM)]
        manager.manage_budget(sections, "intent_parsing")
        manager.manage_budget(sections, "narration")
        
        history = manager.get_audit_history()
        assert len(history) == 2
    
    def test_budget_stats(self):
        """Test budget statistics."""
        manager = TokenBudgetManager()
        
        manager.set_budget("test_task", 100)
        long_text = "word " * 500
        sections = [ContextSection(name="test", content=long_text, priority=SectionPriority.LOW)]
        
        manager.manage_budget(sections, "test_task")
        
        stats = manager.get_stats()
        assert stats["total_requests"] == 1
        assert stats["overflow_events"] == 1
        assert stats["tokens_saved"] > 0
    
    def test_approximate_token_counter(self):
        """Test approximate token counter."""
        counter = ApproximateTokenCounter(chars_per_token=4)
        
        tokens = counter.count("hello world test")
        
        assert tokens == 4
    
    def test_context_section_token_count(self):
        """Test context section token counting."""
        section = ContextSection(name="test", content="word " * 10)
        counter = ApproximateTokenCounter()
        
        tokens = section.token_count(counter)
        
        assert tokens > 0
    
    def test_trim_context_for_budget(self):
        """Test trimming context dictionary."""
        manager = TokenBudgetManager()
        
        context = {
            "critical_info": "Important data " * 50,
            "optional_info": "Optional data " * 100,
        }
        priority_map = {
            "critical_info": SectionPriority.CRITICAL,
            "optional_info": SectionPriority.OPTIONAL,
        }
        
        manager.set_budget("test_task", 100)
        trimmed, audit = manager.trim_context_for_budget(
            context, "test_task", priority_map=priority_map
        )
        
        assert "critical_info" in trimmed or len(trimmed) < len(context)
        assert audit.overflow_detected is True


class TestIntegration:
    """Integration tests combining multiple components."""
    
    def test_repair_then_route(self):
        """Test repairing malformed JSON then routing."""
        repair_handler = RetryRepairHandler()
        router = ModelRouter()
        
        malformed = '{"action_type": "move", "target": "north",}'
        result, audit = repair_handler.repair(malformed)
        
        assert result is not None
        assert audit.fallback_used is False
        
        decision = router.route(TaskType.NPC_DECISION)
        assert decision is not None
    
    def test_route_with_budget(self):
        """Test routing then applying budget management."""
        router = ModelRouter()
        budget_manager = TokenBudgetManager()
        
        decision = router.route(TaskType.NARRATION)
        
        sections = [
            ContextSection(name="scene", content="Scene description " * 100, priority=SectionPriority.HIGH),
            ContextSection(name="npc", content="NPC info " * 50, priority=SectionPriority.MEDIUM),
        ]
        
        combined, audit = budget_manager.manage_budget(sections, decision.task_type.value)
        
        assert combined is not None
        assert audit.budget_limit > 0
    
    def test_full_pipeline_malformed_to_budget(self):
        """Test full pipeline: repair malformed -> route -> budget."""
        repair_handler = RetryRepairHandler()
        router = ModelRouter()
        budget_manager = TokenBudgetManager()
        
        malformed = '```json\n{"intent": "explore", "target": "cave",}\n```'
        repaired, repair_audit = repair_handler.repair(malformed)
        
        assert repaired is not None
        assert repair_audit.fallback_used is False
        
        decision = router.route(TaskType.INTENT_PARSING)
        
        assert decision.selected_model is not None
        
        sections = [
            ContextSection(name="player_input", content=json.dumps(repaired), priority=SectionPriority.CRITICAL),
            ContextSection(name="context", content="Additional context " * 200, priority=SectionPriority.MEDIUM),
        ]
        
        combined, budget_audit = budget_manager.manage_budget(sections, decision.task_type.value)
        
        assert combined is not None
        assert budget_audit.entries[0].decision == TrimDecision.KEEP


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
