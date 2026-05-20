#!/usr/bin/env python3
"""CLI worker for processing asset generation jobs.

Supports --once (process batch then exit) and --loop (continuous polling) modes.

Usage:
    python3 -m llm_rpg.scripts.asset_worker --once --batch-size 5
    python3 -m llm_rpg.scripts.asset_worker --loop --poll-interval 2
"""

import argparse
import asyncio
import json
import logging
import os
import signal
import socket
import sys
from datetime import datetime, timezone
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from llm_rpg.assets.jobs import AssetJobRunner
from llm_rpg.assets.retry_policy import RetryPolicy
from llm_rpg.storage.database import Base, DATABASE_URL
from llm_rpg.storage.repositories import AssetJobRepository, AssetRepository


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if hasattr(record, "event"):
            log_data["event"] = record.event
        if hasattr(record, "pending"):
            log_data["pending"] = record.pending
        if hasattr(record, "processed"):
            log_data["processed"] = record.processed
        if hasattr(record, "provider"):
            log_data["provider"] = record.provider
        if hasattr(record, "worker_id"):
            log_data["worker_id"] = record.worker_id
        if hasattr(record, "job_id"):
            log_data["job_id"] = record.job_id
        if hasattr(record, "error"):
            log_data["error"] = record.error

        return json.dumps(log_data)


def setup_logging(log_level: str = "INFO") -> logging.Logger:
    """Setup structured JSON logging."""
    logger = logging.getLogger("asset_worker")
    logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))
    logger.handlers = []

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    logger.addHandler(handler)

    return logger


class WorkerShutdown:
    """Graceful shutdown handler for SIGINT/SIGTERM."""

    def __init__(self):
        self.shutdown_requested = False
        self._original_sigint = None
        self._original_sigterm = None

    def request_shutdown(self, signum, frame):
        """Signal handler that sets shutdown flag."""
        self.shutdown_requested = True

    def __enter__(self):
        self._original_sigint = signal.signal(signal.SIGINT, self.request_shutdown)
        self._original_sigterm = signal.signal(signal.SIGTERM, self.request_shutdown)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        signal.signal(signal.SIGINT, self._original_sigint or signal.SIG_DFL)
        signal.signal(signal.SIGTERM, self._original_sigterm or signal.SIG_DFL)
        return False


