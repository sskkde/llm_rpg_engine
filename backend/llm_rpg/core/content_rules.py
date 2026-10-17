"""Pure execution rules for a frozen ``content_v1`` bundle.

No persistence, DB session, LLM, wall clock, or randomness is used here. The
WorldAdvancer owns queue ordering and state-copy isolation; this class supplies
only state transitions, finite derived steps, and immutable event/delta drafts.
"""

from __future__ import annotations

import copy
from dataclasses import replace
from typing import Any, Dict, List, Mapping, Optional, Tuple

from llm_rpg.models.content_v2 import CONTENT_PROFILE_ID
from llm_rpg.content.runtime_models import (
    CompiledContentRulesData,
    CompiledRule,
    CurrentPlanState,
    ItemInstanceState,
    PlanStatus,
)
from llm_rpg.core.npc_plan_policy import (
    ConditionValue,
    evaluate_condition,
    evaluate_condition_value,
    select_plan,
)
from llm_rpg.core.time_simulation import (
    PlayerActionKind,
    PlayerActionSpec,
    ScheduledStep,
    SimulationPhase,
    StepKind,
    StepStatus,
    TimeSimulationStateError,
    WorkingState,
    travel_step_key,
)
from llm_rpg.core.time_simulation_rules import (
    CognitionDraft,
    SimulationDeltaDraft,
    SimulationEventDraft,
    StepEffect,
)


class ContentPlanReevaluationBudgetError(TimeSimulationStateError):
    """A single advance crossed the bounded 64 plan-boundary evaluations."""

    code = "CONTENT_PLAN_REEVAL_BUDGET"


