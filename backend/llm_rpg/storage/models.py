from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import Column, String, Integer, Float, DateTime, JSON, Boolean, Text, ForeignKey, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID, ARRAY

from .database import Base

import uuid


def generate_uuid():
    return str(uuid.uuid4())


class WorldModel(Base):
    __tablename__ = "worlds"

    id = Column(String, primary_key=True, default=generate_uuid)
    code = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=False)
    genre = Column(String, nullable=True)
    lore_summary = Column(Text, nullable=True)
    status = Column(String, default="active")
    created_at = Column(DateTime, default=datetime.now)

    chapters = relationship("ChapterModel", back_populates="world")
    locations = relationship("LocationModel", back_populates="world")
    npc_templates = relationship("NPCTemplateModel", back_populates="world")
    item_templates = relationship("ItemTemplateModel", back_populates="world")
    quest_templates = relationship("QuestTemplateModel", back_populates="world")
    prompt_templates = relationship("PromptTemplateModel", back_populates="world")
    factions = relationship("FactionModel", back_populates="world")
    plot_beats = relationship("PlotBeatModel", back_populates="world")


class ChapterModel(Base):
    __tablename__ = "chapters"

    id = Column(String, primary_key=True, default=generate_uuid)
    world_id = Column(String, ForeignKey("worlds.id"), nullable=False)
    chapter_no = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    summary = Column(Text, nullable=True)
    start_conditions = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.now)

    world = relationship("WorldModel", back_populates="chapters")
    locations = relationship("LocationModel", back_populates="chapter")

    __table_args__ = (UniqueConstraint("world_id", "chapter_no"),)


class LocationModel(Base):
    __tablename__ = "locations"

    id = Column(String, primary_key=True, default=generate_uuid)
    world_id = Column(String, ForeignKey("worlds.id"), nullable=False)
    chapter_id = Column(String, ForeignKey("chapters.id"), nullable=True)
    code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    tags = Column(JSON, default=list)
    description = Column(Text, nullable=True)
    access_rules = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.now)

    world = relationship("WorldModel", back_populates="locations")
    chapter = relationship("ChapterModel", back_populates="locations")


class NPCTemplateModel(Base):
    __tablename__ = "npc_templates"

    id = Column(String, primary_key=True, default=generate_uuid)
    world_id = Column(String, ForeignKey("worlds.id"), nullable=False)
    code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    role_type = Column(String, nullable=True)
    public_identity = Column(Text, nullable=True)
    hidden_identity = Column(Text, nullable=True)
    personality = Column(Text, nullable=True)
    speech_style = Column(Text, nullable=True)
    goals = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.now)

    world = relationship("WorldModel", back_populates="npc_templates")
    session_npc_states = relationship("SessionNPCStateModel", back_populates="npc_template")


class ItemTemplateModel(Base):
    __tablename__ = "item_templates"

    id = Column(String, primary_key=True, default=generate_uuid)
    world_id = Column(String, ForeignKey("worlds.id"), nullable=False)
    code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    item_type = Column(String, nullable=True)
    rarity = Column(String, default="common")
    effects_json = Column(JSON, default=dict)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    world = relationship("WorldModel", back_populates="item_templates")
    inventory_items = relationship("SessionInventoryItemModel", back_populates="item_template")


class QuestTemplateModel(Base):
    __tablename__ = "quest_templates"

    id = Column(String, primary_key=True, default=generate_uuid)
    world_id = Column(String, ForeignKey("worlds.id"), nullable=False)
    code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    quest_type = Column(String, nullable=True)
    summary = Column(Text, nullable=True)
    visibility = Column(String, default="hidden")
    created_at = Column(DateTime, default=datetime.now)

    world = relationship("WorldModel", back_populates="quest_templates")
    quest_steps = relationship("QuestStepModel", back_populates="quest_template")
    quest_states = relationship("SessionQuestStateModel", back_populates="quest_template")


class QuestStepModel(Base):
    __tablename__ = "quest_steps"

    id = Column(String, primary_key=True, default=generate_uuid)
    quest_template_id = Column(String, ForeignKey("quest_templates.id"), nullable=False)
    step_no = Column(Integer, nullable=False)
    objective = Column(Text, nullable=False)
    success_conditions = Column(JSON, default=dict)
    fail_conditions = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.now)

    quest_template = relationship("QuestTemplateModel", back_populates="quest_steps")

    __table_args__ = (UniqueConstraint("quest_template_id", "step_no"),)


