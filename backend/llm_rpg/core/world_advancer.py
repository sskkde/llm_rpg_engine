"""Pure in-memory advancement of the phase-3 trial world."""

from __future__ import annotations

from typing import Any, Container, List, Optional, Protocol, Sequence, Set

from .time_simulation import (
    ACTION_INTERRUPTED,
    MAX_STEPS_PER_ADVANCE,
    PROFILE_ID,
    AdvanceResult,
    CognitionSpec,
    PlayerActionKind,
    PlayerActionResult,
    PlayerActionSpec,
    PlayerActionStatus,
    ScheduledStep,
    SimulationDelta,
    SimulationEvent,
    StepOutcome,
    StepStatus,
    TimeSimulationBudgetError,
    TimeSimulationStateError,
    WorkingState,
)


class WorldRules(Protocol):
    """Minimal duck-typed rule contract consumed by the pure advancer."""

    def player_completion_step(self, player_action: PlayerActionSpec) -> Optional[ScheduledStep]: ...

    def apply_step(
        self, *, state: WorkingState, step: ScheduledStep, player_action: PlayerActionSpec
    ) -> Any: ...


class WorldAdvancer:
    """Advance one action against a single evolving copy of world state."""

    def __init__(
        self, rules: WorldRules, *, max_steps: int = MAX_STEPS_PER_ADVANCE
    ) -> None:
        self.rules = rules
        self.max_steps = max_steps

    def advance(
        self,
        *,
        state: WorkingState,
        player_action: PlayerActionSpec,
        pending_steps: Sequence[ScheduledStep] = (),
        consumed_step_keys: Container[str] = frozenset(),
        start_event_seq: int = 0,
    ) -> AdvanceResult:
        """Process the action interval and return its immutable-input result.

        ``start_event_seq`` is the session's monotonic event cursor. Event
        sequence numbers continue from it, so an engine fact's ``sequence`` is
        stable and ordered across turns, not merely within one advance.
        """
        start_tick = player_action.start_tick
        target_tick = player_action.end_tick
        if state.logical_tick != start_tick:
            raise TimeSimulationStateError(
                "working-state logical_tick does not match player action start_tick"
            )
        if isinstance(start_event_seq, bool) or not isinstance(start_event_seq, int):
            raise TimeSimulationStateError("start_event_seq must be an integer")
        if start_event_seq < 0:
            raise TimeSimulationStateError("start_event_seq must not be negative")

        continuous = player_action.kind in (PlayerActionKind.IDLE, PlayerActionKind.MOVE)
        if continuous and player_action.duration_minutes == 0:
            raise TimeSimulationStateError("continuous player action must have positive duration")

        work = state.copy()
        completion_step: Optional[ScheduledStep] = None
        if continuous and player_action.refused is not True:
            completion_step = self.rules.player_completion_step(player_action)
            if completion_step is None:
                raise TimeSimulationStateError(
                    "continuous player action has no completion step"
                )

        # `known_keys` covers consumed, queued, and deferred steps so a duplicate
        # derived step cannot cause a second effect or duplicate pending row.
        known_keys: Set[str] = set(consumed_step_keys)
        queue: List[ScheduledStep] = []
        future: List[ScheduledStep] = []

        def enqueue(step: ScheduledStep) -> None:
            if step.step_key in known_keys:
                return
            known_keys.add(step.step_key)
            if step.tick > target_tick:
                future.append(step)
            else:
                queue.append(step)

        for step in sorted(pending_steps, key=lambda item: item.order_key):
            if step.step_key in consumed_step_keys:
                # A consumed step is terminal: it is never re-run, and its tick is
                # legitimately in the past.
                continue
            if step.tick <= start_tick:
                raise TimeSimulationStateError(
                    f"pending step {step.step_key!r} is not after start_tick"
                )
            enqueue(step)

        if completion_step is not None:
            enqueue(completion_step)

        events: List[SimulationEvent] = []
        deltas: List[SimulationDelta] = []
        cognition: List[CognitionSpec] = []
        consumed_steps: List[StepOutcome] = []
        consumed_step_specs: List[ScheduledStep] = []
        event_seq = start_event_seq
        delta_seq = 0
        cognition_seq = 0
        steps_processed = 0
        completion_outcome: Optional[StepOutcome] = None
        interrupted = False
        interruption_tick: Optional[int] = None
        interruption_location: Optional[str] = None

        while queue:
            queue.sort(key=lambda item: item.order_key)
            step = queue[0]
            if interrupted and interruption_tick is not None and step.tick > interruption_tick:
                break
            queue.pop(0)

            effect = self.rules.apply_step(
                state=work,
                step=step,
                player_action=player_action,
            )
            outcome = StepOutcome(
                step_key=step.step_key,
                tick=step.tick,
                phase=int(step.phase),
                actor_code=step.actor_code,
                kind=step.kind,
                status=effect.status,
                detail_code=effect.detail_code,
                detail_message=effect.detail_message,
            )
            consumed_steps.append(outcome)
            consumed_step_specs.append(step)
            steps_processed += 1
            if steps_processed > self.max_steps:
                raise TimeSimulationBudgetError(
                    f"advance processed more than {self.max_steps} steps"
                )
            if completion_step is not None and step.step_key == completion_step.step_key:
                completion_outcome = outcome

            for event_draft in effect.events:
                current_event_seq = event_seq
                events.append(
                    SimulationEvent(
                        seq=current_event_seq,
                        tick=step.tick,
                        phase=int(step.phase),
                        actor_code=step.actor_code,
                        step_code=step.step_key,
                        event_type=event_draft.event_type,
                        visibility_scope=event_draft.visibility_scope,
                        target_ids=tuple(event_draft.target_ids),
                        public_payload=event_draft.public_payload,
                        private_payload=event_draft.private_payload,
                        result_json=event_draft.result_json,
                    )
                )
                event_seq += 1
                for cognition_draft in event_draft.cognition:
                    cognition.append(
                        CognitionSpec(
                            seq=cognition_seq,
                            subject_type=cognition_draft.subject_type,
                            subject_ref=cognition_draft.subject_ref,
                            tick=step.tick,
                            content=cognition_draft.content,
                            visibility=cognition_draft.visibility,
                            memory_kind=cognition_draft.memory_kind,
                            source_step_code=step.step_key,
                            event_seq=current_event_seq,
                        )
                    )
                    cognition_seq += 1

            for delta_draft in effect.deltas:
                deltas.append(
                    SimulationDelta(
                        seq=delta_seq,
                        tick=step.tick,
                        step_code=step.step_key,
                        path=delta_draft.path,
                        operation=delta_draft.operation,
                        old_value=delta_draft.old_value,
                        new_value=delta_draft.new_value,
                        visibility_scope=delta_draft.visibility_scope,
                    )
                )
                delta_seq += 1

            for derived in effect.derived_steps:
                if derived.tick < step.tick:
                    raise TimeSimulationStateError(
                        f"derived step {derived.step_key!r} precedes its source step"
                    )
                if derived.tick == step.tick and int(derived.phase) < int(step.phase):
                    raise TimeSimulationStateError(
                        f"derived step {derived.step_key!r} reverses phase order"
                    )
                if derived.tick <= start_tick:
                    raise TimeSimulationStateError(
                        f"derived step {derived.step_key!r} is not after start_tick"
                    )
                enqueue(derived)

            if (
                effect.interrupts_player is True
                and continuous
                and completion_step is not None
                and any(item.step_key == completion_step.step_key for item in queue)
            ):
                queue = [
                    item for item in queue if item.step_key != completion_step.step_key
                ]
                cancelled = StepOutcome(
                    step_key=completion_step.step_key,
                    tick=completion_step.tick,
                    phase=int(completion_step.phase),
                    actor_code=completion_step.actor_code,
                    kind=completion_step.kind,
                    status=StepStatus.CANCELLED,
                    detail_code=ACTION_INTERRUPTED,
                )
                consumed_steps.append(cancelled)
                consumed_step_specs.append(completion_step)
                steps_processed += 1
                if steps_processed > self.max_steps:
                    raise TimeSimulationBudgetError(
                        f"advance processed more than {self.max_steps} steps"
                    )
                completion_outcome = cancelled
                interrupted = True
                interruption_tick = step.tick
                interruption_location = work.player_location_code

        actual_end_tick = interruption_tick if interrupted else target_tick
        if actual_end_tick is None:  # defensive; interrupted always sets its tick
            raise TimeSimulationStateError("interrupted advance has no interruption tick")

        refused = player_action.refused is True
        if refused:
            player_status = PlayerActionStatus.REFUSED
            detail_code = player_action.detail_code
            result_location = work.player_location_code
            arrival_task_code = None
        elif interrupted:
            player_status = PlayerActionStatus.INTERRUPTED
            detail_code = ACTION_INTERRUPTED
            result_location = interruption_location or work.player_location_code
            arrival_task_code = None
        elif player_action.kind == PlayerActionKind.INSTANT:
            player_status = PlayerActionStatus.COMPLETED
            detail_code = None
            result_location = work.player_location_code
            arrival_task_code = None
        elif completion_outcome is None:
            raise TimeSimulationStateError(
                "continuous player action completed without processing its completion step"
            )
        elif completion_outcome.status == StepStatus.APPLIED:
            player_status = PlayerActionStatus.COMPLETED
            detail_code = None
            result_location = work.player_location_code
            arrival_task_code = work.player_arrival_task_code
        elif completion_outcome.status == StepStatus.BLOCKED:
            player_status = PlayerActionStatus.REFUSED
            detail_code = completion_outcome.detail_code
            result_location = work.player_location_code
            arrival_task_code = None
        else:
            raise TimeSimulationStateError(
                "player completion step has an unsupported terminal status"
            )

        work.logical_tick = actual_end_tick
        work.player_action_status = player_status
        player_result = PlayerActionResult(
            status=player_status,
            action_type=player_action.action_type,
            location_code=result_location,
            elapsed_minutes=actual_end_tick - start_tick,
            detail_code=detail_code,
            arrival_task_code=arrival_task_code,
        )

        pending_by_key = {}
        for step in future + queue:
            if step.tick > actual_end_tick and step.step_key not in pending_by_key:
                pending_by_key[step.step_key] = step
        result_pending = sorted(pending_by_key.values(), key=lambda item: item.order_key)

        # Legacy rule objects need not expose profile_id; keep their phase3 identity.
        profile_id = getattr(self.rules, "profile_id", PROFILE_ID) or PROFILE_ID
        return AdvanceResult(
            profile_id=profile_id,
            start_tick=start_tick,
            target_tick=target_tick,
            actual_end_tick=actual_end_tick,
            interrupted=interrupted,
            player_result=player_result,
            final_state=work,
            events=events,
            deltas=deltas,
            cognition=cognition,
            consumed_steps=consumed_steps,
            consumed_step_specs=consumed_step_specs,
            pending_steps=result_pending,
            next_event_seq=event_seq,
            steps_processed=steps_processed,
        )
