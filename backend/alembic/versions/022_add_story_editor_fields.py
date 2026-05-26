"""add story editor fields

Revision ID: 022
Revises: 021
Create Date: 2026-05-26 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '022'
down_revision: Union[str, Sequence[str], None] = '021'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # WorldModel editor fields
    op.add_column('worlds', sa.Column('story_package_version_id', sa.String(), nullable=True))
    op.add_column('worlds', sa.Column('world_book_json', sa.JSON(), nullable=True))
    op.add_column('worlds', sa.Column('calendar_json', sa.JSON(), nullable=True))
    op.add_column('worlds', sa.Column('ruleset_json', sa.JSON(), nullable=True))
    op.add_column('worlds', sa.Column('starter_location_id', sa.String(), nullable=True))
    op.add_column('worlds', sa.Column('editor_metadata_json', sa.JSON(), nullable=True))
    op.create_foreign_key(
        'fk_worlds_story_package_version_id',
        'worlds',
        'story_package_versions',
        ['story_package_version_id'],
        ['id'],
    )
    op.create_foreign_key(
        'fk_worlds_starter_location_id',
        'worlds',
        'locations',
        ['starter_location_id'],
        ['id'],
    )

    # LocationModel editor fields
    op.add_column('locations', sa.Column('parent_location_id', sa.String(), nullable=True))
    op.add_column('locations', sa.Column('location_type', sa.String(), nullable=True))
    op.add_column('locations', sa.Column('environment_json', sa.JSON(), nullable=True))
    op.add_column('locations', sa.Column('discovery_rules_json', sa.JSON(), nullable=True))
    op.add_column('locations', sa.Column('scene_hooks_json', sa.JSON(), nullable=True))
    op.create_foreign_key(
        'fk_locations_parent_location_id',
        'locations',
        'locations',
        ['parent_location_id'],
        ['id'],
    )

    # NPCTemplateModel editor fields
    op.add_column('npc_templates', sa.Column('appearance_json', sa.JSON(), nullable=True))
    op.add_column('npc_templates', sa.Column('body_features_json', sa.JSON(), nullable=True))
    op.add_column('npc_templates', sa.Column('baseline_stats_json', sa.JSON(), nullable=True))
    op.add_column('npc_templates', sa.Column('speech_profile_json', sa.JSON(), nullable=True))
    op.add_column('npc_templates', sa.Column('personality_traits_json', sa.JSON(), nullable=True))
    op.add_column('npc_templates', sa.Column('background_bio', sa.Text(), nullable=True))
    op.add_column('npc_templates', sa.Column('decision_profile_json', sa.JSON(), nullable=True))
    op.add_column('npc_templates', sa.Column('initial_location_id', sa.String(), nullable=True))
    op.add_column('npc_templates', sa.Column('faction_id', sa.String(), nullable=True))
    op.add_column('npc_templates', sa.Column('portrait_asset_id', sa.String(), nullable=True))
    op.create_foreign_key(
        'fk_npc_templates_initial_location_id',
        'npc_templates',
        'locations',
        ['initial_location_id'],
        ['id'],
    )
    op.create_foreign_key(
        'fk_npc_templates_faction_id',
        'npc_templates',
        'factions',
        ['faction_id'],
        ['id'],
    )

    # EventTemplateModel editor fields
    op.add_column('event_templates', sa.Column('npc_memory_write_policy_json', sa.JSON(), nullable=True))
    op.add_column('event_templates', sa.Column('reveal_rules_json', sa.JSON(), nullable=True))

    # PromptTemplateModel editor fields
    op.add_column('prompt_templates', sa.Column('editor_notes', sa.Text(), nullable=True))
    op.add_column('prompt_templates', sa.Column('variable_schema_json', sa.JSON(), nullable=True))


def downgrade() -> None:
    # PromptTemplateModel
    op.drop_column('prompt_templates', 'variable_schema_json')
    op.drop_column('prompt_templates', 'editor_notes')

    # EventTemplateModel
    op.drop_column('event_templates', 'reveal_rules_json')
    op.drop_column('event_templates', 'npc_memory_write_policy_json')

    # NPCTemplateModel
    op.drop_constraint('fk_npc_templates_faction_id', 'npc_templates', type_='foreignkey')
    op.drop_constraint('fk_npc_templates_initial_location_id', 'npc_templates', type_='foreignkey')
    op.drop_column('npc_templates', 'portrait_asset_id')
    op.drop_column('npc_templates', 'faction_id')
    op.drop_column('npc_templates', 'initial_location_id')
    op.drop_column('npc_templates', 'decision_profile_json')
    op.drop_column('npc_templates', 'background_bio')
    op.drop_column('npc_templates', 'personality_traits_json')
    op.drop_column('npc_templates', 'speech_profile_json')
    op.drop_column('npc_templates', 'baseline_stats_json')
    op.drop_column('npc_templates', 'body_features_json')
    op.drop_column('npc_templates', 'appearance_json')

    # LocationModel
    op.drop_constraint('fk_locations_parent_location_id', 'locations', type_='foreignkey')
    op.drop_column('locations', 'scene_hooks_json')
    op.drop_column('locations', 'discovery_rules_json')
    op.drop_column('locations', 'environment_json')
    op.drop_column('locations', 'location_type')
    op.drop_column('locations', 'parent_location_id')

    # WorldModel
    op.drop_constraint('fk_worlds_starter_location_id', 'worlds', type_='foreignkey')
    op.drop_constraint('fk_worlds_story_package_version_id', 'worlds', type_='foreignkey')
    op.drop_column('worlds', 'editor_metadata_json')
    op.drop_column('worlds', 'starter_location_id')
    op.drop_column('worlds', 'ruleset_json')
    op.drop_column('worlds', 'calendar_json')
    op.drop_column('worlds', 'world_book_json')
    op.drop_column('worlds', 'story_package_version_id')