class CompiledContentRules:
    """Interpret the finite compiled condition/effect vocabulary."""

    def __init__(self, data: CompiledContentRulesData) -> None:
        self._data = data
        self._rules_by_id = {rule.id: rule for rule in data.rules}
        self._goals_by_id = {str(goal["id"]): goal for goal in data.goals}

    @property
    def profile_id(self) -> str:
        return CONTENT_PROFILE_ID

    @property
    def data(self) -> CompiledContentRulesData:
        return self._data

    def initial_state(self) -> WorkingState:
        initial = self.data.initial_state
        player = initial.get("player", {})
        positions = {code: str(character.get("initial_location_id", ""))
                     for code, character in self.data.characters.items()}
        alive = {code: bool(character.get("alive", True))
                 for code, character in self.data.characters.items()}
        for character in initial.get("characters", ()):
            positions[character["id"]] = character["location_id"]
            alive[character["id"]] = bool(character.get("alive", True))

        base_routes = {
            f"{source}->{target}": bool(route.get("open", True))
            for (source, target), route in self.data.routes.items()
        }
        initial_route_values = {
            f"{route['from']}->{route['to']}": bool(route["open"])
            for route in initial.get("routes", ())
        }
        overrides = {
            key: value for key, value in initial_route_values.items()
            if key not in base_routes or base_routes[key] != value
        }

        item_initial = {item["id"]: item["owner"] for item in initial.get("items", ())}
        item_instances: Dict[str, ItemInstanceState] = {}
        for code, item in self.data.items.items():
            owner = item_initial.get(code)
            if owner is None:
                continue
            owner_type, owner_ref = _parse_owner(owner)
            item_instances[code] = ItemInstanceState(
                code=code,
                quantity=int(item.get("quantity", 1)),
                owner_type=owner_type,
                owner_ref=owner_ref,
            )

        npc_goals: Dict[str, str] = {}
        for goal in self.data.goals:
            if goal.get("initial_status", "inactive") != "active":
                continue
            goal_actor = goal.get("character_id")
            if goal_actor is not None:
                npc_goals.setdefault(goal_actor, str(goal["id"]))

        return WorkingState(
            logical_tick=int(self.data.world.get("start_tick", 0)),
            player_location_code=str(player.get("location_id", "")),
            player_alive=bool(player.get("alive", True)),
            npc_positions=positions,
            npc_alive=alive,
            npc_plans={code: None for code in self.data.characters},
            routes_open=base_routes,
            one_shot={},
            item_instances=item_instances,
            flags=copy.deepcopy(dict(self.data.declared_flags)),
            npc_goals=npc_goals,
            npc_current_plans={},
            route_overrides=overrides,
        )

    def initial_steps(self) -> List[ScheduledStep]:
        steps: List[ScheduledStep] = []
        for rule in self.data.rules:
            trigger = rule.trigger
            if trigger.kind == "on_time_crossed" and trigger.due_tick is not None and trigger.due_tick >= 1:
                tick = trigger.due_tick
                steps.append(
                    ScheduledStep(
                        step_key=f"rule:{rule.id}@{tick}",
                        tick=tick,
                        phase=trigger.phase,
                        actor_code="world",
                        kind=StepKind.CONTENT_RULE_FIRE,
                        payload={"rule": rule.id, "occurrence": str(tick)},
                    )
                )
        # A Schedule is a finite decision boundary, never a teleport. Reuse the
        # NPC_MOVE start kind as its control step; it carries only schedule_id.
        for schedule in self.data.schedules:
            tick = int(schedule["at_tick"])
            if tick < 1:
                continue
            actor = str(schedule["character_id"])
            schedule_id = str(schedule["id"])
            steps.append(
                ScheduledStep(
                    step_key=f"schedule:{schedule_id}@{tick}",
                    tick=tick,
                    phase=int(SimulationPhase.NPC_MOVE),
                    actor_code=actor,
                    kind=StepKind.NPC_TRAVEL_START,
                    payload={"schedule": schedule_id},
                )
            )
        return sorted(steps, key=lambda step: step.order_key)

    def player_completion_step(self, player_action: PlayerActionSpec) -> Optional[ScheduledStep]:
        if player_action.kind not in (PlayerActionKind.IDLE, PlayerActionKind.MOVE):
            return None
        return ScheduledStep(
            step_key=travel_step_key("player", StepKind.PLAYER_CONTINUOUS_COMPLETE, player_action.end_tick),
            tick=player_action.end_tick,
            phase=int(SimulationPhase.PLAYER_CONTINUOUS),
            actor_code="player",
            kind=StepKind.PLAYER_CONTINUOUS_COMPLETE,
            payload={
                "action_kind": player_action.kind,
                "action_type": player_action.action_type,
                "target_location_code": player_action.target_location_code,
            },
        )

    def apply_step(
        self,
        *,
        state: WorkingState,
        step: ScheduledStep,
        player_action: PlayerActionSpec,
    ) -> StepEffect:
        handlers = {
            StepKind.CONTENT_RULE_FIRE: self._fire_rule,
            StepKind.NPC_TRAVEL_START: self._travel_start,
            StepKind.NPC_TRAVEL_ARRIVE: self._travel_arrive,
            StepKind.NPC_TAKE_ITEM: self._take_item_step,
            StepKind.NPC_USE_ITEM: self._use_item_step,
            StepKind.NPC_WAIT_COMPLETE: self._wait_complete,
            StepKind.PLAYER_CONTINUOUS_COMPLETE: self._player_complete,
        }
        handler = handlers.get(step.kind)
        if handler is None:
            raise TimeSimulationStateError(f"unsupported content_v1 step kind {step.kind!r}")
        return handler(state, step, player_action)

    # ------------------------------------------------------------------
    # Rule firing / effect transaction
    # ------------------------------------------------------------------

    def _fire_rule(self, state: WorkingState, step: ScheduledStep, player_action: PlayerActionSpec) -> StepEffect:
        rule_id = step.payload.get("rule")
        occurrence = step.payload.get("occurrence")
        rule = self._rules_by_id.get(rule_id)
        if rule is None or not isinstance(occurrence, str):
            raise TimeSimulationStateError("content_rule_fire has an unknown rule or occurrence")
        consumed_key = _rule_consumed_key(rule, occurrence)
        if state.one_shot.get(consumed_key):
            return StepEffect(status=StepStatus.CANCELLED, detail_code="already_fired")
        # A trigger is terminal whether its condition is true, false, or unknown;
        # explicit event_schedule is the only way to create a new occurrence.
        state.one_shot[consumed_key] = True
        condition = evaluate_condition_value(rule.condition, data=self.data, state=state, actor="world")
        if condition is not ConditionValue.TRUE:
            return StepEffect(
                status=StepStatus.CANCELLED,
                detail_code="condition_unknown" if condition is ConditionValue.UNKNOWN else "condition_false",
            )

        work = state.copy()
        applied_events: List[SimulationEventDraft] = []
        applied_deltas: List[SimulationDeltaDraft] = []
        derived: List[ScheduledStep] = []
        interrupts = False
        applied_types: List[str] = []
        for effect in rule.effects:
            result = self._apply_effect(
                effect=effect,
                state=work,
                step=step,
                player_action=player_action,
            )
            if not result.applied:
                # Domain precondition failure is an explicit no-effect outcome;
                # discard every tentative mutation in this effect group.
                return StepEffect(
                    status=StepStatus.BLOCKED,
                    events=result.events,
                    detail_code=result.detail_code,
                    detail_message=result.detail_message,
                )
            applied_types.append(effect[0])
            applied_events.extend(result.events)
            applied_deltas.extend(result.deltas)
            derived.extend(result.derived_steps)
            interrupts = interrupts or result.interrupts_player

        state.__dict__.update(work.__dict__)
        applied_events.append(
            self._event(
                state,
                "content_rule_fired",
                {
                    "rule": rule.id,
                    "occurrence": occurrence,
                    "tick": step.tick,
                    "effects_applied": applied_types,
                },
                location=None,
            )
        )
        return StepEffect(
            status=StepStatus.APPLIED,
            events=tuple(applied_events),
            deltas=tuple(applied_deltas),
            derived_steps=tuple(derived),
            interrupts_player=interrupts,
        )

    def _apply_effect(
        self,
        *,
        effect: Any,
        state: WorkingState,
        step: ScheduledStep,
        player_action: PlayerActionSpec,
    ) -> "_EffectResult":
        effect_type, raw_args = effect
        args = {key: _thaw(value) for key, value in raw_args}
        tick = step.tick
        if effect_type == "flag_set":
            key, value = args["key"], args["value"]
            old = state.flags.get(key)
            state.flags[key] = copy.deepcopy(value)
            return _EffectResult(
                events=[self._event(state, "flag_changed", {"key": key, "old_value": old, "new_value": value, "tick": tick})],
                deltas=[SimulationDeltaDraft(f"world.flags.{key}", "set", old, value, "hidden")],
            )
        if effect_type == "route_set_open":
            source, target, opened = args["from"], args["to"], args["open"]
            key = f"{source}->{target}"
            if (source, target) not in self.data.routes:
                return _EffectResult.failure("route_unknown")
            old = state.route_is_open(source, target)
            # Session-scoped mutation only; the compiled route definition is immutable.
            state.route_overrides[key] = bool(opened)
            payload = {"from": source, "to": target, "open": bool(opened), "tick": tick}
            visible = state.player_alive and state.player_location_code == source
            return _EffectResult(
                events=[self._event(state, "route_changed", payload, location=source)],
                deltas=[SimulationDeltaDraft(f"routes.{key}", "set", old, bool(opened), "player_visible" if visible else "hidden")],
            )
        if effect_type == "npc_action_start":
            return self._start_action(
                state=state,
                step=step,
                actor=args["actor"],
                action=args["action"],
                target=args.get("target"),
                ticks=args.get("ticks"),
                player_action=player_action,
                goal_id=state.npc_goals.get(args["actor"], "rule_action"),
                source="goal" if args["actor"] in state.npc_goals else "schedule",
                recipe_step=0,
                generation=None,
            )
        if effect_type == "plan_start":
            actor, goal_id = args["actor"], args["goal"]
            if goal_id not in self._goals_by_id:
                return _EffectResult.failure("goal_unknown")
            state.npc_goals[actor] = goal_id
            plan_events, plan_deltas, plan_steps = self._reevaluate_plan(
                state=state,
                actor=actor,
                tick=tick,
                cause_step=step,
                player_action=player_action,
                only_goal=goal_id,
            )
            return _EffectResult(events=plan_events, deltas=plan_deltas, derived_steps=plan_steps)
        if effect_type == "item_transfer":
            return self._transfer_item(state, step, args["item"], args["to"])
        if effect_type == "item_use":
            return self._use_item(state, step, args["item"], args["actor"])
        if effect_type == "interrupt":
            kind, message = args["kind"], args["message"]
            payload = {"kind": kind, "message": message, "tick": tick}
            return _EffectResult(
                events=[self._event(state, "world_interrupt", payload, force_visible=True)],
                interrupts_player=True,
            )
        if effect_type == "emit_event":
            payload = copy.deepcopy(args["payload"])
            return _EffectResult(events=[self._event(state, args["event_type"], payload)])
        if effect_type == "event_schedule":
            target_rule = self._rules_by_id.get(args["rule"])
            due_tick = args["tick"]
            if target_rule is None:
                raise TimeSimulationStateError(f"event_schedule references unknown rule {args['rule']!r}")
            if isinstance(due_tick, bool) or not isinstance(due_tick, int) or due_tick <= tick:
                raise TimeSimulationStateError("event_schedule tick must be greater than the current tick")
            return _EffectResult(
                derived_steps=[
                    ScheduledStep(
                        step_key=f"rule:{target_rule.id}@{due_tick}",
                        tick=due_tick,
                        phase=target_rule.trigger.phase,
                        actor_code="world",
                        kind=StepKind.CONTENT_RULE_FIRE,
                        payload={"rule": target_rule.id, "occurrence": str(due_tick)},
                    )
                ]
            )
        raise TimeSimulationStateError(f"unsupported compiled effect type {effect_type!r}")

    # ------------------------------------------------------------------
    # NPC plan and action primitives
    # ------------------------------------------------------------------

    def _travel_start(self, state: WorkingState, step: ScheduledStep, player_action: PlayerActionSpec) -> StepEffect:
        schedule_id = step.payload.get("schedule")
        if schedule_id is not None:
            schedule = next((item for item in self.data.schedules if item.get("id") == schedule_id), None)
            if schedule is None or schedule.get("character_id") != step.actor_code:
                raise TimeSimulationStateError("schedule decision step references an unknown schedule")
            events, deltas, derived = self._reevaluate_plan(
                state=state,
                actor=step.actor_code,
                tick=step.tick,
                cause_step=step,
                player_action=player_action,
            )
            return StepEffect(status=StepStatus.APPLIED, events=tuple(events), deltas=tuple(deltas), derived_steps=tuple(derived))

        actor = step.actor_code
        source = step.payload.get("from")
        target = step.payload.get("to")
        end = step.payload.get("expected_end")
        if not isinstance(source, str) or not isinstance(target, str) or isinstance(end, bool) or not isinstance(end, int):
            raise TimeSimulationStateError("npc_travel_start requires from, to, and expected_end")
        if end <= step.tick:
            raise TimeSimulationStateError("npc_travel_start must end after it starts")
        return self._start_action(
            state=state,
            step=step,
            actor=actor,
            action="move",
            target=target,
            ticks=end - step.tick,
            player_action=player_action,
            goal_id=state.npc_goals.get(actor, "rule_action"),
            source="goal" if actor in state.npc_goals else "schedule",
            recipe_step=0,
            generation=None,
            expected_from=source,
        ).as_step_effect()

    def _start_action(
        self,
        *,
        state: WorkingState,
        step: ScheduledStep,
        actor: str,
        action: str,
        target: Optional[str],
        ticks: Optional[int],
        player_action: PlayerActionSpec,
        goal_id: str,
        source: str,
        recipe_step: int,
        generation: Optional[int],
        expected_from: Optional[str] = None,
    ) -> "_EffectResult":
        if actor not in self.data.character_ids():
            return _EffectResult.failure("actor_unknown")
        if not state.npc_is_alive(actor):
            return self._travel_failure(state, actor, step.tick, expected_from or state.npc_positions.get(actor, ""), target or "", "actor_not_alive")
        location = state.npc_positions.get(actor)
        if location is None:
            return _EffectResult.failure("actor_location_unknown")
        if expected_from is not None and location != expected_from:
            return self._travel_failure(state, actor, step.tick, expected_from, target or "", "actor_not_at_origin")
        if action == "move":
            if not isinstance(target, str) or target not in self.data.location_ids():
                return _EffectResult.failure("target_unknown")
            current = state.npc_current_plans.get(actor)
            if current is not None and current.status in {PlanStatus.TRAVELING.value, PlanStatus.WAITING.value}:
                return _EffectResult.failure("already_traveling")
            if not state.route_is_open(location, target):
                return self._travel_failure(state, actor, step.tick, location, target, "route_closed")
            if ticks is None:
                route = self.data.routes.get((location, target))
                ticks = int(route.get("travel_ticks", 1)) if route is not None else 1
            if isinstance(ticks, bool) or not isinstance(ticks, int) or ticks < 1:
                raise TimeSimulationStateError("NPC move ticks must be a positive integer")
            end_tick = step.tick + ticks
            previous = state.npc_current_plans.get(actor)
            plan_generation = generation if generation is not None else (previous.generation + 1 if previous else 1)
            plan = CurrentPlanState(goal_id, source, plan_generation, recipe_step, "move", target, step.tick, end_tick, PlanStatus.TRAVELING.value)
            state.npc_current_plans[actor] = plan
            state.npc_goals[actor] = goal_id
            arrival = ScheduledStep(
                step_key=f"plan:{actor}:{plan_generation}:arrive@{end_tick}",
                tick=end_tick,
                phase=int(SimulationPhase.NPC_MOVE),
                actor_code=actor,
                kind=StepKind.NPC_TRAVEL_ARRIVE,
                payload={"from": location, "to": target, "generation": plan_generation},
            )
            payload = {"npc_id": actor, "from": location, "to": target, "expected_end_tick": end_tick}
            return _EffectResult(
                events=[self._event(state, "npc_travel_started", payload, actor=actor, location=location)],
                deltas=[SimulationDeltaDraft(f"npcs.{actor}.plan", "set", None if previous is None else _plan_to_dict(previous), _plan_to_dict(plan), "hidden")],
                derived_steps=[arrival],
            )
        if action == "wait":
            current = state.npc_current_plans.get(actor)
            if current is not None and current.status in {PlanStatus.TRAVELING.value, PlanStatus.WAITING.value}:
                return _EffectResult.failure("already_traveling")
            if ticks is None:
                raise TimeSimulationStateError("NPC wait action requires ticks")
            if isinstance(ticks, bool) or not isinstance(ticks, int) or ticks < 1:
                raise TimeSimulationStateError("NPC wait ticks must be a positive integer")
            end_tick = step.tick + ticks
            previous = state.npc_current_plans.get(actor)
            plan_generation = generation if generation is not None else (previous.generation + 1 if previous else 1)
            plan = CurrentPlanState(goal_id, source, plan_generation, recipe_step, "wait", target, step.tick, end_tick, PlanStatus.WAITING.value)
            state.npc_current_plans[actor] = plan
            state.npc_goals[actor] = goal_id
            wait_step = ScheduledStep(
                step_key=f"plan:{actor}:{plan_generation}:wait@{end_tick}",
                tick=end_tick,
                phase=int(SimulationPhase.NPC_MOVE),
                actor_code=actor,
                kind=StepKind.NPC_WAIT_COMPLETE,
                payload={"location": location, "generation": plan_generation},
            )
            payload = {"npc_id": actor, "location": location, "expected_end_tick": end_tick}
            return _EffectResult(
                events=[self._event(state, "npc_wait_started", payload, actor=actor, location=location)],
                deltas=[SimulationDeltaDraft(f"npcs.{actor}.plan", "set", None if previous is None else _plan_to_dict(previous), _plan_to_dict(plan), "hidden")],
                derived_steps=[wait_step],
            )
        if action in {"take", "use", "transfer"}:
            if not isinstance(target, str):
                return _EffectResult.failure("item_unknown")
            previous = state.npc_current_plans.get(actor)
            plan_generation = generation if generation is not None else (previous.generation + 1 if previous else 1)
            plan = CurrentPlanState(goal_id, source, plan_generation, recipe_step, action, target, step.tick, step.tick, PlanStatus.ACTIVE.value)
            state.npc_current_plans[actor] = plan
            state.npc_goals[actor] = goal_id
            if action == "take":
                result = self._transfer_item(state, step, target, f"character:{actor}")
            elif action == "use":
                result = self._use_item(state, step, target, actor)
            else:
                item = state.item_instances.get(target)
                to = f"location:{location}" if item is not None else "player"
                result = self._transfer_item(state, step, target, to)
            return result
        raise TimeSimulationStateError(f"unsupported NPC plan action {action!r}")

    # 当前无 DSL 取消触发源，故未实现取消边界。
    def _reevaluate_plan(
        self,
        *,
        state: WorkingState,
        actor: str,
        tick: int,
        cause_step: ScheduledStep,
        player_action: PlayerActionSpec,
        only_goal: Optional[str] = None,
    ) -> Tuple[List[SimulationEventDraft], List[SimulationDeltaDraft], List[ScheduledStep]]:
        self._count_plan_reevaluation(state, actor, tick, cause_step, player_action)
        current = state.npc_current_plans.get(actor)
        current_goal_id = state.npc_goals.get(actor)
        current_goal = self._goals_by_id.get(current_goal_id) if current_goal_id else None

        def completion_true(condition: Any) -> bool:
            return evaluate_condition(condition, data=self.data, state=state, actor=actor)

        # Every policy boundary runs the same deterministic candidate filter;
        # current-goal completion then takes precedence over fallback candidates.
        policy_data = self.data
        if only_goal is not None:
            requested = self._goals_by_id.get(only_goal)
            policy_data = replace(self.data, goals=() if requested is None else (requested,))
        selection = select_plan(
            data=policy_data,
            state=state,
            actor=actor,
            tick=tick,
            completion_condition_is_true=completion_true,
        )
        if current_goal is not None and current_goal.get("completion") is not None:
            if evaluate_condition(current_goal["completion"], data=self.data, state=state, actor=actor):
                if current is not None and current.status == PlanStatus.ACHIEVED.value:
                    return [], [], []
                generation = current.generation if current is not None else 0
                if current is not None:
                    state.npc_current_plans[actor] = replace(current, status=PlanStatus.ACHIEVED.value, failure_code=None)
                return [self._event(state, "plan_achieved", {"npc_id": actor, "goal_id": current_goal_id, "generation": generation}, actor=actor)], [], []

        if selection is None:
            fallback = self._default_schedule_selection(actor, tick, state)
            if fallback is None:
                if current is not None:
                    state.npc_current_plans[actor] = replace(current, status=PlanStatus.BLOCKED.value)
                return [self._event(state, "plan_blocked", {"npc_id": actor, "reason": "no_candidate"}, actor=actor)], [], []
            selection, fallback_goal_id = fallback
            goal_id = fallback_goal_id
            source = "schedule"
            priority = 0
        else:
            goal_id = selection.goal_id
            source = selection.source
            priority = int(self._goals_by_id[goal_id].get("priority", 0))

        previous = state.npc_current_plans.get(actor)
        generation = previous.generation + 1 if previous is not None else 1
        expected_end = tick + selection.ticks if selection.action in {"move", "wait"} else tick
        state.npc_goals[actor] = goal_id
        plan_selected = self._event(
            state,
            "plan_selected",
            {
                "npc_id": actor,
                "goal_id": goal_id,
                "priority": priority,
                "source": source,
                "generation": generation,
                "recipe_step": selection.recipe_step,
                "action": selection.action,
                "target": selection.target,
                "expected_end_tick": expected_end,
            },
            actor=actor,
            location=state.npc_positions.get(actor),
        )
        start = self._start_action(
            state=state,
            step=cause_step,
            actor=actor,
            action=selection.action,
            target=selection.target,
            ticks=selection.ticks,
            player_action=player_action,
            goal_id=goal_id,
            source=source,
            recipe_step=selection.recipe_step,
            generation=generation,
        )
        return [plan_selected, *start.events], start.deltas, start.derived_steps

    def _default_schedule_selection(
        self, actor: str, tick: int, state: WorkingState
    ) -> Optional[Tuple[Any, str]]:
        schedules = [
            schedule for schedule in self.data.schedules
            if schedule.get("character_id") == actor
            and schedule.get("default_activity") is True
            and int(schedule.get("at_tick", 0)) <= tick < int(schedule.get("at_tick", 0)) + int(schedule.get("window_ticks", 1))
        ]
        if not schedules:
            return None
        schedule = sorted(schedules, key=lambda item: str(item["id"]))[0]
        location = state.npc_positions.get(actor)
        target_location = str(schedule["location_id"])
        if location == target_location:
            from llm_rpg.core.npc_plan_policy import PlanSelection
            selection = PlanSelection(str(schedule["id"]), "schedule", 0, "wait", None, int(schedule["window_ticks"]))
        else:
            route = self.data.routes.get((location, target_location)) if location is not None else None
            if route is None or not state.route_is_open(location, target_location):
                return None
            from llm_rpg.core.npc_plan_policy import PlanSelection
            selection = PlanSelection(str(schedule["id"]), "schedule", 0, "move", target_location, int(route.get("travel_ticks", 1)))
        return selection, str(schedule["id"])

    def _count_plan_reevaluation(
        self,
        state: WorkingState,
        actor: str,
        tick: int,
        cause_step: ScheduledStep,
        player_action: PlayerActionSpec,
    ) -> None:
        # Bounded marker keys are one-per-finite schedule/plan boundary. Counting
        # only markers in (advance.start, advance.end] resets the 64 budget without
        # changing WorldAdvancer or adding unbounded per-turn state.
        prefix = "content_plan_reeval:"
        marker = f"{prefix}{tick}:{actor}:{cause_step.step_key}"
        if state.one_shot.get(marker):
            return
        in_advance = 0
        for key, consumed in state.one_shot.items():
            if not consumed or not key.startswith(prefix):
                continue
            try:
                marker_tick = int(key[len(prefix):].split(":", 1)[0])
            except (ValueError, IndexError):
                continue
            if player_action.start_tick < marker_tick <= player_action.end_tick:
                in_advance += 1
        if in_advance >= 64:
            raise ContentPlanReevaluationBudgetError("content plan reevaluation budget exceeded (64 per advance)")
        state.one_shot[marker] = True

    def _travel_arrive(self, state: WorkingState, step: ScheduledStep, player_action: PlayerActionSpec) -> StepEffect:
        actor = step.actor_code
        plan = state.npc_current_plans.get(actor)
        generation = step.payload.get("generation")
        if plan is None or plan.generation != generation or plan.action != "move" or plan.status != PlanStatus.TRAVELING.value:
            raise TimeSimulationStateError("npc_travel_arrive has no matching traveling CurrentPlan")
        source = state.npc_positions.get(actor)
        target = plan.target or ""
        reason = None
        if not state.npc_is_alive(actor):
            reason = "actor_not_alive"
        elif source != step.payload.get("from"):
            reason = "actor_moved"
        elif not state.route_is_open(source or "", target):
            reason = "route_closed"
        if reason is not None:
            failed = replace(plan, status=PlanStatus.FAILED.value, failure_code=reason)
            state.npc_current_plans[actor] = failed
            events = [self._event(state, "npc_travel_failed", {"npc_id": actor, "from": step.payload.get("from", ""), "to": target, "reason": reason}, actor=actor, location=source)]
            events.append(self._event(state, "plan_failed", {"npc_id": actor, "goal_id": plan.goal_id, "generation": plan.generation, "recipe_step": plan.recipe_step, "failure_code": reason}, actor=actor, location=source))
            more_events, deltas, derived = self._reevaluate_plan(state=state, actor=actor, tick=step.tick, cause_step=step, player_action=player_action)
            return StepEffect(status=StepStatus.BLOCKED, events=tuple(events + more_events), deltas=tuple(deltas), derived_steps=tuple(derived), detail_code=reason)

        old_location = state.npc_positions[actor]
        state.npc_positions[actor] = target
        state.npc_current_plans[actor] = replace(plan, status=PlanStatus.ACTIVE.value, failure_code=None)
        payload = {"npc_id": actor, "from": old_location, "to": target}
        events = [self._event(state, "npc_arrived", payload, actor=actor, location=target)]
        deltas = [SimulationDeltaDraft(f"npcs.{actor}.location", "set", old_location, target, "player_visible" if state.player_alive and state.player_location_code == target else "hidden")]
        completion_steps = self._completion_rule_events(state, actor, "move", target, step, player_action)
        more_events, more_deltas, derived = self._reevaluate_plan(state=state, actor=actor, tick=step.tick, cause_step=step, player_action=player_action)
        return StepEffect(status=StepStatus.APPLIED, events=tuple(events + more_events), deltas=tuple(deltas + more_deltas), derived_steps=tuple(completion_steps + derived))

    def _wait_complete(self, state: WorkingState, step: ScheduledStep, player_action: PlayerActionSpec) -> StepEffect:
        actor = step.actor_code
        plan = state.npc_current_plans.get(actor)
        generation = step.payload.get("generation")
        if plan is None or plan.generation != generation or plan.action != "wait" or plan.status != PlanStatus.WAITING.value:
            raise TimeSimulationStateError("npc_wait_complete has no matching waiting CurrentPlan")
        location = state.npc_positions.get(actor)
        planned_location = step.payload.get("location")
        reason = None
        if not state.npc_is_alive(actor):
            reason = "actor_not_alive"
        elif location != planned_location:
            reason = "actor_moved"
        if reason is not None:
            failed = replace(plan, status=PlanStatus.FAILED.value, failure_code=reason)
            state.npc_current_plans[actor] = failed
            events = [self._event(state, "npc_travel_failed", {"npc_id": actor, "from": planned_location or "", "to": plan.target or planned_location or "", "reason": reason}, actor=actor, location=location)]
            events.append(self._event(state, "plan_failed", {"npc_id": actor, "goal_id": plan.goal_id, "generation": plan.generation, "recipe_step": plan.recipe_step, "failure_code": reason}, actor=actor, location=location))
            more_events, deltas, derived = self._reevaluate_plan(state=state, actor=actor, tick=step.tick, cause_step=step, player_action=player_action)
            return StepEffect(status=StepStatus.BLOCKED, events=tuple(events + more_events), deltas=tuple(deltas), derived_steps=tuple(derived), detail_code=reason)

        state.npc_current_plans[actor] = replace(plan, status=PlanStatus.ACTIVE.value, failure_code=None)
        events = [self._event(state, "npc_wait_completed", {"npc_id": actor, "location": location}, actor=actor, location=location)]
        completion_steps = self._completion_rule_events(state, actor, "idle", location, step, player_action)
        more_events, deltas, derived = self._reevaluate_plan(state=state, actor=actor, tick=step.tick, cause_step=step, player_action=player_action)
        return StepEffect(status=StepStatus.APPLIED, events=tuple(events + more_events), deltas=tuple(deltas), derived_steps=tuple(completion_steps + derived))

    def _travel_failure(self, state: WorkingState, actor: str, tick: int, source: str, target: str, reason: str) -> "_EffectResult":
        current = state.npc_current_plans.get(actor)
        events = [self._event(state, "npc_travel_failed", {"npc_id": actor, "from": source, "to": target, "reason": reason}, actor=actor, location=source)]
        if current is not None:
            state.npc_current_plans[actor] = replace(current, status=PlanStatus.FAILED.value, failure_code=reason)
            events.append(self._event(state, "plan_failed", {"npc_id": actor, "goal_id": current.goal_id, "generation": current.generation, "recipe_step": current.recipe_step, "failure_code": reason}, actor=actor, location=source))
        return _EffectResult(applied=False, events=events, detail_code=reason)

    # ------------------------------------------------------------------
    # Items and player completion
    # ------------------------------------------------------------------

    def _take_item_step(self, state: WorkingState, step: ScheduledStep, player_action: PlayerActionSpec) -> StepEffect:
        result = self._transfer_item(state, step, step.payload.get("item"), f"character:{step.actor_code}")
        return result.as_step_effect()

    def _use_item_step(self, state: WorkingState, step: ScheduledStep, player_action: PlayerActionSpec) -> StepEffect:
        result = self._use_item(state, step, step.payload.get("item"), step.actor_code)
        return result.as_step_effect()

    def _transfer_item(self, state: WorkingState, step: ScheduledStep, item_code: Any, destination: Any) -> "_EffectResult":
        actor = _destination_actor(destination, step.actor_code)
        item = state.item_instances.get(item_code) if isinstance(item_code, str) else None
        if item is None:
            return self._item_failure(state, "item_take_failed", item_code, actor, "item_unknown")
        _assert_unique_instance(state, item_code, item)
        destination_parts = _parse_owner_safe(destination)
        if destination_parts is None:
            raise TimeSimulationStateError(f"invalid item destination {destination!r}")
        destination_type, destination_ref = destination_parts
        if destination_type == "location":
            acting_actor = item.owner_ref if item.owner_type == "character" else ("player" if item.owner_type == "player" else actor)
            if not self._actor_alive(state, acting_actor):
                return self._item_failure(state, "item_take_failed", item_code, acting_actor, "actor_not_alive")
            actor_location = self._actor_location(state, acting_actor)
            if actor_location != destination_ref:
                return self._item_failure(state, "item_take_failed", item_code, acting_actor, "actor_not_at_item")
        else:
            acting_actor = destination_ref if destination_type == "character" else "player"
            if not self._actor_alive(state, acting_actor):
                return self._item_failure(state, "item_take_failed", item_code, acting_actor, "actor_not_alive")
            if item.owner_type != "location":
                return self._item_failure(state, "item_take_failed", item_code, acting_actor, "already_taken")
            actor_location = self._actor_location(state, acting_actor)
            if actor_location is None or actor_location != item.owner_ref:
                return self._item_failure(state, "item_take_failed", item_code, acting_actor, "actor_not_at_item")
        old_owner = _owner_text(item.owner_type, item.owner_ref)
        new_owner = _owner_text(destination_type, destination_ref)
        if old_owner == new_owner:
            return self._item_failure(state, "item_take_failed", item_code, actor, "already_taken")
        state.item_instances[item_code] = replace(item, owner_type=destination_type, owner_ref=destination_ref)
        payload = {"item": item_code, "from": old_owner, "to": new_owner}
        return _EffectResult(
            events=[self._event(state, "item_acquired", payload, actor=acting_actor, location=self._actor_location(state, acting_actor))],
            deltas=[SimulationDeltaDraft(f"inventory.{item_code}.owner", "set", old_owner, new_owner, "hidden")],
        )

    def _use_item(self, state: WorkingState, step: ScheduledStep, item_code: Any, actor: Any) -> "_EffectResult":
        actor_code = actor if isinstance(actor, str) else step.actor_code
        item = state.item_instances.get(item_code) if isinstance(item_code, str) else None
        if item is None:
            return self._item_failure(state, "item_use_failed", item_code, actor_code, "item_unknown")
        _assert_unique_instance(state, item_code, item)
        if not self._actor_alive(state, actor_code) or self._actor_location(state, actor_code) is None:
            return self._item_failure(state, "item_use_failed", item_code, actor_code, "actor_not_alive")
        owner = ("player", "player") if actor_code == "player" else ("character", actor_code)
        if (item.owner_type, item.owner_ref) != owner:
            return self._item_failure(state, "item_use_failed", item_code, actor_code, "not_owner")
        if state.one_shot.get(f"content_item_used:{item_code}:{actor_code}"):
            return self._item_failure(state, "item_use_failed", item_code, actor_code, "already_used")
        state.one_shot[f"content_item_used:{item_code}:{actor_code}"] = True
        item_def = self.data.items.get(item_code, {})
        payload = {"item": item_code, "actor": actor_code, "effect": item_def.get("item_type", "used")}
        return _EffectResult(
            events=[self._event(state, "item_used", payload, actor=actor_code, location=self._actor_location(state, actor_code))],
            deltas=[SimulationDeltaDraft(f"inventory.{item_code}.used_by", "set", None, actor_code, "hidden")],
        )

    def _item_failure(self, state: WorkingState, event_type: str, item_code: Any, actor: Any, reason: str) -> "_EffectResult":
        if event_type == "item_take_failed":
            valid = {"already_taken", "actor_not_at_item", "item_unknown", "actor_not_alive"}
        else:
            valid = {"not_owner", "already_used", "item_unknown", "actor_not_alive"}
        if reason not in valid:
            raise TimeSimulationStateError(f"invalid frozen item failure reason {reason!r}")
        payload = {"item": item_code, "actor": actor, "reason": reason}
        return _EffectResult(
            applied=False,
            events=[self._event(state, event_type, payload, actor=actor if isinstance(actor, str) else None, location=self._actor_location(state, actor) if isinstance(actor, str) else None)],
            detail_code=reason,
        )

    def _player_complete(self, state: WorkingState, step: ScheduledStep, player_action: PlayerActionSpec) -> StepEffect:
        action_kind = step.payload.get("action_kind")
        if action_kind != player_action.kind:
            raise TimeSimulationStateError("player completion step does not match the player action")
        if action_kind == PlayerActionKind.IDLE:
            state.player_action_status = "completed"
            event = self._event(
                state,
                "player_action_completed",
                {"action_type": player_action.action_type, "action_kind": action_kind, "tick": step.tick},
                force_visible=True,
            )
            derived = self._completion_rule_events(state, "player", "idle", state.player_location_code, step, player_action)
            return StepEffect(status=StepStatus.APPLIED, events=(event,), derived_steps=tuple(derived))
        target = player_action.target_location_code
        if not state.player_alive:
            return StepEffect(status=StepStatus.BLOCKED, detail_code="player_not_alive")
        if not target or not state.route_is_open(state.player_location_code, target):
            return StepEffect(status=StepStatus.BLOCKED, detail_code="route_closed")
        source = state.player_location_code
        state.player_location_code = target
        state.player_arrival_task_code = None
        state.player_action_status = "completed"
        event = self._event(
            state,
            "player_move_completed",
            {"from": source, "to": target, "arrival_task": None, "tick": step.tick},
            location=target,
            force_visible=True,
        )
        derived = self._completion_rule_events(state, "player", "move", target, step, player_action)
        delta = SimulationDeltaDraft("player.location_id", "set", source, target, "player_visible")
        return StepEffect(status=StepStatus.APPLIED, events=(event,), deltas=(delta,), derived_steps=tuple(derived))

    # ------------------------------------------------------------------
    # Action-completion rules, event perspective, and state accessors
    # ------------------------------------------------------------------

    def _completion_rule_events(
        self,
        state: WorkingState,
        actor: str,
        action: str,
        location: Optional[str],
        source_step: ScheduledStep,
        player_action: PlayerActionSpec,
    ) -> List[ScheduledStep]:
        occurrence = f"{actor}:{action}@{source_step.tick}:{location or '-'}"
        derived = []
        for rule in self.data.rules:
            trigger = rule.trigger
            if trigger.kind != "on_action_completed" or trigger.action != action or trigger.actor != actor:
                continue
            if trigger.location is not None and trigger.location != location:
                continue
            derived.append(
                ScheduledStep(
                    step_key=f"rule:{rule.id}@{source_step.tick}",
                    tick=source_step.tick,
                    phase=trigger.phase,
                    actor_code="world",
                    kind=StepKind.CONTENT_RULE_FIRE,
                    payload={"rule": rule.id, "occurrence": occurrence},
                )
            )
        return derived

    def _event(
        self,
        state: WorkingState,
        event_type: str,
        payload: Mapping[str, Any],
        *,
        actor: Optional[str] = None,
        location: Optional[str] = None,
        force_visible: bool = False,
    ) -> SimulationEventDraft:
        body = copy.deepcopy(dict(payload))
        if event_type == "route_changed":
            location = body.get("from")
        elif event_type == "npc_travel_started":
            location = body.get("from")
        elif event_type == "npc_arrived":
            location = body.get("to")
        elif event_type in {"item_acquired", "item_take_failed", "item_used", "item_use_failed"} and actor:
            location = self._actor_location(state, actor)
        if actor is None:
            actor = body.get("npc_id") or body.get("actor")
        visible = force_visible or (location is not None and state.player_alive and state.player_location_code == location)
        if event_type == "world_interrupt":
            visible = True
        cognitions = self._cognition_drafts(state, event_type, body, actor, location)
        return SimulationEventDraft(
            event_type=event_type,
            visibility_scope="player_visible" if visible else "hidden",
            public_payload=body if visible else None,
            private_payload=None if visible else body,
            cognition=tuple(cognitions),
        )

    def _cognition_drafts(
        self,
        state: WorkingState,
        event_type: str,
        payload: Mapping[str, Any],
        actor: Optional[str],
        location: Optional[str],
    ) -> List[CognitionDraft]:
        result = []
        for rule in self.data.knowledge_rules:
            if event_type not in rule.get("source_event_types", ()):
                continue
            observers: List[str] = []
            scope = rule.get("observers")
            if scope == "actor" and actor in state.npc_alive and state.npc_is_alive(actor):
                observers = [actor]
            elif scope == "at_location" and location is not None:
                observers = [
                    code for code in sorted(state.npc_positions)
                    if state.npc_is_alive(code) and state.npc_positions.get(code) == location
                ]
            elif scope == "all_alive":
                observers = [code for code in sorted(state.npc_alive) if state.npc_is_alive(code)]
            values = {
                "actor": actor or "",
                "target": str(payload.get("target", payload.get("to", ""))),
                "item": str(payload.get("item", "")),
                "location": str(location or payload.get("location", "")),
            }
            template = str(rule.get("template", ""))
            try:
                content = template.format_map(values)
            except (KeyError, ValueError):
                content = template
            for observer in observers:
                result.append(
                    CognitionDraft(
                        subject_type="npc",
                        subject_ref=observer,
                        content=content,
                        visibility=str(rule.get("visibility", "npc_private")),
                        memory_kind=str(rule.get("memory_kind", "observation")),
                    )
                )
        return result

    def _actor_alive(self, state: WorkingState, actor: str) -> bool:
        if actor == "player":
            return bool(state.player_alive)
        return actor in state.npc_alive and bool(state.npc_alive[actor])

    def _actor_location(self, state: WorkingState, actor: str) -> Optional[str]:
        if actor == "player":
            return state.player_location_code or None
        return state.npc_positions.get(actor)


