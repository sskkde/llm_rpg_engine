"""World seed configuration for the demo LLM RPG.

This module defines the static world metadata for the cultivation trial world.
"""

from typing import Dict, List

from ...models.lore import WorldLore, LoreCategory
from ...models.states import WorldState, WorldTime

# Demo world metadata
DEMO_WORLD_ID = "demo_cultivation_world"
DEMO_WORLD_NAME = "修仙试炼世界"
DEMO_WORLD_DESCRIPTION = "在这个宗门中，你将经历试炼、发现异变并寻找真相。"


class DemoWorldConfig:
    """Static configuration for the demo world."""

    world_id: str = DEMO_WORLD_ID
    name: str = DEMO_WORLD_NAME
    description: str = DEMO_WORLD_DESCRIPTION
    calendar: str = "青岚历"
    starting_season: str = "春"
    starting_day: int = 1
    starting_period: str = "辰时"


def build_demo_world_lore() -> WorldLore:
    """Build the world lore entry for the demo world."""
    return WorldLore(
        lore_id="lore_world_demo",
        title=DEMO_WORLD_NAME,
        canonical_content=DEMO_WORLD_DESCRIPTION,
        public_content="这是一个修仙宗门的试炼之地，外门弟子在此接受考验。",
        tags=["world", "demo", "cultivation"],
        metadata={
            "world_id": DEMO_WORLD_ID,
            "setting_type": "cultivation_sect",
            "theme": "trial_and_discovery",
        },
    )


def build_initial_world_time() -> WorldTime:
    """Build the initial world time for a new game."""
    return WorldTime(
        calendar=DemoWorldConfig.calendar,
        season=DemoWorldConfig.starting_season,
        day=DemoWorldConfig.starting_day,
        period=DemoWorldConfig.starting_period,
    )


# Convenience export
DEMO_WORLD = DemoWorldConfig()
