"""add p10c session and npc columns

Revision ID: 021
Revises: 020
Create Date: 2026-05-25 10:03:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '021'
down_revision: Union[str, Sequence[str], None] = '020'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('sessions', sa.Column('playthrough_instance_id', sa.String(), nullable=True))
    op.add_column('sessions', sa.Column('story_package_version_id', sa.String(), nullable=True))
    op.add_column('sessions', sa.Column('entry_snapshot_id', sa.String(), nullable=True))
    op.add_column('sessions', sa.Column('resume_snapshot_id', sa.String(), nullable=True))
    op.add_column('sessions', sa.Column('session_type', sa.String(), nullable=True))
    op.add_column('sessions', sa.Column('runtime_status', sa.String(), nullable=True))
    op.add_column('npc_templates', sa.Column('is_major_npc', sa.Boolean(), nullable=True))
    op.add_column('npc_templates', sa.Column('memory_profile_json', sa.JSON(), nullable=True))
    op.add_column('npc_templates', sa.Column('seed_memory_bundle_json', sa.JSON(), nullable=True))
    op.create_foreign_key(
        'fk_sessions_playthrough_instance_id',
        'sessions',
        'playthrough_instances',
        ['playthrough_instance_id'],
        ['id'],
    )
    op.create_foreign_key(
        'fk_sessions_story_package_version_id',
        'sessions',
        'story_package_versions',
        ['story_package_version_id'],
        ['id'],
    )
    op.create_foreign_key(
        'fk_sessions_entry_snapshot_id',
        'sessions',
        'instance_snapshots',
        ['entry_snapshot_id'],
        ['id'],
    )
    op.create_foreign_key(
        'fk_sessions_resume_snapshot_id',
        'sessions',
        'instance_snapshots',
        ['resume_snapshot_id'],
        ['id'],
    )


def downgrade() -> None:
    op.drop_constraint('fk_sessions_resume_snapshot_id', 'sessions', type_='foreignkey')
    op.drop_constraint('fk_sessions_entry_snapshot_id', 'sessions', type_='foreignkey')
    op.drop_constraint('fk_sessions_story_package_version_id', 'sessions', type_='foreignkey')
    op.drop_constraint('fk_sessions_playthrough_instance_id', 'sessions', type_='foreignkey')
    op.drop_column('npc_templates', 'seed_memory_bundle_json')
    op.drop_column('npc_templates', 'memory_profile_json')
    op.drop_column('npc_templates', 'is_major_npc')
    op.drop_column('sessions', 'runtime_status')
    op.drop_column('sessions', 'session_type')
    op.drop_column('sessions', 'resume_snapshot_id')
    op.drop_column('sessions', 'entry_snapshot_id')
    op.drop_column('sessions', 'story_package_version_id')
    op.drop_column('sessions', 'playthrough_instance_id')