class EventTemplateModel(Base):
    __tablename__ = "event_templates"

    id = Column(String, primary_key=True, default=generate_uuid)
    world_id = Column(String, ForeignKey("worlds.id"), nullable=True)
    code = Column(String, nullable=False)
    name = Column(String, nullable=False)
    event_type = Column(String, nullable=True)
    trigger_conditions = Column(JSON, default=dict)
    effects = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.now)

    scheduled_events = relationship("ScheduledEventModel", back_populates="event_template")


class PromptTemplateModel(Base):
    __tablename__ = "prompt_templates"

    id = Column(String, primary_key=True, default=generate_uuid)
    world_id = Column(String, ForeignKey("worlds.id"), nullable=True)
    prompt_type = Column(String, nullable=False)
    version = Column(String, default="1.0")
    content = Column(Text, nullable=False)
    enabled_flag = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)

    world = relationship("WorldModel", back_populates="prompt_templates")
    llm_stage_results = relationship("LLMStageResultModel", back_populates="prompt_template")


class UserModel(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=generate_uuid)
    username = Column(String, nullable=False, unique=True)
    email = Column(String, nullable=True, unique=True)
    password_hash = Column(String, nullable=True)
    is_admin = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.now)
    last_login_at = Column(DateTime, nullable=True)

    save_slots = relationship("SaveSlotModel", back_populates="user")
    sessions = relationship("SessionModel", back_populates="user")


class SystemSettingsModel(Base):
    __tablename__ = "system_settings"

    id = Column(String, primary_key=True, default=generate_uuid)
    provider_mode = Column(String, default="auto", nullable=False)
    default_model = Column(String, default="gpt-4", nullable=True)
    temperature = Column(Float, default=0.7, nullable=False)
    max_tokens = Column(Integer, default=2000, nullable=False)
    registration_enabled = Column(Boolean, default=True, nullable=False)
    maintenance_mode = Column(Boolean, default=False, nullable=False)
    debug_enabled = Column(Boolean, default=True, nullable=False)
    openai_api_key_encrypted = Column(Text, nullable=True)
    openai_api_key_last4 = Column(String, nullable=True)
    secret_updated_at = Column(DateTime, nullable=True)
    secret_cleared_at = Column(DateTime, nullable=True)
    custom_base_url = Column(String, nullable=True)
    custom_api_key_encrypted = Column(Text, nullable=True)
    custom_api_key_last4 = Column(String, nullable=True)
    custom_secret_updated_at = Column(DateTime, nullable=True)
    custom_secret_cleared_at = Column(DateTime, nullable=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    updated_by_user_id = Column(String, ForeignKey("users.id"), nullable=True)


class SaveSlotModel(Base):
    __tablename__ = "save_slots"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    slot_number = Column(Integer, nullable=False)
    name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    user = relationship("UserModel", back_populates="save_slots")
    sessions = relationship("SessionModel", back_populates="save_slot")

    __table_args__ = (UniqueConstraint("user_id", "slot_number"),)


class SessionModel(Base):
    __tablename__ = "sessions"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    save_slot_id = Column(String, ForeignKey("save_slots.id"), nullable=True)
    world_id = Column(String, ForeignKey("worlds.id"), nullable=False)
    current_chapter_id = Column(String, ForeignKey("chapters.id"), nullable=True)
    status = Column(String, default="active")
    started_at = Column(DateTime, default=datetime.now)
    last_played_at = Column(DateTime, default=datetime.now)

    user = relationship("UserModel", back_populates="sessions")
    save_slot = relationship("SaveSlotModel", back_populates="sessions")
    session_state = relationship("SessionStateModel", back_populates="session", uselist=False)
    player_state = relationship("SessionPlayerStateModel", back_populates="session", uselist=False)
    npc_states = relationship("SessionNPCStateModel", back_populates="session")
    inventory_items = relationship("SessionInventoryItemModel", back_populates="session")
    quest_states = relationship("SessionQuestStateModel", back_populates="session")
    event_logs = relationship("EventLogModel", back_populates="session")
    memory_summaries = relationship("MemorySummaryModel", back_populates="session")
    memory_facts = relationship("MemoryFactModel", back_populates="session")
    model_call_logs = relationship("ModelCallLogModel", back_populates="session")
    combat_sessions = relationship("CombatSessionModel", back_populates="session")
    scheduled_events = relationship("ScheduledEventModel", back_populates="session")
    turn_transactions = relationship("TurnTransactionModel", back_populates="session")
    npc_memory_scopes = relationship("NPCMemoryScopeModel", back_populates="session")
    npc_beliefs = relationship("NPCBeliefModel", back_populates="session")
    npc_private_memories = relationship("NPCPrivateMemoryModel", back_populates="session")
    npc_secrets = relationship("NPCSecretModel", back_populates="session")
    npc_relationship_memories = relationship("NPCRelationshipMemoryModel", back_populates="session")


class SessionStateModel(Base):
    __tablename__ = "session_states"

    id = Column(String, primary_key=True, default=generate_uuid)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False, unique=True)
    current_time = Column(String, nullable=True)
    time_phase = Column(String, nullable=True)
    current_location_id = Column(String, ForeignKey("locations.id"), nullable=True)
    active_mode = Column(String, default="exploration")
    global_flags_json = Column(JSON, default=dict)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    session = relationship("SessionModel", back_populates="session_state")


