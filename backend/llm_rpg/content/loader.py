"""Content pack loader - reads YAML files and parses to models."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from llm_rpg.models.content_pack import (
    ContentPackDefinition,
    ContentPackManifest,
    ContentFileRefs,
    FactionDefinition,
    FactionGoalDefinition,
    FactionRelationshipDefinition,
    PlotBeatCondition,
    PlotBeatDefinition,
    PlotBeatEffect,
    PlotBeatVisibility,
)


class ContentPackLoadError(Exception):
    """Raised when content pack loading fails."""
    pass


def load_content_pack(pack_dir: Path) -> ContentPackDefinition:
    """Load a content pack from a directory.
    
    Args:
        pack_dir: Path to the content pack directory containing pack.yaml
        
    Returns:
        ContentPackDefinition with all loaded content
        
    Raises:
        ContentPackLoadError: If pack.yaml is missing or invalid
    """
    pack_dir = Path(pack_dir)
    pack_yaml_path = pack_dir / "pack.yaml"
    
    if not pack_yaml_path.exists():
        raise ContentPackLoadError(f"pack.yaml not found in {pack_dir}")
    
    try:
        with open(pack_yaml_path, "r", encoding="utf-8") as f:
            pack_data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ContentPackLoadError(f"Invalid YAML in pack.yaml: {e}") from e
    
    manifest = _parse_manifest(pack_data)
    file_refs = _build_file_refs(pack_dir)
    
    factions: List[FactionDefinition] = []
    plot_beats: List[PlotBeatDefinition] = []
    
    factions_path = pack_dir / "factions.yaml"
    if factions_path.exists():
        factions = load_factions_from_yaml(factions_path, manifest.id)
    
    plot_beats_path = pack_dir / "plot_beats.yaml"
    if plot_beats_path.exists():
        plot_beats = load_plot_beats_from_yaml(plot_beats_path, manifest.id)
    
    return ContentPackDefinition(
        manifest=manifest,
        factions=factions,
        plot_beats=plot_beats,
        file_refs=file_refs,
        metadata={
            "genre": pack_data.get("genre", ""),
            "theme": pack_data.get("theme", ""),
            "tags": pack_data.get("tags", []),
        }
    )


def _parse_manifest(data: Dict[str, Any]) -> ContentPackManifest:
    """Parse manifest data from pack.yaml."""
    created_at_str = data.get("created_at")
    if created_at_str:
        try:
            created_at = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        except ValueError:
            created_at = datetime.now()
    else:
        created_at = datetime.now()
    
    return ContentPackManifest(
        id=data.get("id", ""),
        name=data.get("name", ""),
        version=data.get("version", "0.0.0"),
        description=data.get("description", ""),
        author=data.get("author", ""),
        created_at=created_at,
    )


def _build_file_refs(pack_dir: Path) -> ContentFileRefs:
    """Build file references for expected YAML files."""
    expected_files = {
        "factions": "factions.yaml",
        "plot_beats": "plot_beats.yaml",
        "npcs": "npcs.yaml",
        "locations": "locations.yaml",
        "items": "items.yaml",
        "quests": "quests.yaml",
    }
    
    refs = {}
    for key, filename in expected_files.items():
        path = pack_dir / filename
        if path.exists():
            refs[key] = [filename]
        else:
            refs[key] = []
    
    return ContentFileRefs(**refs)


def load_factions_from_yaml(path: Path, world_id: str = "") -> List[FactionDefinition]:
    """Load faction definitions from a YAML file.
    
    Args:
        path: Path to the factions YAML file
        world_id: World ID to assign to factions
        
    Returns:
        List of FactionDefinition objects
        
    Raises:
        ContentPackLoadError: If the file cannot be read or parsed
    """
    path = Path(path)
    
    if not path.exists():
        raise ContentPackLoadError(f"Factions file not found: {path}")
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ContentPackLoadError(f"Invalid YAML in {path}: {e}") from e
    
    if not data or "factions" not in data:
        return []
    
    factions = []
    for faction_data in data.get("factions", []):
        faction = _parse_faction(faction_data, world_id)
        factions.append(faction)
    
    return factions


def _parse_faction(data: Dict[str, Any], world_id: str) -> FactionDefinition:
    """Parse a single faction from YAML data."""
    goals = _parse_faction_goals(data.get("goals", []))
    relationships = _parse_faction_relationships(data.get("relationships", {}))
    
    return FactionDefinition(
        id=data.get("id", ""),
        name=data.get("name", ""),
        world_id=world_id,
        ideology=data.get("ideology", ""),
        goals=goals,
        relationships=relationships,
        visibility=data.get("visibility", "public"),
    )


def _parse_faction_goals(goals_data: List[Any]) -> List[FactionGoalDefinition]:
    """Parse faction goals from YAML data.
    
    Goals can be:
    - List of strings (simple goals)
    - List of dicts with goal_id, description, priority, status
    """
    goals = []
    for i, goal_data in enumerate(goals_data):
        if isinstance(goal_data, str):
            goals.append(FactionGoalDefinition(
                goal_id=f"goal_{i}",
                description=goal_data,
                priority=0,
                status="active",
            ))
        elif isinstance(goal_data, dict):
            goals.append(FactionGoalDefinition(
                goal_id=goal_data.get("goal_id", f"goal_{i}"),
                description=goal_data.get("description", ""),
                priority=goal_data.get("priority", 0),
                status=goal_data.get("status", "active"),
            ))
    return goals


def _parse_faction_relationships(
    rel_data: Dict[str, Any]
) -> List[FactionRelationshipDefinition]:
    """Parse faction relationships from YAML data.
    
    Relationships in YAML are a dict: {target_faction_id: relationship_type}
    """
    relationships = []
    for target_id, rel_type in rel_data.items():
        if isinstance(rel_type, str):
            score = _relationship_type_to_score(rel_type)
            relationships.append(FactionRelationshipDefinition(
                target_faction_id=target_id,
                relationship_type=rel_type,
                score=score,
            ))
        elif isinstance(rel_type, dict):
            relationships.append(FactionRelationshipDefinition(
                target_faction_id=target_id,
                relationship_type=rel_type.get("type", "neutral"),
                score=rel_type.get("score", 0),
            ))
    return relationships


def _relationship_type_to_score(rel_type: str) -> int:
    """Convert relationship type string to a score."""
    scores = {
        "ally": 75,
        "friendly": 50,
        "neutral": 0,
        "suspicious": -25,
        "rival": -50,
        "hostile": -75,
        "enemy": -100,
        "vassal": -30,
    }
    return scores.get(rel_type, 0)


def load_plot_beats_from_yaml(path: Path, world_id: str = "") -> List[PlotBeatDefinition]:
    """Load plot beat definitions from a YAML file.
    
    Args:
        path: Path to the plot beats YAML file
        world_id: World ID to assign to plot beats
        
    Returns:
        List of PlotBeatDefinition objects
        
    Raises:
        ContentPackLoadError: If the file cannot be read or parsed
    """
    path = Path(path)
    
    if not path.exists():
        raise ContentPackLoadError(f"Plot beats file not found: {path}")
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ContentPackLoadError(f"Invalid YAML in {path}: {e}") from e
    
    if not data or "plot_beats" not in data:
        return []
    
    plot_beats = []
    for beat_data in data.get("plot_beats", []):
        beat = _parse_plot_beat(beat_data, world_id)
        plot_beats.append(beat)
    
    return plot_beats


def _parse_plot_beat(data: Dict[str, Any], world_id: str) -> PlotBeatDefinition:
    """Parse a single plot beat from YAML data."""
    conditions = _parse_trigger_conditions(data.get("trigger_conditions", {}))
    effects = _parse_effects(data.get("effects", []))
    visibility = _parse_visibility(data.get("visibility", "conditional"))
    
    return PlotBeatDefinition(
        id=data.get("id", ""),
        title=data.get("name", ""),
        world_id=world_id,
        conditions=conditions,
        effects=effects,
        priority=data.get("priority", 0),
        visibility=visibility,
        status=data.get("status", "pending"),
    )


def _parse_visibility(visibility_str: str) -> PlotBeatVisibility:
    """Parse visibility string to enum."""
    visibility_map = {
        "hidden": PlotBeatVisibility.HIDDEN,
        "conditional": PlotBeatVisibility.CONDITIONAL,
        "revealed": PlotBeatVisibility.REVEALED,
    }
    return visibility_map.get(visibility_str, PlotBeatVisibility.CONDITIONAL)


def _parse_trigger_conditions(
    conditions_data: Dict[str, Any]
) -> List[PlotBeatCondition]:
    """Parse trigger conditions from YAML data.
    
    Trigger conditions in YAML are a dict with various keys.
    We convert them to a list of PlotBeatCondition objects.
    """
    conditions = []
    
    if "location" in conditions_data:
        conditions.append(PlotBeatCondition(
            type="location_is",
            params={"location_id": conditions_data["location"]},
        ))
    
    if "event_flag" in conditions_data:
        conditions.append(PlotBeatCondition(
            type="state_equals",
            params={"key": conditions_data["event_flag"], "value": True},
        ))
    
    if "turn_minimum" in conditions_data:
        conditions.append(PlotBeatCondition(
            type="state_equals",
            params={"key": "turn_count", "value": conditions_data["turn_minimum"], "operator": "gte"},
        ))
    
    if "npc_interaction" in conditions_data:
        conditions.append(PlotBeatCondition(
            type="npc_present",
            params={"npc_id": conditions_data["npc_interaction"]},
        ))
    
    if "item_held" in conditions_data:
        conditions.append(PlotBeatCondition(
            type="state_equals",
            params={"key": f"has_item_{conditions_data['item_held']}", "value": True},
        ))
    
    if "quest_stage" in conditions_data:
        quest_data = conditions_data["quest_stage"]
        if isinstance(quest_data, dict):
            conditions.append(PlotBeatCondition(
                type="quest_stage",
                params={
                    "quest_id": quest_data.get("quest", ""),
                    "stage": quest_data.get("stage", 0),
                },
            ))
    
    if "trust_threshold" in conditions_data:
        trust_data = conditions_data["trust_threshold"]
        if isinstance(trust_data, dict):
            conditions.append(PlotBeatCondition(
                type="state_equals",
                params={
                    "key": f"trust_{trust_data.get('npc', '')}",
                    "value": trust_data.get("below", 0),
                    "operator": "lt",
                },
            ))
    
    return conditions


def _parse_effects(effects_data: List[Dict[str, Any]]) -> List[PlotBeatEffect]:
    """Parse effects from YAML data."""
    effects = []
    
    for effect_data in effects_data:
        effect_type = effect_data.get("type", "")
        params = _extract_effect_params(effect_data)
        
        mapped_type = _map_effect_type(effect_type)
        
        effects.append(PlotBeatEffect(
            type=mapped_type,
            params=params,
        ))
    
    return effects


def _map_effect_type(yaml_type: str) -> str:
    """Map YAML effect type to schema effect type."""
    type_map = {
        "set_flag": "set_state",
        "npc_hint": "add_memory",
        "narrative": "emit_event",
        "unlock_location": "set_state",
        "advance_quest": "advance_quest",
        "add_known_fact": "add_known_fact",
        "change_relationship": "change_relationship",
        "emit_event": "emit_event",
    }
    return type_map.get(yaml_type, yaml_type)


def _extract_effect_params(effect_data: Dict[str, Any]) -> Dict[str, Any]:
    """Extract parameters from effect data, excluding 'type' key."""
    params = {}
    for key, value in effect_data.items():
        if key != "type":
            params[key] = value
    return params
