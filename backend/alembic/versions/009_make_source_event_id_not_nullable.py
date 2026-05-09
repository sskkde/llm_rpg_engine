"""Make state_deltas.source_event_id NOT NULL.

Revision ID: 009
Revises: 008
Create Date: 2026-05-09 00:00:00.000000

This migration:
1. Creates synthetic game_events for any state_deltas with NULL source_event_id
2. Backfills those state_deltas with the synthetic event IDs
3. Makes source_event_id NOT NULL

"""
from typing import Sequence, Union
import uuid
from datetime import datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text


# revision identifiers, used by Alembic.
revision: str = '009'
down_revision: Union[str, Sequence[str], None] = '008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Make source_event_id NOT NULL with synthetic event backfill."""
    
    conn = op.get_bind()
    
    # Step 1: Find all state_deltas with NULL source_event_id
    # Group by transaction_id to create one synthetic event per transaction
    result = conn.execute(text("""
        SELECT DISTINCT sd.transaction_id, sd.session_id, sd.turn_no
        FROM state_deltas sd
        WHERE sd.source_event_id IS NULL
        ORDER BY sd.transaction_id
    """))
    
    null_delta_transactions = result.fetchall()
    
    # Step 2: For each transaction with NULL deltas, create a synthetic game_event
    for row in null_delta_transactions:
        transaction_id = row[0]
        session_id = row[1]
        turn_no = row[2]
        
        # Generate a deterministic UUID for the synthetic event
        # Using transaction_id as seed for reproducibility
        synthetic_event_id = f"synthetic_{transaction_id}"
        
        # Create synthetic game_event with event_type='system_bootstrap'
        conn.execute(text("""
            INSERT INTO game_events (
                id, transaction_id, session_id, turn_no, event_type,
                actor_id, target_ids_json, visibility_scope,
                public_payload_json, private_payload_json, result_json,
                occurred_at
            ) VALUES (
                :event_id, :transaction_id, :session_id, :turn_no, 'system_bootstrap',
                'system', '[]', 'world',
                '{"description": "Synthetic event for historical state deltas"}',
                NULL, NULL, :occurred_at
            )
        """), {
            'event_id': synthetic_event_id,
            'transaction_id': transaction_id,
            'session_id': session_id,
            'turn_no': turn_no,
            'occurred_at': datetime.utcnow()
        })
        
        # Update state_deltas with the synthetic event ID
        conn.execute(text("""
            UPDATE state_deltas
            SET source_event_id = :event_id
            WHERE transaction_id = :transaction_id AND source_event_id IS NULL
        """), {
            'event_id': synthetic_event_id,
            'transaction_id': transaction_id
        })
    
    # Step 3: Drop foreign key constraint temporarily
    op.drop_constraint('state_deltas_source_event_id_fkey', 'state_deltas', type_='foreignkey')
    
    # Step 4: Alter column to NOT NULL
    op.alter_column('state_deltas', 'source_event_id',
                    existing_type=sa.String(),
                    nullable=False)
    
    # Step 5: Re-create foreign key constraint
    op.create_foreign_key('state_deltas_source_event_id_fkey', 'state_deltas', 'game_events', ['source_event_id'], ['id'])


def downgrade() -> None:
    """Revert source_event_id to nullable and remove synthetic events."""
    
    conn = op.get_bind()
    
    # Step 1: Drop foreign key constraint
    op.drop_constraint('state_deltas_source_event_id_fkey', 'state_deltas', type_='foreignkey')
    
    # Step 2: Set synthetic source_event_ids back to NULL
    conn.execute(text("""
        UPDATE state_deltas
        SET source_event_id = NULL
        WHERE source_event_id LIKE 'synthetic_%'
    """))
    
    # Step 3: Delete synthetic game_events
    conn.execute(text("""
        DELETE FROM game_events
        WHERE id LIKE 'synthetic_%'
    """))
    
    # Step 4: Alter column back to nullable
    op.alter_column('state_deltas', 'source_event_id',
                    existing_type=sa.String(),
                    nullable=True)
    
    # Step 5: Re-create foreign key constraint
    op.create_foreign_key('state_deltas_source_event_id_fkey', 'state_deltas', 'game_events', ['source_event_id'], ['id'])