class SessionPlayerStateModel(Base):
    __tablename__ = "session_player_states"

    id = Column(String, primary_key=True, default=generate_uuid)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False, unique=True)
    realm_stage = Column(String, default="炼气一层")
    hp = Column(Integer, default=100)
    max_hp = Column(Integer, default=100)
    stamina = Column(Integer, default=100)
    spirit_power = Column(Integer, default=100)
    relation_bias_json = Column(JSON, default=dict)
    conditions_json = Column(JSON, default=list)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    session = relationship("SessionModel", back_populates="player_state")


class SessionNPCStateModel(Base):
    __tablename__ = "session_npc_states"

    id = Column(String, primary_key=True, default=generate_uuid)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    npc_template_id = Column(String, ForeignKey("npc_templates.id"), nullable=False)
    current_location_id = Column(String, ForeignKey("locations.id"), nullable=True)
    trust_score = Column(Integer, default=50)
    suspicion_score = Column(Integer, default=0)
    status_flags = Column(JSON, default=dict)
    short_memory_summary = Column(Text, nullable=True)
    hidden_plan_state = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    session = relationship("SessionModel", back_populates="npc_states")
    npc_template = relationship("NPCTemplateModel", back_populates="session_npc_states")

    __table_args__ = (UniqueConstraint("session_id", "npc_template_id"),)


class SessionInventoryItemModel(Base):
    __tablename__ = "session_inventory_items"

    id = Column(String, primary_key=True, default=generate_uuid)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    item_template_id = Column(String, ForeignKey("item_templates.id"), nullable=False)
    owner_type = Column(String, default="player")
    owner_ref_id = Column(String, nullable=True)
    quantity = Column(Integer, default=1)
    durability = Column(Integer, nullable=True)
    bound_flag = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)

    session = relationship("SessionModel", back_populates="inventory_items")
    item_template = relationship("ItemTemplateModel", back_populates="inventory_items")


class SessionQuestStateModel(Base):
    __tablename__ = "session_quest_states"

    id = Column(String, primary_key=True, default=generate_uuid)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    quest_template_id = Column(String, ForeignKey("quest_templates.id"), nullable=False)
    current_step_no = Column(Integer, default=1)
    progress_json = Column(JSON, default=dict)
    status = Column(String, default="active")
    last_updated_at = Column(DateTime, default=datetime.now)

    session = relationship("SessionModel", back_populates="quest_states")
    quest_template = relationship("QuestTemplateModel", back_populates="quest_states")


class SessionEventFlagModel(Base):
    __tablename__ = "session_event_flags"

    id = Column(String, primary_key=True, default=generate_uuid)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    flag_key = Column(String, nullable=False)
    flag_value = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (UniqueConstraint("session_id", "flag_key"),)


