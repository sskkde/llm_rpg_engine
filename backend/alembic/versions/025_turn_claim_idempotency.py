"""Add session-scoped turn idempotency and claim metadata.

Revision ID: 025
Revises: 024
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "025"
down_revision: Union[str, Sequence[str], None] = "024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for constraint in inspector.get_unique_constraints("turn_transactions"):
        if constraint.get("column_names") == ["idempotency_key"]:
            op.drop_constraint(constraint["name"], "turn_transactions", type_="unique")

    op.add_column("turn_transactions", sa.Column("request_fingerprint", sa.String(), nullable=True))
    op.add_column("turn_transactions", sa.Column("lease_expires_at", sa.DateTime(), nullable=True))
    op.add_column("turn_transactions", sa.Column("fencing_generation", sa.Integer(), nullable=True))
    op.add_column("turn_transactions", sa.Column("attempt_history_json", sa.JSON(), nullable=True))
    op.create_unique_constraint(
        "uq_turn_transactions_session_key",
        "turn_transactions",
        ["session_id", "idempotency_key"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    duplicate = bind.execute(
        sa.text(
            "SELECT idempotency_key FROM turn_transactions "
            "GROUP BY idempotency_key HAVING COUNT(DISTINCT session_id) > 1 LIMIT 1"
        )
    ).first()
    if duplicate is not None:
        raise RuntimeError(
            "Cannot downgrade turn idempotency: an idempotency_key is reused across sessions"
        )

    op.drop_constraint("uq_turn_transactions_session_key", "turn_transactions", type_="unique")
    op.create_unique_constraint(
        "uq_turn_transactions_idempotency_key",
        "turn_transactions",
        ["idempotency_key"],
    )
    op.drop_column("turn_transactions", "attempt_history_json")
    op.drop_column("turn_transactions", "fencing_generation")
    op.drop_column("turn_transactions", "lease_expires_at")
    op.drop_column("turn_transactions", "request_fingerprint")
