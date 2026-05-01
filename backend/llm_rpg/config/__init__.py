"""Configuration and seeding module for LLM RPG Engine."""

from .seeds.world_seed import DEMO_WORLD
from .seeds.locations_seed import DEMO_LOCATIONS
from .seeds.npcs_seed import DEMO_NPCS

__all__ = ["DEMO_WORLD", "DEMO_LOCATIONS", "DEMO_NPCS"]
