#!/usr/bin/env python3
"""
Deterministic content seeding script for the LLM RPG Engine.

This script populates the database with documented world content:
- 1 world
- 3 chapters
- 5+ core NPC templates
- 10 locations/scenes
- Quests/steps
- Event templates
- Prompt templates
- Items
- 3 endings

Usage:
    cd backend && python -m llm_rpg.scripts.seed_content
    
The script is idempotent - running it multiple times will not create duplicates.
"""

import os
import sys
from datetime import datetime
from typing import Dict, List, Optional

# Add backend to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base, DATABASE_URL
from llm_rpg.storage.repositories import (
    WorldRepository,
    ChapterRepository,
    LocationRepository,
    NPCTemplateRepository,
    ItemTemplateRepository,
    QuestTemplateRepository,
    QuestStepRepository,
    EventTemplateRepository,
    PromptTemplateRepository,
)


# =============================================================================
# World Configuration
# =============================================================================

WORLD_CONFIG = {
    "code": "cultivation_trial_world",
    "name": "修仙试炼世界",
    "genre": "xianxia",
    "lore_summary": "在这个宗门中，你将经历试炼、发现异变并寻找真相。",
    "status": "active",
}

# =============================================================================
# Chapter Configuration (3 chapters)
# =============================================================================

CHAPTERS_CONFIG = [
    {
        "chapter_no": 1,
        "name": "初入宗门",
        "summary": "作为外门弟子初入宗门，了解试炼规则，结识同门师兄弟姐妹。",
        "start_conditions": {
            "player_realm": "炼气一层",
            "starting_location": "square",
            "intro_event": "welcome_to_sect",
        },
    },
    {
        "chapter_no": 2,
        "name": "异变初现",
        "summary": "试炼过程中发现异常，山林深处出现邪气，需要调查真相。",
        "start_conditions": {
            "required_quest_completed": "first_trial",
            "trigger_event": "strange_occurrence",
            "unlock_location": "secret_gate",
        },
    },
    {
        "chapter_no": 3,
        "name": "真相揭露",
        "summary": "深入秘境核心，揭露幕后黑手，决定宗门命运。",
        "start_conditions": {
            "required_quest_completed": "investigate_anomaly",
            "trigger_event": "confrontation",
            "unlock_location": "core",
        },
    },
]

# =============================================================================
# Location Configuration (10 locations/scenes)
# =============================================================================

