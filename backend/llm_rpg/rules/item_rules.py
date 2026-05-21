"""
Item Rules

Validates item-related actions (use, give, take) and resolves item effects.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from llm_rpg.core.validation.result import passed_result, failed_result, ValidationResult
from llm_rpg.rules.rule_engine import RuleEngine, RuleType, RulePriority


@dataclass
class ItemEffect:
    """Represents the resolved effect of using an item."""
    item_id: str
    hp_heal: int = 0
    mp_heal: int = 0
    buff_type: str = ""
    buff_magnitude: float = 0.0
    buff_duration: int = 0
    debuff_type: str = ""
    debuff_magnitude: float = 0.0
    debuff_duration: int = 0
    status_effects: List[str] = field(default_factory=list)
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "item_id": self.item_id,
            "hp_heal": self.hp_heal,
            "mp_heal": self.mp_heal,
            "buff_type": self.buff_type,
            "buff_magnitude": self.buff_magnitude,
            "buff_duration": self.buff_duration,
            "debuff_type": self.debuff_type,
            "debuff_magnitude": self.debuff_magnitude,
            "debuff_duration": self.debuff_duration,
            "status_effects": self.status_effects,
            "extra": self.extra,
        }


class ItemRules:
    """
    Validates item-related actions and resolves item effects.

    Rules:
    - Use item: item must have effects, player must have enough quantity, HP/conditions met
    - Give item: item must be tradeable, giver must have enough quantity
    - Take item: item must exist in location/container, item must be pickuppable
    """

    def validate_use_item(
        self,
        action: Dict[str, Any],
        inventory_state: Dict[str, Any],
        item_template: Dict[str, Any],
    ) -> ValidationResult:
        """
        Validate using an item from inventory.

        Args:
            action: Dict with keys like action_type, item_id, quantity
            inventory_state: Dict with player inventory info (items list, etc.)
            item_template: Dict describing the item (effects, usable, etc.)

        Returns:
            ValidationResult
        """
        # Check item has effects (is usable)
        effects = item_template.get("effects", {})
        if not effects:
            return failed_result(
                "item_usable",
                f"Item '{item_template.get('id', 'unknown')}' has no effects and cannot be used",
            )

        # Check player has enough quantity
        item_id = action.get("item_id", item_template.get("id", ""))
        quantity_needed = action.get("quantity", 1)
        inventory_items = inventory_state.get("items", [])
        owned_quantity = 0
        for inv_item in inventory_items:
            if inv_item.get("item_id") == item_id or inv_item.get("template_id") == item_id:
                owned_quantity = inv_item.get("quantity", 0)
                break

        if owned_quantity < quantity_needed:
            return failed_result(
                "item_quantity",
                f"Insufficient quantity: have {owned_quantity}, need {quantity_needed}",
            )

        # Check HP/conditions are met
        conditions = item_template.get("use_conditions", {})
        if conditions:
            player_hp = inventory_state.get("hp", 100)
            hp_min = conditions.get("hp_min", 0)
            if player_hp < hp_min:
                return failed_result(
                    "item_conditions",
                    f"HP too low to use item: have {player_hp}, need at least {hp_min}",
                )

            hp_max = conditions.get("hp_max", float("inf"))
            if player_hp > hp_max:
                return failed_result(
                    "item_conditions",
                    f"HP too high to use item: have {player_hp}, max allowed {hp_max}",
                )

            required_status = conditions.get("required_status", [])
            player_status = inventory_state.get("status_effects", [])
            for req in required_status:
                if req not in player_status:
                    return failed_result(
                        "item_conditions",
                        f"Missing required status effect: {req}",
                    )

        return passed_result("item_use", "Item use is valid")

    def validate_give_item(
        self,
        action: Dict[str, Any],
        giver_inventory: Dict[str, Any],
        receiver_state: Dict[str, Any],
    ) -> ValidationResult:
        """
        Validate giving an item to another entity.

        Args:
            action: Dict with item_id, quantity, target_id
            giver_inventory: Giver's inventory state
            receiver_state: Receiver's state (inventory capacity, etc.)

        Returns:
            ValidationResult
        """
        item_id = action.get("item_id", "")
        quantity_needed = action.get("quantity", 1)

        # Check item is tradeable
        # The action may carry item_template info; if not, we check from inventory
        inventory_items = giver_inventory.get("items", [])
        item_found = None
        for inv_item in inventory_items:
            if inv_item.get("item_id") == item_id or inv_item.get("template_id") == item_id:
                item_found = inv_item
                break

        if item_found is None:
            return failed_result(
                "item_in_inventory",
                f"Item '{item_id}' not found in giver's inventory",
            )

        if not item_found.get("tradeable", True):
            return failed_result(
                "item_tradeable",
                f"Item '{item_id}' is not tradeable",
            )

        # Check giver has enough quantity
        owned_quantity = item_found.get("quantity", 0)
        if owned_quantity < quantity_needed:
            return failed_result(
                "item_quantity",
                f"Insufficient quantity: have {owned_quantity}, need {quantity_needed}",
            )

        # Check receiver capacity
        receiver_capacity = receiver_state.get("inventory_capacity", float("inf"))
        receiver_current = receiver_state.get("inventory_count", 0)
        if receiver_current >= receiver_capacity:
            return failed_result(
                "receiver_capacity",
                "Receiver inventory is full",
            )

        return passed_result("item_give", "Item give is valid")

    def validate_take_item(
        self,
        action: Dict[str, Any],
        taker_state: Dict[str, Any],
        location_items: List[Dict[str, Any]],
    ) -> ValidationResult:
        """
        Validate taking an item from a location or container.

        Args:
            action: Dict with item_id, quantity
            taker_state: Taker's state (inventory capacity, etc.)
            location_items: List of items available at the location

        Returns:
            ValidationResult
        """
        item_id = action.get("item_id", "")
        quantity_needed = action.get("quantity", 1)

        # Check item exists in location
        item_found = None
        for loc_item in location_items:
            if loc_item.get("item_id") == item_id or loc_item.get("id") == item_id:
                item_found = loc_item
                break

        if item_found is None:
            return failed_result(
                "item_in_location",
                f"Item '{item_id}' not found in location",
            )

        # Check item is pickuppable
        if not item_found.get("pickuppable", True):
            return failed_result(
                "item_pickuppable",
                f"Item '{item_id}' cannot be picked up",
            )

        # Check quantity available
        available_quantity = item_found.get("quantity", 1)
        if available_quantity < quantity_needed:
            return failed_result(
                "item_quantity",
                f"Insufficient quantity in location: have {available_quantity}, need {quantity_needed}",
            )

        # Check taker capacity
        taker_capacity = taker_state.get("inventory_capacity", float("inf"))
        taker_current = taker_state.get("inventory_count", 0)
        if taker_current >= taker_capacity:
            return failed_result(
                "taker_capacity",
                "Taker inventory is full",
            )

        return passed_result("item_take", "Item take is valid")

    def resolve_item_effect(
        self,
        item_template: Dict[str, Any],
        user_state: Dict[str, Any],
    ) -> ItemEffect:
        """
        Resolve the effect of using an item based on template and user state.

        Args:
            item_template: Dict describing the item with effects
            user_state: Current state of the user (hp, mp, status_effects, etc.)

        Returns:
            ItemEffect dataclass with resolved values
        """
        effects = item_template.get("effects", {})
        item_id = item_template.get("id", "unknown")

        hp_heal = effects.get("hp_heal", 0)
        mp_heal = effects.get("mp_heal", 0)

        # Cap healing at missing amount
        if hp_heal > 0:
            current_hp = user_state.get("hp", 100)
            max_hp = user_state.get("max_hp", 100)
            missing_hp = max_hp - current_hp
            hp_heal = min(hp_heal, missing_hp) if missing_hp > 0 else 0

        if mp_heal > 0:
            current_mp = user_state.get("mp", 50)
            max_mp = user_state.get("max_mp", 50)
            missing_mp = max_mp - current_mp
            mp_heal = min(mp_heal, missing_mp) if missing_mp > 0 else 0

        buff_type = effects.get("buff_type", "")
        buff_magnitude = effects.get("buff_magnitude", 0.0)
        buff_duration = effects.get("buff_duration", 0)

        debuff_type = effects.get("debuff_type", "")
        debuff_magnitude = effects.get("debuff_magnitude", 0.0)
        debuff_duration = effects.get("debuff_duration", 0)

        status_effects = effects.get("status_effects", [])

        extra = {
            k: v for k, v in effects.items()
            if k not in (
                "hp_heal", "mp_heal", "buff_type", "buff_magnitude",
                "buff_duration", "debuff_type", "debuff_magnitude",
                "debuff_duration", "status_effects",
            )
        }

        return ItemEffect(
            item_id=item_id,
            hp_heal=hp_heal,
            mp_heal=mp_heal,
            buff_type=buff_type,
            buff_magnitude=buff_magnitude,
            buff_duration=buff_duration,
            debuff_type=debuff_type,
            debuff_magnitude=debuff_magnitude,
            debuff_duration=debuff_duration,
            status_effects=status_effects,
            extra=extra,
        )


def register_rules(rule_engine: RuleEngine) -> List[str]:
    """
    Register all ItemRules methods with the RuleEngine.

    Args:
        rule_engine: The RuleEngine instance to register with

    Returns:
        List of registered rule IDs
    """
    item_rules = ItemRules()
    rule_ids = []

    rule_ids.append(rule_engine.register_rule(
        rule_type=RuleType.CUSTOM,
        handler=lambda context: item_rules.validate_use_item(
            context.get("action", {}),
            context.get("inventory_state", {}),
            context.get("item_template", {}),
        ),
        rule_id="item_validate_use",
        priority=RulePriority.NORMAL,
        description="Validate item use action",
    ))

    rule_ids.append(rule_engine.register_rule(
        rule_type=RuleType.CUSTOM,
        handler=lambda context: item_rules.validate_give_item(
            context.get("action", {}),
            context.get("giver_inventory", {}),
            context.get("receiver_state", {}),
        ),
        rule_id="item_validate_give",
        priority=RulePriority.NORMAL,
        description="Validate item give action",
    ))

    rule_ids.append(rule_engine.register_rule(
        rule_type=RuleType.CUSTOM,
        handler=lambda context: item_rules.validate_take_item(
            context.get("action", {}),
            context.get("taker_state", {}),
            context.get("location_items", []),
        ),
        rule_id="item_validate_take",
        priority=RulePriority.NORMAL,
        description="Validate item take action",
    ))

    return rule_ids