class EventLogModel(Base):
    __tablename__ = "event_logs"

    id = Column(String, primary_key=True, default=generate_uuid)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    turn_no = Column(Integer, nullable=False)
    event_type = Column(String, nullable=False)
    input_text = Column(Text, nullable=True)
    structured_action = Column(JSON, nullable=True)
    result_json = Column(JSON, nullable=True)
    narrative_text = Column(Text, nullable=True)
    occurred_at = Column(DateTime, default=datetime.now)

    session = relationship("SessionModel", back_populates="event_logs")
    combat_sessions = relationship("CombatSessionModel", back_populates="trigger_event")
    memory_facts = relationship("MemoryFactModel", back_populates="source_event")

    __table_args__ = (
        Index("idx_event_logs_session_turn", "session_id", "turn_no"),
        UniqueConstraint("session_id", "turn_no", "event_type", name="uq_event_logs_session_turn_type"),
    )


class MemorySummaryModel(Base):
    __tablename__ = "memory_summaries"

    id = Column(String, primary_key=True, default=generate_uuid)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    scope_type = Column(String, nullable=False)
    scope_ref_id = Column(String, nullable=True)
    summary_text = Column(Text, nullable=False)
    source_turn_range = Column(JSON, nullable=True)
    importance_score = Column(Float, default=0.5)
    embedding = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    session = relationship("SessionModel", back_populates="memory_summaries")


class MemoryFactModel(Base):
    __tablename__ = "memory_facts"

    id = Column(String, primary_key=True, default=generate_uuid)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    fact_type = Column(String, nullable=False)
    subject_ref = Column(String, nullable=True)
    fact_key = Column(String, nullable=False)
    fact_value = Column(Text, nullable=True)
    confidence = Column(Float, default=1.0)
    source_event_id = Column(String, ForeignKey("event_logs.id"), nullable=True)
    embedding = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    session = relationship("SessionModel", back_populates="memory_facts")
    source_event = relationship("EventLogModel", back_populates="memory_facts")

    __table_args__ = (Index("idx_memory_facts_lookup", "session_id", "fact_type", "subject_ref"),)


class ModelCallLogModel(Base):
    __tablename__ = "model_call_logs"

    id = Column(String, primary_key=True, default=generate_uuid)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    turn_no = Column(Integer, nullable=False)
    provider = Column(String, nullable=True)
    model_name = Column(String, nullable=True)
    prompt_type = Column(String, nullable=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    cost_estimate = Column(Float, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    request_payload = Column(JSON, nullable=True)
    response_payload = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    session = relationship("SessionModel", back_populates="model_call_logs")

    __table_args__ = (Index("idx_model_calls_lookup", "session_id", "turn_no", "prompt_type"),)


class ModelCallAuditLogModel(Base):
    __tablename__ = "model_call_audit_logs"

    call_id = Column(String, primary_key=True)
    session_id = Column(String, nullable=False, index=True)
    turn_no = Column(Integer, nullable=False)
    provider = Column(String, nullable=True)
    model_name = Column(String, nullable=True)
    prompt_type = Column(String, nullable=True)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    cost_estimate = Column(Float, nullable=True)
    latency_ms = Column(Integer, default=0)
    success = Column(Boolean, default=True)
    error_message = Column(Text, nullable=True)
    context_build_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_audit_logs_session", "session_id"),
        Index("idx_audit_logs_session_turn", "session_id", "turn_no"),
    )


class CombatSessionModel(Base):
    __tablename__ = "combat_sessions"

    id = Column(String, primary_key=True, default=generate_uuid)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    trigger_event_id = Column(String, ForeignKey("event_logs.id"), nullable=True)
    location_id = Column(String, ForeignKey("locations.id"), nullable=True)
    combat_status = Column(String, default="active")
    winner = Column(String, nullable=True)
    started_at = Column(DateTime, default=datetime.now)
    ended_at = Column(DateTime, nullable=True)

    session = relationship("SessionModel", back_populates="combat_sessions")
    trigger_event = relationship("EventLogModel", back_populates="combat_sessions")
    combat_rounds = relationship("CombatRoundModel", back_populates="combat_session")


class CombatRoundModel(Base):
    __tablename__ = "combat_rounds"

    id = Column(String, primary_key=True, default=generate_uuid)
    combat_session_id = Column(String, ForeignKey("combat_sessions.id"), nullable=False)
    round_no = Column(Integer, nullable=False)
    initiative_order_json = Column(JSON, default=list)
    round_summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    combat_session = relationship("CombatSessionModel", back_populates="combat_rounds")
    combat_actions = relationship("CombatActionModel", back_populates="combat_round")


class CombatActionModel(Base):
    __tablename__ = "combat_actions"

    id = Column(String, primary_key=True, default=generate_uuid)
    combat_round_id = Column(String, ForeignKey("combat_rounds.id"), nullable=False)
    actor_type = Column(String, nullable=False)
    actor_ref_id = Column(String, nullable=False)
    action_type = Column(String, nullable=False)
    action_payload_json = Column(JSON, default=dict)
    resolution_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.now)

    combat_round = relationship("CombatRoundModel", back_populates="combat_actions")


