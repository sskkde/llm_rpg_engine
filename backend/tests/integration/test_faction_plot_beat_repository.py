"""Integration tests for FactionRepository and PlotBeatRepository."""

import pytest
from sqlalchemy.orm import Session

from llm_rpg.storage.repositories import FactionRepository, PlotBeatRepository
from llm_rpg.storage.models import WorldModel, FactionModel, PlotBeatModel


@pytest.fixture
def test_world(db_session: Session) -> WorldModel:
    """Create a test world for use in tests."""
    world = WorldModel(
        code="test_world",
        name="Test World",
        genre="fantasy",
        status="active"
    )
    db_session.add(world)
    db_session.commit()
    db_session.refresh(world)
    return world


class TestFactionRepository:
    """Tests for FactionRepository."""

    def test_list_by_world_empty(self, db_session: Session, test_world: WorldModel):
        """Test listing factions when none exist."""
        repo = FactionRepository(db_session)
        factions = repo.list_by_world(test_world.id)
        assert factions == []

    def test_create_and_list_faction(self, db_session: Session, test_world: WorldModel):
        """Test creating a faction and listing it."""
        repo = FactionRepository(db_session)
        
        faction_data = {
            "logical_id": "faction_001",
            "world_id": test_world.id,
            "name": "Test Faction",
            "ideology": {"core_belief": "honor"},
            "goals": [{"goal_id": "g1", "description": "Expand territory"}],
            "relationships": [{"target_faction_id": "faction_002", "relationship_type": "ally"}],
            "visibility": "public",
            "status": "active"
        }
        
        created = repo.create(faction_data)
        assert created.id is not None
        assert created.logical_id == "faction_001"
        assert created.name == "Test Faction"
        
        listed = repo.list_by_world(test_world.id)
        assert len(listed) == 1
        assert listed[0].logical_id == "faction_001"

    def test_get_by_logical_id(self, db_session: Session, test_world: WorldModel):
        """Test getting a faction by logical_id."""
        repo = FactionRepository(db_session)
        
        repo.create({
            "logical_id": "faction_001",
            "world_id": test_world.id,
            "name": "Test Faction"
        })
        
        found = repo.get_by_logical_id(test_world.id, "faction_001")
        assert found is not None
        assert found.name == "Test Faction"
        
        not_found = repo.get_by_logical_id(test_world.id, "nonexistent")
        assert not_found is None

    def test_upsert_definition_create(self, db_session: Session, test_world: WorldModel):
        """Test upsert creates new faction when not exists."""
        repo = FactionRepository(db_session)
        
        data = {
            "logical_id": "faction_001",
            "world_id": test_world.id,
            "name": "Test Faction",
            "ideology": {"core": "test"}
        }
        
        result = repo.upsert_definition(data)
        assert result.id is not None
        assert result.logical_id == "faction_001"

    def test_upsert_definition_update(self, db_session: Session, test_world: WorldModel):
        """Test upsert updates existing faction."""
        repo = FactionRepository(db_session)
        
        repo.create({
            "logical_id": "faction_001",
            "world_id": test_world.id,
            "name": "Original Name"
        })
        
        updated = repo.upsert_definition({
            "logical_id": "faction_001",
            "world_id": test_world.id,
            "name": "Updated Name",
            "status": "inactive"
        })
        
        assert updated.name == "Updated Name"
        assert updated.status == "inactive"

    def test_delete_by_logical_id(self, db_session: Session, test_world: WorldModel):
        """Test deleting a faction by logical_id."""
        repo = FactionRepository(db_session)
        
        repo.create({
            "logical_id": "faction_001",
            "world_id": test_world.id,
            "name": "Test Faction"
        })
        
        deleted = repo.delete_by_logical_id(test_world.id, "faction_001")
        assert deleted is True
        
        found = repo.get_by_logical_id(test_world.id, "faction_001")
        assert found is None
        
        not_deleted = repo.delete_by_logical_id(test_world.id, "nonexistent")
        assert not_deleted is False

    def test_json_fields_round_trip(self, db_session: Session, test_world: WorldModel):
        """Test that JSON fields survive round-trip."""
        repo = FactionRepository(db_session)
        
        complex_ideology = {
            "core_beliefs": ["honor", "duty"],
            "forbidden_actions": ["betrayal", "cowardice"]
        }
        complex_goals = [
            {"goal_id": "g1", "description": "Conquer north", "priority": 90},
            {"goal_id": "g2", "description": "Build alliances", "priority": 50}
        ]
        complex_relationships = [
            {"target_faction_id": "f2", "relationship_type": "ally", "score": 80},
            {"target_faction_id": "f3", "relationship_type": "enemy", "score": -60}
        ]
        
        created = repo.create({
            "logical_id": "faction_complex",
            "world_id": test_world.id,
            "name": "Complex Faction",
            "ideology": complex_ideology,
            "goals": complex_goals,
            "relationships": complex_relationships
        })
        
        found = repo.get_by_logical_id(test_world.id, "faction_complex")
        assert found is not None
        assert found.ideology == complex_ideology
        assert found.goals == complex_goals
        assert found.relationships == complex_relationships

    def test_logical_id_unique_constraint(self, db_session: Session, test_world: WorldModel):
        """Test that logical_id must be unique within a world."""
        repo = FactionRepository(db_session)
        
        repo.create({
            "logical_id": "faction_001",
            "world_id": test_world.id,
            "name": "First Faction"
        })
        
        with pytest.raises(Exception):
            repo.create({
                "logical_id": "faction_001",
                "world_id": test_world.id,
                "name": "Second Faction"
            })


