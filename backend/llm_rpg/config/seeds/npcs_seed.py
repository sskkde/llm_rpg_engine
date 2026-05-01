"""NPC seed configuration for the demo LLM RPG.

This module defines all NPCs in the cultivation trial world,
including their personalities, roles, and secrets.
"""

from typing import Dict, List

from ...models.memories import NPCProfile, NPCMemoryScope, MemoryType
from ...models.states import NPCState
from ...models.lore import CharacterLore, LoreCategory


class NPCSeed:
    """Represents an NPC definition for seeding."""

    def __init__(
        self,
        npc_id: str,
        name: str,
        surface_role: str,
        secret_role: str,
        personality: str,
        starting_location: str,
        trust_toward_player: float = 0.5,
        secrets: List[str] = None,
    ):
        self.npc_id = npc_id
        self.name = name
        self.surface_role = surface_role
        self.secret_role = secret_role
        self.personality = personality
        self.starting_location = starting_location
        self.trust_toward_player = trust_toward_player
        self.secrets = secrets or []


# Demo world NPCs
DEMO_NPCS: Dict[str, NPCSeed] = {
    "senior_sister": NPCSeed(
        npc_id="senior_sister",
        name="柳师姐",
        surface_role="外门师姐",
        secret_role="内门使者",
        personality="温和而略带谨慎，喜欢指点新弟子。",
        starting_location="square",
        trust_toward_player=0.7,
        secrets=["知道一些关于试炼的秘密，但不能直接告诉弟子"],
    ),
    "male_competitor": NPCSeed(
        npc_id="male_competitor",
        name="江程",
        surface_role="同期弟子",
        secret_role="潜在盟友",
        personality="自负但讲义气，擅长剑术。",
        starting_location="residence",
        trust_toward_player=0.4,
    ),
    "female_competitor": NPCSeed(
        npc_id="female_competitor",
        name="林菲",
        surface_role="同期弟子",
        secret_role="潜在盟友",
        personality="聪明而冷静，喜欢独自行动。",
        starting_location="herb_garden",
        trust_toward_player=0.5,
    ),
    "mysterious": NPCSeed(
        npc_id="mysterious",
        name="神秘人",
        surface_role="流浪修士",
        secret_role="知晓真相的引导者",
        personality="说话模糊，喜欢用谜语提醒他人。",
        starting_location="forest",
        trust_toward_player=0.3,
        secrets=["知道异变的真相", "知道如何进入秘境核心"],
    ),
    "elder": NPCSeed(
        npc_id="elder",
        name="李长老",
        surface_role="试炼长老",
        secret_role="幕后黑手",
        personality="威严且沉默，隐藏真实目的。",
        starting_location="trial_hall",
        trust_toward_player=0.2,
        secrets=["策划了试炼异变", "想要利用弟子们达成某种目的"],
    ),
    "master": NPCSeed(
        npc_id="master",
        name="清玄上人",
        surface_role="宗门护法",
        secret_role="护道者",
        personality="慈祥中透露出深不可测的气息。",
        starting_location="square",
        trust_toward_player=0.8,
        secrets=["一直在暗中观察试炼", "知道李长老的计划"],
    ),
}


def build_npc_profiles() -> Dict[str, NPCProfile]:
    """Build NPCProfile objects from seed data."""
    return {
        npc_id: NPCProfile(
            npc_id=npc_id,
            name=seed.name,
            public_identity=seed.surface_role,
            true_identity=seed.secret_role,
            personality_summary=seed.personality,
            known_facts=[],
            knowledge_level="outsider",
        )
        for npc_id, seed in DEMO_NPCS.items()
    }


def build_npc_states() -> Dict[str, NPCState]:
    """Build NPCState objects from seed data."""
    from ...models.states import MentalState
    
    return {
        npc_id: NPCState(
            entity_id=f"npc_{npc_id}",
            npc_id=npc_id,
            name=seed.name,
            location_id=seed.starting_location,
            mental_state=MentalState(
                trust_toward_player=seed.trust_toward_player,
            ),
        )
        for npc_id, seed in DEMO_NPCS.items()
    }


def build_npc_lores() -> Dict[str, CharacterLore]:
    """Build CharacterLore objects from seed data."""
    lores = {}
    for npc_id, seed in DEMO_NPCS.items():
        lore = CharacterLore(
            lore_id=f"lore_npc_{npc_id}",
            title=seed.name,
            character_id=npc_id,
            true_identity=seed.secret_role,
            background_story=seed.personality,
            secrets=seed.secrets,
            tags=["character", "npc", "demo"],
        )
        lores[npc_id] = lore
    return lores


# Dialogue hints for narrative generation (extracted from legacy app.py)
NPC_DIALOGUE_HINTS: Dict[str, str] = {
    "senior_sister": "柳师姐微笑着为你解释试炼规则，并叮嘱你要小心行事。",
    "male_competitor": "江程挑衅地看着你，说以后可别拖他的后腿。",
    "female_competitor": "林菲目光清冷，对你的问题只是点头示意。",
    "mysterious": "神秘人低声说道：'山林深处埋藏着真相，也埋藏着危险。'",
    "elder": "李长老沉默不语，只是让你尽快通过试炼。",
    "master": "清玄上人慈祥地问候你，并叮嘱你专心修行。",
}


def get_npc_dialogue_hint(npc_id: str) -> str:
    """Get a dialogue hint for an NPC."""
    return NPC_DIALOGUE_HINTS.get(
        npc_id,
        f"{DEMO_NPCS.get(npc_id, NPCSeed('', '某人', '', '', '', '')).name}没有什么特别想说的。"
    )
