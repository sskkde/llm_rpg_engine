"""asset runtime production fields + npc_templates.appearance

Revision ID: 015
Revises: 014
Create Date: 2026-05-20 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '015'
down_revision: Union[str, Sequence[str], None] = '014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Add new columns to asset_generation_jobs ---
    op.add_column('asset_generation_jobs', sa.Column('lease_owner', sa.String(), nullable=True))
    op.add_column('asset_generation_jobs', sa.Column('lease_expires_at', sa.DateTime(), nullable=True))
    op.add_column('asset_generation_jobs', sa.Column('heartbeat_at', sa.DateTime(), nullable=True))
    op.add_column('asset_generation_jobs', sa.Column('dead_lettered_at', sa.DateTime(), nullable=True))
    op.add_column('asset_generation_jobs', sa.Column('dead_letter_reason', sa.Text(), nullable=True))
    op.add_column('asset_generation_jobs', sa.Column('provider_request_id', sa.String(), nullable=True))
    op.add_column('asset_generation_jobs', sa.Column('estimated_cost_usd', sa.Float(), nullable=True))
    op.add_column('asset_generation_jobs', sa.Column('actual_cost_usd', sa.Float(), nullable=True))
    op.add_column('asset_generation_jobs', sa.Column('rate_limit_bucket', sa.String(), nullable=True))

    # --- New indexes on asset_generation_jobs ---
    op.create_index('idx_jobs_lease_expires_at', 'asset_generation_jobs', ['lease_expires_at'], unique=False)
    op.create_index('idx_jobs_dead_lettered_at', 'asset_generation_jobs', ['dead_lettered_at'], unique=False)
    op.create_index('idx_jobs_provider_request_id', 'asset_generation_jobs', ['provider_request_id'], unique=False)
    op.create_index('idx_jobs_rate_limit_bucket', 'asset_generation_jobs', ['rate_limit_bucket'], unique=False)

    # --- Create asset_usage_logs table ---
    op.create_table(
        'asset_usage_logs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('usage_id', sa.String(), nullable=False),
        sa.Column('job_id', sa.String(), nullable=True),
        sa.Column('asset_id', sa.String(), nullable=True),
        sa.Column('session_id', sa.String(), nullable=True),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('provider_name', sa.String(), nullable=True),
        sa.Column('asset_type', sa.String(), nullable=True),
        sa.Column('operation', sa.String(), nullable=True),
        sa.Column('input_units', sa.Float(), nullable=True),
        sa.Column('output_units', sa.Float(), nullable=True),
        sa.Column('estimated_cost_usd', sa.Float(), nullable=True),
        sa.Column('actual_cost_usd', sa.Float(), nullable=True),
        sa.Column('currency', sa.String(), nullable=True, server_default='USD'),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('usage_id'),
    )
    op.create_index('idx_asset_usage_session', 'asset_usage_logs', ['session_id'], unique=False)
    op.create_index('idx_asset_usage_user', 'asset_usage_logs', ['user_id'], unique=False)
    op.create_index('idx_asset_usage_provider', 'asset_usage_logs', ['provider_name'], unique=False)
    op.create_index('idx_asset_usage_created_at', 'asset_usage_logs', ['created_at'], unique=False)

    # --- Create asset_rate_limit_events table ---
    op.create_table(
        'asset_rate_limit_events',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('event_id', sa.String(), nullable=False),
        sa.Column('user_id', sa.String(), nullable=True),
        sa.Column('session_id', sa.String(), nullable=True),
        sa.Column('provider_name', sa.String(), nullable=True),
        sa.Column('bucket_key', sa.String(), nullable=True),
        sa.Column('limit_type', sa.String(), nullable=True),
        sa.Column('allowed', sa.Boolean(), nullable=True),
        sa.Column('limit_value', sa.Integer(), nullable=True),
        sa.Column('current_value', sa.Integer(), nullable=True),
        sa.Column('reset_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('event_id'),
    )
    op.create_index('idx_rate_limit_bucket', 'asset_rate_limit_events', ['bucket_key'], unique=False)
    op.create_index('idx_rate_limit_user', 'asset_rate_limit_events', ['user_id'], unique=False)
    op.create_index('idx_rate_limit_created_at', 'asset_rate_limit_events', ['created_at'], unique=False)

    # --- Add appearance column to npc_templates ---
    op.add_column('npc_templates', sa.Column('appearance', sa.Text(), nullable=True))


def downgrade() -> None:
    # --- Remove appearance column from npc_templates ---
    op.drop_column('npc_templates', 'appearance')

    # --- Drop asset_rate_limit_events ---
    op.drop_index('idx_rate_limit_created_at', table_name='asset_rate_limit_events')
    op.drop_index('idx_rate_limit_user', table_name='asset_rate_limit_events')
    op.drop_index('idx_rate_limit_bucket', table_name='asset_rate_limit_events')
    op.drop_table('asset_rate_limit_events')

    # --- Drop asset_usage_logs ---
    op.drop_index('idx_asset_usage_created_at', table_name='asset_usage_logs')
    op.drop_index('idx_asset_usage_provider', table_name='asset_usage_logs')
    op.drop_index('idx_asset_usage_user', table_name='asset_usage_logs')
    op.drop_index('idx_asset_usage_session', table_name='asset_usage_logs')
    op.drop_table('asset_usage_logs')

    # --- Drop new indexes on asset_generation_jobs ---
    op.drop_index('idx_jobs_rate_limit_bucket', table_name='asset_generation_jobs')
    op.drop_index('idx_jobs_provider_request_id', table_name='asset_generation_jobs')
    op.drop_index('idx_jobs_dead_lettered_at', table_name='asset_generation_jobs')
    op.drop_index('idx_jobs_lease_expires_at', table_name='asset_generation_jobs')

    # --- Drop new columns from asset_generation_jobs ---
    op.drop_column('asset_generation_jobs', 'rate_limit_bucket')
    op.drop_column('asset_generation_jobs', 'actual_cost_usd')
    op.drop_column('asset_generation_jobs', 'estimated_cost_usd')
    op.drop_column('asset_generation_jobs', 'provider_request_id')
    op.drop_column('asset_generation_jobs', 'dead_letter_reason')
    op.drop_column('asset_generation_jobs', 'dead_lettered_at')
    op.drop_column('asset_generation_jobs', 'heartbeat_at')
    op.drop_column('asset_generation_jobs', 'lease_expires_at')
    op.drop_column('asset_generation_jobs', 'lease_owner')