class _EffectResult:
    def __init__(
        self,
        *,
        applied: bool = True,
        events: Optional[List[SimulationEventDraft]] = None,
        deltas: Optional[List[SimulationDeltaDraft]] = None,
        derived_steps: Optional[List[ScheduledStep]] = None,
        interrupts_player: bool = False,
        detail_code: Optional[str] = None,
        detail_message: Optional[str] = None,
    ) -> None:
        self.applied = applied
        self.events = events or []
        self.deltas = deltas or []
        self.derived_steps = derived_steps or []
        self.interrupts_player = interrupts_player
        self.detail_code = detail_code
        self.detail_message = detail_message

    @classmethod
    def failure(cls, detail_code: str, event: Optional[SimulationEventDraft] = None) -> "_EffectResult":
        return cls(applied=False, events=[] if event is None else [event], detail_code=detail_code)

    def as_step_effect(self) -> StepEffect:
        return StepEffect(
            status=StepStatus.APPLIED if self.applied else StepStatus.BLOCKED,
            events=tuple(self.events),
            deltas=tuple(self.deltas),
            derived_steps=tuple(self.derived_steps),
            interrupts_player=self.interrupts_player,
            detail_code=self.detail_code,
            detail_message=self.detail_message,
        )


def _thaw(value: Any) -> Any:
    if isinstance(value, tuple) and len(value) == 2 and value[0] == "__content_v1_mapping__":
        return {key: _thaw(child) for key, child in value[1]}
    if isinstance(value, tuple):
        return [_thaw(child) for child in value]
    return value