class ScheduledEventModel(Base):
    __tablename__ = "scheduled_events"

    id = Column(String, primary_key=True, default=generate_uuid)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    event_template_id = Column(String, ForeignKey("event_templates.id"), nullable=True)
    trigger_time = Column(DateTime, nullable=True)
    trigger_conditions_json = Column(JSON, default=dict)
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.now)

    session = relationship("SessionModel", back_populates="scheduled_events")
    event_template = relationship("EventTemplateModel", back_populates="scheduled_events")

    __table_args__ = (Index("idx_scheduled_events_lookup", "session_id", "trigger_time", "status"),)


class TurnTransactionModel(Base):
    __tablename__ = "turn_transactions"

    id = Column(String, primary_key=True, default=generate_uuid)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    turn_no = Column(Integer, nullable=False)
    idempotency_key = Column(String, nullable=False, unique=True)
    status = Column(String, nullable=False)
    player_input = Column(Text, nullable=True)
    world_time_before = Column(String, nullable=True)
    world_time_after = Column(String, nullable=True)
    started_at = Column(DateTime, nullable=False)
    committed_at = Column(DateTime, nullable=True)
    aborted_at = Column(DateTime, nullable=True)
    error_json = Column(JSON, nullable=True)

    session = relationship("SessionModel", back_populates="turn_transactions")
    game_events = relationship("GameEventModel", back_populates="transaction")
    state_deltas = relationship("StateDeltaModel", back_populates="transaction")
    llm_stage_results = relationship("LLMStageResultModel", back_populates="transaction")
    validation_reports = relationship("ValidationReportModel", back_populates="transaction")

    __table_args__ = (
        UniqueConstraint("session_id", "turn_no"),
        Index("idx_turn_transactions_session", "session_id", "turn_no"),
        Index("idx_turn_transactions_status", "session_id", "status"),
    )


class GameEventModel(Base):
    __tablename__ = "game_events"

    id = Column(String, primary_key=True, default=generate_uuid)
    transaction_id = Column(String, ForeignKey("turn_transactions.id"), nullable=False)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    turn_no = Column(Integer, nullable=False)
    event_type = Column(String, nullable=False)
    actor_id = Column(String, nullable=True)
    target_ids_json = Column(JSON, nullable=True)
    visibility_scope = Column(String, nullable=True)
    public_payload_json = Column(JSON, nullable=True)
    private_payload_json = Column(JSON, nullable=True)
    result_json = Column(JSON, nullable=True)
    occurred_at = Column(DateTime, nullable=False)

    transaction = relationship("TurnTransactionModel", back_populates="game_events")
    state_deltas = relationship("StateDeltaModel", back_populates="source_event")

    __table_args__ = (
        Index("idx_game_events_transaction", "transaction_id"),
        Index("idx_game_events_session_turn", "session_id", "turn_no"),
        Index("idx_game_events_type", "session_id", "event_type"),
    )


