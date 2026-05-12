"""Content Pack Schema - Pydantic v2 models for content pack definitions.

This module defines the schema for content packs, including:
- Content pack manifest and definition
- Faction definitions with goals and relationships
- Plot beat definitions with conditions and effects
- Validation models for content pack integrity
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


CONDITIONS: List[str] = [
    "fact_known",
    "state_equals",
    "state_in",
    "quest_stage",
    "npc_present",
    "location_is",
]

EFFECTS: List[str] = [
    "add_known_fact",
    "advance_quest",
    "set_state",
    "emit_event",
    "change_relationship",
    "add_memory",
]


class PlotBeatVisibility(str, Enum):
    """Visibility level for plot beats."""
    HIDDEN = "hidden"
    CONDITIONAL = "conditional"
    REVEALED = "revealed"


class ContentPackManifest(BaseModel):
    """Metadata about a content pack."""
    id: str = Field(..., description="Unique identifier for the content pack")
    name: str = Field(..., description="Human-readable name")
    version: str = Field(..., description="Version string (semver recommended)")
    description: str = Field(default="", description="Description of the content pack")
    author: str = Field(default="", description="Author or organization name")
    created_at: datetime = Field(
        default_factory=datetime.now,
        description="Creation timestamp"
    )


class FactionGoalDefinition(BaseModel):
    """A goal that a faction is pursuing."""
    goal_id: str = Field(..., description="Unique identifier for this goal")
    description: str = Field(..., description="Human-readable goal description")
    priority: int = Field(default=0, ge=0, le=100, description="Priority (0-100, higher = more important)")
    status: str = Field(default="active", description="Goal status: active, completed, abandoned")


class FactionRelationshipDefinition(BaseModel):
    """A relationship between two factions."""
    target_faction_id: str = Field(..., description="ID of the target faction")
    relationship_type: str = Field(
        default="neutral",
        description="Type of relationship: ally, enemy, neutral, rival, vassal"
    )
    score: int = Field(
        default=0,
        ge=-100,
        le=100,
        description="Relationship score (-100 to 100)"
    )


class FactionDefinition(BaseModel):
    """Complete definition of a faction within a content pack."""
    id: str = Field(..., description="Unique faction identifier")
    name: str = Field(..., description="Human-readable faction name")
    world_id: str = Field(..., description="World this faction belongs to")
    ideology: str = Field(default="", description="Faction ideology or belief system")
    goals: List[FactionGoalDefinition] = Field(
        default_factory=list,
        description="List of faction goals"
    )
    relationships: List[FactionRelationshipDefinition] = Field(
        default_factory=list,
        description="Relationships with other factions"
    )
    visibility: str = Field(
        default="public",
        description="Visibility: public, hidden, secret"
    )


class PlotBeatCondition(BaseModel):
    """A condition that must be met for a plot beat to activate."""
    type: str = Field(..., description="Condition type (must be in CONDITIONS whitelist)")
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Condition parameters"
    )


class PlotBeatEffect(BaseModel):
    """An effect that occurs when a plot beat is triggered."""
    type: str = Field(..., description="Effect type (must be in EFFECTS whitelist)")
    params: Dict[str, Any] = Field(
        default_factory=dict,
        description="Effect parameters"
    )


class PlotBeatDefinition(BaseModel):
    """Complete definition of a plot beat within a content pack."""
    id: str = Field(..., description="Unique plot beat identifier")
    title: str = Field(..., description="Human-readable title")
    world_id: str = Field(..., description="World this plot beat belongs to")
    conditions: List[PlotBeatCondition] = Field(
        default_factory=list,
        description="Conditions that must be met for activation"
    )
    effects: List[PlotBeatEffect] = Field(
        default_factory=list,
        description="Effects that occur when triggered"
    )
    priority: int = Field(default=0, ge=0, le=100, description="Priority (0-100)")
    visibility: PlotBeatVisibility = Field(
        default=PlotBeatVisibility.CONDITIONAL,
        description="Visibility level"
    )
    status: str = Field(
        default="pending",
        description="Status: pending, active, completed, skipped"
    )


class ContentFileRefs(BaseModel):
    """References to expected YAML files in a content pack."""
    factions: List[str] = Field(
        default_factory=list,
        description="List of faction YAML file paths"
    )
    plot_beats: List[str] = Field(
        default_factory=list,
        description="List of plot beat YAML file paths"
    )
    npcs: List[str] = Field(
        default_factory=list,
        description="List of NPC YAML file paths"
    )
    locations: List[str] = Field(
        default_factory=list,
        description="List of location YAML file paths"
    )
    items: List[str] = Field(
        default_factory=list,
        description="List of item YAML file paths"
    )
    quests: List[str] = Field(
        default_factory=list,
        description="List of quest YAML file paths"
    )


class ContentPackDefinition(BaseModel):
    """Complete definition of a content pack."""
    manifest: ContentPackManifest = Field(..., description="Pack metadata")
    factions: List[FactionDefinition] = Field(
        default_factory=list,
        description="Faction definitions"
    )
    plot_beats: List[PlotBeatDefinition] = Field(
        default_factory=list,
        description="Plot beat definitions"
    )
    file_refs: Optional[ContentFileRefs] = Field(
        default=None,
        description="References to source YAML files"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metadata"
    )


class ContentValidationIssue(BaseModel):
    """A single validation issue found in content pack."""
    severity: str = Field(
        ...,
        description="Severity level: error, warning, info"
    )
    message: str = Field(..., description="Human-readable error message")
    path: str = Field(..., description="Path to the problematic content")
    code: str = Field(..., description="Error code for programmatic handling")


class ContentValidationReport(BaseModel):
    """Complete validation report for a content pack."""
    is_valid: bool = Field(..., description="Whether the content pack is valid")
    issues: List[ContentValidationIssue] = Field(
        default_factory=list,
        description="List of validation issues"
    )

    def has_errors(self) -> bool:
        """Check if there are any error-level issues."""
        return any(issue.severity == "error" for issue in self.issues)

    def has_warnings(self) -> bool:
        """Check if there are any warning-level issues."""
        return any(issue.severity == "warning" for issue in self.issues)
