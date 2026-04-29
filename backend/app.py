"""
Simple FastAPI backend for a demonstration LLM‑driven RPG engine.

This implementation is intentionally lightweight: it does not persist
state to a real database and it does not call any external large
language model.  Instead it uses in‑memory dictionaries and simple
rule‑based text generation to illustrate how the engine might work.

The goal of this proof of concept is to demonstrate that the core
event loop – creating a session, handling player input, updating
world state and returning a narrative response – can function.  It
also lays the foundation for future expansions such as persistent
storage, richer world models, proper NPC personalities and AI‑driven
text.

To run the development server, execute::

    uvicorn app:app --reload --port 8000

in the ``backend`` directory.  Then you can send requests to
``http://localhost:8000`` to create sessions and play through the
demo world.  See the endpoints defined below for details.
"""

import uuid
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


app = FastAPI(title="LLM RPG Demo Engine")

# -----------------------------------------------------------------------------
# Data models
# -----------------------------------------------------------------------------

class NPC(BaseModel):
    """Represents a non‑player character template.

    "surface_name" is the public facing name the player sees.  "secret_role"
    can hint at a hidden agenda.  "personality" describes how the NPC speaks.
    """

    npc_id: str
    surface_name: str
    secret_role: str
    personality: str
    location: str


class Location(BaseModel):
    """Represents a world location.

    Locations have a name, a description and optional connections to other
    locations.  In this minimal demo we do not enforce movement rules but
    expose the connections for future use.
    """

    loc_id: str
    name: str
    description: str
    connections: List[str] = Field(default_factory=list)


class World(BaseModel):
    """Holds the static configuration for the demo world."""

    world_id: str
    name: str
    description: str
    locations: Dict[str, Location]
    npcs: Dict[str, NPC]


class PlayerState(BaseModel):
    """Mutable state associated with a single session."""

    current_location: str
    chapter: int
    inventory: List[str] = Field(default_factory=list)
    time: int = 0  # Simple integer tick count representing game time
    log: List[str] = Field(default_factory=list)


class Session(BaseModel):
    """Represents a running game session."""

    session_id: str
    world_id: str
    player_state: PlayerState
    npc_states: Dict[str, dict]  # Minimal mutable state per NPC


class InputModel(BaseModel):
    """Request body for the turn endpoint."""

    action: str


class TurnResult(BaseModel):
    """Response body for the turn endpoint."""

    narrative: str
    recommended_actions: List[str]
    state: PlayerState


# -----------------------------------------------------------------------------
# In‑memory world definition
# -----------------------------------------------------------------------------

