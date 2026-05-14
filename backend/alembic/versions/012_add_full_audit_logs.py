"""add full audit logs tables

Revision ID: 012
Revises: 011
Create Date: 2026-05-15 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '012'
down_revision: Union[str, Sequence[str], None] = '011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'proposal_audit_logs',
        sa.Column('audit_id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=True),
        sa.Column('turn_no', sa.Integer(), nullable=False),
        sa.Column('proposal_type', sa.String(), nullable=True),
        sa.Column('payload_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('audit_id'),
    )
    op.create_index('idx_proposal_audit_logs_session', 'proposal_audit_logs', ['session_id'], unique=False)
    op.create_index('idx_proposal_audit_logs_session_turn', 'proposal_audit_logs', ['session_id', 'turn_no'], unique=False)

    op.create_table(
        'context_build_audit_logs',
        sa.Column('build_id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('turn_no', sa.Integer(), nullable=False),
        sa.Column('perspective_type', sa.String(), nullable=True),
        sa.Column('payload_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('build_id'),
    )
    op.create_index('idx_ctx_build_audit_logs_session', 'context_build_audit_logs', ['session_id'], unique=False)
    op.create_index('idx_ctx_build_audit_logs_session_turn', 'context_build_audit_logs', ['session_id', 'turn_no'], unique=False)

    op.create_table(
        'validation_audit_logs',
        sa.Column('validation_id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('turn_no', sa.Integer(), nullable=False),
        sa.Column('validation_type', sa.String(), nullable=True),
        sa.Column('payload_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('validation_id'),
    )
    op.create_index('idx_validation_audit_logs_session', 'validation_audit_logs', ['session_id'], unique=False)
    op.create_index('idx_validation_audit_logs_session_turn', 'validation_audit_logs', ['session_id', 'turn_no'], unique=False)

    op.create_table(
        'turn_audit_logs',
        sa.Column('audit_id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('turn_no', sa.Integer(), nullable=False),
        sa.Column('payload_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('audit_id'),
    )
    op.create_index('idx_turn_audit_logs_session', 'turn_audit_logs', ['session_id'], unique=False)
    op.create_index('idx_turn_audit_logs_session_turn', 'turn_audit_logs', ['session_id', 'turn_no'], unique=False)

    op.create_table(
        'error_audit_logs',
        sa.Column('error_id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=True),
        sa.Column('error_type', sa.String(), nullable=True),
        sa.Column('payload_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('error_id'),
    )
    op.create_index('idx_error_audit_logs_session', 'error_audit_logs', ['session_id'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_error_audit_logs_session', table_name='error_audit_logs')
    op.drop_table('error_audit_logs')

    op.drop_index('idx_turn_audit_logs_session_turn', table_name='turn_audit_logs')
    op.drop_index('idx_turn_audit_logs_session', table_name='turn_audit_logs')
    op.drop_table('turn_audit_logs')

    op.drop_index('idx_validation_audit_logs_session_turn', table_name='validation_audit_logs')
    op.drop_index('idx_validation_audit_logs_session', table_name='validation_audit_logs')
    op.drop_table('validation_audit_logs')

    op.drop_index('idx_ctx_build_audit_logs_session_turn', table_name='context_build_audit_logs')
    op.drop_index('idx_ctx_build_audit_logs_session', table_name='context_build_audit_logs')
    op.drop_table('context_build_audit_logs')

    op.drop_index('idx_proposal_audit_logs_session_turn', table_name='proposal_audit_logs')
    op.drop_index('idx_proposal_audit_logs_session', table_name='proposal_audit_logs')
    op.drop_table('proposal_audit_logs')