class TestPlotBeatRepository:
    """Tests for PlotBeatRepository."""

    def test_list_by_world_empty(self, db_session: Session, test_world: WorldModel):
        """Test listing plot beats when none exist."""
        repo = PlotBeatRepository(db_session)
        beats = repo.list_by_world(test_world.id)
        assert beats == []

    def test_create_and_list_plot_beat(self, db_session: Session, test_world: WorldModel):
        """Test creating a plot beat and listing it."""
        repo = PlotBeatRepository(db_session)
        
        beat_data = {
            "logical_id": "beat_001",
            "world_id": test_world.id,
            "title": "Test Plot Beat",
            "conditions": [{"type": "fact_known", "params": {"fact": "test"}}],
            "effects": [{"type": "emit_event", "params": {"event": "test_event"}}],
            "priority": 50,
            "visibility": "conditional",
            "status": "pending"
        }
        
        created = repo.create(beat_data)
        assert created.id is not None
        assert created.logical_id == "beat_001"
        assert created.title == "Test Plot Beat"
        
        listed = repo.list_by_world(test_world.id)
        assert len(listed) == 1
        assert listed[0].logical_id == "beat_001"

    def test_get_by_logical_id(self, db_session: Session, test_world: WorldModel):
        """Test getting a plot beat by logical_id."""
        repo = PlotBeatRepository(db_session)
        
        repo.create({
            "logical_id": "beat_001",
            "world_id": test_world.id,
            "title": "Test Beat"
        })
        
        found = repo.get_by_logical_id(test_world.id, "beat_001")
        assert found is not None
        assert found.title == "Test Beat"
        
        not_found = repo.get_by_logical_id(test_world.id, "nonexistent")
        assert not_found is None

    def test_list_candidates(self, db_session: Session, test_world: WorldModel):
        """Test listing plot beat candidates by status."""
        repo = PlotBeatRepository(db_session)
        
        repo.create({
            "logical_id": "beat_001",
            "world_id": test_world.id,
            "title": "Pending Beat 1",
            "status": "pending",
            "priority": 30
        })
        repo.create({
            "logical_id": "beat_002",
            "world_id": test_world.id,
            "title": "Pending Beat 2",
            "status": "pending",
            "priority": 70
        })
        repo.create({
            "logical_id": "beat_003",
            "world_id": test_world.id,
            "title": "Active Beat",
            "status": "active",
            "priority": 50
        })
        
        pending = repo.list_candidates(test_world.id, "pending")
        assert len(pending) == 2
        assert pending[0].priority == 70
        assert pending[1].priority == 30
        
        active = repo.list_candidates(test_world.id, "active")
        assert len(active) == 1
        assert active[0].title == "Active Beat"

    def test_upsert_definition_create(self, db_session: Session, test_world: WorldModel):
        """Test upsert creates new plot beat when not exists."""
        repo = PlotBeatRepository(db_session)
        
        data = {
            "logical_id": "beat_001",
            "world_id": test_world.id,
            "title": "Test Beat"
        }
        
        result = repo.upsert_definition(data)
        assert result.id is not None
        assert result.logical_id == "beat_001"

    def test_upsert_definition_update(self, db_session: Session, test_world: WorldModel):
        """Test upsert updates existing plot beat."""
        repo = PlotBeatRepository(db_session)
        
        repo.create({
            "logical_id": "beat_001",
            "world_id": test_world.id,
            "title": "Original Title"
        })
        
        updated = repo.upsert_definition({
            "logical_id": "beat_001",
            "world_id": test_world.id,
            "title": "Updated Title",
            "status": "completed"
        })
        
        assert updated.title == "Updated Title"
        assert updated.status == "completed"

    def test_delete_by_logical_id(self, db_session: Session, test_world: WorldModel):
        """Test deleting a plot beat by logical_id."""
        repo = PlotBeatRepository(db_session)
        
        repo.create({
            "logical_id": "beat_001",
            "world_id": test_world.id,
            "title": "Test Beat"
        })
        
        deleted = repo.delete_by_logical_id(test_world.id, "beat_001")
        assert deleted is True
        
        found = repo.get_by_logical_id(test_world.id, "beat_001")
        assert found is None
        
        not_deleted = repo.delete_by_logical_id(test_world.id, "nonexistent")
        assert not_deleted is False

    def test_json_fields_round_trip(self, db_session: Session, test_world: WorldModel):
        """Test that JSON fields survive round-trip."""
        repo = PlotBeatRepository(db_session)
        
        complex_conditions = [
            {"type": "fact_known", "params": {"fact": "player_visited_castle"}},
            {"type": "state_equals", "params": {"key": "chapter", "value": 2}}
        ]
        complex_effects = [
            {"type": "add_known_fact", "params": {"fact": "secret_revealed"}},
            {"type": "advance_quest", "params": {"quest_id": "q1", "step": 3}}
        ]
        
        created = repo.create({
            "logical_id": "beat_complex",
            "world_id": test_world.id,
            "title": "Complex Beat",
            "conditions": complex_conditions,
            "effects": complex_effects
        })
        
        found = repo.get_by_logical_id(test_world.id, "beat_complex")
        assert found is not None
        assert found.conditions == complex_conditions
        assert found.effects == complex_effects

    def test_logical_id_unique_constraint(self, db_session: Session, test_world: WorldModel):
        """Test that logical_id must be unique within a world."""
        repo = PlotBeatRepository(db_session)
        
        repo.create({
            "logical_id": "beat_001",
            "world_id": test_world.id,
            "title": "First Beat"
        })
        
        with pytest.raises(Exception):
            repo.create({
                "logical_id": "beat_001",
                "world_id": test_world.id,
                "title": "Second Beat"
            })


