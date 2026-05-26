"""add playthrough instances

Revision ID: 019
Revises: 018
Create Date: 2026-05-25 10:01:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '019'
down_revision: Union[str, Sequence[str], None] = '018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'playthrough_instances',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('story_package_version_id', sa.String(), sa.ForeignKey('story_package_versions.id'), nullable=True),
        sa.Column('world_id', sa.String(), sa.ForeignKey('worlds.id'), nullable=False),
        sa.Column('user_id', sa.String(), sa.ForeignKey('users.id'), nullable=True),
        sa.Column('root_session_id', sa.String(), sa.ForeignKey('sessions.id', name='fk_playthrough_instances_root_session_id'), nullable=True),
        sa.Column('baseline_snapshot_id', sa.String(), nullable=True),
        sa.Column('current_snapshot_id', sa.String(), nullable=True),
        sa.Column('current_turn_no', sa.Integer(), server_default='0'),
        sa.Column('instance_status', sa.String(), server_default='active'),
        sa.Column('config_json', sa.JSON(), server_default='{}'),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('idx_pi_world_id', 'playthrough_instances', ['world_id'])
    op.create_index('idx_pi_user_id', 'playthrough_instances', ['user_id'])
    op.create_index('idx_pi_root_session_id', 'playthrough_instances', ['root_session_id'])
    op.create_index('idx_pi_status', 'playthrough_instances', ['instance_status'])


def downgrade() -> None:
    op.drop_index('idx_pi_status', table_name='playthrough_instances')
    op.drop_index('idx_pi_root_session_id', table_name='playthrough_instances')
    op.drop_index('idx_pi_user_id', table_name='playthrough_instances')
    op.drop_index('idx_pi_world_id', table_name='playthrough_instances')
    op.drop_table('playthrough_instances')
