"""Add nullable phase-4 content_v1 runtime binding fields.

Revision ID: 026
Revises: 025

NULL-compatible uniqueness means multiple NULL rows remain legal on both
SQLite and PostgreSQL. Downgrade is only verified on the dedicated test database.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "026"
down_revision: Union[str, Sequence[str], None] = "025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # StoryPackageVersionModel: nullable content_v1 runtime binding fields.
    op.add_column(
        "story_package_versions",
        sa.Column("runtime_bundle_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "story_package_versions",
        sa.Column("runtime_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "story_package_versions",
        sa.Column("runtime_schema_version", sa.Integer(), nullable=True),
    )

    # SessionInventoryItemModel: nullable content_v1 instance identity.
    op.add_column(
        "session_inventory_items",
        sa.Column("instance_key", sa.String(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_session_inventory_items_session_instance_key",
        "session_inventory_items",
        ["session_id", "instance_key"],
    )

    # NPCPrivateMemoryModel: nullable content_v1 derivation identity.
    op.add_column(
        "npc_private_memories",
        sa.Column("derivation_key", sa.String(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_npc_private_memories_session_npc_derivation",
        "npc_private_memories",
        ["session_id", "npc_id", "derivation_key"],
    )

    # MemoryFactModel: nullable content_v1 provenance and derivation identity.
    op.add_column(
        "memory_facts",
        sa.Column("source_game_event_id", sa.String(), nullable=True),
    )
    op.create_foreign_key(
        "fk_memory_facts_source_game_event_id",
        "memory_facts",
        "game_events",
        ["source_game_event_id"],
        ["id"],
    )
    op.add_column(
        "memory_facts",
        sa.Column("derivation_key", sa.String(), nullable=True),
    )
    op.create_unique_constraint(
        "uq_memory_facts_session_subject_derivation",
        "memory_facts",
        ["session_id", "subject_ref", "derivation_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_memory_facts_session_subject_derivation",
        "memory_facts",
        type_="unique",
    )
    op.drop_column("memory_facts", "derivation_key")
    op.drop_constraint(
        "fk_memory_facts_source_game_event_id",
        "memory_facts",
        type_="foreignkey",
    )
    op.drop_column("memory_facts", "source_game_event_id")

    op.drop_constraint(
        "uq_npc_private_memories_session_npc_derivation",
        "npc_private_memories",
        type_="unique",
    )
    op.drop_column("npc_private_memories", "derivation_key")

    op.drop_constraint(
        "uq_session_inventory_items_session_instance_key",
        "session_inventory_items",
        type_="unique",
    )
    op.drop_column("session_inventory_items", "instance_key")

    op.drop_column("story_package_versions", "runtime_schema_version")
    op.drop_column("story_package_versions", "runtime_hash")
    op.drop_column("story_package_versions", "runtime_bundle_json")
