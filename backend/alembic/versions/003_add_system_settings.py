"""Add system_settings table.

Revision ID: 003
Revises: 002
Create Date: 2026-05-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '003'
down_revision: Union[str, None] = '002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('system_settings',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('provider_mode', sa.String(), nullable=False, server_default='auto'),
        sa.Column('default_model', sa.String(), nullable=True),
        sa.Column('temperature', sa.Float(), nullable=False, server_default='0.7'),
        sa.Column('max_tokens', sa.Integer(), nullable=False, server_default='2000'),
        sa.Column('registration_enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('maintenance_mode', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('debug_enabled', sa.Boolean(), nullable=False, server_default='true'),
        sa.Column('openai_api_key_encrypted', sa.Text(), nullable=True),
        sa.Column('openai_api_key_last4', sa.String(), nullable=True),
        sa.Column('secret_updated_at', sa.DateTime(), nullable=True),
        sa.Column('secret_cleared_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('updated_by_user_id', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['updated_by_user_id'], ['users.id'])
    )
    
    op.execute("INSERT INTO system_settings (id, provider_mode, default_model, temperature, max_tokens, registration_enabled, maintenance_mode, debug_enabled) VALUES ('singleton', 'auto', 'gpt-4', 0.7, 2000, true, false, true)")


def downgrade() -> None:
    op.drop_table('system_settings')