LOCATIONS_CONFIG = [
    {
        "code": "square",
        "name": "宗门广场",
        "chapter_no": 1,
        "tags": ["public", "safe", "starting_point"],
        "description": "你站在宗门的广场上，弟子们正在忙碌准备试炼。广场中央矗立着一座古老的石碑，上面记载着宗门的历史。",
        "access_rules": {"always_accessible": True},
    },
    {
        "code": "residence",
        "name": "外门居所",
        "chapter_no": 1,
        "tags": ["private", "safe", "rest"],
        "description": "简朴的居所散发着淡淡药香，是外门弟子起居之所。这里可以恢复体力，整理装备。",
        "access_rules": {"player_level": "outer_disciple"},
    },
    {
        "code": "trial_hall",
        "name": "试炼堂",
        "chapter_no": 1,
        "tags": ["public", "quest_hub", "danger_low"],
        "description": "高大的试炼堂内悬挂着历代长老的画像，弟子们在此领受试炼任务。空气中弥漫着庄严的气息。",
        "access_rules": {"time_restrictions": "daytime_only"},
    },
    {
        "code": "herb_garden",
        "name": "药园",
        "chapter_no": 1,
        "tags": ["gathering", "resource", "safe"],
        "description": "药园里种着各类灵草，空气中弥漫着草木清香。弟子们可以在此采集草药用于修炼。",
        "access_rules": {"quest_requirement": None},
    },
    {
        "code": "library",
        "name": "藏经阁外区",
        "chapter_no": 1,
        "tags": ["knowledge", "lore", "safe"],
        "description": "藏经阁外区供外门弟子查阅基础功法，内区对你暂时封闭。书架上陈列着众多古籍。",
        "access_rules": {"player_level": "outer_disciple", "inner_restricted": True},
    },
    {
        "code": "forest",
        "name": "山林试炼区",
        "chapter_no": 1,
        "tags": ["combat", "exploration", "danger_medium"],
        "description": "这片山林是试炼的主要区域，传说其中藏着秘境入口。密林深处偶尔传来奇怪的声音。",
        "access_rules": {"combat_level": "apprentice"},
    },
    {
        "code": "cliff",
        "name": "崖边祭坛",
        "chapter_no": 2,
        "tags": ["mystery", "danger_medium", "hidden"],
        "description": "悬崖旁的古老祭坛上刻满阵纹，似乎早已失去灵力。但最近有弟子报告这里散发着诡异的气息。",
        "access_rules": {"quest_trigger": "strange_occurrence"},
    },
    {
        "code": "secret_gate",
        "name": "秘境入口",
        "chapter_no": 2,
        "tags": ["dungeon", "danger_high", "key_location"],
        "description": "山林深处隐蔽着一处石门，石门缝隙里吹出寒气。这里是通往异变核心的入口。",
        "access_rules": {"item_required": "gate_key", "quest_completed": "investigate_anomaly"},
    },
    {
        "code": "core",
        "name": "异变核心",
        "chapter_no": 3,
        "tags": ["boss_area", "danger_extreme", "finale"],
        "description": "这是试炼异变的源头，邪气缭绕，令人胆寒。幕后黑手就在这里等待着你。",
        "access_rules": {"chapter": 3, "boss_unlocked": True},
    },
    {
        "code": "inner_library",
        "name": "藏经阁内区",
        "chapter_no": 3,
        "tags": ["knowledge", "secret", "safe"],
        "description": "只有通过内门考核的弟子才能进入的区域，藏有宗门最高深的功法秘籍。",
        "access_rules": {"player_level": "inner_disciple", "chapter": 3},
    },
]

# =============================================================================
# NPC Configuration (6 core NPCs)
# =============================================================================

NPCS_CONFIG = [
    {
        "code": "senior_sister",
        "name": "柳师姐",
        "role_type": "guide",
        "public_identity": "外门师姐",
        "hidden_identity": "内门使者",
        "personality": "温和而略带谨慎，喜欢指点新弟子。对宗门事务了解颇深，但总是有所保留。",
        "speech_style": "温婉有礼，时常引用宗门规矩",
        "goals": ["帮助新弟子适应宗门", "观察有潜力的弟子", "维护宗门秩序"],
    },
    {
        "code": "male_competitor",
        "name": "江程",
        "role_type": "rival",
        "public_identity": "同期弟子",
        "hidden_identity": "潜在盟友",
        "personality": "自负但讲义气，擅长剑术。表面上与你竞争，但在关键时刻会伸出援手。",
        "speech_style": "直率豪爽，带有些许傲气",
        "goals": ["成为内门弟子", "证明自己的实力", "找到真正的对手"],
    },
    {
        "code": "female_competitor",
        "name": "林菲",
        "role_type": "rival",
        "public_identity": "同期弟子",
        "hidden_identity": "潜在盟友",
        "personality": "聪明而冷静，喜欢独自行动。心思缜密，对宗门中的异常现象保持警惕。",
        "speech_style": "简洁冷淡，但每句话都经过深思熟虑",
        "goals": ["调查宗门异变", "保护重要的人", "揭开隐藏的秘密"],
    },
    {
        "code": "mysterious",
        "name": "神秘人",
        "role_type": "mystery",
        "public_identity": "流浪修士",
        "hidden_identity": "知晓真相的引导者",
        "personality": "说话模糊，喜欢用谜语提醒他人。似乎知道宗门异变的真相，但不愿直接透露。",
        "speech_style": "神秘莫测，常用比喻和暗示",
        "goals": ["引导有缘人发现真相", "对抗幕后黑手", "保护无辜者"],
    },
    {
        "code": "elder",
        "name": "李长老",
        "role_type": "antagonist",
        "public_identity": "试炼长老",
        "hidden_identity": "幕后黑手",
        "personality": "威严且沉默，隐藏真实目的。表面上主持试炼，实际上策划了异变。",
        "speech_style": "严肃冷淡，命令式语气",
        "goals": ["利用弟子达成邪恶目的", "掌控宗门", "获得禁忌力量"],
    },
    {
        "code": "master",
        "name": "清玄上人",
        "role_type": "mentor",
        "public_identity": "宗门护法",
        "hidden_identity": "护道者",
        "personality": "慈祥中透露出深不可测的气息。一直在暗中观察试炼，保护有潜力的弟子。",
        "speech_style": "睿智温和，充满人生哲理",
        "goals": ["保护宗门传承", "培养优秀弟子", "对抗邪恶势力"],
    },
]

