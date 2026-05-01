from typing import Any, Dict, List, Optional


class PromptTemplate:
    
    def __init__(self, template: str, variables: List[str] = None):
        self.template = template
        self.variables = variables or []
    
    def render(self, **kwargs) -> str:
        result = self.template
        for key, value in kwargs.items():
            result = result.replace(f"{{{key}}}", str(value))
        return result


WORLD_PROMPT = PromptTemplate(
    template="""你是一个世界引擎，负责推进游戏世界的状态。

当前世界状态：
{world_state}

当前时间：{current_time}
天气：{weather}

活跃的世界事件：
{active_events}

玩家输入：{player_input}

请根据以上信息，推进世界状态并生成世界事件。""",
    variables=["world_state", "current_time", "weather", "active_events", "player_input"]
)


NPC_DECISION_PROMPT = PromptTemplate(
    template="""你是NPC {npc_name}。

你的性格：{personality}
你的当前目标：{goals}
你的当前情绪：{mood}

你所知道的事实：
{known_facts}

你最近的记忆：
{recent_memories}

当前场景：
{current_scene}

玩家行动：{player_action}

请根据你的性格、目标和知识，决定你的下一步行动。""",
    variables=["npc_name", "personality", "goals", "mood", "known_facts", 
               "recent_memories", "current_scene", "player_action"]
)


NARRATION_PROMPT = PromptTemplate(
    template="""你是一个文字RPG的叙事者。

文风要求：{style}
语调：{tone}
节奏：{pacing}

玩家当前状态：
{player_state}

当前场景：
{current_scene}

可见的NPC：
{visible_npcs}

最近发生的事件：
{recent_events}

玩家行动：{player_action}

请根据以上信息，生成一段引人入胜的叙事文本。注意：
1. 只描述玩家可以看到的信息
2. 不要泄露隐藏的秘密
3. 保持文风和语调一致
4. 营造适当的氛围""",
    variables=["style", "tone", "pacing", "player_state", "current_scene",
               "visible_npcs", "recent_events", "player_action"]
)


SUMMARY_PROMPT = PromptTemplate(
    template="""请为以下游戏事件生成一个简洁的摘要。

时间范围：{time_range}
事件列表：
{events}

请生成一个客观、简洁的摘要，突出关键事件和重要变化。""",
    variables=["time_range", "events"]
)


NPC_SUBJECTIVE_SUMMARY_PROMPT = PromptTemplate(
    template="""你是NPC {npc_name}。

请根据你的视角，为以下事件生成一个主观摘要。

你的性格：{personality}
你的目标：{goals}

事件列表：
{events}

请从你的角度描述这些事件，包括你的感受和理解。""",
    variables=["npc_name", "personality", "goals", "events"]
)


LORE_DISCOVERY_PROMPT = PromptTemplate(
    template="""玩家发现了新的世界观信息。

已知信息：
{known_lore}

新发现的线索：
{new_clues}

请根据新线索，更新玩家对世界的理解，并生成新的世界观描述。""",
    variables=["known_lore", "new_clues"]
)


COMBAT_PROMPT = PromptTemplate(
    template="""战斗场景。

参与者：
{participants}

当前回合：{current_turn}
战斗状态：{combat_state}

请描述当前回合的战斗情况，并生成战斗叙事。""",
    variables=["participants", "current_turn", "combat_state"]
)


DIALOGUE_PROMPT = PromptTemplate(
    template="""对话场景。

NPC：{npc_name}
NPC性格：{npc_style}
NPC当前情绪：{npc_mood}

对话历史：
{dialogue_history}

玩家发言：{player_speech}

请生成NPC的回应，保持其性格和情绪的一致性。""",
    variables=["npc_name", "npc_style", "npc_mood", "dialogue_history", "player_speech"]
)