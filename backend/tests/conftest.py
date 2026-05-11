"""
Pytest configuration and fixtures for LLM RPG Engine tests.

This module provides:
- Mock LLM provider for tests (no real API keys required)
- Test database fixtures using SQLite
- FastAPI test client
- Common test utilities
"""

import os

# Set APP_ENV to testing BEFORE any other imports
os.environ["APP_ENV"] = "testing"
# Only set DATABASE_URL to SQLite if not already configured (e.g., for pgvector tests)
if "DATABASE_URL" not in os.environ:
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"

import pytest
import uuid
from typing import Generator, Dict, Any
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

# Import the FastAPI app
from llm_rpg.main import app


# =============================================================================
# Mock LLM Provider
# =============================================================================

class MockLLMProvider:
    """
    Mock LLM provider for testing.
    Returns predictable responses without requiring real API keys.
    """
    
    def __init__(self):
        self.responses: Dict[str, Any] = {}
        self.call_count = 0
        self.last_prompt = None
    
    def set_response(self, key: str, response: Any):
        """Set a predefined response for a specific prompt pattern."""
        self.responses[key] = response
    
    def generate(self, prompt: str, **kwargs) -> str:
        """Generate a mock response."""
        self.call_count += 1
        self.last_prompt = prompt
        
        # Return predefined response if available
        for key, response in self.responses.items():
            if key in prompt.lower():
                return response
        
        # Default responses based on prompt content
        if "narrative" in prompt.lower() or "describe" in prompt.lower():
            return "The ancient square stretches before you, cobblestones worn smooth by centuries."
        elif "action" in prompt.lower() or "decision" in prompt.lower():
            return '{"action": "observe", "target": "surroundings", "reasoning": "Gathering information"}'
        elif "summary" in prompt.lower():
            return "A brief summary of recent events."
        else:
            return "Mock LLM response"
    
    def generate_json(self, prompt: str, **kwargs) -> Dict[str, Any]:
        """Generate a mock JSON response."""
        text = self.generate(prompt, **kwargs)
        try:
            import json
            return json.loads(text)
        except json.JSONDecodeError:
            return {"response": text}


@pytest.fixture
def mock_llm_provider() -> MockLLMProvider:
    """Fixture providing a mock LLM provider."""
    return MockLLMProvider()


@pytest.fixture(autouse=True)
def mock_openai_env(monkeypatch):
    """Automatically mock OpenAI environment variables in tests."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-api-key")
    monkeypatch.setenv("APP_ENV", "testing")


# =============================================================================
# Test Database Fixtures
# =============================================================================

# Use in-memory SQLite for tests
TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="session")
def engine():
    """Create a SQLAlchemy engine for testing."""
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    from llm_rpg.storage.database import Base
    Base.metadata.create_all(bind=engine)

    yield engine
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(engine) -> Generator[Session, None, None]:
    """Create a fresh database session for each test."""
    connection = engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection)()
    
    yield session
    
    session.close()
    transaction.rollback()
    connection.close()


# =============================================================================
# FastAPI Test Client
# =============================================================================

@pytest.fixture
def client(engine) -> Generator[TestClient, None, None]:
    """Create a FastAPI test client with test database."""
    from llm_rpg.storage.database import get_db
    
    def override_get_db():
        connection = engine.connect()
        session = sessionmaker(bind=connection)()
        try:
            yield session
        finally:
            session.close()
            connection.close()
    
    app.dependency_overrides[get_db] = override_get_db
    
    with TestClient(app) as test_client:
        yield test_client
    
    app.dependency_overrides.clear()


# =============================================================================
# Test Data Fixtures
# =============================================================================

@pytest.fixture
def sample_game_id() -> str:
    """Generate a sample game ID."""
    return f"game_{uuid.uuid4().hex[:8]}"


@pytest.fixture
def sample_session_id() -> str:
    """Generate a sample session ID."""
    return str(uuid.uuid4())


@pytest.fixture
def sample_player_action() -> str:
    """Return a sample player action."""
    return "观察四周"


# =============================================================================
# Core System Fixtures
# =============================================================================

@pytest.fixture
def retrieval_system():
    """Provide a retrieval system instance."""
    from llm_rpg.core.retrieval import RetrievalSystem
    return RetrievalSystem()


@pytest.fixture
def perspective_service():
    """Provide a perspective service instance."""
    from llm_rpg.core.perspective import PerspectiveService
    return PerspectiveService()


@pytest.fixture
def context_builder(retrieval_system, perspective_service):
    """Provide a context builder instance."""
    from llm_rpg.core.context_builder import ContextBuilder
    return ContextBuilder(retrieval_system, perspective_service)


# =============================================================================
# Async Support
# =============================================================================

@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for async tests."""
    import asyncio
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# =============================================================================
# Pytest Configuration
# =============================================================================

def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line("markers", "unit: Unit tests")
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "slow: Slow tests")


def pytest_collection_modifyitems(config, items):
    """Modify test collection to add markers based on path."""
    for item in items:
        if "integration" in item.nodeid:
            item.add_marker(pytest.mark.integration)
        elif "unit" in item.nodeid:
            item.add_marker(pytest.mark.unit)
