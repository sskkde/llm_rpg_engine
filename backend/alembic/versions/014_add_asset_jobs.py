"""add asset_generation_jobs table

Revision ID: 014
Revises: 013
Create Date: 2026-05-16 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '014'
down_revision: Union[str, Sequence[str], None] = '013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'asset_generation_jobs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('job_id', sa.String(), nullable=False),
        sa.Column('asset_id', sa.String(), nullable=True),
        sa.Column('session_id', sa.String(), nullable=True),
        sa.Column('asset_type', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('provider_name', sa.String(), nullable=True),
        sa.Column('request_json', sa.JSON(), nullable=True),
        sa.Column('cache_key', sa.String(), nullable=True),
        sa.Column('attempt_count', sa.Integer(), nullable=True),
        sa.Column('max_attempts', sa.Integer(), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('last_error_type', sa.String(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('cancelled_at', sa.DateTime(), nullable=True),
        sa.Column('next_retry_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('job_id'),
    )
    op.create_index('idx_jobs_job_id', 'asset_generation_jobs', ['job_id'], unique=False)
    op.create_index('idx_jobs_asset_id', 'asset_generation_jobs', ['asset_id'], unique=False)
    op.create_index('idx_jobs_session_id', 'asset_generation_jobs', ['session_id'], unique=False)
    op.create_index('idx_jobs_asset_type', 'asset_generation_jobs', ['asset_type'], unique=False)
    op.create_index('idx_jobs_status', 'asset_generation_jobs', ['status'], unique=False)
    op.create_index('idx_jobs_provider_name', 'asset_generation_jobs', ['provider_name'], unique=False)
    op.create_index('idx_jobs_cache_key', 'asset_generation_jobs', ['cache_key'], unique=False)
    op.create_index('idx_jobs_session_status', 'asset_generation_jobs', ['session_id', 'status'], unique=False)
    op.create_index('idx_jobs_status_priority', 'asset_generation_jobs', ['status', 'priority'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_jobs_status_priority', table_name='asset_generation_jobs')
    op.drop_index('idx_jobs_session_status', table_name='asset_generation_jobs')
    op.drop_index('idx_jobs_cache_key', table_name='asset_generation_jobs')
    op.drop_index('idx_jobs_provider_name', table_name='asset_generation_jobs')
    op.drop_index('idx_jobs_status', table_name='asset_generation_jobs')
    op.drop_index('idx_jobs_asset_type', table_name='asset_generation_jobs')
    op.drop_index('idx_jobs_session_id', table_name='asset_generation_jobs')
    op.drop_index('idx_jobs_asset_id', table_name='asset_generation_jobs')
    op.drop_index('idx_jobs_job_id', table_name='asset_generation_jobs')
    op.drop_table('asset_generation_jobs')
