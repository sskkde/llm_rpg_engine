"""add story package versions

Revision ID: 018
Revises: 017
Create Date: 2026-05-25 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '018'
down_revision: Union[str, Sequence[str], None] = '017'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'story_package_versions',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('story_package_id', sa.String(), nullable=False),
        sa.Column('version', sa.String(), nullable=False),
        sa.Column('status', sa.String(), server_default='draft'),
        sa.Column('world_id', sa.String(), sa.ForeignKey('worlds.id'), nullable=True),
        sa.Column('manifest_json', sa.JSON(), server_default='{}'),
        sa.Column('editor_schema_version', sa.String(), nullable=True),
        sa.Column('source_hash', sa.String(), nullable=True),
        sa.Column('published_at', sa.DateTime(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint('story_package_id', 'version'),
    )
    op.create_index('idx_spv_story_package_id', 'story_package_versions', ['story_package_id'])
    op.create_index('idx_spv_status', 'story_package_versions', ['status'])


def downgrade() -> None:
    op.drop_index('idx_spv_status', table_name='story_package_versions')
    op.drop_index('idx_spv_story_package_id', table_name='story_package_versions')
    op.drop_table('story_package_versions')
