"""add P10-C story editor authoring fields for chapter/item/quest

Revision ID: 024
Revises: 023
Create Date: 2026-05-26 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '024'
down_revision: Union[str, Sequence[str], None] = '023'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ChapterModel: P10-C authoring fields
    op.add_column('chapters', sa.Column('entry_conditions_json', sa.JSON(), nullable=True))
    op.add_column('chapters', sa.Column('exit_conditions_json', sa.JSON(), nullable=True))
    op.add_column('chapters', sa.Column('end_conditions_json', sa.JSON(), nullable=True))
    op.add_column('chapters', sa.Column('timeline_json', sa.JSON(), nullable=True))
    op.add_column('chapters', sa.Column('tags_json', sa.JSON(), nullable=True))
    op.add_column('chapters', sa.Column('schema_json', sa.JSON(), nullable=True))
    op.add_column('chapters', sa.Column('estimated_playtime_minutes', sa.Integer(), nullable=True))

    # ItemTemplateModel: P10-C authoring fields
    op.add_column('item_templates', sa.Column('stackable_flag', sa.Boolean(), nullable=True))
    op.add_column('item_templates', sa.Column('durability_max', sa.Integer(), nullable=True))
    op.add_column('item_templates', sa.Column('equip_slot', sa.String(), nullable=True))
    op.add_column('item_templates', sa.Column('stat_modifiers_json', sa.JSON(), nullable=True))
    op.add_column('item_templates', sa.Column('use_effects_json', sa.JSON(), nullable=True))
    op.add_column('item_templates', sa.Column('ownership_rules_json', sa.JSON(), nullable=True))
    op.add_column('item_templates', sa.Column('visibility_rules_json', sa.JSON(), nullable=True))
    op.add_column('item_templates', sa.Column('price_json', sa.JSON(), nullable=True))
    op.add_column('item_templates', sa.Column('crafting_json', sa.JSON(), nullable=True))
    op.add_column('item_templates', sa.Column('lore_text', sa.Text(), nullable=True))

    # QuestTemplateModel: P10-C authoring fields
    op.add_column('quest_templates', sa.Column('trigger_conditions_json', sa.JSON(), nullable=True))
    op.add_column('quest_templates', sa.Column('availability_conditions_json', sa.JSON(), nullable=True))
    op.add_column('quest_templates', sa.Column('fail_conditions_json', sa.JSON(), nullable=True))
    op.add_column('quest_templates', sa.Column('rewards_json', sa.JSON(), nullable=True))
    op.add_column('quest_templates', sa.Column('branching_json', sa.JSON(), nullable=True))
    op.add_column('quest_templates', sa.Column('deadline_json', sa.JSON(), nullable=True))
    op.add_column('quest_templates', sa.Column('repeatable_flag', sa.Boolean(), nullable=True))
    op.add_column('quest_templates', sa.Column('step_conditions_json', sa.JSON(), nullable=True))


def downgrade() -> None:
    # QuestTemplateModel
    op.drop_column('quest_templates', 'step_conditions_json')
    op.drop_column('quest_templates', 'repeatable_flag')
    op.drop_column('quest_templates', 'deadline_json')
    op.drop_column('quest_templates', 'branching_json')
    op.drop_column('quest_templates', 'rewards_json')
    op.drop_column('quest_templates', 'fail_conditions_json')
    op.drop_column('quest_templates', 'availability_conditions_json')
    op.drop_column('quest_templates', 'trigger_conditions_json')

    # ItemTemplateModel
    op.drop_column('item_templates', 'lore_text')
    op.drop_column('item_templates', 'crafting_json')
    op.drop_column('item_templates', 'price_json')
    op.drop_column('item_templates', 'visibility_rules_json')
    op.drop_column('item_templates', 'ownership_rules_json')
    op.drop_column('item_templates', 'use_effects_json')
    op.drop_column('item_templates', 'stat_modifiers_json')
    op.drop_column('item_templates', 'equip_slot')
    op.drop_column('item_templates', 'durability_max')
    op.drop_column('item_templates', 'stackable_flag')

    # ChapterModel
    op.drop_column('chapters', 'estimated_playtime_minutes')
    op.drop_column('chapters', 'schema_json')
    op.drop_column('chapters', 'tags_json')
    op.drop_column('chapters', 'timeline_json')
    op.drop_column('chapters', 'end_conditions_json')
    op.drop_column('chapters', 'exit_conditions_json')
    op.drop_column('chapters', 'entry_conditions_json')