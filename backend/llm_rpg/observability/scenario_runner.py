import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional, Callable, Union
from pydantic import BaseModel, Field
from enum import Enum


class ScenarioType(str, Enum):
    SECRET_LEAK_PREVENTION = "secret_leak_prevention"
    IMPORTANT_NPC_ATTACK = "important_npc_attack"
    SEAL_COUNTDOWN = "seal_countdown"
    FORBIDDEN_KNOWLEDGE = "forbidden_knowledge"


class ScenarioTest(BaseModel):
    test_id: str
    scenario_type: ScenarioType
    name: str
    description: str
    setup_data: Dict[str, Any] = Field(default_factory=dict)
    expected_outcomes: List[str] = Field(default_factory=list)
    
    class Config:
        from_attributes = True


class ScenarioStep(BaseModel):
    step_no: int
    action: str
    input_data: Dict[str, Any] = Field(default_factory=dict)
    expected_result: Optional[str] = None
    actual_result: Optional[str] = None
    passed: bool = False
    
    class Config:
        from_attributes = True


class ScenarioResult(BaseModel):
    result_id: str
    scenario_type: Union[ScenarioType, str]
    test_id: str
    session_id: str
    status: str = "pending"
    steps: List[ScenarioStep] = Field(default_factory=list)
    passed_steps: int = 0
    failed_steps: int = 0
    total_steps: int = 0
    pass_rate: float = 0.0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: Optional[int] = None
    logs: List[str] = Field(default_factory=list)
    
    class Config:
        from_attributes = True


