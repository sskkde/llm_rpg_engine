"""Initial schema with all 27 tables.

Revision ID: 001
Revises:
Create Date: 2025-04-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    
    op.create_table('worlds',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('code', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('genre', sa.String(), nullable=True),
        sa.Column('lore_summary', sa.Text(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code')
    )
    
    op.create_table('event_templates',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('world_id', sa.String(), nullable=True),
        sa.Column('code', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('event_type', sa.String(), nullable=True),
        sa.Column('trigger_conditions', sa.JSON(), nullable=True),
        sa.Column('effects', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_table('users',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('username', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=True),
        sa.Column('password_hash', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('last_login_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email'),
        sa.UniqueConstraint('username')
    )
    
    op.create_table('chapters',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('world_id', sa.String(), nullable=False),
        sa.Column('chapter_no', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('start_conditions', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['world_id'], ['worlds.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('world_id', 'chapter_no')
    )
    
    op.create_table('item_templates',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('world_id', sa.String(), nullable=False),
        sa.Column('code', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('item_type', sa.String(), nullable=True),
        sa.Column('rarity', sa.String(), nullable=True),
        sa.Column('effects_json', sa.JSON(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['world_id'], ['worlds.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_table('locations',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('world_id', sa.String(), nullable=False),
        sa.Column('chapter_id', sa.String(), nullable=True),
        sa.Column('code', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('tags', sa.JSON(), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('access_rules', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['chapter_id'], ['chapters.id'], ),
        sa.ForeignKeyConstraint(['world_id'], ['worlds.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_table('npc_templates',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('world_id', sa.String(), nullable=False),
        sa.Column('code', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('role_type', sa.String(), nullable=True),
        sa.Column('public_identity', sa.Text(), nullable=True),
        sa.Column('hidden_identity', sa.Text(), nullable=True),
        sa.Column('personality', sa.Text(), nullable=True),
        sa.Column('speech_style', sa.Text(), nullable=True),
        sa.Column('goals', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['world_id'], ['worlds.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_table('prompt_templates',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('world_id', sa.String(), nullable=True),
        sa.Column('prompt_type', sa.String(), nullable=False),
        sa.Column('version', sa.String(), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('enabled_flag', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['world_id'], ['worlds.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_table('quest_templates',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('world_id', sa.String(), nullable=False),
        sa.Column('code', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('quest_type', sa.String(), nullable=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('visibility', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['world_id'], ['worlds.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_table('save_slots',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('slot_number', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'slot_number')
    )
    
    op.create_table('quest_steps',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('quest_template_id', sa.String(), nullable=False),
        sa.Column('step_no', sa.Integer(), nullable=False),
        sa.Column('objective', sa.Text(), nullable=False),
        sa.Column('success_conditions', sa.JSON(), nullable=True),
        sa.Column('fail_conditions', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['quest_template_id'], ['quest_templates.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('quest_template_id', 'step_no')
    )
    
    op.create_table('sessions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('save_slot_id', sa.String(), nullable=True),
        sa.Column('world_id', sa.String(), nullable=False),
        sa.Column('current_chapter_id', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('last_played_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['current_chapter_id'], ['chapters.id'], ),
        sa.ForeignKeyConstraint(['save_slot_id'], ['save_slots.id'], ),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
        sa.ForeignKeyConstraint(['world_id'], ['worlds.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_table('combat_sessions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('trigger_event_id', sa.String(), nullable=True),
        sa.Column('location_id', sa.String(), nullable=True),
        sa.Column('combat_status', sa.String(), nullable=True),
        sa.Column('winner', sa.String(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('ended_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['location_id'], ['locations.id'], ),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_table('event_logs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('turn_no', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('input_text', sa.Text(), nullable=True),
        sa.Column('structured_action', sa.JSON(), nullable=True),
        sa.Column('result_json', sa.JSON(), nullable=True),
        sa.Column('narrative_text', sa.Text(), nullable=True),
        sa.Column('occurred_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_event_logs_session_turn', 'event_logs', ['session_id', 'turn_no'], unique=False)
    
    op.create_table('memory_facts',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('fact_type', sa.String(), nullable=False),
        sa.Column('subject_ref', sa.String(), nullable=True),
        sa.Column('fact_key', sa.String(), nullable=False),
        sa.Column('fact_value', sa.Text(), nullable=True),
        sa.Column('confidence', sa.Float(), nullable=True),
        sa.Column('source_event_id', sa.String(), nullable=True),
        sa.Column('embedding', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_memory_facts_lookup', 'memory_facts', ['session_id', 'fact_type', 'subject_ref'], unique=False)
    
    op.create_table('memory_summaries',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('scope_type', sa.String(), nullable=False),
        sa.Column('scope_ref_id', sa.String(), nullable=True),
        sa.Column('summary_text', sa.Text(), nullable=False),
        sa.Column('source_turn_range', sa.JSON(), nullable=True),
        sa.Column('importance_score', sa.Float(), nullable=True),
        sa.Column('embedding', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_table('model_call_logs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('turn_no', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(), nullable=True),
        sa.Column('model_name', sa.String(), nullable=True),
        sa.Column('prompt_type', sa.String(), nullable=True),
        sa.Column('input_tokens', sa.Integer(), nullable=True),
        sa.Column('output_tokens', sa.Integer(), nullable=True),
        sa.Column('cost_estimate', sa.Float(), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_model_calls_lookup', 'model_call_logs', ['session_id', 'turn_no', 'prompt_type'], unique=False)
    
    op.create_table('scheduled_events',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('event_template_id', sa.String(), nullable=True),
        sa.Column('trigger_time', sa.DateTime(), nullable=True),
        sa.Column('trigger_conditions_json', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['event_template_id'], ['event_templates.id'], ),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_scheduled_events_lookup', 'scheduled_events', ['session_id', 'trigger_time', 'status'], unique=False)
    
    op.create_table('session_event_flags',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('flag_key', sa.String(), nullable=False),
        sa.Column('flag_value', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_id', 'flag_key')
    )
    
    op.create_table('session_inventory_items',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('item_template_id', sa.String(), nullable=False),
        sa.Column('owner_type', sa.String(), nullable=True),
        sa.Column('owner_ref_id', sa.String(), nullable=True),
        sa.Column('quantity', sa.Integer(), nullable=True),
        sa.Column('durability', sa.Integer(), nullable=True),
        sa.Column('bound_flag', sa.Boolean(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['item_template_id'], ['item_templates.id'], ),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_table('session_npc_states',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('npc_template_id', sa.String(), nullable=False),
        sa.Column('current_location_id', sa.String(), nullable=True),
        sa.Column('trust_score', sa.Integer(), nullable=True),
        sa.Column('suspicion_score', sa.Integer(), nullable=True),
        sa.Column('status_flags', sa.JSON(), nullable=True),
        sa.Column('short_memory_summary', sa.Text(), nullable=True),
        sa.Column('hidden_plan_state', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['current_location_id'], ['locations.id'], ),
        sa.ForeignKeyConstraint(['npc_template_id'], ['npc_templates.id'], ),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_id', 'npc_template_id')
    )
    
    op.create_table('session_player_states',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('realm_stage', sa.String(), nullable=True),
        sa.Column('hp', sa.Integer(), nullable=True),
        sa.Column('max_hp', sa.Integer(), nullable=True),
        sa.Column('stamina', sa.Integer(), nullable=True),
        sa.Column('spirit_power', sa.Integer(), nullable=True),
        sa.Column('relation_bias_json', sa.JSON(), nullable=True),
        sa.Column('conditions_json', sa.JSON(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_id')
    )
    
    op.create_table('session_quest_states',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('quest_template_id', sa.String(), nullable=False),
        sa.Column('current_step_no', sa.Integer(), nullable=True),
        sa.Column('progress_json', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('last_updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['quest_template_id'], ['quest_templates.id'], ),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_table('session_states',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('current_time', sa.String(), nullable=True),
        sa.Column('time_phase', sa.String(), nullable=True),
        sa.Column('current_location_id', sa.String(), nullable=True),
        sa.Column('active_mode', sa.String(), nullable=True),
        sa.Column('global_flags_json', sa.JSON(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['current_location_id'], ['locations.id'], ),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_id')
    )
    
    op.create_table('combat_rounds',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('combat_session_id', sa.String(), nullable=False),
        sa.Column('round_no', sa.Integer(), nullable=False),
        sa.Column('initiative_order_json', sa.JSON(), nullable=True),
        sa.Column('round_summary', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['combat_session_id'], ['combat_sessions.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    
    op.create_table('combat_actions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('combat_round_id', sa.String(), nullable=False),
        sa.Column('actor_type', sa.String(), nullable=False),
        sa.Column('actor_ref_id', sa.String(), nullable=False),
        sa.Column('action_type', sa.String(), nullable=False),
        sa.Column('action_payload_json', sa.JSON(), nullable=True),
        sa.Column('resolution_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['combat_round_id'], ['combat_rounds.id'], ),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('combat_actions')
    op.drop_table('combat_rounds')
    op.drop_table('session_states')
    op.drop_table('session_quest_states')
    op.drop_table('session_player_states')
    op.drop_table('session_npc_states')
    op.drop_table('session_inventory_items')
    op.drop_table('session_event_flags')
    op.drop_index('idx_scheduled_events_lookup', table_name='scheduled_events')
    op.drop_table('scheduled_events')
    op.drop_index('idx_model_calls_lookup', table_name='model_call_logs')
    op.drop_table('model_call_logs')
    op.drop_table('memory_summaries')
    op.drop_index('idx_memory_facts_lookup', table_name='memory_facts')
    op.drop_table('memory_facts')
    op.drop_index('idx_event_logs_session_turn', table_name='event_logs')
    op.drop_table('event_logs')
    op.drop_table('combat_sessions')
    op.drop_table('sessions')
    op.drop_table('quest_steps')
    op.drop_table('save_slots')
    op.drop_table('quest_templates')
    op.drop_table('prompt_templates')
    op.drop_table('npc_templates')
    op.drop_table('locations')
    op.drop_table('item_templates')
    op.drop_table('chapters')
    op.drop_table('users')
    op.drop_table('event_templates')
    op.drop_table('worlds')
