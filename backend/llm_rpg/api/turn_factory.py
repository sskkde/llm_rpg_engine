"""
Factory module for constructing TurnOrchestrator with consistent dependencies.

This module provides a centralized factory function for creating TurnOrchestrator
instances with all required engines and services. It ensures:
- Single shared ProposalPipeline instance when LLMService is provided
- SceneEngine is always constructed and passed to TurnOrchestrator
- Consistent dependency injection across all engines
"""

from typing import Optional

from llm_rpg.core.event_log import EventLog
from llm_rpg.core.canonical_state import CanonicalStateManager
from llm_rpg.core.action_scheduler import ActionScheduler
from llm_rpg.core.validator import Validator
from llm_rpg.core.perspective import PerspectiveService
from llm_rpg.core.retrieval import RetrievalSystem
from llm_rpg.core.context_builder import ContextBuilder
from llm_rpg.core.npc_memory import NPCMemoryManager
from llm_rpg.core.lore_store import LoreStore
from llm_rpg.core.summary import SummaryManager
from llm_rpg.core.memory_writer import MemoryWriter
from llm_rpg.core.turn_orchestrator import TurnOrchestrator
from llm_rpg.engines.world_engine import WorldEngine
from llm_rpg.engines.npc_engine import NPCEngine
from llm_rpg.engines.narration_engine import NarrationEngine
from llm_rpg.engines.scene_engine import SceneEngine
from llm_rpg.llm.service import LLMService
from llm_rpg.llm.proposal_pipeline import ProposalPipeline, create_proposal_pipeline


def build_turn_orchestrator(llm_service: Optional[LLMService] = None) -> TurnOrchestrator:
    """
    Construct a TurnOrchestrator with all dependencies.
    
    When llm_service is provided:
    - Creates a single ProposalPipeline instance
    - Injects the pipeline into TurnOrchestrator and all engines (WorldEngine, NPCEngine, SceneEngine, NarrationEngine)
    
    When llm_service is None:
    - All engines are constructed with proposal_pipeline=None
    - Engines will use deterministic fallback behavior
    
    Args:
        llm_service: Optional LLMService instance. If provided, a ProposalPipeline
                    will be created and shared across all engines.
    
    Returns:
        TurnOrchestrator: Fully configured orchestrator with all dependencies.
    """
    # Create shared dependencies
    event_log = EventLog()
    state_manager = CanonicalStateManager()
    action_scheduler = ActionScheduler()
    validator = Validator()
    perspective_service = PerspectiveService()
    retrieval_system = RetrievalSystem()
    context_builder = ContextBuilder(retrieval_system, perspective_service)
    npc_memory = NPCMemoryManager()
    lore_store = LoreStore()
    summary_manager = SummaryManager()
    memory_writer = MemoryWriter(event_log, npc_memory, summary_manager)
    
    # Create ProposalPipeline if LLMService is provided
    proposal_pipeline: Optional[ProposalPipeline] = None
    if llm_service is not None:
        proposal_pipeline = create_proposal_pipeline(llm_service=llm_service)
    
    # Create engines with pipeline injection
    world_engine = WorldEngine(
        state_manager=state_manager,
        event_log=event_log,
        proposal_pipeline=proposal_pipeline,
    )
    
    npc_engine = NPCEngine(
        state_manager=state_manager,
        memory_manager=npc_memory,
        perspective_service=perspective_service,
        context_builder=context_builder,
        proposal_pipeline=proposal_pipeline,
    )
    
    narration_engine = NarrationEngine(
        state_manager=state_manager,
        perspective_service=perspective_service,
        context_builder=context_builder,
        validator=validator,
        proposal_pipeline=proposal_pipeline,
    )
    
    # Always create SceneEngine
    scene_engine = SceneEngine(proposal_pipeline=proposal_pipeline)
    
    # Create and return TurnOrchestrator
    return TurnOrchestrator(
        state_manager=state_manager,
        event_log=event_log,
        action_scheduler=action_scheduler,
        validator=validator,
        perspective_service=perspective_service,
        context_builder=context_builder,
        world_engine=world_engine,
        npc_engine=npc_engine,
        narration_engine=narration_engine,
        scene_engine=scene_engine,
        proposal_pipeline=proposal_pipeline,
        memory_writer=memory_writer,
    )
