"""
Unit tests for ItemRules.

Tests item validation and effect resolution:
- validate_use_item
- validate_give_item
- validate_take_item
- resolve_item_effect
- register_rules with RuleEngine
"""

import pytest

from llm_rpg.rules.item_rules import ItemRules, ItemEffect, register_rules
from llm_rpg.rules.rule_engine import RuleEngine, RuleType


class TestValidateUseItem:
    """Tests for ItemRules.validate_use_item."""

    def test_use_valid_healing_potion_success(self):
        """Test 1: Use valid healing potion -> success."""
        rules = ItemRules()
        action = {"item_id": "healing_potion", "quantity": 1}
        inventory_state = {
            "items": [{"item_id": "healing_potion", "quantity": 3}],
            "hp": 50,
        }
        item_template = {
            "id": "healing_potion",
            "effects": {"hp_heal": 30},
        }

        result = rules.validate_use_item(action, inventory_state, item_template)
        assert result.is_valid is True

    def test_use_item_insufficient_quantity_fail(self):
        """Test 2: Use item with insufficient quantity -> fail."""
        rules = ItemRules()
        action = {"item_id": "healing_potion", "quantity": 2}
        inventory_state = {
            "items": [{"item_id": "healing_potion", "quantity": 1}],
            "hp": 50,
        }
        item_template = {
            "id": "healing_potion",
            "effects": {"hp_heal": 30},
        }

        result = rules.validate_use_item(action, inventory_state, item_template)
        assert result.is_valid is False
        assert any("Insufficient quantity" in e for e in result.errors)

    def test_use_item_no_effects_fail(self):
        """An item with no effects cannot be used."""
        rules = ItemRules()
        action = {"item_id": "key_item", "quantity": 1}
        inventory_state = {
            "items": [{"item_id": "key_item", "quantity": 1}],
            "hp": 50,
        }
        item_template = {"id": "key_item", "effects": {}}

        result = rules.validate_use_item(action, inventory_state, item_template)
        assert result.is_valid is False
        assert any("no effects" in e.lower() for e in result.errors)

    def test_use_item_hp_too_high_fail(self):
        """Cannot use healing potion when HP exceeds hp_max condition."""
        rules = ItemRules()
        action = {"item_id": "healing_potion", "quantity": 1}
        inventory_state = {
            "items": [{"item_id": "healing_potion", "quantity": 1}],
            "hp": 100,
        }
        item_template = {
            "id": "healing_potion",
            "effects": {"hp_heal": 30},
            "use_conditions": {"hp_max": 80},
        }

        result = rules.validate_use_item(action, inventory_state, item_template)
        assert result.is_valid is False
        assert any("HP too high" in e for e in result.errors)

    def test_use_item_missing_required_status_fail(self):
        """Cannot use item when missing required status effect."""
        rules = ItemRules()
        action = {"item_id": "antidote", "quantity": 1}
        inventory_state = {
            "items": [{"item_id": "antidote", "quantity": 1}],
            "hp": 50,
            "status_effects": [],
        }
        item_template = {
            "id": "antidote",
            "effects": {"status_effects": ["cure_poison"]},
            "use_conditions": {"required_status": ["poisoned"]},
        }

        result = rules.validate_use_item(action, inventory_state, item_template)
        assert result.is_valid is False
        assert any("Missing required status" in e for e in result.errors)


