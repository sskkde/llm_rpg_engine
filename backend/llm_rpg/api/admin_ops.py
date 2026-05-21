"""
Admin Operations API routes for LLM RPG Engine.

Provides health checks, metrics, and release-readiness endpoints.
All endpoints require admin role authentication.
"""

import os
from datetime import datetime
from typing import Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session as DBSession
from sqlalchemy import text

from ..storage.database import get_db
from ..storage.models import UserModel, SessionModel
from .auth import get_current_active_user

router = APIRouter(prefix="/admin", tags=["admin-ops"])

_start_time = datetime.utcnow()


# =============================================================================
# Helper Functions
# =============================================================================

async def require_admin(
    current_user: UserModel = Depends(get_current_active_user)
) -> UserModel:
    """
    Dependency to require admin role.

    Raises:
        HTTPException: If user is not an admin
    """
    if not current_user.is_admin:  # pyright: ignore[reportGeneralTypeIssues]
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user


def _check_db_health(db: DBSession) -> Dict[str, Any]:
    """Check database connection health."""
    try:
        # Execute a simple query to test connection
        db.execute(text("SELECT 1"))
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "error": str(e)[:100]}


def _check_redis_health() -> Dict[str, Any]:
    """Check Redis connection health."""
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        return {"status": "disabled"}
    
    try:
        from ..storage.redis_client import get_redis
        redis_client = get_redis()
        if redis_client.ping():
            return {"status": "ok"}
        return {"status": "error", "error": "Ping failed"}
    except Exception as e:
        return {"status": "error", "error": str(e)[:100]}


def _check_provider_health() -> Dict[str, Any]:
    """Check provider registry health."""
    try:
        from ..assets.provider_registry import ProviderRegistry
        registry = ProviderRegistry()
        providers = registry.list_providers()
        
        # Check if at least one provider is enabled and configured
        has_available = any(
            p.enabled and p.configured for p in providers
        )
        
        if has_available:
            return {"status": "ok", "providers": len(providers)}
        return {"status": "warning", "providers": len(providers), "message": "No providers configured"}
    except Exception as e:
        return {"status": "error", "error": str(e)[:100]}


def _get_uptime_seconds() -> int:
    """Get application uptime in seconds."""
    return int((datetime.utcnow() - _start_time).total_seconds())


def _get_active_sessions_count(db: DBSession) -> int:
    """Get count of active sessions."""
    try:
        return db.query(SessionModel).filter(
            SessionModel.status == "active"
        ).count()
    except Exception:
        return 0


def _get_rate_limit_hit_count() -> int:
    """Get rate limit hit count (placeholder)."""
    # In a real implementation, this would query the rate limit event store
    return 0