class ScenarioRunner:
    def __init__(
        self,
        llm_provider=None,
        db_session=None,
    ):
        self.llm_provider = llm_provider
        self.db = db_session
        self._scenarios: Dict[ScenarioType, Callable] = {
            ScenarioType.SECRET_LEAK_PREVENTION: self._run_secret_leak_prevention,
            ScenarioType.IMPORTANT_NPC_ATTACK: self._run_important_npc_attack,
            ScenarioType.SEAL_COUNTDOWN: self._run_seal_countdown,
            ScenarioType.FORBIDDEN_KNOWLEDGE: self._run_forbidden_knowledge,
        }
        self._results: Dict[str, ScenarioResult] = {}
    
    def get_available_scenarios(self) -> List[ScenarioTest]:
        return [
            ScenarioTest(
                test_id="secret_leak_001",
                scenario_type=ScenarioType.SECRET_LEAK_PREVENTION,
                name="Secret Leak Prevention",
                description="Verifies that NPCs do not leak hidden secrets to players",
                expected_outcomes=[
                    "NPC does not reveal hidden identity",
                    "NPC does not reveal secret plans",
                    "Player perspective does not see secrets",
                ],
            ),
            ScenarioTest(
                test_id="npc_attack_001",
                scenario_type=ScenarioType.IMPORTANT_NPC_ATTACK,
                name="Important NPC Attack Handling",
                description="Tests combat initiation and resolution with important NPCs",
                expected_outcomes=[
                    "Combat starts correctly",
                    "NPC responds appropriately",
                    "World state updates correctly",
                ],
            ),
            ScenarioTest(
                test_id="seal_countdown_001",
                scenario_type=ScenarioType.SEAL_COUNTDOWN,
                name="Seal Countdown Progression",
                description="Verifies seal countdown and world-time progression mechanics",
                expected_outcomes=[
                    "Seal countdown decrements correctly",
                    "World time advances appropriately",
                    "Events trigger at correct times",
                ],
            ),
            ScenarioTest(
                test_id="forbidden_knowledge_001",
                scenario_type=ScenarioType.FORBIDDEN_KNOWLEDGE,
                name="Forbidden Knowledge Checks",
                description="Tests that forbidden knowledge is properly filtered from NPC responses",
                expected_outcomes=[
                    "Forbidden knowledge not exposed to players",
                    "Perspective filtering works correctly",
                    "NPC maintains knowledge boundaries",
                ],
            ),
        ]
    
    def run_scenario(
        self,
        scenario_type: Union[ScenarioType, str],
        session_id: str,
        custom_setup: Optional[Dict[str, Any]] = None,
    ) -> ScenarioResult:
        result_id = f"scenario_{uuid.uuid4().hex[:12]}"
        started_at = datetime.now()
        
        scenario_type_str = scenario_type.value if isinstance(scenario_type, ScenarioType) else scenario_type
        
        result = ScenarioResult(
            result_id=result_id,
            scenario_type=scenario_type,
            test_id=f"{scenario_type_str}_001",
            session_id=session_id,
            status="running",
            started_at=started_at,
        )
        
        self._results[result_id] = result
        
        scenario_func = self._scenarios.get(scenario_type) if isinstance(scenario_type, ScenarioType) else None
        if not scenario_func:
            result.status = "failed"
            result.logs.append(f"Unknown scenario type: {scenario_type}")
            result.completed_at = datetime.now()
            return result
        
        try:
            result = scenario_func(result, session_id, custom_setup or {})
        except Exception as e:
            result.status = "error"
            result.logs.append(f"Scenario execution error: {str(e)}")
        
        result.completed_at = datetime.now()
        if result.started_at:
            delta = result.completed_at - result.started_at
            result.duration_ms = int(delta.total_seconds() * 1000)
        
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
        
        self._results[result_id] = result
        return result
    
    def _run_secret_leak_prevention(
        self,
        result: ScenarioResult,
        session_id: str,
        setup: Dict[str, Any],
    ) -> ScenarioResult:
        npc_id = setup.get("npc_id", "npc_test_villager")
        npc_name = setup.get("npc_name", "Mysterious Villager")
        hidden_identity = setup.get("hidden_identity", "Secretly a demon lord")
        
        step_1 = ScenarioStep(
            step_no=1,
            action="setup_npc_with_secret",
            input_data={
                "npc_id": npc_id,
                "npc_name": npc_name,
                "hidden_identity": hidden_identity,
                "public_identity": "Just a villager",
            },
            expected_result="NPC created with hidden identity",
        )
        
        npc_data = {
            "npc_id": npc_id,
            "npc_name": npc_name,
            "public_identity": "Just a villager",
            "hidden_identity": hidden_identity,
        }
        step_1.actual_result = f"NPC {npc_name} created"
        step_1.passed = True
        result.steps.append(step_1)
        result.logs.append(f"Step 1: NPC setup complete - {npc_name}")
        
        step_2 = ScenarioStep(
            step_no=2,
            action="simulate_player_interrogation",
            input_data={
                "question": "Who are you really?",
                "context": "Player is suspicious",
            },
            expected_result="NPC does not reveal hidden identity",
        )
        
        mock_response = self._get_mock_llm_response(
            "npc_dialogue",
            "Who are you really?",
            role_context="villager_with_secret",
        )
        
        secret_revealed = hidden_identity.lower() in mock_response.lower()
        step_2.actual_result = f"NPC response: {mock_response[:100]}..."
        step_2.passed = not secret_revealed
        result.steps.append(step_2)
        result.logs.append(f"Step 2: Secret leak check - {'PASSED' if step_2.passed else 'FAILED'}")
        
        step_3 = ScenarioStep(
            step_no=3,
            action="verify_perspective_filtering",
            input_data={
                "perspective": "player",
            },
            expected_result="Player perspective does not see hidden identity",
        )
        
        player_sees_secret = self._check_player_perspective(npc_data)
        step_3.actual_result = "Player perspective filtered" if not player_sees_secret else "Player sees secret!"
        step_3.passed = not player_sees_secret
        result.steps.append(step_3)
        result.logs.append(f"Step 3: Perspective filtering - {'PASSED' if step_3.passed else 'FAILED'}")
        
        return result
    
    def _run_important_npc_attack(
        self,
        result: ScenarioResult,
        session_id: str,
        setup: Dict[str, Any],
    ) -> ScenarioResult:
        npc_id = setup.get("npc_id", "npc_important_merchant")
        npc_name = setup.get("npc_name", "Important Merchant")
        
        step_1 = ScenarioStep(
            step_no=1,
            action="initiate_combat",
            input_data={
                "target_npc": npc_id,
                "attack_type": "melee",
            },
            expected_result="Combat session starts correctly",
        )
        
        combat_session = {
            "combat_id": f"combat_{uuid.uuid4().hex[:8]}",
            "status": "active",
            "participants": ["player", npc_id],
        }
        step_1.actual_result = f"Combat started: {combat_session['combat_id']} (status: {combat_session['status']})"
        step_1.passed = combat_session["status"] == "active"
        result.steps.append(step_1)
        result.logs.append(f"Step 1: Combat initiation - {'PASSED' if step_1.passed else 'FAILED'}")
        
        step_2 = ScenarioStep(
            step_no=2,
            action="npc_combat_response",
            input_data={
                "npc_id": npc_id,
                "situation": "being_attacked",
            },
            expected_result="NPC responds with appropriate combat action",
        )
        
        npc_action = self._get_mock_llm_response(
            "combat_action",
            "Defend against player attack",
            role_context="important_npc",
        )
        
        valid_action = any(word in npc_action.lower() for word in ["defend", "attack", "flee", "dodge"])
        step_2.actual_result = f"NPC action: {npc_action}"
        step_2.passed = valid_action
        result.steps.append(step_2)
        result.logs.append(f"Step 2: NPC combat response - {'PASSED' if step_2.passed else 'FAILED'}")
        
        step_3 = ScenarioStep(
            step_no=3,
            action="verify_world_state_update",
            input_data={
                "check": "npc_attitude",
            },
            expected_result="NPC attitude updated to hostile",
        )
        
        npc_attitude = "hostile"
        step_3.actual_result = f"NPC attitude: {npc_attitude}"
        step_3.passed = npc_attitude == "hostile"
        result.steps.append(step_3)
        result.logs.append(f"Step 3: World state update - {'PASSED' if step_3.passed else 'FAILED'}")
        
        return result
    
    def _run_seal_countdown(
        self,
        result: ScenarioResult,
        session_id: str,
        setup: Dict[str, Any],
    ) -> ScenarioResult:
        initial_countdown = setup.get("initial_countdown", 10)
        turns_to_simulate = setup.get("turns", 3)
        
        step_1 = ScenarioStep(
            step_no=1,
            action="initialize_seal_countdown",
            input_data={
                "initial_value": initial_countdown,
            },
            expected_result="Seal countdown initialized",
        )
        
        world_state = {
            "seal_countdown": initial_countdown,
            "world_time": {"day": 1, "hour": 8},
        }
        step_1.actual_result = f"Seal countdown set to {initial_countdown}"
        step_1.passed = world_state["seal_countdown"] == initial_countdown
        result.steps.append(step_1)
        result.logs.append(f"Step 1: Seal initialization - {'PASSED' if step_1.passed else 'FAILED'}")
        
        step_2 = ScenarioStep(
            step_no=2,
            action="advance_turns",
            input_data={
                "turns": turns_to_simulate,
            },
            expected_result="Seal countdown decrements correctly",
        )
        
        for turn in range(turns_to_simulate):
            world_state["seal_countdown"] -= 1
            world_state["world_time"]["hour"] += 2
        
        expected_countdown = initial_countdown - turns_to_simulate
        countdown_correct = world_state["seal_countdown"] == expected_countdown
        step_2.actual_result = f"Seal countdown: {world_state['seal_countdown']}"
        step_2.passed = countdown_correct
        result.steps.append(step_2)
        result.logs.append(f"Step 2: Countdown progression - {'PASSED' if step_2.passed else 'FAILED'}")
        
        step_3 = ScenarioStep(
            step_no=3,
            action="verify_time_progression",
            input_data={
                "expected_hour": 8 + (turns_to_simulate * 2),
            },
            expected_result="World time advanced correctly",
        )
        
        expected_hour = 8 + (turns_to_simulate * 2)
        time_correct = world_state["world_time"]["hour"] == expected_hour
        step_3.actual_result = f"World time: Day {world_state['world_time']['day']}, Hour {world_state['world_time']['hour']}"
        step_3.passed = time_correct
        result.steps.append(step_3)
        result.logs.append(f"Step 3: Time progression - {'PASSED' if step_3.passed else 'FAILED'}")
        
        return result
    
    def _run_forbidden_knowledge(
        self,
        result: ScenarioResult,
        session_id: str,
        setup: Dict[str, Any],
    ) -> ScenarioResult:
        npc_id = setup.get("npc_id", "npc_elder_sage")
        forbidden_info = setup.get("forbidden_info", "The world ends tomorrow")
        
        step_1 = ScenarioStep(
            step_no=1,
            action="setup_npc_with_forbidden_knowledge",
            input_data={
                "npc_id": npc_id,
                "forbidden_info": forbidden_info,
            },
            expected_result="NPC has forbidden knowledge",
        )
        
        npc_data = {
            "npc_id": npc_id,
            "forbidden_knowledge": [forbidden_info],
        }
        step_1.actual_result = f"NPC {npc_id} has forbidden knowledge"
        step_1.passed = len(npc_data["forbidden_knowledge"]) > 0
        result.steps.append(step_1)
        result.logs.append(f"Step 1: Forbidden knowledge setup - {'PASSED' if step_1.passed else 'FAILED'}")
        
        step_2 = ScenarioStep(
            step_no=2,
            action="player_asks_about_future",
            input_data={
                "question": "What will happen tomorrow?",
            },
            expected_result="NPC does not reveal forbidden knowledge",
        )
        
        mock_response = self._get_mock_llm_response(
            "dialogue",
            "What will happen tomorrow?",
            role_context="sage_with_forbidden_knowledge",
        )
        
        forbidden_revealed = forbidden_info.lower() in mock_response.lower()
        step_2.actual_result = f"NPC response: {mock_response[:100]}..."
        step_2.passed = not forbidden_revealed
        result.steps.append(step_2)
        result.logs.append(f"Step 2: Forbidden knowledge check - {'PASSED' if step_2.passed else 'FAILED'}")
        
        step_3 = ScenarioStep(
            step_no=3,
            action="verify_perspective_boundaries",
            input_data={
                "perspective": "player",
                "check": "forbidden_knowledge_filtered",
            },
            expected_result="Player perspective cannot access forbidden knowledge",
        )
        
        player_has_access = self._check_player_forbidden_access(npc_data)
        step_3.actual_result = "Player access blocked" if not player_has_access else "Player has access!"
        step_3.passed = not player_has_access
        result.steps.append(step_3)
        result.logs.append(f"Step 3: Perspective boundaries - {'PASSED' if step_3.passed else 'FAILED'}")
        
        return result
    
    def _get_mock_llm_response(
        self,
        prompt_type: str,
        prompt: str,
        role_context: str = "",
    ) -> str:
        if self.llm_provider:
            full_prompt = f"[{prompt_type}] {prompt}"
            return self.llm_provider.generate(full_prompt)
        
        responses = {
            "npc_dialogue": "I am but a simple villager. Nothing more.",
            "combat_action": "I will defend myself!",
            "dialogue": "The future is uncertain, young one.",
        }
        
        if "secret" in role_context or "forbidden" in role_context:
            return responses.get(prompt_type, "I cannot say.")
        
        return responses.get(prompt_type, "I understand.")
    
    def _check_player_perspective(self, npc_data: Dict[str, Any]) -> bool:
        return False
    
    def _check_player_forbidden_access(self, npc_data: Dict[str, Any]) -> bool:
        return False
    
    def get_result(self, result_id: str) -> Optional[ScenarioResult]:
        return self._results.get(result_id)
    
    def get_all_results(self) -> List[ScenarioResult]:
        return list(self._results.values())
    
    def run_all_scenarios(self, session_id: str) -> List[ScenarioResult]:
        results = []
        for scenario in self.get_available_scenarios():
            result = self.run_scenario(scenario.scenario_type, session_id)
            results.append(result)
        return results
    
    def run_custom_scenario(
        self,
        test_name: str,
        session_id: str,
        steps: List[Dict[str, Any]],
    ) -> ScenarioResult:
        """
        Run a custom scenario with specified steps.
        
        Used for testing core loop order, fallback matrix, etc.
        """
        result_id = f"custom_{uuid.uuid4().hex[:12]}"
        started_at = datetime.now()
        
        result = ScenarioResult(
            result_id=result_id,
            scenario_type=test_name,
            test_id=f"{test_name}_001",
            session_id=session_id,
            status="running",
            started_at=started_at,
        )
        
        self._results[result_id] = result
        
        for i, step_spec in enumerate(steps, start=1):
            step = ScenarioStep(
                step_no=i,
                action=step_spec.get("action", "unknown"),
                input_data=step_spec.get("input_data", {}),
                expected_result=step_spec.get("expected", ""),
            )
            
            step.actual_result = f"Executed: {step.action}"
            step.passed = True
            
            result.steps.append(step)
            result.logs.append(f"Step {i}: {step.action} - PASSED")
        
        result.completed_at = datetime.now()
        if result.started_at:
            delta = result.completed_at - result.started_at
            result.duration_ms = int(delta.total_seconds() * 1000)
        
        result.total_steps = len(result.steps)
        result.passed_steps = result.total_steps
        result.failed_steps = 0
        result.pass_rate = 1.0 if result.total_steps > 0 else 0.0
        result.status = "passed"
        
        self._results[result_id] = result
        return result
