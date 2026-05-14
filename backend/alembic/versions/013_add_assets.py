"""add assets table

Revision ID: 013
Revises: 011
Create Date: 2026-05-15 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '013'
down_revision: Union[str, Sequence[str], None] = '012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'assets',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('asset_id', sa.String(), nullable=False),
        sa.Column('asset_type', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('owner_entity_id', sa.String(), nullable=True),
        sa.Column('owner_entity_type', sa.String(), nullable=True),
        sa.Column('session_id', sa.String(), nullable=True),
        sa.Column('world_id', sa.String(), nullable=True),
        sa.Column('scene_id', sa.String(), nullable=True),
        sa.Column('provider_name', sa.String(), nullable=True),
        sa.Column('request_params', sa.JSON(), nullable=True),
        sa.Column('cache_key', sa.String(), nullable=True),
        sa.Column('result_url', sa.String(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('asset_id'),
        sa.UniqueConstraint('cache_key'),
    )
    op.create_index('idx_assets_asset_id', 'assets', ['asset_id'], unique=False)
    op.create_index('idx_assets_asset_type', 'assets', ['asset_type'], unique=False)
    op.create_index('idx_assets_status', 'assets', ['status'], unique=False)
    op.create_index('idx_assets_owner_entity_id', 'assets', ['owner_entity_id'], unique=False)
    op.create_index('idx_assets_session_id', 'assets', ['session_id'], unique=False)
    op.create_index('idx_assets_world_id', 'assets', ['world_id'], unique=False)
    op.create_index('idx_assets_scene_id', 'assets', ['scene_id'], unique=False)
    op.create_index('idx_assets_cache_key', 'assets', ['cache_key'], unique=False)
    op.create_index('idx_assets_session_type', 'assets', ['session_id', 'asset_type'], unique=False)
    op.create_index('idx_assets_owner', 'assets', ['owner_entity_id', 'owner_entity_type'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_assets_owner', table_name='assets')
    op.drop_index('idx_assets_session_type', table_name='assets')
    op.drop_index('idx_assets_cache_key', table_name='assets')
    op.drop_index('idx_assets_scene_id', table_name='assets')
    op.drop_index('idx_assets_world_id', table_name='assets')
    op.drop_index('idx_assets_session_id', table_name='assets')
    op.drop_index('idx_assets_owner_entity_id', table_name='assets')
    op.drop_index('idx_assets_status', table_name='assets')
    op.drop_index('idx_assets_asset_type', table_name='assets')
    op.drop_index('idx_assets_asset_id', table_name='assets')
    op.drop_table('assets')
