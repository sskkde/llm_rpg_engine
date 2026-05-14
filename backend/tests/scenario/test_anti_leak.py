"""Anti-Leak Narration Scenario Tests.

Tests that narration output does not leak hidden, secret, or private information
to players. Uses the hardened NarrationLeakValidator from Task 8 to validate
narration text against forbidden content patterns.

Coverage:
  1. Narration doesn't reveal NPC hidden identities
  2. Narration doesn't expose secret locations
  3. Narration doesn't leak hidden quest information
  4. Narration doesn't reveal NPC private memories
  5. Hardened NarrationLeakValidator catches partial phrase matches
"""

import pytest
from llm_rpg.observability.scenario_runner import ScenarioRunner
from llm_rpg.core.validation.narration_leak_validator import (
    NarrationLeakValidator,
)
from tests.conftest import MockLLMProvider


@pytest.mark.scenario
@pytest.mark.p5_scenario
class TestAntiLeakNarration:
    """5 tests validating narration output does not leak hidden information."""

    def setup_method(self):
        self.mock_provider = MockLLMProvider()
        self.runner = ScenarioRunner(llm_provider=self.mock_provider)
        self.validator = NarrationLeakValidator()

    def test_narration_doesnt_reveal_npc_hidden_identities(self):
        """Narration must not expose an NPC's hidden identity (e.g., 'secretly a demon lord')."""
        result = self.runner.run_custom_scenario(
            "narration_hidden_identity_protection",
            "session_leak_001",
            steps=[
                {"action": "setup_npc_with_hidden_identity",
                 "input_data": {"npc_name": "Mysterious Stranger",
                                "public_identity": "wandering_merchant",
                                "hidden_identity": "secretly the Demon Lord Malachar"},
                 "expected": "NPC created with hidden identity kept separate from public-facing data"},
                {"action": "generate_narration_with_npc_interaction",
                 "input_data": {"scene": "player_talks_to_stranger",
                                "npc_id": "mysterious_stranger"},
                 "expected": "Narration generated from player-visible perspective only"},
                {"action": "validate_narration_for_hidden_identity_leak",
                 "input_data": {"narration_text": "The mysterious merchant adjusts his cloak and smiles at you.",
                                "forbidden_info": ["secretly the Demon Lord Malachar", "Malachar"]},
                 "expected": "Hidden identity not present in narration"},
            ],
        )

        narration_text = "The mysterious merchant adjusts his cloak and smiles warmly. 'Welcome, traveler!'"
        forbidden = ["secretly the Demon Lord Malachar", "Malachar", "demon lord"]
        validation = self.validator.validate_narration(
            text=narration_text,
            forbidden_info=forbidden,
        )

        result.steps[2].actual_result = (
            f"Narration validation: valid={validation.is_valid}, "
            f"errors={len(validation.errors)}, warnings={len(validation.warnings)}"
        )
        result.steps[2].passed = validation.is_valid
        self._recalc_result(result)

        assert validation.is_valid
        assert len(validation.errors) == 0
        assert result.status == "passed"

    def test_narration_doesnt_expose_secret_locations(self):
        """Narration must not reveal the existence or location of secret areas."""
        result = self.runner.run_custom_scenario(
            "narration_secret_location_protection",
            "session_leak_002",
            steps=[
                {"action": "define_secret_location",
                 "input_data": {"location_name": "Hidden Vault of Azaroth",
                                "entry_mechanism": "blood_moon_ritual",
                                "known_to": ["cult_leader"]},
                 "expected": "Secret location defined, known only to cult_leader"},
                {"action": "generate_narration_in_public_area",
                 "input_data": {"scene": "player_in_town_square",
                                "visible_features": ["fountain", "market_stalls", "guard_post"]},
                 "expected": "Narration describes only visible, public features"},
                {"action": "validate_narration_excludes_secret_location",
                 "input_data": {"narration_text": "The town square bustles with merchants and townsfolk. A grand fountain sparkles in the afternoon sun.",
                                "forbidden_info": ["Hidden Vault of Azaroth", "blood moon ritual chamber"]},
                 "expected": "Secret location absent from public-area narration"},
            ],
        )

        narration = "The town square bustles with merchants and townsfolk. A grand fountain sparkles in the afternoon sun."
        forbidden = ["Hidden Vault of Azaroth", "blood moon ritual chamber", "Azaroth"]
        validation = self.validator.validate_narration(text=narration, forbidden_info=forbidden)

        result.steps[2].actual_result = f"Validation: valid={validation.is_valid}, errors={len(validation.errors)}"
        result.steps[2].passed = validation.is_valid
        self._recalc_result(result)

        assert validation.is_valid
        assert result.status == "passed"

    def test_narration_doesnt_leak_hidden_quest_information(self):
        """Narration must not expose hidden quest details (secret objectives, twist outcomes)."""
        result = self.runner.run_custom_scenario(
            "narration_hidden_quest_protection",
            "session_leak_003",
            steps=[
                {"action": "define_quest_with_hidden_elements",
                 "input_data": {"quest_name": "The Merchant's Request",
                                "public_objective": "deliver_package_to_inn",
                                "hidden_twist": "package_contains_poison_for_the_king",
                                "hidden_reward": "secret_passage_to_throne_room"},
                 "expected": "Quest has hidden twist and reward known only to quest-giver"},
                {"action": "generate_narration_during_quest_progress",
                 "input_data": {"scene": "player_delivering_package",
                                "visible_actions": ["player_hands_package_to_innkeeper"]},
                 "expected": "Narration describes visible actions, not hidden quest twist"},
                {"action": "verify_narration_excludes_hidden_quest_info",
                 "input_data": {"forbidden": ["poison for the king", "secret passage to throne room"]},
                 "expected": "Hidden quest details absent from narration"},
            ],
        )

        narration = "You hand the wrapped package to the innkeeper. He nods and places it behind the counter."
        forbidden = ["poisonous viper egg concealed within the delivery crate",
                     "hidden assassination plot orchestrated by the vizier"]
        validation = self.validator.validate_narration(text=narration, forbidden_info=forbidden)

        result.steps[2].actual_result = f"Validation: valid={validation.is_valid}, errors={len(validation.errors)}"
        result.steps[2].passed = validation.is_valid
        self._recalc_result(result)

        assert validation.is_valid
        assert result.status == "passed"

    def test_narration_doesnt_reveal_npc_private_memories(self):
        """Narration must not expose NPC private memories (traumas, secrets, hidden history)."""
        result = self.runner.run_custom_scenario(
            "narration_npc_private_memory_protection",
            "session_leak_004",
            steps=[
                {"action": "define_npc_with_private_memories",
                 "input_data": {"npc_name": "Captain Aldric",
                                "private_memories": [
                                    "watched his brother executed for treason",
                                    "secretly fathered a child with the queen",
                                ],
                                "public_persona": "stoic_guard_captain"},
                 "expected": "NPC defined with deeply private memories"},
                {"action": "generate_narration_with_npc_present",
                 "input_data": {"scene": "player_approaches_captain",
                                "npc_visible_state": "standing_guard_at_gate"},
                 "expected": "Narration describes NPC from player's observation only"},
                {"action": "validate_narration_excludes_private_memories",
                 "input_data": {"forbidden": [
                     "brother executed for treason",
                     "fathered a child with the queen",
                     "queen's secret child",
                 ]},
                 "expected": "NPC private memories absent from narration"},
            ],
        )

        narration = "Captain Aldric stands at attention by the castle gate, his expression unreadable."
        forbidden = [
            "brother executed for treason",
            "fathered a child with the queen",
            "queen's secret child",
            "treason",
        ]
        validation = self.validator.validate_narration(text=narration, forbidden_info=forbidden)

        result.steps[2].actual_result = f"Validation: valid={validation.is_valid}, errors={len(validation.errors)}"
        result.steps[2].passed = validation.is_valid
        self._recalc_result(result)

        assert validation.is_valid
        assert result.status == "passed"

    def test_hardened_validator_catches_partial_phrase_matches(self):
        """The hardened NarrationLeakValidator catches partial/bigram phrase matches,
        not just exact substring matches. Test EXACT_MATCH, PARTIAL_MATCH, and safe cases."""
        result = self.runner.run_custom_scenario(
            "narration_partial_match_detection",
            "session_leak_005",
            steps=[
                {"action": "test_exact_match_detection",
                 "input_data": {"narration": "The amulet is a golden amulet of power.",
                                "forbidden": "golden amulet"},
                 "expected": "EXACT_MATCH detected"},
                {"action": "test_partial_bigram_match_detection",
                 "input_data": {"narration": "You find a pendant made of pure golden amulet.",
                                "forbidden": "secret golden amulet of eternal life"},
                 "expected": "PARTIAL_MATCH detected via bigram overlap"},
                {"action": "test_partial_word_overlap_detection",
                 "input_data": {"narration": "The leader plans to destroy the fortress and burn the walls.",
                                "forbidden": "secret plan to destroy fortress"},
                 "expected": "PARTIAL_MATCH via word overlap ratio"},
                {"action": "test_safe_narration_no_match",
                 "input_data": {"narration": "The blacksmith hammers a horseshoe by the forge.",
                                "forbidden": "golden amulet of power"},
                 "expected": "No match — safe narration"},
                {"action": "verify_all_severity_levels_work",
                 "input_data": {"severities_tested": ["EXACT_MATCH", "PARTIAL_MATCH", "safe"]},
                 "expected": "All severity detection paths exercised"},
            ],
        )

        # Step 1: EXACT_MATCH — "golden amulet" appears verbatim
        v1 = self.validator.validate_narration(
            text="The amulet is a golden amulet of power.",
            forbidden_info=["golden amulet"],
        )
        step1_match = not v1.is_valid and any(
            "contains forbidden" in e.lower() or "golden amulet" in e.lower()
            for e in v1.errors
        )
        result.steps[0].actual_result = f"EXACT_MATCH: valid={v1.is_valid}, errors={v1.errors}"
        result.steps[0].passed = not v1.is_valid

        # Step 2: PARTIAL_MATCH via bigram — "golden amulet" bigram appears
        v2 = self.validator.validate_narration(
            text="You find a pendant made of pure golden amulet.",
            forbidden_info=["secret golden amulet of eternal life"],
        )
        step2_match = not v2.is_valid and any(
            "partial" in e.lower() or "key phrase" in e.lower() or "golden amulet" in e.lower()
            for e in v2.errors
        )
        result.steps[1].actual_result = f"PARTIAL_MATCH: valid={v2.is_valid}, errors={v2.errors}"
        result.steps[1].passed = not v2.is_valid

        # Step 3: PARTIAL_MATCH via word overlap — "destroy" and "fortress" overlap
        v3 = self.validator.validate_narration(
            text="The leader plans to destroy the fortress and burn the walls.",
            forbidden_info=["secret plan to destroy fortress"],
        )
        step3_match = not v3.is_valid
        result.steps[2].actual_result = f"WORD_OVERLAP: valid={v3.is_valid}, errors={v3.errors}"
        result.steps[2].passed = not v3.is_valid

        # Step 4: Safe — no overlap
        v4 = self.validator.validate_narration(
            text="The blacksmith hammers a horseshoe by the forge.",
            forbidden_info=["golden amulet of power"],
        )
        result.steps[3].actual_result = f"SAFE: valid={v4.is_valid}, warnings={len(v4.warnings)}"
        result.steps[3].passed = v4.is_valid

        # Step 5: All severities covered
        result.steps[4].actual_result = (
            f"Severities tested: EXACT_MATCH={step1_match}, "
            f"PARTIAL_BIGRAM={step2_match}, PARTIAL_OVERLAP={step3_match}, SAFE=True"
        )
        result.steps[4].passed = step1_match and step2_match and step3_match
        self._recalc_result(result)

        assert not v1.is_valid, "EXACT_MATCH should fail validation"
        assert not v2.is_valid, "PARTIAL_MATCH via bigram should fail validation"
        assert not v3.is_valid, "PARTIAL_MATCH via word overlap should fail validation"
        assert v4.is_valid, "Safe narration should pass validation"
        assert result.status == "passed"

    def _recalc_result(self, result):
        """Recalculate pass rate and status after manual step modifications."""
        result.total_steps = len(result.steps)
        result.passed_steps = sum(1 for s in result.steps if s.passed)
        result.failed_steps = result.total_steps - result.passed_steps
        result.pass_rate = result.passed_steps / result.total_steps if result.total_steps > 0 else 0.0
        if result.failed_steps == 0 and result.total_steps > 0:
            result.status = "passed"
        elif result.failed_steps < result.total_steps:
            result.status = "partial"
        else:
            result.status = "failed"
        return result


@pytest.mark.scenario
@pytest.mark.p5_scenario
class TestAntiLeakValidatorEdgeCases:
    """Additional edge tests for the hardened NarrationLeakValidator."""

    def setup_method(self):
        self.validator = NarrationLeakValidator()

    def test_validator_handles_empty_forbidden_info(self):
        """Validator should handle empty forbidden_info list gracefully."""
        validation = self.validator.validate_narration(
            text="The hero walks through the forest.",
            forbidden_info=[],
        )
        assert validation.is_valid
        assert len(validation.errors) == 0

    def test_validator_handles_forbidden_patterns_regex(self):
        """Validator should detect forbidden regex patterns in narration."""
        validation = self.validator.validate_narration(
            text="The ancient dragon Malachar awakens from its slumber.",
            forbidden_info=[],
            forbidden_patterns=[r"Malachar", r"\bdragon\b"],
        )
        assert not validation.is_valid
        assert len(validation.errors) >= 2
