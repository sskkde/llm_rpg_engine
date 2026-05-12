"""Content pack validator - validates content pack integrity."""

from __future__ import annotations

from typing import Any, List, Optional, Set

from llm_rpg.models.content_pack import (
    CONDITIONS,
    EFFECTS,
    ContentPackDefinition,
    ContentValidationIssue,
    ContentValidationReport,
    FactionDefinition,
    PlotBeatCondition,
    PlotBeatDefinition,
)


class ContentValidator:
    """Validates content pack integrity and correctness."""
    
    def validate_id_uniqueness(
        self,
        factions: List[FactionDefinition],
        plot_beats: List[PlotBeatDefinition],
    ) -> List[ContentValidationIssue]:
        """Validate that all IDs are unique within their content type.
        
        Args:
            factions: List of faction definitions
            plot_beats: List of plot beat definitions
            
        Returns:
            List of validation issues for duplicate IDs
        """
        issues: List[ContentValidationIssue] = []
        
        seen_faction_ids: Set[str] = set()
        for faction in factions:
            if faction.id in seen_faction_ids:
                issues.append(ContentValidationIssue(
                    severity="error",
                    message=f"Duplicate faction ID: {faction.id}",
                    path=f"factions/{faction.id}",
                    code="DUPLICATE_FACTION_ID",
                ))
            seen_faction_ids.add(faction.id)
        
        seen_beat_ids: Set[str] = set()
        for beat in plot_beats:
            if beat.id in seen_beat_ids:
                issues.append(ContentValidationIssue(
                    severity="error",
                    message=f"Duplicate plot beat ID: {beat.id}",
                    path=f"plot_beats/{beat.id}",
                    code="DUPLICATE_PLOT_BEAT_ID",
                ))
            seen_beat_ids.add(beat.id)
        
        return issues
    
    def validate_reference_integrity(
        self,
        factions: List[FactionDefinition],
        plot_beats: List[PlotBeatDefinition],
        npcs: Optional[List[Any]] = None,
        locations: Optional[List[Any]] = None,
        quests: Optional[List[Any]] = None,
    ) -> List[ContentValidationIssue]:
        """Validate that all references point to existing entities.
        
        Args:
            factions: List of faction definitions
            plot_beats: List of plot beat definitions
            npcs: List of NPC definitions (optional)
            locations: List of location definitions (optional)
            quests: List of quest definitions (optional)
            
        Returns:
            List of validation issues for broken references
        """
        issues: List[ContentValidationIssue] = []
        
        faction_ids = {f.id for f in factions}
        
        for faction in factions:
            for rel in faction.relationships:
                if rel.target_faction_id not in faction_ids:
                    issues.append(ContentValidationIssue(
                        severity="error",
                        message=f"Faction '{faction.id}' references unknown faction '{rel.target_faction_id}'",
                        path=f"factions/{faction.id}/relationships/{rel.target_faction_id}",
                        code="INVALID_FACTION_REFERENCE",
                    ))
        
        npc_ids = {n.id for n in npcs} if npcs else set()
        location_ids = {l.id for l in locations} if locations else set()
        quest_ids = {q.id for q in quests} if quests else set()
        
        for beat in plot_beats:
            for condition in beat.conditions:
                cond_issues = self._validate_condition_references(
                    condition, beat.id, npc_ids, location_ids, quest_ids
                )
                issues.extend(cond_issues)
        
        return issues
    
    def _validate_condition_references(
        self,
        condition: PlotBeatCondition,
        beat_id: str,
        npc_ids: Set[str],
        location_ids: Set[str],
        quest_ids: Set[str],
    ) -> List[ContentValidationIssue]:
        """Validate references within a condition."""
        issues: List[ContentValidationIssue] = []
        
        if condition.type == "npc_present":
            npc_id = condition.params.get("npc_id", "")
            if npc_id and npc_ids and npc_id not in npc_ids:
                issues.append(ContentValidationIssue(
                    severity="error",
                    message=f"Plot beat '{beat_id}' references unknown NPC '{npc_id}'",
                    path=f"plot_beats/{beat_id}/conditions/npc_present",
                    code="INVALID_NPC_REFERENCE",
                ))
        
        elif condition.type == "location_is":
            location_id = condition.params.get("location_id", "")
            if location_id and location_ids and location_id not in location_ids:
                issues.append(ContentValidationIssue(
                    severity="error",
                    message=f"Plot beat '{beat_id}' references unknown location '{location_id}'",
                    path=f"plot_beats/{beat_id}/conditions/location_is",
                    code="INVALID_LOCATION_REFERENCE",
                ))
        
        elif condition.type == "quest_stage":
            quest_id = condition.params.get("quest_id", "")
            if quest_id and quest_ids and quest_id not in quest_ids:
                issues.append(ContentValidationIssue(
                    severity="error",
                    message=f"Plot beat '{beat_id}' references unknown quest '{quest_id}'",
                    path=f"plot_beats/{beat_id}/conditions/quest_stage",
                    code="INVALID_QUEST_REFERENCE",
                ))
        
        return issues
    
    def validate_condition_whitelist(
        self,
        plot_beats: List[PlotBeatDefinition],
    ) -> List[ContentValidationIssue]:
        """Validate that all condition types are in the whitelist.
        
        Args:
            plot_beats: List of plot beat definitions
            
        Returns:
            List of validation issues for unknown condition types
        """
        issues: List[ContentValidationIssue] = []
        
        for beat in plot_beats:
            for condition in beat.conditions:
                if condition.type not in CONDITIONS:
                    issues.append(ContentValidationIssue(
                        severity="error",
                        message=f"Unknown condition type '{condition.type}' in plot beat '{beat.id}'",
                        path=f"plot_beats/{beat.id}/conditions/{condition.type}",
                        code="UNKNOWN_CONDITION_TYPE",
                    ))
        
        return issues
    
    def validate_effect_whitelist(
        self,
        plot_beats: List[PlotBeatDefinition],
    ) -> List[ContentValidationIssue]:
        """Validate that all effect types are in the whitelist.
        
        Args:
            plot_beats: List of plot beat definitions
            
        Returns:
            List of validation issues for unknown effect types
        """
        issues: List[ContentValidationIssue] = []
        
        for beat in plot_beats:
            for effect in beat.effects:
                if effect.type not in EFFECTS:
                    issues.append(ContentValidationIssue(
                        severity="error",
                        message=f"Unknown effect type '{effect.type}' in plot beat '{beat.id}'",
                        path=f"plot_beats/{beat.id}/effects/{effect.type}",
                        code="UNKNOWN_EFFECT_TYPE",
                    ))
        
        return issues
    
    def validate(self, pack: ContentPackDefinition) -> ContentValidationReport:
        """Run all validations on a content pack.
        
        Args:
            pack: Content pack to validate
            
        Returns:
            ContentValidationReport with all issues found
        """
        all_issues: List[ContentValidationIssue] = []
        
        all_issues.extend(self.validate_id_uniqueness(pack.factions, pack.plot_beats))
        all_issues.extend(self.validate_reference_integrity(pack.factions, pack.plot_beats))
        all_issues.extend(self.validate_condition_whitelist(pack.plot_beats))
        all_issues.extend(self.validate_effect_whitelist(pack.plot_beats))
        
        is_valid = not any(issue.severity == "error" for issue in all_issues)
        
        return ContentValidationReport(
            is_valid=is_valid,
            issues=all_issues,
        )
