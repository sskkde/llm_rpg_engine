"""Add custom provider columns to system_settings.

Revision ID: 004
Revises: 003
Create Date: 2026-05-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '004'
down_revision: Union[str, None] = '003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('system_settings', sa.Column('custom_base_url', sa.String(), nullable=True))
    op.add_column('system_settings', sa.Column('custom_api_key_encrypted', sa.Text(), nullable=True))
    op.add_column('system_settings', sa.Column('custom_api_key_last4', sa.String(), nullable=True))
    op.add_column('system_settings', sa.Column('custom_secret_updated_at', sa.DateTime(), nullable=True))
    op.add_column('system_settings', sa.Column('custom_secret_cleared_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('system_settings', 'custom_secret_cleared_at')
    op.drop_column('system_settings', 'custom_secret_updated_at')
    op.drop_column('system_settings', 'custom_api_key_last4')
    op.drop_column('system_settings', 'custom_api_key_encrypted')
    op.drop_column('system_settings', 'custom_base_url')
