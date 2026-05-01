"""Location seed configuration for the demo LLM RPG.

This module defines all locations in the cultivation trial world,
including their descriptions and connections.
"""

from typing import Dict, List

from ...models.states import LocationState
from ...models.lore import LocationLore, LoreCategory


class LocationSeed:
    """Represents a location definition for seeding."""

    def __init__(
        self,
        loc_id: str,
        name: str,
        description: str,
        connections: List[str],
        danger_level: float = 0.0,
        hidden_features: List[str] = None,
    ):
        self.loc_id = loc_id
        self.name = name
        self.description = description
        self.connections = connections
        self.danger_level = danger_level
        self.hidden_features = hidden_features or []


# Demo world locations
DEMO_LOCATIONS: Dict[str, LocationSeed] = {
    "square": LocationSeed(
        loc_id="square",
        name="宗门广场",
        description="你站在宗门的广场上，弟子们正在忙碌准备试炼。",
        connections=["residence", "trial_hall"],
        danger_level=0.0,
    ),
    "residence": LocationSeed(
        loc_id="residence",
        name="外门居所",
        description="简朴的居所散发着淡淡药香，是外门弟子起居之所。",
        connections=["square", "herb_garden"],
        danger_level=0.0,
    ),
    "trial_hall": LocationSeed(
        loc_id="trial_hall",
        name="试炼堂",
        description="高大的试炼堂内悬挂着历代长老的画像，弟子们在此领受试炼任务。",
        connections=["square", "mountain_path"],
        danger_level=0.1,
    ),
    "herb_garden": LocationSeed(
        loc_id="herb_garden",
        name="药园",
        description="药园里种着各类灵草，空气中弥漫着草木清香。",
        connections=["residence", "forest"],
        danger_level=0.0,
    ),
    "library": LocationSeed(
        loc_id="library",
        name="藏经阁外区",
        description="藏经阁外区供外门弟子查阅基础功法，内区对你暂时封闭。",
        connections=["square"],
        danger_level=0.0,
    ),
    "forest": LocationSeed(
        loc_id="forest",
        name="山林试炼区",
        description="这片山林是试炼的主要区域，传说其中藏着秘境入口。",
        connections=["herb_garden", "cliff", "secret_gate"],
        danger_level=0.3,
    ),
    "cliff": LocationSeed(
        loc_id="cliff",
        name="崖边祭坛",
        description="悬崖旁的古老祭坛上刻满阵纹，似乎早已失去灵力。",
        connections=["forest"],
        danger_level=0.4,
        hidden_features=["祭坛下封印着通往秘境的通道"],
    ),
    "secret_gate": LocationSeed(
        loc_id="secret_gate",
        name="秘境入口",
        description="山林深处隐蔽着一处石门，石门缝隙里吹出寒气。",
        connections=["forest", "core"],
        danger_level=0.6,
        hidden_features=["需要特定法器才能完全开启"],
    ),
    "core": LocationSeed(
        loc_id="core",
        name="异变核心",
        description="这是试炼异变的源头，邪气缭绕，令人胆寒。",
        connections=["secret_gate"],
        danger_level=0.9,
        hidden_features=["真正的幕后黑手在此等待"],
    ),
}


def build_location_states() -> Dict[str, LocationState]:
    """Build LocationState objects from seed data."""
    return {
        loc_id: LocationState(
            entity_id=f"loc_{loc_id}",
            location_id=loc_id,
            name=seed.name,
            danger_level=seed.danger_level,
            known_to_player=(loc_id == "square"),  # Player starts at square
        )
        for loc_id, seed in DEMO_LOCATIONS.items()
    }


def build_location_lores() -> Dict[str, LocationLore]:
    """Build LocationLore objects from seed data."""
    lores = {}
    for loc_id, seed in DEMO_LOCATIONS.items():
        lore = LocationLore(
            lore_id=f"lore_loc_{loc_id}",
            title=seed.name,
            location_id=loc_id,
            canonical_content=seed.description,
            public_content=seed.description,
            hidden_features=seed.hidden_features,
            tags=["location", "demo"],
        )
        lores[loc_id] = lore
    return lores


# Connection graph for pathfinding
LOCATION_CONNECTIONS: Dict[str, List[str]] = {
    loc_id: seed.connections for loc_id, seed in DEMO_LOCATIONS.items()
}
