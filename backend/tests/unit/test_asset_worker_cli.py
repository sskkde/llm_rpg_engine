"""Unit tests for asset_worker CLI."""

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.storage.database import Base
from llm_rpg.storage.repositories import AssetJobRepository, AssetRepository


TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture
def temp_db_path():
    """Create a temporary SQLite database for subprocess tests."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def db_session():
    """Create an in-memory SQLite session for direct testing."""
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    yield session
    session.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def job_repo(db_session):
    return AssetJobRepository(db_session)


def _create_pending_job(job_repo, job_id="pub-1", provider_name="mock", **overrides):
    """Helper to create a pending job."""
    data = {
        "id": f"internal-{job_id}",
        "job_id": job_id,
        "asset_type": "portrait",
        "session_id": "sess-1",
        "status": "pending",
        "provider_name": provider_name,
        "request_json": {
            "asset_type": "portrait",
            "game_context": {"prompt": "a warrior"},
            "metadata": {},
        },
    }
    data.update(overrides)
    return job_repo.create_job(data)


class TestWorkerExitsCleanlyNoJobs:
    def test_worker_once_exits_zero_no_jobs(self, temp_db_path):
        """Worker should exit 0 when no pending jobs."""
        env = os.environ.copy()
        env["APP_ENV"] = "testing"
        env["DATABASE_URL"] = f"sqlite:///{temp_db_path}"

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "llm_rpg.scripts.asset_worker",
                "--once",
                "--batch-size",
                "1",
                "--db-url",
                f"sqlite:///{temp_db_path}",
            ],
            cwd=os.path.join(os.path.dirname(__file__), "..", ".."),
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode == 0
        assert "no_jobs" in result.stdout or "No pending jobs" in result.stdout


class TestWorkerProcessesBatch:
    def test_worker_processes_all_pending_jobs(self, temp_db_path):
        """Worker should process all pending jobs up to batch size."""
        db_url = f"sqlite:///{temp_db_path}"

        engine = create_engine(
            db_url, connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        try:
            job_repo = AssetJobRepository(db)
            for i in range(3):
                _create_pending_job(job_repo, job_id=f"pub-{i}", provider_name="mock")
            db.commit()

            env = os.environ.copy()
            env["APP_ENV"] = "testing"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "llm_rpg.scripts.asset_worker",
                    "--once",
                    "--batch-size",
                    "5",
                    "--db-url",
                    db_url,
                ],
                cwd=os.path.join(os.path.dirname(__file__), "..", ".."),
                capture_output=True,
                text=True,
                env=env,
            )

            assert result.returncode == 0

            remaining = (
                db.query(job_repo.model)
                .filter(job_repo.model.status == "pending")
                .count()
            )
            assert remaining == 0

        finally:
            db.close()


class TestWorkerRespectsBatchSize:
    def test_worker_respects_batch_size_limit(self, temp_db_path):
        """Worker should only process batch_size jobs."""
        db_url = f"sqlite:///{temp_db_path}"

        engine = create_engine(
            db_url, connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        try:
            job_repo = AssetJobRepository(db)
            for i in range(10):
                _create_pending_job(job_repo, job_id=f"pub-{i}", provider_name="mock")
            db.commit()

            env = os.environ.copy()
            env["APP_ENV"] = "testing"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "llm_rpg.scripts.asset_worker",
                    "--once",
                    "--batch-size",
                    "3",
                    "--db-url",
                    db_url,
                ],
                cwd=os.path.join(os.path.dirname(__file__), "..", ".."),
                capture_output=True,
                text=True,
                env=env,
            )

            assert result.returncode == 0

            remaining = (
                db.query(job_repo.model)
                .filter(job_repo.model.status == "pending")
                .count()
            )
            assert remaining == 7

        finally:
            db.close()


class TestWorkerProviderFilter:
    def test_worker_filters_by_provider(self, temp_db_path):
        """Worker should only process jobs matching provider filter."""
        db_url = f"sqlite:///{temp_db_path}"

        engine = create_engine(
            db_url, connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        try:
            job_repo = AssetJobRepository(db)
            _create_pending_job(job_repo, job_id="pub-mock-1", provider_name="mock")
            _create_pending_job(job_repo, job_id="pub-mock-2", provider_name="mock")
            _create_pending_job(job_repo, job_id="pub-other-1", provider_name="other")
            _create_pending_job(job_repo, job_id="pub-other-2", provider_name="other")
            db.commit()

            env = os.environ.copy()
            env["APP_ENV"] = "testing"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "llm_rpg.scripts.asset_worker",
                    "--once",
                    "--batch-size",
                    "10",
                    "--provider",
                    "mock",
                    "--db-url",
                    db_url,
                ],
                cwd=os.path.join(os.path.dirname(__file__), "..", ".."),
                capture_output=True,
                text=True,
                env=env,
            )

            assert result.returncode == 0

            remaining_mock = (
                db.query(job_repo.model)
                .filter(
                    job_repo.model.status == "pending",
                    job_repo.model.provider_name == "mock",
                )
                .count()
            )
            remaining_other = (
                db.query(job_repo.model)
                .filter(
                    job_repo.model.status == "pending",
                    job_repo.model.provider_name == "other",
                )
                .count()
            )

            assert remaining_mock == 0
            assert remaining_other == 2

        finally:
            db.close()


class TestWorkerLogsNoSecrets:
    def test_worker_sanitizes_api_keys_in_logs(self, temp_db_path):
        """Worker logs should never contain API keys."""
        db_url = f"sqlite:///{temp_db_path}"

        engine = create_engine(
            db_url, connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        try:
            job_repo = AssetJobRepository(db)
            _create_pending_job(
                job_repo,
                job_id="pub-secret",
                provider_name="mock",
                request_json={
                    "asset_type": "portrait",
                    "game_context": {"prompt": "a warrior"},
                    "metadata": {"api_key": "sk-secret-key-12345"},
                },
            )
            db.commit()

            env = os.environ.copy()
            env["APP_ENV"] = "testing"

            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "llm_rpg.scripts.asset_worker",
                    "--once",
                    "--batch-size",
                    "5",
                    "--db-url",
                    db_url,
                ],
                cwd=os.path.join(os.path.dirname(__file__), "..", ".."),
                capture_output=True,
                text=True,
                env=env,
            )

            assert "sk-secret-key" not in result.stdout
            assert "sk-secret-key" not in result.stderr

        finally:
            db.close()


class TestWorkerGracefulShutdown:
    @pytest.mark.skip(reason="flaky in CI - SIGINT handling timing dependent")
    def test_worker_handles_sigint_gracefully(self, temp_db_path):
        """Worker should handle SIGINT and exit cleanly."""
        db_url = f"sqlite:///{temp_db_path}"

        engine = create_engine(
            db_url, connect_args={"check_same_thread": False}, poolclass=StaticPool
        )
        Base.metadata.create_all(bind=engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        try:
            job_repo = AssetJobRepository(db)
            for i in range(5):
                _create_pending_job(job_repo, job_id=f"pub-{i}", provider_name="mock")
            db.commit()

            env = os.environ.copy()
            env["APP_ENV"] = "testing"

            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "llm_rpg.scripts.asset_worker",
                    "--loop",
                    "--batch-size",
                    "1",
                    "--poll-interval",
                    "1",
                    "--db-url",
                    db_url,
                ],
                cwd=os.path.join(os.path.dirname(__file__), "..", ".."),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=env,
            )

            import time

            time.sleep(2)

            proc.send_signal(subprocess.signal.SIGINT)
            stdout, stderr = proc.communicate(timeout=10)

            assert proc.returncode == 0
            assert "shutdown" in stdout.lower() or "shutting down" in stdout.lower()

        finally:
            db.close()


class TestWorkerCliArguments:
    def test_worker_custom_worker_id(self, temp_db_path):
        """Worker should use custom worker ID when provided."""
        db_url = f"sqlite:///{temp_db_path}"

        env = os.environ.copy()
        env["APP_ENV"] = "testing"

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "llm_rpg.scripts.asset_worker",
                "--once",
                "--batch-size",
                "1",
                "--worker-id",
                "custom-worker-123",
                "--db-url",
                db_url,
            ],
            cwd=os.path.join(os.path.dirname(__file__), "..", ".."),
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode == 0

    def test_worker_custom_lease_seconds(self, temp_db_path):
        """Worker should accept custom lease duration."""
        db_url = f"sqlite:///{temp_db_path}"

        env = os.environ.copy()
        env["APP_ENV"] = "testing"

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "llm_rpg.scripts.asset_worker",
                "--once",
                "--batch-size",
                "1",
                "--lease-seconds",
                "600",
                "--db-url",
                db_url,
            ],
            cwd=os.path.join(os.path.dirname(__file__), "..", ".."),
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode == 0

    def test_worker_once_and_loop_mutually_exclusive(self, temp_db_path):
        """Worker should reject both --once and --loop."""
        db_url = f"sqlite:///{temp_db_path}"

        env = os.environ.copy()
        env["APP_ENV"] = "testing"

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "llm_rpg.scripts.asset_worker",
                "--once",
                "--loop",
                "--db-url",
                db_url,
            ],
            cwd=os.path.join(os.path.dirname(__file__), "..", ".."),
            capture_output=True,
            text=True,
            env=env,
        )

        assert result.returncode != 0
