"""quest journal visibility columns on session_quest_states

Revision ID: 016
Revises: 014
Create Date: 2026-05-23 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '016'
down_revision: Union[str, Sequence[str], None] = '015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Add visibility tracking columns to session_quest_states ---
    op.add_column('session_quest_states', sa.Column('player_visibility', sa.String(20), nullable=True, server_default='hidden'))
    op.add_column('session_quest_states', sa.Column('revealed_at', sa.DateTime(), nullable=True))
    op.add_column('session_quest_states', sa.Column('reveal_source_event_id', sa.String(), nullable=True))
    op.add_column('session_quest_states', sa.Column('last_revealed_step_no', sa.Integer(), nullable=True))

    # --- Data migration: existing active/completed quests become 'discovered' ---
    op.execute(
        "UPDATE session_quest_states SET player_visibility = 'discovered' "
        "WHERE status IN ('active', 'completed')"
    )


def downgrade() -> None:
    # --- Drop visibility tracking columns from session_quest_states ---
    op.drop_column('session_quest_states', 'last_revealed_step_no')
    op.drop_column('session_quest_states', 'reveal_source_event_id')
    op.drop_column('session_quest_states', 'revealed_at')
    op.drop_column('session_quest_states', 'player_visibility')