class StateDeltaModel(Base):
    __tablename__ = "state_deltas"

    id = Column(String, primary_key=True, default=generate_uuid)
    transaction_id = Column(String, ForeignKey("turn_transactions.id"), nullable=False)
    source_event_id = Column(String, ForeignKey("game_events.id"), nullable=False)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    turn_no = Column(Integer, nullable=False)
    path = Column(String, nullable=False)
    operation = Column(String, nullable=False)
    old_value_json = Column(JSON, nullable=True)
    new_value_json = Column(JSON, nullable=True)
    visibility_scope = Column(String, nullable=True)
    validation_status = Column(String, nullable=True)
    created_at = Column(DateTime, nullable=False)

    transaction = relationship("TurnTransactionModel", back_populates="state_deltas")
    source_event = relationship("GameEventModel", back_populates="state_deltas")

    __table_args__ = (
        Index("idx_state_deltas_transaction", "transaction_id"),
        Index("idx_state_deltas_session_turn", "session_id", "turn_no"),
        Index("idx_state_deltas_path", "session_id", "path"),
    )


class LLMStageResultModel(Base):
    __tablename__ = "llm_stage_results"

    id = Column(String, primary_key=True, default=generate_uuid)
    transaction_id = Column(String, ForeignKey("turn_transactions.id"), nullable=False)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    turn_no = Column(Integer, nullable=False)
    stage_name = Column(String, nullable=False)
    provider = Column(String, nullable=True)
    model = Column(String, nullable=True)
    prompt_template_id = Column(String, ForeignKey("prompt_templates.id"), nullable=True)
    request_payload_ref = Column(String, nullable=True)
    raw_output_ref = Column(String, nullable=True)
    parsed_proposal_json = Column(JSON, nullable=True)
    accepted = Column(Boolean, nullable=True)
    fallback_reason = Column(String, nullable=True)
    validation_errors_json = Column(JSON, nullable=True)
    latency_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, nullable=False)

    transaction = relationship("TurnTransactionModel", back_populates="llm_stage_results")
    prompt_template = relationship("PromptTemplateModel", back_populates="llm_stage_results")

    __table_args__ = (
        Index("idx_llm_stage_results_transaction", "transaction_id"),
        Index("idx_llm_stage_results_session_turn", "session_id", "turn_no"),
        Index("idx_llm_stage_results_stage", "session_id", "stage_name"),
    )


class ValidationReportModel(Base):
    __tablename__ = "validation_reports"

    id = Column(String, primary_key=True, default=generate_uuid)
    transaction_id = Column(String, ForeignKey("turn_transactions.id"), nullable=False)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    turn_no = Column(Integer, nullable=False)
    scope = Column(String, nullable=False)
    target_ref_id = Column(String, nullable=True)
    is_valid = Column(Boolean, nullable=False)
    errors_json = Column(JSON, nullable=True)
    warnings_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False)

    transaction = relationship("TurnTransactionModel", back_populates="validation_reports")

    __table_args__ = (
        Index("idx_validation_reports_transaction", "transaction_id"),
        Index("idx_validation_reports_session_turn", "session_id", "turn_no"),
    )


class NPCMemoryScopeModel(Base):
    __tablename__ = "npc_memory_scopes"

    id = Column(String, primary_key=True, default=generate_uuid)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    npc_id = Column(String, nullable=False)
    profile_json = Column(JSON, nullable=True)
    forget_curve_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.now)
    updated_at = Column(DateTime, nullable=False, default=datetime.now, onupdate=datetime.now)

    session = relationship("SessionModel", back_populates="npc_memory_scopes")

    __table_args__ = (
        UniqueConstraint("session_id", "npc_id"),
        Index("idx_npc_memory_scopes_session", "session_id"),
        Index("idx_npc_memory_scopes_npc", "session_id", "npc_id"),
    )


class NPCBeliefModel(Base):
    __tablename__ = "npc_beliefs"

    id = Column(String, primary_key=True, default=generate_uuid)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    npc_id = Column(String, nullable=False)
    belief_type = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    confidence = Column(Float, nullable=False, default=0.5)
    truth_status = Column(String, nullable=False, default="unknown")
    source_event_id = Column(String, nullable=True)
    created_turn = Column(Integer, nullable=False)
    last_updated_turn = Column(Integer, nullable=False)
    embedding = Column(JSON, nullable=True)

    session = relationship("SessionModel", back_populates="npc_beliefs")

    __table_args__ = (
        Index("idx_npc_beliefs_session", "session_id"),
        Index("idx_npc_beliefs_npc", "session_id", "npc_id"),
        Index("idx_npc_beliefs_type", "session_id", "belief_type"),
    )


