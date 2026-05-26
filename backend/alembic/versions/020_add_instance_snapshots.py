"""add instance snapshots

Revision ID: 020
Revises: 019
Create Date: 2026-05-25 10:02:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '020'
down_revision: Union[str, Sequence[str], None] = '019'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'instance_snapshots',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('playthrough_instance_id', sa.String(), sa.ForeignKey('playthrough_instances.id'), nullable=False),
        sa.Column('session_id', sa.String(), sa.ForeignKey('sessions.id'), nullable=False),
        sa.Column('snapshot_kind', sa.String(), nullable=False),
        sa.Column('turn_no', sa.Integer(), server_default='0'),
        sa.Column('source_transaction_id', sa.String(), sa.ForeignKey('turn_transactions.id', name='fk_instance_snapshots_source_transaction_id'), nullable=True),
        sa.Column('snapshot_json', sa.JSON(), server_default='{}'),
        sa.Column('checksum', sa.String(), nullable=True),
        sa.Column('parent_snapshot_id', sa.String(), sa.ForeignKey('instance_snapshots.id'), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index('idx_is_playthrough_instance_id', 'instance_snapshots', ['playthrough_instance_id'])
    op.create_index('idx_is_session_id', 'instance_snapshots', ['session_id'])
    op.create_index('idx_is_snapshot_kind', 'instance_snapshots', ['playthrough_instance_id', 'snapshot_kind'])
    op.create_foreign_key(
        'fk_playthrough_instances_baseline_snapshot_id',
        'playthrough_instances',
        'instance_snapshots',
        ['baseline_snapshot_id'],
        ['id'],
    )
    op.create_foreign_key(
        'fk_playthrough_instances_current_snapshot_id',
        'playthrough_instances',
        'instance_snapshots',
        ['current_snapshot_id'],
        ['id'],
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_playthrough_instances_current_snapshot_id',
        'playthrough_instances',
        type_='foreignkey',
    )
    op.drop_constraint(
        'fk_playthrough_instances_baseline_snapshot_id',
        'playthrough_instances',
        type_='foreignkey',
    )
    op.drop_index('idx_is_snapshot_kind', table_name='instance_snapshots')
    op.drop_index('idx_is_session_id', table_name='instance_snapshots')
    op.drop_index('idx_is_playthrough_instance_id', table_name='instance_snapshots')
    op.drop_table('instance_snapshots')
