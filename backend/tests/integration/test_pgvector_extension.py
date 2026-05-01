import pytest
import os
import uuid
from typing import Optional

pytestmark = pytest.mark.integration


def is_postgres_available() -> bool:
    try:
        import psycopg2
        database_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/llm_rpg")
        conn = psycopg2.connect(database_url)
        conn.close()
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def postgres_skip():
    if not is_postgres_available():
        pytest.skip("PostgreSQL not available - skipping pgvector tests")


@pytest.fixture
def pgvector_db(postgres_skip):
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker, Session
    from llm_rpg.storage.database import Base
    
    database_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/llm_rpg")
    engine = create_engine(database_url, echo=False)
    
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    
    yield session
    
    session.close()
    Base.metadata.drop_all(bind=engine)


class TestPgvectorExtension:
    def test_pgvector_extension_available(self, postgres_skip):
        import psycopg2
        database_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/llm_rpg")
        conn = psycopg2.connect(database_url)
        cur = conn.cursor()
        cur.execute("SELECT * FROM pg_extension WHERE extname = 'vector'")
        result = cur.fetchone()
        cur.close()
        conn.close()
        
        if result is None:
            pytest.skip("pgvector extension not installed in PostgreSQL")
        assert result is not None

    def test_vector_type_operations(self, postgres_skip):
        import psycopg2
        from pgvector.psycopg2 import register_vector
        
        database_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/llm_rpg")
        conn = psycopg2.connect(database_url)
        register_vector(conn)
        
        cur = conn.cursor()
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        
        cur.execute("DROP TABLE IF EXISTS test_vectors")
        cur.execute("CREATE TABLE test_vectors (id serial PRIMARY KEY, embedding vector(3))")
        
        cur.execute("INSERT INTO test_vectors (embedding) VALUES (%s), (%s), (%s)",
                    ([1.0, 2.0, 3.0], [4.0, 5.0, 6.0], [1.1, 2.1, 3.1]))
        conn.commit()
        
        cur.execute("SELECT * FROM test_vectors ORDER BY embedding <-> %s LIMIT 1",
                    ([1.0, 2.0, 3.0],))
        result = cur.fetchone()
        
        cur.execute("DROP TABLE test_vectors")
        conn.commit()
        cur.close()
        conn.close()
        
        assert result is not None
        assert result[0] == 1

    def test_vector_distance_operations(self, postgres_skip):
        import psycopg2
        from pgvector.psycopg2 import register_vector
        
        database_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/llm_rpg")
        conn = psycopg2.connect(database_url)
        register_vector(conn)
        
        cur = conn.cursor()
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        
        cur.execute("DROP TABLE IF EXISTS test_distances")
        cur.execute("CREATE TABLE test_distances (id serial PRIMARY KEY, embedding vector(3))")
        
        cur.execute("INSERT INTO test_distances (embedding) VALUES (%s), (%s)",
                    ([1.0, 0.0, 0.0], [0.0, 1.0, 0.0]))
        conn.commit()
        
        cur.execute("SELECT embedding <=> %s as distance FROM test_distances ORDER BY distance",
                    ([1.0, 0.0, 0.0],))
        results = cur.fetchall()
        
        cur.execute("DROP TABLE test_distances")
        conn.commit()
        cur.close()
        conn.close()
        
        assert len(results) == 2
        assert results[0][0] == 0.0

    def test_vector_index_creation(self, postgres_skip):
        import psycopg2
        
        database_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/llm_rpg")
        conn = psycopg2.connect(database_url)
        cur = conn.cursor()
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        
        cur.execute("DROP TABLE IF EXISTS test_index_vectors")
        cur.execute("CREATE TABLE test_index_vectors (id serial PRIMARY KEY, embedding vector(384))")
        cur.execute("CREATE INDEX ON test_index_vectors USING ivfflat (embedding vector_l2_ops)")
        conn.commit()
        
        cur.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'test_index_vectors'")
        result = cur.fetchone()
        
        cur.execute("DROP TABLE test_index_vectors")
        conn.commit()
        cur.close()
        conn.close()
        
        assert result is not None

    def test_memory_fact_with_embedding(self, pgvector_db):
        from llm_rpg.storage.repositories import MemoryFactRepository
        from llm_rpg.storage.models import SessionModel, UserModel, WorldModel
        
        db = pgvector_db
        
        world = WorldModel(code="test_world", name="Test World")
        db.add(world)
        db.commit()
        
        user = UserModel(username=f"test_{uuid.uuid4().hex[:8]}", email="test@test.com")
        db.add(user)
        db.commit()
        
        session = SessionModel(user_id=user.id, world_id=world.id)
        db.add(session)
        db.commit()
        
        repo = MemoryFactRepository(db)
        fact_data = {
            "session_id": session.id,
            "fact_type": "knowledge",
            "fact_key": "test_fact",
            "fact_value": "test value",
            "embedding": [0.1, 0.2, 0.3, 0.4, 0.5],
        }
        fact = repo.create(fact_data)
        
        assert fact is not None
        assert fact.id is not None
        assert fact.embedding is not None
        assert len(fact.embedding) == 5

    def test_memory_summary_with_embedding(self, pgvector_db):
        from llm_rpg.storage.repositories import MemorySummaryRepository
        from llm_rpg.storage.models import SessionModel, UserModel, WorldModel
        
        db = pgvector_db
        
        world = WorldModel(code="test_world2", name="Test World 2")
        db.add(world)
        db.commit()
        
        user = UserModel(username=f"test2_{uuid.uuid4().hex[:8]}", email="test2@test.com")
        db.add(user)
        db.commit()
        
        session = SessionModel(user_id=user.id, world_id=world.id)
        db.add(session)
        db.commit()
        
        repo = MemorySummaryRepository(db)
        summary_data = {
            "session_id": session.id,
            "scope_type": "session",
            "summary_text": "Test summary",
            "embedding": [0.5, 0.4, 0.3, 0.2, 0.1],
        }
        summary = repo.create(summary_data)
        
        assert summary is not None
        assert summary.id is not None
        assert summary.embedding is not None

    def test_embedding_json_storage(self, pgvector_db):
        from llm_rpg.storage.repositories import MemoryFactRepository
        from llm_rpg.storage.models import SessionModel, UserModel, WorldModel
        
        db = pgvector_db
        
        world = WorldModel(code="test_world3", name="Test World 3")
        db.add(world)
        db.commit()
        
        user = UserModel(username=f"test3_{uuid.uuid4().hex[:8]}", email="test3@test.com")
        db.add(user)
        db.commit()
        
        session = SessionModel(user_id=user.id, world_id=world.id)
        db.add(session)
        db.commit()
        
        repo = MemoryFactRepository(db)
        large_embedding = [float(i) / 100.0 for i in range(384)]
        
        fact_data = {
            "session_id": session.id,
            "fact_type": "large_embedding_test",
            "fact_key": "large_fact",
            "fact_value": "large value",
            "embedding": large_embedding,
        }
        fact = repo.create(fact_data)
        
        fetched = repo.get_by_id(fact.id)
        assert fetched is not None
        assert fetched.embedding is not None
        assert len(fetched.embedding) == 384


class TestPgvectorWithSQLAlchemy:
    def test_sqlalchemy_vector_column(self, postgres_skip):
        from sqlalchemy import create_engine, Column, String, JSON
        from sqlalchemy.orm import declarative_base, Session
        from sqlalchemy.dialects.postgresql import ARRAY, FLOAT
        
        database_url = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/llm_rpg")
        engine = create_engine(database_url)
        Base = declarative_base()
        
        class TestEmbedding(Base):
            __tablename__ = "test_sqlalchemy_embeddings"
            id = Column(String, primary_key=True)
            text = Column(String)
            embedding = Column(JSON)
        
        Base.metadata.create_all(engine)
        
        with Session(engine) as session:
            test_emb = TestEmbedding(
                id=str(uuid.uuid4()),
                text="test text",
                embedding=[0.1, 0.2, 0.3, 0.4, 0.5]
            )
            session.add(test_emb)
            session.commit()
            
            fetched = session.query(TestEmbedding).first()
            assert fetched is not None
            assert fetched.embedding is not None
            assert len(fetched.embedding) == 5
        
        Base.metadata.drop_all(engine)