def build_demo_world() -> World:
    """Constructs the static world used in this demo.

    The descriptions here are intentionally brief.  In a production system
    these would be far richer and potentially loaded from external
    authoring tools.  Connections define which locations are adjacent.
    """

    locations = {
        "square": Location(
            loc_id="square",
            name="宗门广场",
            description="你站在宗门的广场上，弟子们正在忙碌准备试炼。",
            connections=["residence", "trial_hall"],
        ),
        "residence": Location(
            loc_id="residence",
            name="外门居所",
            description="简朴的居所散发着淡淡药香，是外门弟子起居之所。",
            connections=["square", "herb_garden"],
        ),
        "trial_hall": Location(
            loc_id="trial_hall",
            name="试炼堂",
            description="高大的试炼堂内悬挂着历代长老的画像，弟子们在此领受试炼任务。",
            connections=["square", "mountain_path"],
        ),
        "herb_garden": Location(
            loc_id="herb_garden",
            name="药园",
            description="药园里种着各类灵草，空气中弥漫着草木清香。",
            connections=["residence", "forest"],
        ),
        "library": Location(
            loc_id="library",
            name="藏经阁外区",
            description="藏经阁外区供外门弟子查阅基础功法，内区对你暂时封闭。",
            connections=["square"],
        ),
        "forest": Location(
            loc_id="forest",
            name="山林试炼区",
            description="这片山林是试炼的主要区域，传说其中藏着秘境入口。",
            connections=["herb_garden", "cliff", "secret_gate"],
        ),
        "cliff": Location(
            loc_id="cliff",
            name="崖边祭坛",
            description="悬崖旁的古老祭坛上刻满阵纹，似乎早已失去灵力。",
            connections=["forest"],
        ),
        "secret_gate": Location(
            loc_id="secret_gate",
            name="秘境入口",
            description="山林深处隐蔽着一处石门，石门缝隙里吹出寒气。",
            connections=["forest", "core"],
        ),
        "core": Location(
            loc_id="core",
            name="异变核心",
            description="这是试炼异变的源头，邪气缭绕，令人胆寒。",
            connections=["secret_gate"],
        ),
    }

    npcs = {
        "senior_sister": NPC(
            npc_id="senior_sister",
            surface_name="柳师姐",
            secret_role="内门使者",
            personality="温和而略带谨慎，喜欢指点新弟子。",
            location="square",
        ),
        "male_competitor": NPC(
            npc_id="male_competitor",
            surface_name="江程",
            secret_role="潜在盟友",
            personality="自负但讲义气，擅长剑术。",
            location="residence",
        ),
        "female_competitor": NPC(
            npc_id="female_competitor",
            surface_name="林菲",
            secret_role="潜在盟友",
            personality="聪明而冷静，喜欢独自行动。",
            location="herb_garden",
        ),
        "mysterious": NPC(
            npc_id="mysterious",
            surface_name="神秘人",
            secret_role="知晓真相的引导者",
            personality="说话模糊，喜欢用谜语提醒他人。",
            location="forest",
        ),
        "elder": NPC(
            npc_id="elder",
            surface_name="李长老",
            secret_role="幕后黑手",
            personality="威严且沉默，隐藏真实目的。",
            location="trial_hall",
        ),
        "master": NPC(
            npc_id="master",
            surface_name="清玄上人",
            secret_role="护道者",
            personality="慈祥中透露出深不可测的气息。",
            location="square",
        ),
    }

    return World(
        world_id="demo_world",
        name="修仙试炼世界",
        description="在这个宗门中，你将经历试炼、发现异变并寻找真相。",
        locations={loc.loc_id: loc for loc in locations.values()},
        npcs={npc.npc_id: npc for npc in npcs.values()},
    )


DEMO_WORLD = build_demo_world()


# -----------------------------------------------------------------------------
# Session management
# -----------------------------------------------------------------------------

SESSIONS: Dict[str, Session] = {}


def create_session() -> Session:
    """Creates a new session with initial player and NPC state."""
    session_id = str(uuid.uuid4())
    # Player starts at the square in chapter 1
    player_state = PlayerState(current_location="square", chapter=1)
    # Initialize NPC state; for this demo we only track current location
    npc_states = {nid: {"current_location": npc.location} for nid, npc in DEMO_WORLD.npcs.items()}
    session = Session(
        session_id=session_id,
        world_id=DEMO_WORLD.world_id,
        player_state=player_state,
        npc_states=npc_states,
    )
    SESSIONS[session_id] = session
    return session


def get_session(session_id: str) -> Session:
    try:
        return SESSIONS[session_id]
    except KeyError:
        raise HTTPException(status_code=404, detail="Session not found")


# -----------------------------------------------------------------------------
# Narrative generation helpers
# -----------------------------------------------------------------------------

def describe_location(location: Location) -> str:
    return location.description


def describe_npc_interaction(npc: NPC) -> str:
    """Returns a simple line of dialogue based on the NPC's personality.

    In a real system this would call into an LLM with the NPC's memory and
    current context.  For this demo we hardcode a brief response and hint at
    hidden agendas via secret_role.
    """
    if npc.npc_id == "senior_sister":
        return "柳师姐微笑着为你解释试炼规则，并叮嘱你要小心行事。"
    if npc.npc_id == "male_competitor":
        return "江程挑衅地看着你，说以后可别拖他的后腿。"
    if npc.npc_id == "female_competitor":
        return "林菲目光清冷，对你的问题只是点头示意。"
    if npc.npc_id == "mysterious":
        return "神秘人低声说道：“山林深处埋藏着真相，也埋藏着危险。”"
    if npc.npc_id == "elder":
        return "李长老沉默不语，只是让你尽快通过试炼。"
    if npc.npc_id == "master":
        return "清玄上人慈祥地问候你，并叮嘱你专心修行。"
    return f"{npc.surface_name}没有什么特别想说的。"


