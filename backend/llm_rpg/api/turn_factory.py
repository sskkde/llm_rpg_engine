"""
Factory module for constructing TurnOrchestrator with consistent dependencies.

This module provides a centralized factory function for creating TurnOrchestrator
instances with all required engines and services. It ensures:
- Single shared ProposalPipeline instance when LLMService is provided
- SceneEngine is always constructed and passed to TurnOrchestrator
- Consistent dependency injection across all engines

Two factory functions are provided:
- build_db_turn_orchestrator: Production use with DB session and repositories
- build_memory_turn_orchestrator_for_tests: Testing use with in-memory dependencies
"""

from typing import Optional, TYPE_CHECKING

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

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from llm_rpg.storage.repositories import (
        WorldRepository,
        ChapterRepository,
        LocationRepository,
        NPCTemplateRepository,
        ItemTemplateRepository,
        QuestTemplateRepository,
        EventTemplateRepository,
        PromptTemplateRepository,
        SessionRepository,
        SessionStateRepository,
        EventLogRepository,
        NPCMemoryScopeRepository,
        NPCBeliefRepository,
        NPCPrivateMemoryRepository,
        NPCSecretRepository,
        NPCRelationshipMemoryRepository,
    )


def build_db_turn_orchestrator(
    db: "Session",
    llm_service: LLMService,
    repositories: dict,
) -> TurnOrchestrator:
    """
    Construct a TurnOrchestrator for production use with DB-backed dependencies.
    
    This function creates a TurnOrchestrator that uses database session and
    repositories for persistent state management.
    
    Args:
        db: SQLAlchemy database session
        llm_service: LLMService instance for LLM calls
        repositories: Dictionary of repository instances for DB access
            Expected keys: 'world', 'chapter', 'location', 'npc_template',
                          'session', 'session_state', 'event_log', 
                          'npc_memory_scope', 'npc_belief', 'npc_private_memory',
                          'npc_secret', 'npc_relationship_memory'
    
    Returns:
        TurnOrchestrator: Fully configured orchestrator with DB-backed dependencies.
    """
    from llm_rpg.storage.repositories import (
        NPCMemoryScopeRepository,
        NPCBeliefRepository,
        NPCPrivateMemoryRepository,
        NPCSecretRepository,
        NPCRelationshipMemoryRepository,
    )
    
    event_log = EventLog()
    state_manager = CanonicalStateManager()
    action_scheduler = ActionScheduler()
    validator = Validator()
    perspective_service = PerspectiveService()
    retrieval_system = RetrievalSystem()
    context_builder = ContextBuilder(retrieval_system, perspective_service)
    
    session_id = repositories.get('session_id')
    npc_memory_scope_repo = repositories.get('npc_memory_scope') or NPCMemoryScopeRepository(db)
    npc_belief_repo = repositories.get('npc_belief') or NPCBeliefRepository(db)
    npc_private_memory_repo = repositories.get('npc_private_memory') or NPCPrivateMemoryRepository(db)
    npc_secret_repo = repositories.get('npc_secret') or NPCSecretRepository(db)
    npc_relationship_repo = repositories.get('npc_relationship_memory') or NPCRelationshipMemoryRepository(db)
    
    npc_memory = NPCMemoryManager(
        scope_repo=npc_memory_scope_repo,
        belief_repo=npc_belief_repo,
        memory_repo=npc_private_memory_repo,
        secret_repo=npc_secret_repo,
        relationship_repo=npc_relationship_repo,
        session_id=session_id,
    )
    lore_store = LoreStore()
    summary_manager = SummaryManager()
    
    from llm_rpg.storage.repositories import (
        MemorySummaryRepository,
        MemoryFactRepository,
    )
    memory_summary_repo = MemorySummaryRepository(db)
    memory_fact_repo = MemoryFactRepository(db)
    
    memory_writer = MemoryWriter(
        event_log=event_log,
        npc_memory_manager=npc_memory,
        summary_manager=summary_manager,
        memory_summary_repo=memory_summary_repo,
        memory_fact_repo=memory_fact_repo,
        npc_belief_repo=npc_belief_repo,
        npc_relationship_repo=npc_relationship_repo,
        session_id=session_id,
    )
    
    # Create ProposalPipeline for LLM calls
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


def build_memory_turn_orchestrator_for_tests(
    llm_service: Optional[LLMService] = None
) -> TurnOrchestrator:
    """
    Construct a TurnOrchestrator for testing with in-memory dependencies.
    
    This function creates a TurnOrchestrator that uses in-memory state
    management, suitable for unit tests and integration tests that don't
    require database persistence.
    
    Args:
        llm_service: Optional LLMService instance. If provided, a ProposalPipeline
                    will be created and shared across all engines.
                    If None, engines use deterministic fallback behavior.
    
    Returns:
        TurnOrchestrator: Fully configured orchestrator with in-memory dependencies.
    """
    # Create shared in-memory dependencies
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


# Alias for backward compatibility - points to memory version for tests
build_turn_orchestrator = build_memory_turn_orchestrator_for_tests
