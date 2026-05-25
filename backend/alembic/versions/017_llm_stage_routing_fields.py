"""llm stage routing fields

Revision ID: 017
Revises: 016
Create Date: 2026-05-24 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '017'
down_revision: Union[str, Sequence[str], None] = '016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- Add routing fields to llm_stage_results ---
    op.add_column('llm_stage_results', sa.Column('provider_mode', sa.String(), nullable=True))
    op.add_column('llm_stage_results', sa.Column('default_model', sa.String(), nullable=True))
    op.add_column('llm_stage_results', sa.Column('config_source', sa.String(), nullable=True))
    op.add_column('llm_stage_results', sa.Column('fallback_used', sa.Boolean(), nullable=True, server_default=None))


def downgrade() -> None:
    # --- Drop routing fields from llm_stage_results ---
    op.drop_column('llm_stage_results', 'fallback_used')
    op.drop_column('llm_stage_results', 'config_source')
    op.drop_column('llm_stage_results', 'default_model')
    op.drop_column('llm_stage_results', 'provider_mode')
