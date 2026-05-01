"""World seeding data for the LLM RPG Engine demo.

This module contains the static world configuration extracted from the legacy app.py.
These seeds define the initial state of the demo world including locations, NPCs,
and world metadata.
"""

from .world_seed import DEMO_WORLD
from .locations_seed import DEMO_LOCATIONS, build_location_states
from .npcs_seed import DEMO_NPCS, build_npc_profiles, build_npc_states

__all__ = [
    "DEMO_WORLD",
    "DEMO_LOCATIONS",
    "DEMO_NPCS",
    "build_location_states",
    "build_npc_profiles",
    "build_npc_states",
]
