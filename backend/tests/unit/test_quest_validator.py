"""Unit tests for QuestValidator."""

from llm_rpg.core.validation.quest_validator import QuestValidator
from llm_rpg.models.common import ProposedAction
from llm_rpg.models.states import QuestState


def make_quest_state(
    quest_id: str = "quest_main",
    name: str = "Main Quest",
    status: str = "active",
    stage: str = "stage_1",
    known_objectives: list[str] | None = None,
    hidden_objectives: list[str] | None = None,
    next_possible_stages: list[str] | None = None,
) -> QuestState:
    return QuestState(
        entity_id=quest_id,
        quest_id=quest_id,
        name=name,
        status=status,
        stage=stage,
        known_objectives=known_objectives or [],
        hidden_objectives=hidden_objectives or [],
        next_possible_stages=next_possible_stages or [],
    )


def make_action(
    action_type: str = "quest_progress",
    summary: str = "Progress the quest",
    intention: str = "",
    target_ids: list[str] | None = None,
    state_delta_candidates: list[dict] | None = None,
) -> ProposedAction:
    return ProposedAction(
        action_id="action_1",
        actor_id="player",
        action_type=action_type,
        target_ids=target_ids or ["quest_main"],
        summary=summary,
        intention=intention,
        state_delta_candidates=state_delta_candidates or [],
    )


class TestValidQuestStageProgression:
    """Test 1: Valid quest stage progression (current stage allows next)."""

    def test_valid_transition_to_next_stage(self):
        validator = QuestValidator()
        quest_state = make_quest_state(
            stage="stage_1",
            next_possible_stages=["stage_2", "stage_3"],
        )
        action = make_action(
            state_delta_candidates=[{"path": "quests.quest_main.stage", "new_value": "stage_2"}],
        )

        result = validator.validate_quest_progress(action, quest_state)

        assert result.is_valid is True

    def test_valid_transition_with_all_objectives_met(self):
        validator = QuestValidator()
        quest_state = make_quest_state(
            stage="stage_1",
            next_possible_stages=["stage_2"],
            known_objectives=["obj_talk_to_npc", "obj_find_item"],
        )
        quest_template = {
            "stage_objectives": {
                "stage_1": ["obj_talk_to_npc", "obj_find_item"],
            },
        }
        action = make_action(
            state_delta_candidates=[{"path": "quests.quest_main.stage", "new_value": "stage_2"}],
        )

        result = validator.validate_quest_progress(action, quest_state, quest_template)

        assert result.is_valid is True


class TestInvalidStageJump:
    """Test 2: Invalid stage jump (skipping required stages)."""

    def test_target_stage_not_in_next_possible_stages(self):
        validator = QuestValidator()
        quest_state = make_quest_state(
            stage="stage_1",
            next_possible_stages=["stage_2"],
        )
        action = make_action(
            state_delta_candidates=[{"path": "quests.quest_main.stage", "new_value": "stage_5"}],
        )

        result = validator.validate_quest_progress(action, quest_state)

        assert result.is_valid is False
        assert any("stage_transition_check" in c.check_name and not c.passed for c in result.checks)

    def test_no_next_possible_stages_at_all(self):
        validator = QuestValidator()
        quest_state = make_quest_state(
            stage="stage_final",
            next_possible_stages=[],
        )
        action = make_action(
            state_delta_candidates=[{"path": "quests.quest_main.stage", "new_value": "stage_beyond"}],
        )

        result = validator.validate_quest_progress(action, quest_state)

        assert result.is_valid is False
        assert any("No allowed next stages" in e for e in result.errors)


