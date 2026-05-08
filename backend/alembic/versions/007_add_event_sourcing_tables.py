"""Add event sourcing tables.

Revision ID: 007
Revises: 629a7f8e996b
Create Date: 2026-05-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '007'
down_revision: Union[str, Sequence[str], None] = '629a7f8e996b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add event sourcing tables for turn transactions, game events, state deltas, LLM stage results, and validation reports."""
    
    # turn_transactions: 事务表，跟踪每个回合的执行状态
    op.create_table('turn_transactions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('turn_no', sa.Integer(), nullable=False),
        sa.Column('idempotency_key', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('player_input', sa.Text(), nullable=True),
        sa.Column('world_time_before', sa.String(), nullable=True),
        sa.Column('world_time_after', sa.String(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('committed_at', sa.DateTime(), nullable=True),
        sa.Column('aborted_at', sa.DateTime(), nullable=True),
        sa.Column('error_json', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_id', 'turn_no'),
        sa.UniqueConstraint('idempotency_key')
    )
    op.create_index('idx_turn_transactions_session', 'turn_transactions', ['session_id', 'turn_no'], unique=False)
    op.create_index('idx_turn_transactions_status', 'turn_transactions', ['session_id', 'status'], unique=False)
    
    # game_events: 事件表，记录回合内发生的所有事件
    op.create_table('game_events',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('transaction_id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('turn_no', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('actor_id', sa.String(), nullable=True),
        sa.Column('target_ids_json', sa.JSON(), nullable=True),
        sa.Column('visibility_scope', sa.String(), nullable=True),
        sa.Column('public_payload_json', sa.JSON(), nullable=True),
        sa.Column('private_payload_json', sa.JSON(), nullable=True),
        sa.Column('result_json', sa.JSON(), nullable=True),
        sa.Column('occurred_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['transaction_id'], ['turn_transactions.id'], ),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_game_events_transaction', 'game_events', ['transaction_id'], unique=False)
    op.create_index('idx_game_events_session_turn', 'game_events', ['session_id', 'turn_no'], unique=False)
    op.create_index('idx_game_events_type', 'game_events', ['session_id', 'event_type'], unique=False)
    
    # state_deltas: 状态变化表，记录所有状态修改
    op.create_table('state_deltas',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('transaction_id', sa.String(), nullable=False),
        sa.Column('source_event_id', sa.String(), nullable=True),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('turn_no', sa.Integer(), nullable=False),
        sa.Column('path', sa.String(), nullable=False),
        sa.Column('operation', sa.String(), nullable=False),
        sa.Column('old_value_json', sa.JSON(), nullable=True),
        sa.Column('new_value_json', sa.JSON(), nullable=True),
        sa.Column('visibility_scope', sa.String(), nullable=True),
        sa.Column('validation_status', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['transaction_id'], ['turn_transactions.id'], ),
        sa.ForeignKeyConstraint(['source_event_id'], ['game_events.id'], ),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_state_deltas_transaction', 'state_deltas', ['transaction_id'], unique=False)
    op.create_index('idx_state_deltas_session_turn', 'state_deltas', ['session_id', 'turn_no'], unique=False)
    op.create_index('idx_state_deltas_path', 'state_deltas', ['session_id', 'path'], unique=False)
    
    # llm_stage_results: LLM 阶段结果表，记录每个 LLM 调用的详细信息
    op.create_table('llm_stage_results',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('transaction_id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('turn_no', sa.Integer(), nullable=False),
        sa.Column('stage_name', sa.String(), nullable=False),
        sa.Column('provider', sa.String(), nullable=True),
        sa.Column('model', sa.String(), nullable=True),
        sa.Column('prompt_template_id', sa.String(), nullable=True),
        sa.Column('request_payload_ref', sa.String(), nullable=True),
        sa.Column('raw_output_ref', sa.String(), nullable=True),
        sa.Column('parsed_proposal_json', sa.JSON(), nullable=True),
        sa.Column('accepted', sa.Boolean(), nullable=True),
        sa.Column('fallback_reason', sa.String(), nullable=True),
        sa.Column('validation_errors_json', sa.JSON(), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['transaction_id'], ['turn_transactions.id'], ),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
        sa.ForeignKeyConstraint(['prompt_template_id'], ['prompt_templates.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_llm_stage_results_transaction', 'llm_stage_results', ['transaction_id'], unique=False)
    op.create_index('idx_llm_stage_results_session_turn', 'llm_stage_results', ['session_id', 'turn_no'], unique=False)
    op.create_index('idx_llm_stage_results_stage', 'llm_stage_results', ['session_id', 'stage_name'], unique=False)
    
    # validation_reports: 验证报告表，记录验证结果
    op.create_table('validation_reports',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('transaction_id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('turn_no', sa.Integer(), nullable=False),
        sa.Column('scope', sa.String(), nullable=False),
        sa.Column('target_ref_id', sa.String(), nullable=True),
        sa.Column('is_valid', sa.Boolean(), nullable=False),
        sa.Column('errors_json', sa.JSON(), nullable=True),
        sa.Column('warnings_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['transaction_id'], ['turn_transactions.id'], ),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_validation_reports_transaction', 'validation_reports', ['transaction_id'], unique=False)
    op.create_index('idx_validation_reports_session_turn', 'validation_reports', ['session_id', 'turn_no'], unique=False)


def downgrade() -> None:
    """Remove event sourcing tables."""
    op.drop_index('idx_validation_reports_session_turn', table_name='validation_reports')
    op.drop_index('idx_validation_reports_transaction', table_name='validation_reports')
    op.drop_table('validation_reports')
    
    op.drop_index('idx_llm_stage_results_stage', table_name='llm_stage_results')
    op.drop_index('idx_llm_stage_results_session_turn', table_name='llm_stage_results')
    op.drop_index('idx_llm_stage_results_transaction', table_name='llm_stage_results')
    op.drop_table('llm_stage_results')
    
    op.drop_index('idx_state_deltas_path', table_name='state_deltas')
    op.drop_index('idx_state_deltas_session_turn', table_name='state_deltas')
    op.drop_index('idx_state_deltas_transaction', table_name='state_deltas')
    op.drop_table('state_deltas')
    
    op.drop_index('idx_game_events_type', table_name='game_events')
    op.drop_index('idx_game_events_session_turn', table_name='game_events')
    op.drop_index('idx_game_events_transaction', table_name='game_events')
    op.drop_table('game_events')
    
    op.drop_index('idx_turn_transactions_status', table_name='turn_transactions')
    op.drop_index('idx_turn_transactions_session', table_name='turn_transactions')
    op.drop_table('turn_transactions')
