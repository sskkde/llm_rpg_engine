"""State Delta Resolver.

This module generates StateDeltaCandidate objects for various resolution
scenarios. The resolver does NOT commit deltas — it only produces candidates
that can subsequently be fed to StateDeltaValidator for contract validation.

Resolution scenarios:
1. Player actions (move, attack, use_item, etc.)
2. NPC actions (same logic as player but for NPCs)
3. Item effects (hp_heal, mp_heal, buff)
4. Quest progress (stage advancement, status changes)
5. Relationship changes (trust, respect, etc.)
6. Combat results (HP changes, status effects)
7. World time changes (time advancement)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class StateDeltaCandidate:
    """A candidate state delta produced by the resolver.

    Attributes:
        path: Dot-notation state path (e.g. "player_state.location_id").
        operation: One of the allowed operations ("set", "increment", etc.).
        old_value: The previous value at the path.
        new_value: The proposed new value.
        source_action_id: ID of the action that triggered this candidate.
        source_event_id: ID of the event that triggered this candidate.
        metadata: Additional context about the delta.
    """

    path: str
    operation: str
    old_value: Any
    new_value: Any
    source_action_id: str = ""
    source_event_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


class StateDeltaResolver:
    """Generates StateDeltaCandidate objects for different resolution scenarios.

    The resolver is a pure function-like object: it reads inputs and produces
    candidate deltas without side effects.  Validation and commitment are
    handled downstream by StateDeltaValidator and the state-reconstruction
    pipeline.
    """

    # ------------------------------------------------------------------
    # 1. Player action resolution
    # ------------------------------------------------------------------

    def resolve_player_action(
        self,
        action: Dict[str, Any],
        state: Any,
    ) -> List[StateDeltaCandidate]:
        """Parse a player action into state delta candidates.

        Supported action_type values:
          - "move": generates a location change delta
          - "attack": generates HP decrement on target(s)
          - "use_item": generates inventory/effect deltas
          - "cast_skill": generates HP/spirit_power deltas
          - "take_item": generates inventory append delta
          - "give_item": generates inventory remove + NPC delta
          - "defend": generates stamina/spirit_power delta
          - "wait": no state delta (empty list)
          - Others: returns empty list (unresolved)

        Args:
            action: Dict with at least ``action_type``.  May also contain
                ``target_ids``, ``item_id``, ``damage``, etc.
            state: Current canonical state (used to read old values).

        Returns:
            List of StateDeltaCandidate objects.
        """
        action_type = action.get("action_type", "")
        action_id = action.get("action_id", "")
        handler = {
            "move": self._resolve_player_move,
            "attack": self._resolve_player_attack,
            "use_item": self._resolve_player_use_item,
            "cast_skill": self._resolve_player_cast_skill,
            "take_item": self._resolve_player_take_item,
            "give_item": self._resolve_player_give_item,
            "defend": self._resolve_player_defend,
        }.get(action_type)

        if handler is None:
            return []

        candidates = handler(action, state)
        for c in candidates:
            if not c.source_action_id:
                c.source_action_id = action_id
        return candidates

    # -- player helpers ------------------------------------------------

    def _resolve_player_move(
        self, action: Dict[str, Any], state: Any
    ) -> List[StateDeltaCandidate]:
        target_ids = action.get("target_ids", [])
        if not target_ids:
            return []
        new_location = target_ids[0]
        old_location = self._get_player_field(state, "location_id", "")
        return [
            StateDeltaCandidate(
                path="session_state.current_location_id",
                operation="set",
                old_value=old_location,
                new_value=new_location,
                metadata={"action_type": "move"},
            )
        ]

    def _resolve_player_attack(
        self, action: Dict[str, Any], state: Any
    ) -> List[StateDeltaCandidate]:
        target_ids = action.get("target_ids", [])
        damage = action.get("damage", 10)
        candidates: List[StateDeltaCandidate] = []
        for tid in target_ids:
            old_hp = self._get_npc_field(state, tid, "hp", 100)
            candidates.append(
                StateDeltaCandidate(
                    path=f"npc_state.{tid}.hp",
                    operation="decrement",
                    old_value=old_hp,
                    new_value=damage,
                    metadata={"action_type": "attack", "target_id": tid},
                )
            )
        return candidates

    def _resolve_player_use_item(
        self, action: Dict[str, Any], state: Any
    ) -> List[StateDeltaCandidate]:
        item_id = action.get("item_id", "")
        if not item_id:
            return []
        old_inventory = self._get_player_field(state, "inventory_ids", [])
        candidates = [
            StateDeltaCandidate(
                path=f"player_state.inventory.{item_id}",
                operation="remove",
                old_value=old_inventory,
                new_value=item_id,
                metadata={"action_type": "use_item", "item_id": item_id},
            )
        ]
        item_effects = action.get("item_effects", [])
        for effect in item_effects:
            effect_type = effect.get("type", "")
            value = effect.get("value", 0)
            if effect_type == "hp_heal":
                old_hp = self._get_player_field(state, "hp", 100)
                candidates.append(
                    StateDeltaCandidate(
                        path="player_state.hp",
                        operation="increment",
                        old_value=old_hp,
                        new_value=value,
                        metadata={
                            "action_type": "use_item",
                            "effect": "hp_heal",
                            "item_id": item_id,
                        },
                    )
                )
            elif effect_type == "mp_heal":
                old_sp = self._get_player_field(state, "spiritual_power", 100)
                candidates.append(
                    StateDeltaCandidate(
                        path="player_state.spirit_power",
                        operation="increment",
                        old_value=old_sp,
                        new_value=value,
                        metadata={
                            "action_type": "use_item",
                            "effect": "mp_heal",
                            "item_id": item_id,
                        },
                    )
                )
        return candidates

    def _resolve_player_cast_skill(
        self, action: Dict[str, Any], state: Any
    ) -> List[StateDeltaCandidate]:
        target_ids = action.get("target_ids", [])
        damage = action.get("damage", 15)
        sp_cost = action.get("sp_cost", 10)
        candidates: List[StateDeltaCandidate] = []
        old_sp = self._get_player_field(state, "spiritual_power", 100)
        candidates.append(
            StateDeltaCandidate(
                path="player_state.spirit_power",
                operation="decrement",
                old_value=old_sp,
                new_value=sp_cost,
                metadata={"action_type": "cast_skill", "cost": True},
            )
        )
        for tid in target_ids:
            old_hp = self._get_npc_field(state, tid, "hp", 100)
            candidates.append(
                StateDeltaCandidate(
                    path=f"npc_state.{tid}.hp",
                    operation="decrement",
                    old_value=old_hp,
                    new_value=damage,
                    metadata={"action_type": "cast_skill", "target_id": tid},
                )
            )
        return candidates

    def _resolve_player_take_item(
        self, action: Dict[str, Any], state: Any
    ) -> List[StateDeltaCandidate]:
        item_id = action.get("item_id", "")
        if not item_id:
            return []
        return [
            StateDeltaCandidate(
                path=f"player_state.inventory.{item_id}",
                operation="append",
                old_value=None,
                new_value=item_id,
                metadata={"action_type": "take_item", "item_id": item_id},
            )
        ]

    def _resolve_player_give_item(
        self, action: Dict[str, Any], state: Any
    ) -> List[StateDeltaCandidate]:
        item_id = action.get("item_id", "")
        target_ids = action.get("target_ids", [])
        if not item_id:
            return []
        old_inventory = self._get_player_field(state, "inventory_ids", [])
        candidates = [
            StateDeltaCandidate(
                path=f"player_state.inventory.{item_id}",
                operation="remove",
                old_value=old_inventory,
                new_value=item_id,
                metadata={"action_type": "give_item", "item_id": item_id},
            )
        ]
        for tid in target_ids:
            old_affinity = self._get_npc_field(state, tid, "affinity", 0)
            candidates.append(
                StateDeltaCandidate(
                    path=f"npc_state.{tid}.affinity",
                    operation="increment",
                    old_value=old_affinity,
                    new_value=5,
                    metadata={"action_type": "give_item", "target_id": tid},
                )
            )
        return candidates

    def _resolve_player_defend(
        self, action: Dict[str, Any], state: Any
    ) -> List[StateDeltaCandidate]:
        stamina_cost = action.get("stamina_cost", 10)
        old_stamina = self._get_player_field(state, "stamina", 100)
        return [
            StateDeltaCandidate(
                path="player_state.stamina",
                operation="decrement",
                old_value=old_stamina,
                new_value=stamina_cost,
                metadata={"action_type": "defend"},
            )
        ]

    # ------------------------------------------------------------------
    # 2. NPC action resolution
    # ------------------------------------------------------------------

    def resolve_npc_action(
        self,
        action: Dict[str, Any],
        state: Any,
    ) -> List[StateDeltaCandidate]:
        """Parse an NPC action into state delta candidates.

        Args:
            action: Dict with ``action_type``, ``actor_id`` (npc_id),
                and optionally ``target_ids``, ``damage``, etc.
            state: Current canonical state.

        Returns:
            List of StateDeltaCandidate objects.
        """
        action_type = action.get("action_type", "")
        npc_id = action.get("actor_id", "")
        action_id = action.get("action_id", "")
        event_id = action.get("source_event_id", "")

        candidates: List[StateDeltaCandidate] = []

        if action_type == "move":
            target_ids = action.get("target_ids", [])
            if target_ids:
                old_loc = self._get_npc_field(state, npc_id, "current_location_id", "")
                candidates.append(
                    StateDeltaCandidate(
                        path=f"npc_state.{npc_id}.current_location_id",
                        operation="set",
                        old_value=old_loc,
                        new_value=target_ids[0],
                        metadata={"action_type": "move", "npc_id": npc_id},
                    )
                )

        elif action_type == "attack":
            target_ids = action.get("target_ids", [])
            damage = action.get("damage", 10)
            for tid in target_ids:
                if tid == "player" or tid.startswith("player"):
                    old_hp = self._get_player_field(state, "hp", 100)
                    candidates.append(
                        StateDeltaCandidate(
                            path="player_state.hp",
                            operation="decrement",
                            old_value=old_hp,
                            new_value=damage,
                            metadata={
                                "action_type": "attack",
                                "npc_id": npc_id,
                                "target_id": tid,
                            },
                        )
                    )
                else:
                    old_hp = self._get_npc_field(state, tid, "hp", 100)
                    candidates.append(
                        StateDeltaCandidate(
                            path=f"npc_state.{tid}.hp",
                            operation="decrement",
                            old_value=old_hp,
                            new_value=damage,
                            metadata={
                                "action_type": "attack",
                                "npc_id": npc_id,
                                "target_id": tid,
                            },
                        )
                    )

        elif action_type == "talk":
            target_ids = action.get("target_ids", [])
            new_dialogue = action.get("dialogue_state", "talking")
            candidates.append(
                StateDeltaCandidate(
                    path=f"npc_state.{npc_id}.dialogue_state",
                    operation="set",
                    old_value=None,
                    new_value=new_dialogue,
                    metadata={"action_type": "talk", "npc_id": npc_id},
                )
            )

        for c in candidates:
            if not c.source_action_id:
                c.source_action_id = action_id
            if not c.source_event_id:
                c.source_event_id = event_id

        return candidates

    # ------------------------------------------------------------------
    # 3. Item effect resolution
    # ------------------------------------------------------------------

    def resolve_item_effect(
        self,
        item_template: Dict[str, Any],
        user_state: Any,
    ) -> List[StateDeltaCandidate]:
        """Parse item effects into delta candidates.

        Each effect in the item template becomes a separate delta candidate.

        Args:
            item_template: Dict with ``effects`` list.  Each effect has
                ``type`` (hp_heal, mp_heal, buff) and ``value``.
            user_state: State of the entity using the item (used for old_value).

        Returns:
            List of StateDeltaCandidate objects.
        """
        effects = item_template.get("effects", [])
        item_id = item_template.get("item_id", item_template.get("id", ""))
        source_event_id = item_template.get("source_event_id", "")
        is_player = item_template.get("is_player", True)
        npc_id = item_template.get("npc_id", "")

        candidates: List[StateDeltaCandidate] = []

        for effect in effects:
            effect_type = effect.get("type", "")
            value = effect.get("value", 0)

            if effect_type == "hp_heal":
                if is_player:
                    old_hp = self._get_player_field(user_state, "hp", 100)
                    path = "player_state.hp"
                else:
                    old_hp = self._get_npc_field(user_state, npc_id, "hp", 100)
                    path = f"npc_state.{npc_id}.hp"
                candidates.append(
                    StateDeltaCandidate(
                        path=path,
                        operation="increment",
                        old_value=old_hp,
                        new_value=value,
                        source_event_id=source_event_id,
                        metadata={"effect_type": "hp_heal", "item_id": item_id},
                    )
                )

            elif effect_type == "mp_heal":
                if is_player:
                    old_sp = self._get_player_field(user_state, "spiritual_power", 100)
                    path = "player_state.spirit_power"
                else:
                    continue
                candidates.append(
                    StateDeltaCandidate(
                        path=path,
                        operation="increment",
                        old_value=old_sp,
                        new_value=value,
                        source_event_id=source_event_id,
                        metadata={"effect_type": "mp_heal", "item_id": item_id},
                    )
                )

            elif effect_type == "buff":
                buff_stat = effect.get("stat", "stamina")
                if is_player:
                    old_val = self._get_player_field(user_state, buff_stat, 0)
                    path = f"player_state.{buff_stat}"
                else:
                    old_val = self._get_npc_field(user_state, npc_id, buff_stat, 0)
                    path = f"npc_state.{npc_id}.{buff_stat}"
                candidates.append(
                    StateDeltaCandidate(
                        path=path,
                        operation="increment",
                        old_value=old_val,
                        new_value=value,
                        source_event_id=source_event_id,
                        metadata={"effect_type": "buff", "stat": buff_stat, "item_id": item_id},
                    )
                )

        return candidates

    # ------------------------------------------------------------------
    # 4. Quest progress resolution
    # ------------------------------------------------------------------

    def resolve_quest_progress(
        self,
        quest_state: Dict[str, Any],
        new_stage: str,
    ) -> List[StateDeltaCandidate]:
        """Generate deltas for quest stage advancement.

        If the new stage indicates completion, also generates a status
        change delta.

        Args:
            quest_state: Dict with ``quest_id``, ``current_step`` (old stage),
                ``status``, and optionally ``source_event_id``.
            new_stage: The target stage.

        Returns:
            List of StateDeltaCandidate objects.
        """
        quest_id = quest_state.get("quest_id", "")
        old_stage = quest_state.get("current_step", quest_state.get("stage", ""))
        old_status = quest_state.get("status", "active")
        source_event_id = quest_state.get("source_event_id", "")

        candidates: List[StateDeltaCandidate] = [
            StateDeltaCandidate(
                path=f"quest_state.{quest_id}.current_step",
                operation="set",
                old_value=old_stage,
                new_value=new_stage,
                source_event_id=source_event_id,
                metadata={"quest_id": quest_id, "resolution": "stage_advance"},
            )
        ]

        completion_stages = {"completed", "done", "finished"}
        if new_stage.lower() in completion_stages or quest_state.get("completing", False):
            candidates.append(
                StateDeltaCandidate(
                    path=f"quest_state.{quest_id}.status",
                    operation="set",
                    old_value=old_status,
                    new_value="completed",
                    source_event_id=source_event_id,
                    metadata={"quest_id": quest_id, "resolution": "status_change"},
                )
            )

        return candidates

    # ------------------------------------------------------------------
    # 5. Relationship change resolution
    # ------------------------------------------------------------------

    def resolve_relationship_change(
        self,
        source: str,
        target: str,
        old_rel: Dict[str, Any],
        new_values: Dict[str, Any],
    ) -> List[StateDeltaCandidate]:
        """Generate deltas for relationship score changes.

        Args:
            source: The source actor ID.
            target: The target actor ID.
            old_rel: Dict of old relationship scores (trust, respect, etc.).
            new_values: Dict of new values for changed scores.

        Returns:
            List of StateDeltaCandidate objects — one per changed dimension.
        """
        source_event_id = old_rel.get("source_event_id", "")
        candidates: List[StateDeltaCandidate] = []

        for dimension, new_val in new_values.items():
            if dimension in ("source_event_id",):
                continue
            old_val = old_rel.get(dimension, 0)
            if isinstance(new_val, (int, float)) and isinstance(old_val, (int, float)):
                delta = new_val - old_val
                if delta > 0:
                    operation = "increment"
                    delta_value = delta
                elif delta < 0:
                    operation = "decrement"
                    delta_value = abs(delta)
                else:
                    continue
            else:
                operation = "set"
                delta_value = new_val

            if target.startswith("npc_") or not target.startswith("player"):
                path = f"npc_state.{target}.{dimension}"
            else:
                path = f"player_state.{dimension}"

            candidates.append(
                StateDeltaCandidate(
                    path=path,
                    operation=operation,
                    old_value=old_val,
                    new_value=delta_value if operation in ("increment", "decrement") else new_val,
                    source_event_id=source_event_id,
                    metadata={
                        "source": source,
                        "target": target,
                        "dimension": dimension,
                        "resolution": "relationship_change",
                    },
                )
            )

        return candidates

    # ------------------------------------------------------------------
    # 6. Combat result resolution
    # ------------------------------------------------------------------

    def resolve_combat_result(
        self,
        action: Dict[str, Any],
        caster: str,
        target: str,
    ) -> List[StateDeltaCandidate]:
        """Generate deltas for HP changes and status effects from combat.

        Args:
            action: Dict with ``damage``, ``healing``, ``status_effects``,
                ``source_action_id``, ``source_event_id``.
            caster: The actor ID of the caster.
            target: The actor ID of the target.

        Returns:
            List of StateDeltaCandidate objects.
        """
        damage = action.get("damage", 0)
        healing = action.get("healing", 0)
        status_effects = action.get("status_effects", [])
        source_action_id = action.get("source_action_id", "")
        source_event_id = action.get("source_event_id", "")

        candidates: List[StateDeltaCandidate] = []

        if damage > 0:
            old_hp = self._resolve_entity_hp(target, None)
            candidates.append(
                StateDeltaCandidate(
                    path=self._hp_path(target),
                    operation="decrement",
                    old_value=old_hp,
                    new_value=damage,
                    source_action_id=source_action_id,
                    source_event_id=source_event_id,
                    metadata={
                        "caster": caster,
                        "target": target,
                        "resolution": "combat_damage",
                    },
                )
            )

        heal_target = action.get("heal_target", caster)
        if healing > 0:
            old_hp = self._resolve_entity_hp(heal_target, None)
            candidates.append(
                StateDeltaCandidate(
                    path=self._hp_path(heal_target),
                    operation="increment",
                    old_value=old_hp,
                    new_value=healing,
                    source_action_id=source_action_id,
                    source_event_id=source_event_id,
                    metadata={
                        "caster": caster,
                        "target": heal_target,
                        "resolution": "combat_healing",
                    },
                )
            )

        for se in status_effects:
            se_name = se.get("name", "") if isinstance(se, dict) else str(se)
            se_duration = se.get("duration", 1) if isinstance(se, dict) else 1
            candidates.append(
                StateDeltaCandidate(
                    path=f"world_state.global_flags.status_{se_name}_{target}",
                    operation="set",
                    old_value=None,
                    new_value=se_duration,
                    source_action_id=source_action_id,
                    source_event_id=source_event_id,
                    metadata={
                        "caster": caster,
                        "target": target,
                        "status_effect": se_name,
                        "duration": se_duration,
                        "resolution": "combat_status_effect",
                    },
                )
            )

        return candidates

    # ------------------------------------------------------------------
    # 7. World time change resolution
    # ------------------------------------------------------------------

    def resolve_world_time_change(
        self,
        old_time: Any,
        new_time: Any,
    ) -> List[StateDeltaCandidate]:
        """Generate delta for world time advancement.

        Args:
            old_time: The previous world time value (int or WorldTime).
            new_time: The new world time value.

        Returns:
            List containing a single StateDeltaCandidate for the time change.
        """
        source_event_id = ""
        if isinstance(old_time, dict):
            source_event_id = old_time.get("source_event_id", "")
            old_time_val = old_time.get("value", old_time)
        else:
            old_time_val = old_time

        if isinstance(new_time, dict):
            new_time_val = new_time.get("value", new_time)
        else:
            new_time_val = new_time

        return [
            StateDeltaCandidate(
                path="session_state.world_time",
                operation="set",
                old_value=old_time_val,
                new_value=new_time_val,
                source_event_id=source_event_id,
                metadata={"resolution": "world_time_change"},
            )
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _hp_path(entity_id: str) -> str:
        """Return the contract path for an entity's HP."""
        if entity_id == "player" or entity_id.startswith("player"):
            return "player_state.hp"
        return f"npc_state.{entity_id}.hp"

    @staticmethod
    def _resolve_entity_hp(entity_id: str, state: Any) -> Any:
        """Best-effort retrieval of an entity's current HP.

        Returns None when the value cannot be determined from the inputs.
        """
        if state is None:
            return None
        try:
            if entity_id == "player" or entity_id.startswith("player"):
                return StateDeltaResolver._get_player_field(state, "hp", None)
            return StateDeltaResolver._get_npc_field(state, entity_id, "hp", None)
        except Exception:
            return None

    @staticmethod
    def _get_player_field(state: Any, field_name: str, default: Any) -> Any:
        """Read a field from player_state, falling back gracefully."""
        if state is None:
            return default
        try:
            ps = getattr(state, "player_state", None)
            if ps is None:
                return default
            val = getattr(ps, field_name, None)
            if val is not None:
                return val
            phys = getattr(ps, "physical_state", None)
            if phys is not None:
                val = getattr(phys, field_name, None)
                if val is not None:
                    return val
            field_map = {
                "hp": "hp",
                "spiritual_power": "spiritual_power",
                "spirit_power": "spiritual_power",
                "stamina": "fatigue",
                "location_id": "location_id",
                "inventory_ids": "inventory_ids",
            }
            mapped = field_map.get(field_name)
            if mapped and mapped != field_name:
                val = getattr(ps, mapped, None)
                if val is not None:
                    return val
                if phys is not None:
                    val = getattr(phys, mapped, None)
                    if val is not None:
                        return val
            return default
        except Exception:
            return default

    @staticmethod
    def _get_npc_field(state: Any, npc_id: str, field_name: str, default: Any) -> Any:
        """Read a field from an NPC's state, falling back gracefully."""
        if state is None:
            return default
        try:
            npc_states = getattr(state, "npc_states", None)
            if npc_states is None:
                return default
            npc = npc_states.get(npc_id) if isinstance(npc_states, dict) else None
            if npc is None:
                return default
            val = getattr(npc, field_name, None)
            if val is not None:
                return val
            phys = getattr(npc, "physical_state", None)
            if phys is not None:
                val = getattr(phys, field_name, None)
                if val is not None:
                    return val
            mental = getattr(npc, "mental_state", None)
            if mental is not None:
                val = getattr(mental, field_name, None)
                if val is not None:
                    return val
            field_map = {
                "hp": "hp",
                "current_location_id": "location_id",
                "trust_score": "trust_toward_player",
                "suspicion_score": "suspicion_toward_player",
            }
            mapped = field_map.get(field_name)
            if mapped and mapped != field_name:
                val = getattr(npc, mapped, None)
                if val is not None:
                    return val
                if phys is not None:
                    val = getattr(phys, mapped, None)
                    if val is not None:
                        return val
                if mental is not None:
                    val = getattr(mental, mapped, None)
                    if val is not None:
                        return val
            return default
        except Exception:
            return default