class TestPrerequisiteQuestNotCompleted:
    """Test 3: Prerequisite quest not completed → fail."""

    def test_prerequisite_not_completed_rejects_start(self):
        validator = QuestValidator()
        quest_state = make_quest_state(quest_id="quest_advanced", status="not_started")
        quest_template = {"prerequisite_quest_ids": ["quest_basic"]}
        all_quest_states = {
            "quest_basic": make_quest_state(quest_id="quest_basic", status="active"),
        }

        result = validator.validate_quest_start(
            action=make_action(action_type="quest_start"),
            quest_state=quest_state,
            quest_template=quest_template,
            all_quest_states=all_quest_states,
        )

        assert result.is_valid is False
        assert any("prerequisite" in e.lower() for e in result.errors)

    def test_prerequisite_completed_allows_start(self):
        validator = QuestValidator()
        quest_state = make_quest_state(quest_id="quest_advanced", status="not_started")
        quest_template = {"prerequisite_quest_ids": ["quest_basic"]}
        all_quest_states = {
            "quest_basic": make_quest_state(quest_id="quest_basic", status="completed"),
        }

        result = validator.validate_quest_start(
            action=make_action(action_type="quest_start"),
            quest_state=quest_state,
            quest_template=quest_template,
            all_quest_states=all_quest_states,
        )

        assert result.is_valid is True

    def test_multiple_prerequisites_one_incomplete(self):
        validator = QuestValidator()
        quest_state = make_quest_state(quest_id="quest_final", status="not_started")
        quest_template = {"prerequisite_quest_ids": ["quest_a", "quest_b"]}
        all_quest_states = {
            "quest_a": make_quest_state(quest_id="quest_a", status="completed"),
            "quest_b": make_quest_state(quest_id="quest_b", status="active"),
        }

        result = validator.validate_quest_start(
            action=make_action(action_type="quest_start"),
            quest_state=quest_state,
            quest_template=quest_template,
            all_quest_states=all_quest_states,
        )

        assert result.is_valid is False
        assert any("quest_b" in e for e in result.errors)


class TestObjectivesNotMet:
    """Test 4: Objectives not met → fail."""

    def test_incomplete_objectives_block_progression(self):
        validator = QuestValidator()
        quest_state = make_quest_state(
            stage="stage_1",
            next_possible_stages=["stage_2"],
            known_objectives=["obj_find_item"],
        )
        quest_template = {
            "stage_objectives": {
                "stage_1": ["obj_find_item", "obj_talk_to_npc"],
            },
        }
        action = make_action(
            state_delta_candidates=[{"path": "quests.quest_main.stage", "new_value": "stage_2"}],
        )

        result = validator.validate_quest_progress(action, quest_state, quest_template)

        assert result.is_valid is False
        assert any("objective_completion_check" in c.check_name and not c.passed for c in result.checks)
        assert any("obj_talk_to_npc" in e for e in result.errors)

    def test_no_template_skips_objective_check(self):
        validator = QuestValidator()
        quest_state = make_quest_state(
            stage="stage_1",
            next_possible_stages=["stage_2"],
        )
        action = make_action(
            state_delta_candidates=[{"path": "quests.quest_main.stage", "new_value": "stage_2"}],
        )

        result = validator.validate_quest_progress(action, quest_state, quest_template=None)

        assert result.is_valid is True


class TestHiddenObjectiveReferencedByPlayer:
    """Test 5: Hidden objective referenced by player → fail."""

    def test_hidden_objective_in_summary_rejected(self):
        validator = QuestValidator()
        quest_state = make_quest_state(
            stage="stage_1",
            next_possible_stages=["stage_2"],
            hidden_objectives=["secret_ritual_location"],
        )
        action = make_action(
            summary="I want to go to the secret_ritual_location",
            state_delta_candidates=[{"path": "quests.quest_main.stage", "new_value": "stage_2"}],
        )

        result = validator.validate_quest_progress(action, quest_state)

        assert result.is_valid is False
        assert any("hidden_objective_check" in c.check_name and not c.passed for c in result.checks)

    def test_hidden_objective_in_intention_rejected(self):
        validator = QuestValidator()
        quest_state = make_quest_state(
            stage="stage_1",
            next_possible_stages=["stage_2"],
            hidden_objectives=["hidden_boss_weakness"],
        )
        action = make_action(
            summary="Attack the boss",
            intention="Exploit the hidden_boss_weakness",
            state_delta_candidates=[{"path": "quests.quest_main.stage", "new_value": "stage_2"}],
        )

        result = validator.validate_quest_progress(action, quest_state)

        assert result.is_valid is False
        assert any("hidden_boss_weakness" in e for e in result.errors)

    def test_no_hidden_objectives_passes(self):
        validator = QuestValidator()
        quest_state = make_quest_state(
            stage="stage_1",
            next_possible_stages=["stage_2"],
            hidden_objectives=[],
        )
        action = make_action(
            state_delta_candidates=[{"path": "quests.quest_main.stage", "new_value": "stage_2"}],
        )

        result = validator.validate_quest_progress(action, quest_state)

        assert result.is_valid is True