class TestCrossWorldIsolation:
    """Tests for ensuring data isolation between worlds."""

    def test_factions_isolated_by_world(self, db_session: Session):
        """Test that factions are isolated between worlds."""
        world1 = WorldModel(code="world1", name="World 1")
        world2 = WorldModel(code="world2", name="World 2")
        db_session.add_all([world1, world2])
        db_session.commit()
        db_session.refresh(world1)
        db_session.refresh(world2)
        
        repo = FactionRepository(db_session)
        
        repo.create({
            "logical_id": "shared_id",
            "world_id": world1.id,
            "name": "World 1 Faction"
        })
        repo.create({
            "logical_id": "shared_id",
            "world_id": world2.id,
            "name": "World 2 Faction"
        })
        
        w1_faction = repo.get_by_logical_id(world1.id, "shared_id")
        w2_faction = repo.get_by_logical_id(world2.id, "shared_id")
        
        assert w1_faction is not None
        assert w2_faction is not None
        assert w1_faction.name == "World 1 Faction"
        assert w2_faction.name == "World 2 Faction"

    def test_plot_beats_isolated_by_world(self, db_session: Session):
        """Test that plot beats are isolated between worlds."""
        world1 = WorldModel(code="world1", name="World 1")
        world2 = WorldModel(code="world2", name="World 2")
        db_session.add_all([world1, world2])
        db_session.commit()
        db_session.refresh(world1)
        db_session.refresh(world2)
        
        repo = PlotBeatRepository(db_session)
        
        repo.create({
            "logical_id": "shared_id",
            "world_id": world1.id,
            "title": "World 1 Beat"
        })
        repo.create({
            "logical_id": "shared_id",
            "world_id": world2.id,
            "title": "World 2 Beat"
        })
        
        w1_beat = repo.get_by_logical_id(world1.id, "shared_id")
        w2_beat = repo.get_by_logical_id(world2.id, "shared_id")
        
        assert w1_beat is not None
        assert w2_beat is not None
        assert w1_beat.title == "World 1 Beat"
        assert w2_beat.title == "World 2 Beat"