def _check_migrations(db: DBSession) -> Dict[str, Any]:
    """Check database migration status."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from alembic.migration import MigrationContext
        
        # Get current revision from database
        conn = db.connection()
        context = MigrationContext.configure(conn)
        current_rev = context.get_current_revision()
        
        # Get head revision from alembic config
        alembic_cfg = Config("alembic.ini")
        script = ScriptDirectory.from_config(alembic_cfg)
        head_rev = script.get_current_head()
        
        return {
            "current": current_rev,
            "head": head_rev,
            "up_to_date": current_rev == head_rev,
        }
    except Exception as e:
        # Fallback: check if alembic_version table exists
        try:
            result = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
            return {
                "current": result,
                "head": None,
                "up_to_date": None,  # Can't determine without alembic config
                "error": "Could not determine head revision",
            }
        except Exception:
            return {
                "current": None,
                "head": None,
                "up_to_date": False,
                "error": str(e)[:100],
            }


def _check_env_vars() -> Dict[str, bool]:
    """Check required environment variables."""
    required_vars = [
        "DATABASE_URL",
        "SECRET_KEY",
        "JWT_SECRET_KEY",
    ]
    
    optional_vars = [
        "REDIS_URL",
        "OPENAI_API_KEY",
        "APP_ENV",
    ]
    
    result = {}
    for var in required_vars:
        result[var] = bool(os.getenv(var))
    
    for var in optional_vars:
        result[var] = bool(os.getenv(var))
    
    return result


def _check_content_seeded(db: DBSession) -> Dict[str, Any]:
    """Check if content has been seeded."""
    try:
        from ..storage.models import WorldModel, NPCTemplateModel, LocationModel
        
        world_count = db.query(WorldModel).count()
        npc_count = db.query(NPCTemplateModel).count()
        location_count = db.query(LocationModel).count()
        
        # Consider seeded if at least one world exists with some content
        seeded = world_count > 0
        
        return {
            "seeded": seeded,
            "worlds": world_count,
            "npcs": npc_count,
            "locations": location_count,
        }
    except Exception as e:
        return {
            "seeded": False,
            "error": str(e)[:100],
        }


def _check_test_gate() -> Dict[str, Any]:
    """Check test gate status (placeholder)."""
    # In a real implementation, this would check if tests pass
    # For now, return a placeholder status
    return {
        "status": "ready",
        "message": "Test gate check not implemented in this endpoint",
    }


# =============================================================================
# Pydantic Models
# =============================================================================

class HealthResponse(BaseModel):
    """Health check response."""
    db: Dict[str, Any]
    redis: Dict[str, Any]
    provider: Dict[str, Any]
    uptime_seconds: int


class MetricsResponse(BaseModel):
    """Metrics response."""
    api_latency: Dict[str, Any] = Field(default_factory=dict)
    llm_calls: Dict[str, Any] = Field(default_factory=dict)
    validator: Dict[str, Any] = Field(default_factory=dict)
    turns: Dict[str, Any] = Field(default_factory=dict)
    rate_limit: Dict[str, Any] = Field(default_factory=dict)
    sessions: Dict[str, Any] = Field(default_factory=dict)


class MigrationStatus(BaseModel):
    """Migration status."""
    current: Optional[str] = None
    head: Optional[str] = None
    up_to_date: Optional[bool] = None
    error: Optional[str] = None


class ContentSeedStatus(BaseModel):
    """Content seed status."""
    seeded: bool
    worlds: Optional[int] = None
    npcs: Optional[int] = None
    locations: Optional[int] = None
    error: Optional[str] = None


class TestGateStatus(BaseModel):
    """Test gate status."""
    status: str
    message: Optional[str] = None


class ReleaseReadinessResponse(BaseModel):
    """Release readiness response."""
    migrations: MigrationStatus
    content: ContentSeedStatus
    env_vars: Dict[str, bool]
    test_gate: TestGateStatus


# =============================================================================
# Endpoints
# =============================================================================

@router.get("/health", response_model=HealthResponse)
def get_health(
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Get system health status.
    
    Returns health status for:
    - Database connection
    - Redis connection (if configured)
    - Provider registry
    - Application uptime
    
    Requires admin role.
    """
    return HealthResponse(
        db=_check_db_health(db),
        redis=_check_redis_health(),
        provider=_check_provider_health(),
        uptime_seconds=_get_uptime_seconds(),
    )


@router.get("/metrics", response_model=MetricsResponse)
def get_metrics(
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Get system metrics.
    
    Returns metrics for:
    - API latency (placeholder)
    - LLM call count and failure rate (placeholder)
    - Validator rejection count (placeholder)
    - Turn success/failure count (placeholder)
    - Rate limit hit count
    - Active sessions count
    
    Requires admin role.
    """
    return MetricsResponse(
        api_latency={
            "avg_ms": 0,
            "p50_ms": 0,
            "p95_ms": 0,
            "p99_ms": 0,
            "count": 0,
        },
        llm_calls={
            "total_count": 0,
            "success_count": 0,
            "failure_count": 0,
            "failure_rate": 0.0,
        },
        validator={
            "rejection_count": 0,
            "validation_count": 0,
        },
        turns={
            "success_count": 0,
            "failure_count": 0,
        },
        rate_limit={
            "hit_count": _get_rate_limit_hit_count(),
        },
        sessions={
            "active_count": _get_active_sessions_count(db),
        },
    )


@router.get("/release-readiness", response_model=ReleaseReadinessResponse)
def get_release_readiness(
    current_user: UserModel = Depends(require_admin),
    db: DBSession = Depends(get_db)
):
    """
    Get release readiness status.
    
    Checks:
    - Database migration status (current vs head)
    - Content pack seeded status
    - Required environment variables
    - Test gate status
    
    Requires admin role.
    """
    migration_status = _check_migrations(db)
    content_status = _check_content_seeded(db)
    
    return ReleaseReadinessResponse(
        migrations=MigrationStatus(
            current=migration_status.get("current"),
            head=migration_status.get("head"),
            up_to_date=migration_status.get("up_to_date"),
            error=migration_status.get("error"),
        ),
        content=ContentSeedStatus(
            seeded=content_status.get("seeded", False),
            worlds=content_status.get("worlds"),
            npcs=content_status.get("npcs"),
            locations=content_status.get("locations"),
            error=content_status.get("error"),
        ),
        env_vars=_check_env_vars(),
        test_gate=TestGateStatus(
            status=_check_test_gate().get("status", "unknown"),
            message=_check_test_gate().get("message"),
        ),
    )
