import os
from typing import Optional, Generator

from sqlalchemy import create_engine, event
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session

APP_ENV = os.getenv("APP_ENV", "development")
DATABASE_URL = os.getenv("DATABASE_URL")

if APP_ENV == "testing":
    DATABASE_URL = DATABASE_URL or "sqlite:///:memory:"
    engine = create_engine(
        DATABASE_URL,
        connect_args={"check_same_thread": False},
        echo=False,
    )
elif DATABASE_URL and "postgresql" in DATABASE_URL:
    engine = create_engine(
        DATABASE_URL,
        echo=False,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )
    
    @event.listens_for(engine, "connect")
    def enable_pgvector(dbapi_conn, connection_record):
        with dbapi_conn.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
        dbapi_conn.commit()
else:
    raise RuntimeError(
        f"Production/Development mode requires PostgreSQL. "
        f"Please set DATABASE_URL environment variable with a PostgreSQL connection string. "
        f"Current APP_ENV: {APP_ENV}, DATABASE_URL: {DATABASE_URL or 'not set'}"
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    Base.metadata.create_all(bind=engine)


def get_engine():
    return engine