# =============================================================================
# Item Configuration
# =============================================================================

ITEMS_CONFIG = [
    {
        "code": "spirit_stone",
        "name": "灵石",
        "item_type": "currency",
        "rarity": "common",
        "effects_json": {"spirit_power_restore": 10},
        "description": "修仙界通用的货币，也可用于恢复少量灵力。",
    },
    {
        "code": "healing_herb",
        "name": "回春草",
        "item_type": "consumable",
        "rarity": "common",
        "effects_json": {"hp_restore": 20},
        "description": "药园中采集的常见草药，可用于治疗轻伤。",
    },
    {
        "code": "gate_key",
        "name": "秘境钥匙",
        "item_type": "key",
        "rarity": "rare",
        "effects_json": {"unlock_location": "secret_gate"},
        "description": "一把古老的钥匙，可以打开通往秘境的石门。",
    },
    {
        "code": "sect_badge",
        "name": "宗门令牌",
        "item_type": "equipment",
        "rarity": "uncommon",
        "effects_json": {"identity_proof": True, "defense_bonus": 5},
        "description": "外门弟子的身份标识，同时也是一件防护法器。",
    },
    {
        "code": "ancient_scroll",
        "name": "上古残卷",
        "item_type": "lore",
        "rarity": "epic",
        "effects_json": {"reveal_secret": "cliff_altar_truth"},
        "description": "从藏经阁深处发现的残破卷轴，记载着关于祭坛的秘密。",
    },
    {
        "code": "trial_sword",
        "name": "试炼剑",
        "item_type": "weapon",
        "rarity": "common",
        "effects_json": {"attack_bonus": 10, "durability": 100},
        "description": "宗门配发给外门弟子的制式长剑，锋利耐用。",
    },
    {
        "code": "spirit_pill",
        "name": "聚灵丹",
        "item_type": "consumable",
        "rarity": "uncommon",
        "effects_json": {"spirit_power_restore": 50, "realm_progress": 5},
        "description": "用多种灵草炼制的丹药，可以恢复大量灵力并辅助修炼。",
    },
]

# =============================================================================
# Quest Configuration with Steps
# =============================================================================

