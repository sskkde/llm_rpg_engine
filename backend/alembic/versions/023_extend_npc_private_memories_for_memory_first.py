"""extend npc private memories for memory first

Revision ID: 023
Revises: 022
Create Date: 2026-05-26 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '023'
down_revision: Union[str, Sequence[str], None] = '022'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # NPCPrivateMemoryModel: add first-person / source-bound fields
    op.add_column('npc_private_memories', sa.Column('npc_template_id', sa.String(), nullable=True))
    op.add_column('npc_private_memories', sa.Column('memory_kind', sa.String(), nullable=True))
    op.add_column('npc_private_memories', sa.Column('memory_text', sa.Text(), nullable=True))
    op.add_column('npc_private_memories', sa.Column('short_summary', sa.Text(), nullable=True))
    op.add_column('npc_private_memories', sa.Column('knowledge_source', sa.String(), nullable=True))
    op.add_column('npc_private_memories', sa.Column('source_id', sa.String(), nullable=True))
    op.add_column('npc_private_memories', sa.Column('source_ref', sa.String(), nullable=True))
    op.add_column('npc_private_memories', sa.Column('source_turn_no', sa.Integer(), nullable=True))
    op.add_column('npc_private_memories', sa.Column('salience', sa.Float(), nullable=True))
    op.add_column('npc_private_memories', sa.Column('visibility', sa.String(), nullable=True))
    op.add_column('npc_private_memories', sa.Column('status', sa.String(), nullable=True))
    op.add_column('npc_private_memories', sa.Column('tags_json', sa.JSON(), nullable=True))
    op.add_column('npc_private_memories', sa.Column('entity_refs_json', sa.JSON(), nullable=True))
    op.add_column('npc_private_memories', sa.Column('location_id', sa.String(), nullable=True))
    op.add_column('npc_private_memories', sa.Column('world_time_text', sa.String(), nullable=True))
    op.add_column('npc_private_memories', sa.Column('world_time_json', sa.JSON(), nullable=True))
    op.add_column('npc_private_memories', sa.Column('checksum', sa.String(), nullable=True))
    op.add_column('npc_private_memories', sa.Column('superseded_by', sa.String(), nullable=True))
    op.add_column('npc_private_memories', sa.Column('contradicts_memory_ids_json', sa.JSON(), nullable=True))
    op.add_column('npc_private_memories', sa.Column('recall_policy_json', sa.JSON(), nullable=True))
    op.add_column('npc_private_memories', sa.Column('created_at', sa.DateTime(), nullable=True))
    op.add_column('npc_private_memories', sa.Column('updated_at', sa.DateTime(), nullable=True))

    op.create_foreign_key(
        'fk_npc_private_memories_npc_template_id',
        'npc_private_memories',
        'npc_templates',
        ['npc_template_id'],
        ['id'],
    )
    op.create_foreign_key(
        'fk_npc_private_memories_location_id',
        'npc_private_memories',
        'locations',
        ['location_id'],
        ['id'],
    )
    op.create_index(
        'idx_npc_private_memories_kind_status',
        'npc_private_memories',
        ['session_id', 'npc_id', 'memory_kind', 'status'],
    )
    op.create_index(
        'idx_npc_private_memories_source_turn',
        'npc_private_memories',
        ['session_id', 'npc_id', 'source_turn_no'],
    )

    # NPCMemoryScopeModel: add retrieval bookkeeping fields
    op.add_column('npc_memory_scopes', sa.Column('npc_template_id', sa.String(), nullable=True))
    op.add_column('npc_memory_scopes', sa.Column('latest_summary_id', sa.String(), nullable=True))
    op.add_column('npc_memory_scopes', sa.Column('active_digest_text', sa.Text(), nullable=True))
    op.add_column('npc_memory_scopes', sa.Column('memory_count', sa.Integer(), nullable=True))
    op.add_column('npc_memory_scopes', sa.Column('last_compacted_turn', sa.Integer(), nullable=True))
    op.add_column('npc_memory_scopes', sa.Column('retrieval_profile_json', sa.JSON(), nullable=True))
    op.add_column('npc_memory_scopes', sa.Column('prompt_budget_json', sa.JSON(), nullable=True))

    op.create_foreign_key(
        'fk_npc_memory_scopes_npc_template_id',
        'npc_memory_scopes',
        'npc_templates',
        ['npc_template_id'],
        ['id'],
    )


def downgrade() -> None:
    # NPCMemoryScopeModel
    op.drop_constraint('fk_npc_memory_scopes_npc_template_id', 'npc_memory_scopes', type_='foreignkey')
    op.drop_column('npc_memory_scopes', 'prompt_budget_json')
    op.drop_column('npc_memory_scopes', 'retrieval_profile_json')
    op.drop_column('npc_memory_scopes', 'last_compacted_turn')
    op.drop_column('npc_memory_scopes', 'memory_count')
    op.drop_column('npc_memory_scopes', 'active_digest_text')
    op.drop_column('npc_memory_scopes', 'latest_summary_id')
    op.drop_column('npc_memory_scopes', 'npc_template_id')

    # NPCPrivateMemoryModel
    op.drop_index('idx_npc_private_memories_source_turn', 'npc_private_memories')
    op.drop_index('idx_npc_private_memories_kind_status', 'npc_private_memories')
    op.drop_constraint('fk_npc_private_memories_location_id', 'npc_private_memories', type_='foreignkey')
    op.drop_constraint('fk_npc_private_memories_npc_template_id', 'npc_private_memories', type_='foreignkey')
    op.drop_column('npc_private_memories', 'updated_at')
    op.drop_column('npc_private_memories', 'created_at')
    op.drop_column('npc_private_memories', 'recall_policy_json')
    op.drop_column('npc_private_memories', 'contradicts_memory_ids_json')
    op.drop_column('npc_private_memories', 'superseded_by')
    op.drop_column('npc_private_memories', 'checksum')
    op.drop_column('npc_private_memories', 'world_time_json')
    op.drop_column('npc_private_memories', 'world_time_text')
    op.drop_column('npc_private_memories', 'location_id')
    op.drop_column('npc_private_memories', 'entity_refs_json')
    op.drop_column('npc_private_memories', 'tags_json')
    op.drop_column('npc_private_memories', 'status')
    op.drop_column('npc_private_memories', 'visibility')
    op.drop_column('npc_private_memories', 'salience')
    op.drop_column('npc_private_memories', 'source_turn_no')
    op.drop_column('npc_private_memories', 'source_ref')
    op.drop_column('npc_private_memories', 'source_id')
    op.drop_column('npc_private_memories', 'knowledge_source')
    op.drop_column('npc_private_memories', 'short_summary')
    op.drop_column('npc_private_memories', 'memory_text')
    op.drop_column('npc_private_memories', 'memory_kind')
    op.drop_column('npc_private_memories', 'npc_template_id')