class NPCPrivateMemoryModel(Base):
    __tablename__ = "npc_private_memories"

    id = Column(String, primary_key=True, default=generate_uuid)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    npc_id = Column(String, nullable=False)
    memory_type = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    source_event_ids_json = Column(JSON, nullable=True)
    entities_json = Column(JSON, nullable=True)
    importance = Column(Float, nullable=False, default=0.5)
    emotional_weight = Column(Float, nullable=False, default=0.0)
    confidence = Column(Float, nullable=False, default=1.0)
    current_strength = Column(Float, nullable=False, default=1.0)
    created_turn = Column(Integer, nullable=False)
    last_accessed_turn = Column(Integer, nullable=False)
    recall_count = Column(Integer, nullable=False, default=0)
    embedding = Column(JSON, nullable=True)

    session = relationship("SessionModel", back_populates="npc_private_memories")

    __table_args__ = (
        Index("idx_npc_private_memories_session", "session_id"),
        Index("idx_npc_private_memories_npc", "session_id", "npc_id"),
        Index("idx_npc_private_memories_type", "session_id", "memory_type"),
    )


class NPCSecretModel(Base):
    __tablename__ = "npc_secrets"

    id = Column(String, primary_key=True, default=generate_uuid)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    npc_id = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    willingness_to_reveal = Column(Float, nullable=False, default=0.1)
    reveal_conditions_json = Column(JSON, nullable=True)
    status = Column(String, nullable=False, default="hidden")
    created_at = Column(DateTime, nullable=False, default=datetime.now)

    session = relationship("SessionModel", back_populates="npc_secrets")

    __table_args__ = (
        Index("idx_npc_secrets_session", "session_id"),
        Index("idx_npc_secrets_npc", "session_id", "npc_id"),
        Index("idx_npc_secrets_status", "session_id", "status"),
    )


class NPCRelationshipMemoryModel(Base):
    __tablename__ = "npc_relationship_memories"

    id = Column(String, primary_key=True, default=generate_uuid)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    npc_id = Column(String, nullable=False)
    target_id = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    impact_json = Column(JSON, nullable=True)
    source_event_id = Column(String, nullable=True)
    created_turn = Column(Integer, nullable=False)

    session = relationship("SessionModel", back_populates="npc_relationship_memories")

    __table_args__ = (
        Index("idx_npc_relationship_memories_session", "session_id"),
        Index("idx_npc_relationship_memories_npc", "session_id", "npc_id"),
        Index("idx_npc_relationship_memories_target", "session_id", "npc_id", "target_id"),
    )


class FactionModel(Base):
    __tablename__ = "factions"

    id = Column(String, primary_key=True, default=generate_uuid)
    logical_id = Column(String, nullable=False)
    world_id = Column(String, ForeignKey("worlds.id"), nullable=False)
    name = Column(String, nullable=False)
    ideology = Column(JSON, default=dict)
    goals = Column(JSON, default=list)
    relationships = Column(JSON, default=list)
    visibility = Column(String, default="public")
    status = Column(String, default="active")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    world = relationship("WorldModel", back_populates="factions")

    __table_args__ = (
        UniqueConstraint("world_id", "logical_id"),
        Index("idx_factions_world", "world_id"),
    )


class PlotBeatModel(Base):
    __tablename__ = "plot_beats"

    id = Column(String, primary_key=True, default=generate_uuid)
    logical_id = Column(String, nullable=False)
    world_id = Column(String, ForeignKey("worlds.id"), nullable=False)
    title = Column(String, nullable=False)
    conditions = Column(JSON, default=list)
    effects = Column(JSON, default=list)
    priority = Column(Integer, default=0)
    visibility = Column(String, default="conditional")
    status = Column(String, default="pending")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    world = relationship("WorldModel", back_populates="plot_beats")

    __table_args__ = (
        UniqueConstraint("world_id", "logical_id"),
        Index("idx_plot_beats_world", "world_id"),
        Index("idx_plot_beats_status", "world_id", "status"),
    )