QUESTS_CONFIG = [
    {
        "code": "first_trial",
        "name": "初次试炼",
        "quest_type": "main",
        "summary": "完成你的第一次宗门试炼，证明自己的实力。",
        "visibility": "visible",
        "steps": [
            {
                "step_no": 1,
                "objective": "前往试炼堂领取试炼任务",
                "success_conditions": {"location": "trial_hall", "action": "accept_quest"},
                "fail_conditions": {"time_limit": "expired"},
            },
            {
                "step_no": 2,
                "objective": "在山林试炼区击败三只妖兽",
                "success_conditions": {"location": "forest", "kill_count": 3},
                "fail_conditions": {"player_hp": 0},
            },
            {
                "step_no": 3,
                "objective": "返回试炼堂汇报",
                "success_conditions": {"location": "trial_hall", "action": "complete_quest"},
                "fail_conditions": {},
            },
        ],
    },
    {
        "code": "investigate_anomaly",
        "name": "调查异变",
        "quest_type": "main",
        "summary": "山林中出现了诡异的现象，调查真相。",
        "visibility": "hidden",
        "steps": [
            {
                "step_no": 1,
                "objective": "在药园收集线索",
                "success_conditions": {"location": "herb_garden", "action": "investigate"},
                "fail_conditions": {},
            },
            {
                "step_no": 2,
                "objective": "前往崖边祭坛调查",
                "success_conditions": {"location": "cliff", "action": "examine_altar"},
                "fail_conditions": {"discovered_by_enemy": True},
            },
            {
                "step_no": 3,
                "objective": "找到秘境入口",
                "success_conditions": {"location": "secret_gate", "action": "discover"},
                "fail_conditions": {},
            },
        ],
    },
    {
        "code": "uncover_truth",
        "name": "揭露真相",
        "quest_type": "main",
        "summary": "深入秘境核心，揭露幕后黑手的阴谋。",
        "visibility": "hidden",
        "steps": [
            {
                "step_no": 1,
                "objective": "突破秘境守卫",
                "success_conditions": {"location": "secret_gate", "action": "defeat_guardians"},
                "fail_conditions": {"player_hp": 0},
            },
            {
                "step_no": 2,
                "objective": "在异变核心找到证据",
                "success_conditions": {"location": "core", "action": "find_evidence"},
                "fail_conditions": {"evidence_destroyed": True},
            },
            {
                "step_no": 3,
                "objective": "面对幕后黑手",
                "success_conditions": {"location": "core", "action": "confront_elder"},
                "fail_conditions": {"player_hp": 0},
            },
        ],
    },
    {
        "code": "help_senior_sister",
        "name": "师姐的请求",
        "quest_type": "side",
        "summary": "柳师姐似乎有什么烦恼，去看看能否帮忙。",
        "visibility": "visible",
        "steps": [
            {
                "step_no": 1,
                "objective": "与柳师姐交谈",
                "success_conditions": {"npc": "senior_sister", "action": "talk"},
                "fail_conditions": {},
            },
            {
                "step_no": 2,
                "objective": "收集十株回春草",
                "success_conditions": {"item": "healing_herb", "quantity": 10},
                "fail_conditions": {},
            },
        ],
    },
]

# =============================================================================
# Event Template Configuration
# =============================================================================

EVENT_TEMPLATES_CONFIG = [
    {
        "code": "welcome_to_sect",
        "name": "初入宗门",
        "event_type": "story",
        "trigger_conditions": {"chapter": 1, "location": "square", "first_visit": True},
        "effects": {"set_flag": "introduced", "unlock_npc": "senior_sister"},
    },
    {
        "code": "strange_occurrence",
        "name": "诡异现象",
        "event_type": "story",
        "trigger_conditions": {"quest_completed": "first_trial", "location": "forest"},
        "effects": {"set_flag": "anomaly_discovered", "unlock_location": "cliff"},
    },
    {
        "code": "confrontation",
        "name": "最终对决",
        "event_type": "story",
        "trigger_conditions": {"quest_completed": "investigate_anomaly", "location": "core"},
        "effects": {"set_flag": "final_confrontation", "spawn_boss": "elder"},
    },
    {
        "code": "random_combat",
        "name": "遭遇妖兽",
        "event_type": "combat",
        "trigger_conditions": {"location": "forest", "random_chance": 0.3},
        "effects": {"start_combat": "wild_beast"},
    },
    {
        "code": "herb_gathering",
        "name": "采集灵草",
        "event_type": "gathering",
        "trigger_conditions": {"location": "herb_garden", "action": "gather"},
        "effects": {"add_item": "healing_herb", "skill_exp": 5},
    },
    {
        "code": "library_discovery",
        "name": "藏经阁发现",
        "event_type": "discovery",
        "trigger_conditions": {"location": "library", "action": "read", "chance": 0.2},
        "effects": {"add_lore": "ancient_sect_history", "add_item": "ancient_scroll"},
    },
]