class TestValidateGiveItem:
    """Tests for ItemRules.validate_give_item."""

    def test_give_item_valid_quantity_success(self):
        """Test 3: Give item with valid quantity -> success."""
        rules = ItemRules()
        action = {"item_id": "sword", "quantity": 1, "target_id": "npc_1"}
        giver_inventory = {
            "items": [{"item_id": "sword", "quantity": 2, "tradeable": True}],
        }
        receiver_state = {"inventory_capacity": 20, "inventory_count": 5}

        result = rules.validate_give_item(action, giver_inventory, receiver_state)
        assert result.is_valid is True

    def test_give_item_not_tradeable_fail(self):
        """Cannot give a non-tradeable item."""
        rules = ItemRules()
        action = {"item_id": "quest_item", "quantity": 1, "target_id": "npc_1"}
        giver_inventory = {
            "items": [{"item_id": "quest_item", "quantity": 1, "tradeable": False}],
        }
        receiver_state = {"inventory_capacity": 20, "inventory_count": 5}

        result = rules.validate_give_item(action, giver_inventory, receiver_state)
        assert result.is_valid is False
        assert any("not tradeable" in e.lower() for e in result.errors)

    def test_give_item_not_in_inventory_fail(self):
        """Cannot give an item not in inventory."""
        rules = ItemRules()
        action = {"item_id": "missing_item", "quantity": 1, "target_id": "npc_1"}
        giver_inventory = {"items": []}
        receiver_state = {"inventory_capacity": 20, "inventory_count": 5}

        result = rules.validate_give_item(action, giver_inventory, receiver_state)
        assert result.is_valid is False
        assert any("not found" in e.lower() for e in result.errors)

    def test_give_item_receiver_full_fail(self):
        """Cannot give item when receiver inventory is full."""
        rules = ItemRules()
        action = {"item_id": "sword", "quantity": 1, "target_id": "npc_1"}
        giver_inventory = {
            "items": [{"item_id": "sword", "quantity": 2, "tradeable": True}],
        }
        receiver_state = {"inventory_capacity": 10, "inventory_count": 10}

        result = rules.validate_give_item(action, giver_inventory, receiver_state)
        assert result.is_valid is False
        assert any("full" in e.lower() for e in result.errors)


class TestValidateTakeItem:
    """Tests for ItemRules.validate_take_item."""

    def test_take_item_from_location_success(self):
        """Test 4: Take item from location -> success."""
        rules = ItemRules()
        action = {"item_id": "gold_coin", "quantity": 1}
        taker_state = {"inventory_capacity": 20, "inventory_count": 5}
        location_items = [
            {"item_id": "gold_coin", "quantity": 10, "pickuppable": True},
        ]

        result = rules.validate_take_item(action, taker_state, location_items)
        assert result.is_valid is True

    def test_take_nonexistent_item_fail(self):
        """Test 5: Take non-existent item -> fail."""
        rules = ItemRules()
        action = {"item_id": "phantom_item", "quantity": 1}
        taker_state = {"inventory_capacity": 20, "inventory_count": 5}
        location_items = [
            {"item_id": "gold_coin", "quantity": 10, "pickuppable": True},
        ]

        result = rules.validate_take_item(action, taker_state, location_items)
        assert result.is_valid is False
        assert any("not found" in e.lower() for e in result.errors)

    def test_take_non_pickuppable_item_fail(self):
        """Cannot take a non-pickuppable item."""
        rules = ItemRules()
        action = {"item_id": "fountain", "quantity": 1}
        taker_state = {"inventory_capacity": 20, "inventory_count": 5}
        location_items = [
            {"item_id": "fountain", "quantity": 1, "pickuppable": False},
        ]

        result = rules.validate_take_item(action, taker_state, location_items)
        assert result.is_valid is False
        assert any("cannot be picked up" in e.lower() for e in result.errors)

    def test_take_item_taker_inventory_full_fail(self):
        """Cannot take item when taker inventory is full."""
        rules = ItemRules()
        action = {"item_id": "gold_coin", "quantity": 1}
        taker_state = {"inventory_capacity": 10, "inventory_count": 10}
        location_items = [
            {"item_id": "gold_coin", "quantity": 10, "pickuppable": True},
        ]

        result = rules.validate_take_item(action, taker_state, location_items)
        assert result.is_valid is False
        assert any("full" in e.lower() for e in result.errors)


