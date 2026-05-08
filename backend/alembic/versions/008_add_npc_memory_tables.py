"""Add NPC memory tables.

Revision ID: 008
Revises: 007
Create Date: 2026-05-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '008'
down_revision: Union[str, Sequence[str], None] = '007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add NPC memory tables for scopes, beliefs, private memories, secrets, and relationship memories."""
    
    # npc_memory_scopes: NPC 记忆范围表，存储每个 NPC 的记忆配置
    op.create_table('npc_memory_scopes',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('npc_id', sa.String(), nullable=False),
        sa.Column('profile_json', sa.JSON(), nullable=True),
        sa.Column('forget_curve_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('session_id', 'npc_id')
    )
    op.create_index('idx_npc_memory_scopes_session', 'npc_memory_scopes', ['session_id'], unique=False)
    op.create_index('idx_npc_memory_scopes_npc', 'npc_memory_scopes', ['session_id', 'npc_id'], unique=False)
    
    # npc_beliefs: NPC 信念表，存储 NPC 对世界的认知和信念
    op.create_table('npc_beliefs',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('npc_id', sa.String(), nullable=False),
        sa.Column('belief_type', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=False, server_default='0.5'),
        sa.Column('truth_status', sa.String(), nullable=False, server_default='unknown'),
        sa.Column('source_event_id', sa.String(), nullable=True),
        sa.Column('created_turn', sa.Integer(), nullable=False),
        sa.Column('last_updated_turn', sa.Integer(), nullable=False),
        sa.Column('embedding', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_npc_beliefs_session', 'npc_beliefs', ['session_id'], unique=False)
    op.create_index('idx_npc_beliefs_npc', 'npc_beliefs', ['session_id', 'npc_id'], unique=False)
    op.create_index('idx_npc_beliefs_type', 'npc_beliefs', ['session_id', 'belief_type'], unique=False)
    
    # npc_private_memories: NPC 私有记忆表，存储 NPC 的个人经历记忆
    op.create_table('npc_private_memories',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('npc_id', sa.String(), nullable=False),
        sa.Column('memory_type', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('source_event_ids_json', sa.JSON(), nullable=True),
        sa.Column('entities_json', sa.JSON(), nullable=True),
        sa.Column('importance', sa.Float(), nullable=False, server_default='0.5'),
        sa.Column('emotional_weight', sa.Float(), nullable=False, server_default='0.0'),
        sa.Column('confidence', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('current_strength', sa.Float(), nullable=False, server_default='1.0'),
        sa.Column('created_turn', sa.Integer(), nullable=False),
        sa.Column('last_accessed_turn', sa.Integer(), nullable=False),
        sa.Column('recall_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('embedding', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_npc_private_memories_session', 'npc_private_memories', ['session_id'], unique=False)
    op.create_index('idx_npc_private_memories_npc', 'npc_private_memories', ['session_id', 'npc_id'], unique=False)
    op.create_index('idx_npc_private_memories_type', 'npc_private_memories', ['session_id', 'memory_type'], unique=False)
    
    # npc_secrets: NPC 秘密表，存储 NPC 隐藏的信息
    op.create_table('npc_secrets',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('npc_id', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('willingness_to_reveal', sa.Float(), nullable=False, server_default='0.1'),
        sa.Column('reveal_conditions_json', sa.JSON(), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='hidden'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_npc_secrets_session', 'npc_secrets', ['session_id'], unique=False)
    op.create_index('idx_npc_secrets_npc', 'npc_secrets', ['session_id', 'npc_id'], unique=False)
    op.create_index('idx_npc_secrets_status', 'npc_secrets', ['session_id', 'status'], unique=False)
    
    # npc_relationship_memories: NPC 关系记忆表，存储 NPC 与其他实体的关系历史
    op.create_table('npc_relationship_memories',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('session_id', sa.String(), nullable=False),
        sa.Column('npc_id', sa.String(), nullable=False),
        sa.Column('target_id', sa.String(), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('impact_json', sa.JSON(), nullable=True),
        sa.Column('source_event_id', sa.String(), nullable=True),
        sa.Column('created_turn', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['sessions.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_npc_relationship_memories_session', 'npc_relationship_memories', ['session_id'], unique=False)
    op.create_index('idx_npc_relationship_memories_npc', 'npc_relationship_memories', ['session_id', 'npc_id'], unique=False)
    op.create_index('idx_npc_relationship_memories_target', 'npc_relationship_memories', ['session_id', 'npc_id', 'target_id'], unique=False)


def downgrade() -> None:
    """Remove NPC memory tables."""
    op.drop_index('idx_npc_relationship_memories_target', table_name='npc_relationship_memories')
    op.drop_index('idx_npc_relationship_memories_npc', table_name='npc_relationship_memories')
    op.drop_index('idx_npc_relationship_memories_session', table_name='npc_relationship_memories')
    op.drop_table('npc_relationship_memories')
    
    op.drop_index('idx_npc_secrets_status', table_name='npc_secrets')
    op.drop_index('idx_npc_secrets_npc', table_name='npc_secrets')
    op.drop_index('idx_npc_secrets_session', table_name='npc_secrets')
    op.drop_table('npc_secrets')
    
    op.drop_index('idx_npc_private_memories_type', table_name='npc_private_memories')
    op.drop_index('idx_npc_private_memories_npc', table_name='npc_private_memories')
    op.drop_index('idx_npc_private_memories_session', table_name='npc_private_memories')
    op.drop_table('npc_private_memories')
    
    op.drop_index('idx_npc_beliefs_type', table_name='npc_beliefs')
    op.drop_index('idx_npc_beliefs_npc', table_name='npc_beliefs')
    op.drop_index('idx_npc_beliefs_session', table_name='npc_beliefs')
    op.drop_table('npc_beliefs')
    
    op.drop_index('idx_npc_memory_scopes_npc', table_name='npc_memory_scopes')
    op.drop_index('idx_npc_memory_scopes_session', table_name='npc_memory_scopes')
    op.drop_table('npc_memory_scopes')