# =============================================================================
# Prompt Template Configuration
# =============================================================================

PROMPT_TEMPLATES_CONFIG = [
    {
        "prompt_type": "narration",
        "version": "1.0",
        "content": """你是一位修仙文字RPG的叙事者。请根据以下信息生成一段叙事文本：

玩家位置：{{location}}
玩家行动：{{action}}
当前时间：{{time}}
周围NPC：{{nearby_npcs}}

要求：
1. 使用富有仙侠风格的语言
2. 描述玩家的行动和周围环境的变化
3. 保持叙事连贯性和沉浸感
4. 长度控制在200-400字之间
""",
    },
    {
        "prompt_type": "npc_dialogue",
        "version": "1.0",
        "content": """你是{{npc_name}}，{{npc_role}}。{{npc_personality}}

当前情境：{{context}}
玩家说的话：{{player_input}}

请根据你的人设和当前情境生成对话回复。要求：
1. 符合角色性格和身份
2. 使用符合修仙世界观的语言风格
3. 如果玩家问到了你不知道的事情，表现出合理的不知情
4. 长度控制在50-150字之间
""",
    },
    {
        "prompt_type": "intent_parsing",
        "version": "1.0",
        "content": """分析以下玩家输入，提取玩家的意图：

玩家输入："{{input}}"
当前位置：{{location}}
可用行动：{{available_actions}}

请以JSON格式返回：
{
    "intent": "意图类型",
    "target": "目标对象（如果有）",
    "parameters": {"参数名": "参数值"}
}

可能的意图类型：move, examine, talk, combat, use_item, rest, gather
""",
    },
    {
        "prompt_type": "combat_narration",
        "version": "1.0",
        "content": """生成一段战斗叙事：

战斗双方：{{combatants}}
行动：{{action}}
结果：{{result}}

请以修仙小说的风格描述这场战斗的经过，突出招式和气势。长度控制在150-300字之间。
""",
    },
    {
        "prompt_type": "memory_summary",
        "version": "1.0",
        "content": """总结以下事件为一段记忆摘要：

事件：{{events}}
涉及角色：{{characters}}
重要性：{{importance}}

请以第三人称视角，简洁地总结这段经历的关键信息。长度控制在100-200字之间。
""",
    },
]

# =============================================================================
# Ending Configuration (3 endings)
# =============================================================================

# Endings are stored as quest steps with special completion states
ENDINGS_CONFIG = [
    {
        "code": "good_ending",
        "name": "宗门英雄",
        "description": "你成功揭露了李长老的阴谋，拯救了宗门。你因此被破格提升为内门弟子，受到宗门的重用。",
        "conditions": {"defeated_elder": True, "saved_sect": True, "innocents_unharmed": True},
    },
    {
        "code": "bittersweet_ending",
        "name": "牺牲与救赎",
        "description": "虽然你揭露了真相，但付出了沉重的代价。清玄上人为保护弟子而牺牲，宗门需要时间来恢复元气。",
        "conditions": {"defeated_elder": True, "master_sacrificed": True},
    },
    {
        "code": "secret_ending",
        "name": "真相之后",
        "description": "你发现李长老背后还有更大的势力。这场试炼异变只是更大阴谋的一部分，你的修仙之路才刚刚开始...",
        "conditions": {"defeated_elder": True, "found_hidden_evidence": True, "chapter_3_complete": True},
    },
]


# =============================================================================
# Seeding Functions
# =============================================================================

def seed_world(db: Session) -> str:
    """Seed the world configuration. Returns world_id."""
    world_repo = WorldRepository(db)
    
    # Check if world already exists
    existing = world_repo.get_by_code(WORLD_CONFIG["code"])
    if existing:
        print(f"World '{WORLD_CONFIG['name']}' already exists (id: {existing.id})")
        return existing.id
    
    world = world_repo.create(WORLD_CONFIG)
    print(f"Created world: {world.name} (id: {world.id})")
    return world.id