class TestResolveItemEffect:
    """Tests for ItemRules.resolve_item_effect."""

    def test_resolve_hp_heal_effect_correct_values(self):
        """Test 6: Resolve HP heal effect -> correct values."""
        rules = ItemRules()
        item_template = {
            "id": "healing_potion",
            "effects": {"hp_heal": 30},
        }
        user_state = {"hp": 70, "max_hp": 100}

        effect = rules.resolve_item_effect(item_template, user_state)
        assert isinstance(effect, ItemEffect)
        assert effect.item_id == "healing_potion"
        assert effect.hp_heal == 30

    def test_resolve_hp_heal_capped_at_missing(self):
        """HP heal is capped at the missing HP amount."""
        rules = ItemRules()
        item_template = {
            "id": "healing_potion",
            "effects": {"hp_heal": 50},
        }
        user_state = {"hp": 90, "max_hp": 100}

        effect = rules.resolve_item_effect(item_template, user_state)
        assert effect.hp_heal == 10

    def test_resolve_hp_heal_zero_when_full(self):
        """HP heal is 0 when already at max HP."""
        rules = ItemRules()
        item_template = {
            "id": "healing_potion",
            "effects": {"hp_heal": 50},
        }
        user_state = {"hp": 100, "max_hp": 100}

        effect = rules.resolve_item_effect(item_template, user_state)
        assert effect.hp_heal == 0

    def test_resolve_buff_effect(self):
        """Resolve buff effect correctly."""
        rules = ItemRules()
        item_template = {
            "id": "strength_elixir",
            "effects": {
                "buff_type": "strength",
                "buff_magnitude": 2.0,
                "buff_duration": 3,
            },
        }
        user_state = {"hp": 100, "max_hp": 100}

        effect = rules.resolve_item_effect(item_template, user_state)
        assert effect.buff_type == "strength"
        assert effect.buff_magnitude == 2.0
        assert effect.buff_duration == 3

    def test_resolve_mp_heal_effect(self):
        """Resolve MP heal effect correctly."""
        rules = ItemRules()
        item_template = {
            "id": "mana_potion",
            "effects": {"mp_heal": 20},
        }
        user_state = {"hp": 100, "max_hp": 100, "mp": 30, "max_mp": 50}

        effect = rules.resolve_item_effect(item_template, user_state)
        assert effect.mp_heal == 20

    def test_resolve_status_effects(self):
        """Resolve status effects from item."""
        rules = ItemRules()
        item_template = {
            "id": "antidote",
            "effects": {"status_effects": ["cure_poison"]},
        }
        user_state = {"hp": 100, "max_hp": 100}

        effect = rules.resolve_item_effect(item_template, user_state)
        assert "cure_poison" in effect.status_effects

    def test_resolve_extra_effects(self):
        """Unknown effect keys go into extra dict."""
        rules = ItemRules()
        item_template = {
            "id": "custom_item",
            "effects": {"hp_heal": 10, "custom_key": "custom_value"},
        }
        user_state = {"hp": 50, "max_hp": 100}

        effect = rules.resolve_item_effect(item_template, user_state)
        assert effect.extra == {"custom_key": "custom_value"}

    def test_item_effect_to_dict(self):
        """ItemEffect.to_dict() returns correct structure."""
        effect = ItemEffect(
            item_id="potion",
            hp_heal=30,
            mp_heal=10,
            buff_type="speed",
            buff_magnitude=1.5,
            buff_duration=2,
        )
        data = effect.to_dict()
        assert data["item_id"] == "potion"
        assert data["hp_heal"] == 30
        assert data["mp_heal"] == 10
        assert data["buff_type"] == "speed"


class TestRegisterRules:
    """Tests for register_rules function with RuleEngine."""

    def test_register_rules_returns_rule_ids(self):
        """register_rules returns list of rule IDs."""
        engine = RuleEngine()
        rule_ids = register_rules(engine)

        assert len(rule_ids) == 3
        assert "item_validate_use" in rule_ids
        assert "item_validate_give" in rule_ids
        assert "item_validate_take" in rule_ids

    def test_registered_rules_appear_in_engine(self):
        """Registered rules are visible in the engine."""
        engine = RuleEngine()
        register_rules(engine)

        registered = engine.get_registered_rules(rule_type=RuleType.CUSTOM)
        assert len(registered) >= 3

    def test_evaluate_registered_use_rule(self):
        """Registered use-item rule can be evaluated."""
        engine = RuleEngine()
        register_rules(engine)

        context = {
            "action": {"item_id": "potion", "quantity": 1},
            "inventory_state": {
                "items": [{"item_id": "potion", "quantity": 2}],
                "hp": 50,
            },
            "item_template": {"id": "potion", "effects": {"hp_heal": 30}},
        }

        result = engine.evaluate_rule("item_validate_use", context)
        assert result is not None
        assert result.passed is True
