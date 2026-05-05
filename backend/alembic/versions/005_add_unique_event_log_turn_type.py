"""Add unique constraint on event_logs(session_id, turn_no, event_type).

Revision ID: 005
Revises: 004
Create Date: 2026-05-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '005'
down_revision: Union[str, None] = '004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        'uq_event_logs_session_turn_type',
        'event_logs',
        ['session_id', 'turn_no', 'event_type'],
        unique=True
    )


def downgrade() -> None:
    op.drop_index('uq_event_logs_session_turn_type', table_name='event_logs')
