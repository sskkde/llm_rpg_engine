"""Add is_admin column to users table.

Revision ID: 002
Revises: 001
Create Date: 2026-05-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('is_admin', sa.Boolean(), nullable=False, server_default='false'))
    
    op.execute("UPDATE users SET is_admin = true WHERE username = 'admin'")


def downgrade() -> None:
    op.drop_column('users', 'is_admin')