def seed_chapters(db: Session, world_id: str) -> Dict[int, str]:
    """Seed chapters. Returns mapping of chapter_no to chapter_id."""
    chapter_repo = ChapterRepository(db)
    chapter_ids = {}
    
    for chapter_data in CHAPTERS_CONFIG:
        # Check if chapter already exists
        existing = chapter_repo.get_by_world_and_number(world_id, chapter_data["chapter_no"])
        if existing:
            print(f"  Chapter {chapter_data['chapter_no']} '{chapter_data['name']}' already exists")
            chapter_ids[chapter_data["chapter_no"]] = existing.id
            continue
        
        data = {**chapter_data, "world_id": world_id}
        chapter = chapter_repo.create(data)
        chapter_ids[chapter_data["chapter_no"]] = chapter.id
        print(f"  Created chapter {chapter.chapter_no}: {chapter.name}")
    
    return chapter_ids


def seed_locations(db: Session, world_id: str, chapter_ids: Dict[int, str]) -> Dict[str, str]:
    """Seed locations. Returns mapping of location_code to location_id."""
    location_repo = LocationRepository(db)
    location_ids = {}
    
    for loc_data in LOCATIONS_CONFIG:
        loc_data_copy = loc_data.copy()
        
        # Check if location already exists
        existing = location_repo.get_by_world(world_id)
        for existing_loc in existing:
            if existing_loc.code == loc_data_copy["code"]:
                print(f"  Location '{loc_data_copy['name']}' already exists")
                location_ids[loc_data_copy["code"]] = existing_loc.id
                break
        else:
            chapter_no = loc_data_copy.pop("chapter_no", 1)
            data = {
                **loc_data_copy,
                "world_id": world_id,
                "chapter_id": chapter_ids.get(chapter_no),
            }
            location = location_repo.create(data)
            location_ids[loc_data_copy["code"]] = location.id
            print(f"  Created location: {location.name}")
    
    return location_ids


def seed_npcs(db: Session, world_id: str) -> Dict[str, str]:
    """Seed NPC templates. Returns mapping of npc_code to npc_id."""
    npc_repo = NPCTemplateRepository(db)
    npc_ids = {}
    
    for npc_data in NPCS_CONFIG:
        # Check if NPC already exists
        existing = npc_repo.get_by_code(world_id, npc_data["code"])
        if existing:
            print(f"  NPC '{npc_data['name']}' already exists")
            npc_ids[npc_data["code"]] = existing.id
            continue
        
        data = {**npc_data, "world_id": world_id}
        npc = npc_repo.create(data)
        npc_ids[npc_data["code"]] = npc.id
        print(f"  Created NPC: {npc.name} ({npc.public_identity})")
    
    return npc_ids


def seed_items(db: Session, world_id: str) -> Dict[str, str]:
    """Seed item templates. Returns mapping of item_code to item_id."""
    item_repo = ItemTemplateRepository(db)
    item_ids = {}
    
    for item_data in ITEMS_CONFIG:
        # Check if item already exists
        existing = item_repo.get_by_world(world_id)
        for existing_item in existing:
            if existing_item.code == item_data["code"]:
                print(f"  Item '{item_data['name']}' already exists")
                item_ids[item_data["code"]] = existing_item.id
                break
        else:
            data = {**item_data, "world_id": world_id}
            item = item_repo.create(data)
            item_ids[item_data["code"]] = item.id
            print(f"  Created item: {item.name} ({item.rarity})")
    
    return item_ids


