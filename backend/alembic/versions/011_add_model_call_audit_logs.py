"""add model_call_audit_logs table

Revision ID: 011
Revises: 010
Create Date: 2026-05-12 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '011'
down_revision: Union[str, Sequence[str], None] = '010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'model_call_audit_logs',
        sa.Column('call_id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('turn_no', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(), nullable=True),
        sa.Column('model_name', sa.String(), nullable=True),
        sa.Column('prompt_type', sa.String(), nullable=True),
        sa.Column('input_tokens', sa.Integer(), nullable=True),
        sa.Column('output_tokens', sa.Integer(), nullable=True),
        sa.Column('total_tokens', sa.Integer(), nullable=True),
        sa.Column('cost_estimate', sa.Float(), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('success', sa.Boolean(), nullable=True),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('context_build_id', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('call_id'),
    )
    op.create_index('idx_audit_logs_session', 'model_call_audit_logs', ['session_id'], unique=False)
    op.create_index('idx_audit_logs_session_turn', 'model_call_audit_logs', ['session_id', 'turn_no'], unique=False)


def downgrade() -> None:
    op.drop_index('idx_audit_logs_session_turn', table_name='model_call_audit_logs')
    op.drop_index('idx_audit_logs_session', table_name='model_call_audit_logs')
    op.drop_table('model_call_audit_logs')