def _assert_unique_instance(state: WorkingState, item_code: str, item: ItemInstanceState) -> None:
    matches = sum(1 for instance in state.item_instances.values() if instance.code == item_code)
    if type(item.quantity) is not int or item.quantity != 1 or item.code != item_code or matches != 1:
        raise TimeSimulationStateError(f"unique item invariant is broken for {item_code!r}")


def _parse_owner(owner: str) -> Tuple[str, str]:
    parts = _parse_owner_safe(owner)
    if parts is None:
        raise TimeSimulationStateError(f"invalid compiled item owner {owner!r}")
    return parts


def _parse_owner_safe(owner: Any) -> Optional[Tuple[str, str]]:
    if owner == "player":
        return "player", "player"
    if isinstance(owner, str) and ":" in owner:
        owner_type, owner_ref = owner.split(":", 1)
        if owner_type in {"location", "character"} and owner_ref:
            return owner_type, owner_ref
    return None


def _destination_actor(destination: Any, fallback: str) -> str:
    parts = _parse_owner_safe(destination)
    if parts is None:
        return fallback
    owner_type, owner_ref = parts
    return owner_ref if owner_type == "character" else "player" if owner_type == "player" else fallback


def _owner_text(owner_type: str, owner_ref: str) -> str:
    return "player" if owner_type == "player" else f"{owner_type}:{owner_ref}"


def _rule_consumed_key(rule: CompiledRule, occurrence: str) -> str:
    if rule.fire_mode == "once_per_instance":
        return f"content_rule:{rule.id}"
    if rule.fire_mode == "once_per_source_event":
        return f"content_rule:{rule.id}:{occurrence}"
    raise TimeSimulationStateError(f"unknown compiled fire mode {rule.fire_mode!r}")


def _plan_to_dict(plan: CurrentPlanState) -> dict[str, Any]:
    return {
        "goal_id": plan.goal_id,
        "source": plan.source,
        "generation": plan.generation,
        "recipe_step": plan.recipe_step,
        "action": plan.action,
        "target": plan.target,
        "start_tick": plan.start_tick,
        "expected_end_tick": plan.expected_end_tick,
        "status": plan.status,
        "failure_code": plan.failure_code,
    }


__all__ = ["CompiledContentRules", "ContentPlanReevaluationBudgetError"]