def seed_quests(db: Session, world_id: str) -> Dict[str, str]:
    """Seed quest templates and steps. Returns mapping of quest_code to quest_id."""
    quest_repo = QuestTemplateRepository(db)
    step_repo = QuestStepRepository(db)
    quest_ids = {}
    
    for quest_data in QUESTS_CONFIG:
        quest_data_copy = quest_data.copy()
        steps_data = quest_data_copy.pop("steps", [])
        
        # Check if quest already exists
        existing = quest_repo.get_by_world(world_id)
        for existing_quest in existing:
            if existing_quest.code == quest_data_copy["code"]:
                print(f"  Quest '{quest_data_copy['name']}' already exists")
                quest_ids[quest_data_copy["code"]] = existing_quest.id
                break
        else:
            data = {**quest_data_copy, "world_id": world_id}
            quest = quest_repo.create(data)
            quest_ids[quest_data_copy["code"]] = quest.id
            print(f"  Created quest: {quest.name} ({quest.quest_type})")
            
            # Create quest steps
            for step_data in steps_data:
                step_data_copy = step_data.copy()
                step_data_copy["quest_template_id"] = quest.id
                step = step_repo.create(step_data_copy)
                print(f"    - Step {step.step_no}: {step.objective}")
    
    return quest_ids


def seed_event_templates(db: Session, world_id: str) -> None:
    """Seed event templates."""
    event_repo = EventTemplateRepository(db)
    
    for event_data in EVENT_TEMPLATES_CONFIG:
        # Check if event template already exists
        existing = event_repo.get_by_world(world_id)
        for existing_event in existing:
            if existing_event.code == event_data["code"]:
                print(f"  Event '{event_data['name']}' already exists")
                break
        else:
            data = {**event_data, "world_id": world_id}
            event = event_repo.create(data)
            print(f"  Created event: {event.name} ({event.event_type})")


def seed_prompt_templates(db: Session, world_id: str) -> None:
    """Seed prompt templates."""
    prompt_repo = PromptTemplateRepository(db)
    
    for prompt_data in PROMPT_TEMPLATES_CONFIG:
        # Check if prompt template already exists
        existing = prompt_repo.get_by_type(prompt_data["prompt_type"], world_id)
        for existing_prompt in existing:
            if existing_prompt.version == prompt_data["version"]:
                print(f"  Prompt '{prompt_data['prompt_type']}' v{prompt_data['version']} already exists")
                break
        else:
            data = {**prompt_data, "world_id": world_id}
            prompt = prompt_repo.create(data)
            print(f"  Created prompt: {prompt.prompt_type} v{prompt.version}")


def seed_endings(db: Session, world_id: str) -> None:
    """Seed endings as special quest templates."""
    quest_repo = QuestTemplateRepository(db)
    
    for ending_data in ENDINGS_CONFIG:
        code = ending_data["code"]
        name = ending_data["name"]
        
        # Check if ending already exists
        existing = quest_repo.get_by_world(world_id)
        for existing_quest in existing:
            if existing_quest.code == code:
                print(f"  Ending '{name}' already exists")
                break
        else:
            data = {
                "code": code,
                "name": name,
                "quest_type": "ending",
                "summary": ending_data["description"],
                "visibility": "hidden",
                "world_id": world_id,
            }
            quest = quest_repo.create(data)
            print(f"  Created ending: {quest.name}")


def seed_all_content(db: Session) -> Dict[str, any]:
    """Seed all content and return IDs mapping."""
    print("\n" + "="*60)
    print("Seeding LLM RPG Engine Content")
    print("="*60)
    
    # 1. World
    world_id = seed_world(db)
    
    # 2. Chapters
    print("\nSeeding chapters...")
    chapter_ids = seed_chapters(db, world_id)
    
    # 3. Locations
    print("\nSeeding locations...")
    location_ids = seed_locations(db, world_id, chapter_ids)
    
    # 4. NPCs
    print("\nSeeding NPC templates...")
    npc_ids = seed_npcs(db, world_id)
    
    # 5. Items
    print("\nSeeding item templates...")
    item_ids = seed_items(db, world_id)
    
    # 6. Quests
    print("\nSeeding quests...")
    quest_ids = seed_quests(db, world_id)
    
    # 7. Event Templates
    print("\nSeeding event templates...")
    seed_event_templates(db, world_id)
    
    # 8. Prompt Templates
    print("\nSeeding prompt templates...")
    seed_prompt_templates(db, world_id)
    
    # 9. Endings
    print("\nSeeding endings...")
    seed_endings(db, world_id)
    
    print("\n" + "="*60)
    print("Content seeding completed!")
    print("="*60)
    
    return {
        "world_id": world_id,
        "chapter_ids": chapter_ids,
        "location_ids": location_ids,
        "npc_ids": npc_ids,
        "item_ids": item_ids,
        "quest_ids": quest_ids,
    }


