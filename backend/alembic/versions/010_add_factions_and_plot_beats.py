"""add factions and plot_beats tables

Revision ID: 010
Revises: 009
Create Date: 2026-05-12 11:50:13.289817

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '010'
down_revision: Union[str, Sequence[str], None] = '009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: add factions and plot_beats tables."""
    # Create factions table
    op.create_table(
        'factions',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('logical_id', sa.String(), nullable=False),
        sa.Column('world_id', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('ideology', sa.JSON(), nullable=True),
        sa.Column('goals', sa.JSON(), nullable=True),
        sa.Column('relationships', sa.JSON(), nullable=True),
        sa.Column('visibility', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['world_id'], ['worlds.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('world_id', 'logical_id')
    )
    op.create_index('idx_factions_world', 'factions', ['world_id'], unique=False)

    # Create plot_beats table
    op.create_table(
        'plot_beats',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('logical_id', sa.String(), nullable=False),
        sa.Column('world_id', sa.String(), nullable=False),
        sa.Column('title', sa.String(), nullable=False),
        sa.Column('conditions', sa.JSON(), nullable=True),
        sa.Column('effects', sa.JSON(), nullable=True),
        sa.Column('priority', sa.Integer(), nullable=True),
        sa.Column('visibility', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['world_id'], ['worlds.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('world_id', 'logical_id')
    )
    op.create_index('idx_plot_beats_world', 'plot_beats', ['world_id'], unique=False)
    op.create_index('idx_plot_beats_status', 'plot_beats', ['world_id', 'status'], unique=False)


def downgrade() -> None:
    """Downgrade schema: remove factions and plot_beats tables."""
    op.drop_index('idx_plot_beats_status', table_name='plot_beats')
    op.drop_index('idx_plot_beats_world', table_name='plot_beats')
    op.drop_table('plot_beats')
    op.drop_index('idx_factions_world', table_name='factions')
    op.drop_table('factions')