def create_parser() -> argparse.ArgumentParser:
    """Create argument parser for asset worker CLI."""
    parser = argparse.ArgumentParser(
        description="Process asset generation jobs from the queue.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Process one batch and exit:
    python3 -m llm_rpg.scripts.asset_worker --once --batch-size 5

  Continuous polling with custom interval:
    python3 -m llm_rpg.scripts.asset_worker --loop --poll-interval 5

  Filter by provider:
    python3 -m llm_rpg.scripts.asset_worker --once --provider mock
""",
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--once",
        action="store_true",
        help="Process one batch then exit",
    )
    mode_group.add_argument(
        "--loop",
        action="store_true",
        default=False,
        help="Continuous polling mode (default if neither --once nor --loop specified)",
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=5,
        metavar="N",
        help="Maximum jobs per batch (default: 5)",
    )

    parser.add_argument(
        "--poll-interval",
        type=int,
        default=2,
        metavar="N",
        help="Seconds between polls in loop mode (default: 2)",
    )

    parser.add_argument(
        "--provider",
        type=str,
        default=None,
        metavar="NAME",
        help="Filter jobs by provider name",
    )

    parser.add_argument(
        "--worker-id",
        type=str,
        default=None,
        metavar="ID",
        help="Worker identifier (default: hostname-pid)",
    )

    parser.add_argument(
        "--lease-seconds",
        type=int,
        default=300,
        metavar="N",
        help="Lease duration in seconds (default: 300)",
    )

    parser.add_argument(
        "--db-url",
        type=str,
        default=None,
        metavar="URL",
        help="Database URL (default: reads from DATABASE_URL env or uses SQLite)",
    )

    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level (default: INFO)",
    )

    return parser


def sanitize_for_logging(data: dict) -> dict:
    """Remove sensitive values (like API keys) from data for logging.

    Filters out values matching common API key patterns.
    """
    if not isinstance(data, dict):
        return data

    result = {}
    for key, value in data.items():
        if isinstance(value, str):
            if value.startswith("sk-") or value.startswith("api-") or value.startswith("key-"):
                result[key] = "[REDACTED]"
            elif "api_key" in key.lower() or "secret" in key.lower() or "token" in key.lower():
                result[key] = "[REDACTED]"
            else:
                result[key] = value
        elif isinstance(value, dict):
            result[key] = sanitize_for_logging(value)
        else:
            result[key] = value

    return result


def run_once_mode(
    runner: AssetJobRunner,
    batch_size: int,
    provider: Optional[str],
    logger: logging.Logger,
) -> int:
    """Run a single batch and exit."""
    logger.info(
        "Processing batch",
        extra={
            "event": "batch_start",
            "batch_size": batch_size,
            "provider": provider or "all",
        },
    )

    try:
        results = asyncio.run(runner.run_pending_batch(batch_size, provider))

        processed = len(results)
        logger.info(
            "Batch complete",
            extra={
                "event": "batch_complete",
                "processed": processed,
                "provider": provider or "all",
            },
        )

        if processed == 0:
            logger.info(
                "No pending jobs",
                extra={
                    "event": "no_jobs",
                    "provider": provider or "all",
                },
            )

        return 0

    except Exception as e:
        error_msg = str(e)
        if "sk-" in error_msg or "api-" in error_msg:
            error_msg = error_msg.replace(
                error_msg[error_msg.find("sk-"):error_msg.find("sk-") + 20],
                "[REDACTED]",
            )

        logger.error(
            f"Batch processing failed: {error_msg}",
            extra={
                "event": "batch_error",
                "error": error_msg,
            },
        )
        return 1


def run_loop_mode(
    runner: AssetJobRunner,
    batch_size: int,
    poll_interval: int,
    provider: Optional[str],
    worker_id: str,
    logger: logging.Logger,
) -> int:
    """Run continuous polling loop."""
    import time

    logger.info(
        "Starting loop mode",
        extra={
            "event": "loop_start",
            "batch_size": batch_size,
            "poll_interval": poll_interval,
            "provider": provider or "all",
            "worker_id": worker_id,
        },
    )

    with WorkerShutdown() as shutdown:
        while not shutdown.shutdown_requested:
            try:
                results = asyncio.run(runner.run_pending_batch(batch_size, provider))
                processed = len(results)

                logger.info(
                    "Tick processed",
                    extra={
                        "event": "tick",
                        "pending": batch_size - processed,  # Approximate
                        "processed": processed,
                        "provider": provider or "all",
                    },
                )

                if poll_interval > 0:
                    time.sleep(poll_interval)

            except Exception as e:
                error_msg = str(e)
                if "sk-" in error_msg:
                    error_msg = "[REDACTED]"

                logger.error(
                    f"Error in loop: {error_msg}",
                    extra={
                        "event": "loop_error",
                        "error": error_msg,
                    },
                )
                if poll_interval > 0:
                    time.sleep(poll_interval)

    logger.info(
        "Shutting down",
        extra={
            "event": "shutdown",
            "worker_id": worker_id,
        },
    )

    return 0


def main() -> int:
    """Main entry point for asset worker CLI."""
    parser = create_parser()
    args = parser.parse_args()

    logger = setup_logging(args.log_level)
    worker_id = args.worker_id or f"{socket.gethostname()}-{os.getpid()}"

    db_url = args.db_url
    if db_url is None:
        db_url = DATABASE_URL
    if db_url is None:
        db_url = "sqlite:///./asset_worker.db"

    # Create engine and session
    try:
        if "sqlite" in db_url:
            engine = create_engine(
                db_url,
                connect_args={"check_same_thread": False},
                poolclass=StaticPool,
            )
        else:
            engine = create_engine(db_url, pool_pre_ping=True)

        Base.metadata.create_all(bind=engine)

        Session = sessionmaker(bind=engine)
        db = Session()

    except Exception as e:
        logger.error(
            f"Failed to connect to database: {e}",
            extra={"event": "db_error", "error": str(e)},
        )
        return 1

    try:
        job_repo = AssetJobRepository(db)
        asset_repo = AssetRepository(db)
        retry_policy = RetryPolicy()

        runner = AssetJobRunner(
            job_repository=job_repo,
            asset_repository=asset_repo,
            retry_policy=retry_policy,
            usage_service=None,
            worker_id=worker_id,
            lease_seconds=args.lease_seconds,
            heartbeat_interval=min(30.0, args.lease_seconds / 10),
        )

        once_mode = args.once

        if once_mode:
            return run_once_mode(runner, args.batch_size, args.provider, logger)
        else:
            return run_loop_mode(
                runner,
                args.batch_size,
                args.poll_interval,
                args.provider,
                worker_id,
                logger,
            )

    except KeyboardInterrupt:
        logger.info(
            "Interrupted",
            extra={"event": "interrupted"},
        )
        return 0

    except Exception as e:
        error_msg = str(e)
        if "sk-" in error_msg or "api-" in error_msg:
            error_msg = "[REDACTED]"

        logger.error(
            f"Worker failed: {error_msg}",
            extra={"event": "worker_error", "error": error_msg},
        )
        return 1

    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