def verify_seed_counts(db: Session, world_id: str) -> Dict[str, int]:
    """Verify that the correct amount of content was seeded."""
    from llm_rpg.storage.repositories import (
        ChapterRepository,
        LocationRepository,
        NPCTemplateRepository,
        ItemTemplateRepository,
        QuestTemplateRepository,
        EventTemplateRepository,
        PromptTemplateRepository,
    )
    
    counts = {
        "worlds": 1,
        "chapters": len(ChapterRepository(db).get_by_world(world_id)),
        "locations": len(LocationRepository(db).get_by_world(world_id)),
        "npcs": len(NPCTemplateRepository(db).get_by_world(world_id)),
        "items": len(ItemTemplateRepository(db).get_by_world(world_id)),
        "quests": len(QuestTemplateRepository(db).get_by_world(world_id)),
        "events": len(EventTemplateRepository(db).get_by_world(world_id)),
        "prompts": len(PromptTemplateRepository(db).get_by_type("narration", world_id)) +
                   len(PromptTemplateRepository(db).get_by_type("npc_dialogue", world_id)) +
                   len(PromptTemplateRepository(db).get_by_type("intent_parsing", world_id)) +
                   len(PromptTemplateRepository(db).get_by_type("combat_narration", world_id)) +
                   len(PromptTemplateRepository(db).get_by_type("memory_summary", world_id)),
    }
    
    # Count endings (quests with type 'ending')
    all_quests = QuestTemplateRepository(db).get_by_world(world_id)
    counts["endings"] = len([q for q in all_quests if q.quest_type == "ending"])
    
    return counts


def main():
    """Main entry point for the seed script."""
    database_url = DATABASE_URL or "sqlite:///./seed.db"
    
    # Create engine
    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False} if "sqlite" in database_url else {},
        poolclass=StaticPool if "sqlite" in database_url else None,
    )
    
    # Create tables if they don't exist
    Base.metadata.create_all(bind=engine)
    
    # Create session
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()
    
    try:
        # Seed all content
        ids = seed_all_content(db)
        
        # Verify counts
        print("\nVerifying content counts...")
        counts = verify_seed_counts(db, ids["world_id"])
        
        print(f"\n  Worlds: {counts['worlds']} (expected: 1)")
        print(f"  Chapters: {counts['chapters']} (expected: 3)")
        print(f"  Locations: {counts['locations']} (expected: 10+)")
        print(f"  NPCs: {counts['npcs']} (expected: 5+)")
        print(f"  Items: {counts['items']} (expected: 5+)")
        print(f"  Quests: {counts['quests']} (expected: 4+)")
        print(f"  Events: {counts['events']} (expected: 5+)")
        print(f"  Prompts: {counts['prompts']} (expected: 5)")
        print(f"  Endings: {counts['endings']} (expected: 3)")
        
        # Check requirements
        all_pass = True
        if counts["worlds"] < 1:
            print("\n  ❌ FAIL: Need at least 1 world")
            all_pass = False
        if counts["chapters"] < 3:
            print("\n  ❌ FAIL: Need at least 3 chapters")
            all_pass = False
        if counts["locations"] < 10:
            print("\n  ❌ FAIL: Need at least 10 locations")
            all_pass = False
        if counts["npcs"] < 5:
            print("\n  ❌ FAIL: Need at least 5 NPCs")
            all_pass = False
        if counts["endings"] < 3:
            print("\n  ❌ FAIL: Need at least 3 endings")
            all_pass = False
        
        if all_pass:
            print("\n  ✅ All content requirements met!")
        
        return 0 if all_pass else 1
        
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