class TestQuestAlreadyCompleted:
    """Test 6: Quest already completed → fail."""

    def test_completed_quest_cannot_start(self):
        validator = QuestValidator()
        quest_state = make_quest_state(status="completed")

        result = validator.validate_quest_start(
            action=make_action(action_type="quest_start"),
            quest_state=quest_state,
        )

        assert result.is_valid is False
        assert any("already completed" in e for e in result.errors)

    def test_completed_quest_cannot_progress(self):
        validator = QuestValidator()
        quest_state = make_quest_state(status="completed")

        result = validator.validate_quest_progress(
            action=make_action(),
            quest_state=quest_state,
        )

        assert result.is_valid is False
        assert any("already completed" in e for e in result.errors)

    def test_failed_quest_cannot_start(self):
        validator = QuestValidator()
        quest_state = make_quest_state(status="failed")

        result = validator.validate_quest_start(
            action=make_action(action_type="quest_start"),
            quest_state=quest_state,
        )

        assert result.is_valid is False
        assert any("failed" in e for e in result.errors)

    def test_failed_quest_cannot_progress(self):
        validator = QuestValidator()
        quest_state = make_quest_state(status="failed")

        result = validator.validate_quest_progress(
            action=make_action(),
            quest_state=quest_state,
        )

        assert result.is_valid is False
        assert any("failed" in e for e in result.errors)

    def test_active_quest_can_progress(self):
        validator = QuestValidator()
        quest_state = make_quest_state(
            status="active",
            stage="stage_1",
            next_possible_stages=["stage_2"],
        )
        action = make_action(
            state_delta_candidates=[{"path": "quests.quest_main.stage", "new_value": "stage_2"}],
        )

        result = validator.validate_quest_progress(action, quest_state)

        assert result.is_valid is True


class TestStageObjectivesTemplateFormats:
    """Test different quest template formats for stage objectives."""

    def test_stages_as_list_of_dicts(self):
        validator = QuestValidator()
        quest_state = make_quest_state(
            stage="stage_1",
            next_possible_stages=["stage_2"],
            known_objectives=["obj_1", "obj_2"],
        )
        quest_template = {
            "stages": [
                {"id": "stage_1", "objectives": ["obj_1", "obj_2"]},
                {"id": "stage_2", "objectives": ["obj_3"]},
            ],
        }
        action = make_action(
            state_delta_candidates=[{"path": "quests.quest_main.stage", "new_value": "stage_2"}],
        )

        result = validator.validate_quest_progress(action, quest_state, quest_template)

        assert result.is_valid is True

    def test_stages_as_dict_of_dicts(self):
        validator = QuestValidator()
        quest_state = make_quest_state(
            stage="stage_1",
            next_possible_stages=["stage_2"],
            known_objectives=["obj_1"],
        )
        quest_template = {
            "stages": {
                "stage_1": {"objectives": ["obj_1"]},
                "stage_2": {"objectives": ["obj_2"]},
            },
        }
        action = make_action(
            state_delta_candidates=[{"path": "quests.quest_main.stage", "new_value": "stage_2"}],
        )

        result = validator.validate_quest_progress(action, quest_state, quest_template)

        assert result.is_valid is True


class TestTargetStageExtraction:
    """Test target stage extraction from different action formats."""

    def test_extract_from_state_delta_path(self):
        validator = QuestValidator()
        quest_state = make_quest_state(
            stage="stage_1",
            next_possible_stages=["stage_2"],
        )
        action = make_action(
            state_delta_candidates=[{"path": "quests.quest_main.stage", "new_value": "stage_2"}],
        )

        result = validator.validate_quest_progress(action, quest_state)

        assert result.is_valid is True

    def test_extract_from_target_ids_prefix(self):
        validator = QuestValidator()
        quest_state = make_quest_state(
            stage="stage_1",
            next_possible_stages=["stage_2"],
        )
        action = make_action(
            target_ids=["stage_stage_2"],
            state_delta_candidates=[],
        )

        result = validator.validate_quest_progress(action, quest_state)

        assert result.is_valid is True

    def test_no_target_stage_skips_transition_check(self):
        validator = QuestValidator()
        quest_state = make_quest_state(
            stage="stage_1",
            next_possible_stages=["stage_2"],
        )
        action = make_action(state_delta_candidates=[])

        result = validator.validate_quest_progress(action, quest_state)

        assert result.is_valid is True