def generate_narrative(session: Session, action: str) -> str:
    """Generates a narrative text based on the player's action.

    This is a placeholder for LLM generation.  We use simple keyword checks
    to produce different outputs.  If the player mentions moving, we attempt
    to change location.  If the player mentions talking, we respond with the
    first NPC at the location.  Otherwise we describe the surroundings.
    """
    ps = session.player_state
    current_loc = DEMO_WORLD.locations[ps.current_location]
    action_lower = action.lower()
    narrative_lines: List[str] = []
    # Move commands
    moved = False
    for direction in ["去", "走", "前往", "move", "go"]:
        if direction in action_lower:
            # Attempt to extract target location name by checking known location
            for loc_id, loc in DEMO_WORLD.locations.items():
                if loc.name in action:
                    # If connection exists or ignoring adjacency for demo
                    ps.current_location = loc_id
                    narrative_lines.append(
                        f"你离开了{current_loc.name}，来到{loc.name}。"
                    )
                    moved = True
                    break
            if not moved:
                narrative_lines.append("你想移动，但不知道要去哪里。")
            break
    # Talk commands
    if any(w in action_lower for w in ["问", "聊", "talk", "问问", "询问"]):
        # Find NPCs at current location
        for npc_id, state in session.npc_states.items():
            if state["current_location"] == ps.current_location:
                npc = DEMO_WORLD.npcs[npc_id]
                narrative_lines.append(describe_npc_interaction(npc))
                break
        else:
            narrative_lines.append("你环顾四周，没有可交谈的人。")
    # Observe/look commands
    elif any(w in action_lower for w in ["看", "观察", "look", "survey"]):
        narrative_lines.append(describe_location(DEMO_WORLD.locations[ps.current_location]))
    # Default fallback
    if not narrative_lines:
        narrative_lines.append(
            f"你在{current_loc.name}行动起来，但不清楚要做什么。不妨先观察四周或与人交谈。"
        )
    # Append any hidden time hints
    ps.log.append(f"[{ps.time}] {action}")
    return "\n".join(narrative_lines)


def generate_recommended_actions(session: Session) -> List[str]:
    """Provides simple recommended actions for the player."""
    current_loc = DEMO_WORLD.locations[session.player_state.current_location]
    actions = []
    # Suggest exploring connected locations
    for conn_id in current_loc.connections:
        target = DEMO_WORLD.locations[conn_id]
        actions.append(f"前往{target.name}")
    # Suggest interacting if NPC present
    for npc_id, state in session.npc_states.items():
        if state["current_location"] == session.player_state.current_location:
            npc = DEMO_WORLD.npcs[npc_id]
            actions.append(f"询问{npc.surface_name}")
    # Always suggest观察
    actions.append("观察四周")
    return actions[:4]  # Limit number of suggestions


# -----------------------------------------------------------------------------
# API endpoints
# -----------------------------------------------------------------------------

@app.post("/saves", response_model=str)
def create_save() -> str:
    """Creates a new save slot and returns the session identifier."""
    session = create_session()
    return session.session_id


@app.get("/saves", response_model=List[str])
def list_saves() -> List[str]:
    """Lists existing session identifiers."""
    return list(SESSIONS.keys())


@app.get("/sessions/{session_id}/snapshot", response_model=PlayerState)
def get_snapshot(session_id: str) -> PlayerState:
    """Returns the current player state for a given session."""
    session = get_session(session_id)
    return session.player_state


@app.post("/sessions/{session_id}/turn", response_model=TurnResult)
def perform_turn(session_id: str, inp: InputModel) -> TurnResult:
    """Performs a single turn for the given session.

    The server will update the world time, process the player's action,
    generate a narrative response and provide recommended next actions.
    """
    session = get_session(session_id)
    # Simple time progression: each turn adds one tick
    session.player_state.time += 1
    narrative = generate_narrative(session, inp.action)
    recommended = generate_recommended_actions(session)
    return TurnResult(
        narrative=narrative,
        recommended_actions=recommended,
        state=session.player_state,
    )


@app.get("/debug/sessions/{session_id}/logs", response_model=List[str])
def get_logs(session_id: str) -> List[str]:
    """Returns the raw event logs for a session.  Useful for debugging."""
    session = get_session(session_id)
    return session.player_state.log