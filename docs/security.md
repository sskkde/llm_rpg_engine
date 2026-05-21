# LLM RPG Engine Security Documentation

This document covers security considerations for the LLM RPG Engine, including authentication, authorization, API security, data protection, LLM-specific risks, infrastructure security, and audit trails.

## Table of Contents

1. [Authentication](#authentication)
2. [Authorization](#authorization)
3. [API Security](#api-security)
4. [Data Protection](#data-protection)
5. [LLM-Specific Risks](#llm-specific-risks)
6. [Infrastructure Security](#infrastructure-security)
7. [Audit Trail](#audit-trail)

---

## Authentication

### JWT Token System

The engine uses JSON Web Tokens (JWT) for authentication with the following configuration:

- **Algorithm**: HS256
- **Token Expiration**: 24 hours (configurable via `ACCESS_TOKEN_EXPIRE_MINUTES`)
- **Secret Key**: Loaded from `JWT_SECRET_KEY` environment variable
- **Fallback**: Development mode uses `dev-secret-key-change-in-production` (must be changed in production)

```python
# backend/llm_rpg/api/auth.py
SECRET_KEY = os.getenv("JWT_SECRET_KEY", "dev-secret-key-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours
```

### Password Security

- **Hashing Algorithm**: bcrypt via passlib
- **Minimum Password Length**: 8 characters
- **Username Requirements**: 3-50 characters

```python
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
```

### Session Management

- User sessions are tracked via `SessionModel` in PostgreSQL
- Each session is associated with a user via `user_id` foreign key
- Last login timestamp is updated on successful authentication
- Registration can be disabled via system settings

### Token Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/register` | POST | Create new user account |
| `/auth/login` | POST | Authenticate and receive JWT token |
| `/auth/me` | GET | Get current user info (requires token) |

---

## Authorization

### Admin Role Check

Admin-only endpoints use the `require_admin` dependency which checks the `is_admin` flag on the user model:

```python
async def require_admin(
    current_user: UserModel = Depends(get_current_active_user)
) -> UserModel:
    if not current_user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required"
        )
    return current_user
```

### Protected Endpoints

**Admin-Only Endpoints** (require `is_admin=True`):

- `/admin/*` - World, chapter, location, NPC, item, quest, event, prompt template management
- `/admin/audit/*` - Audit log access, model call inspection, data export
- `/admin/health`, `/admin/metrics`, `/admin/release-readiness` - System health and metrics
- `/debug/*` - Debug endpoints for session inspection

**User-Scoped Endpoints** (require valid JWT):

- `/saves/*` - Save slot management (user can only access their own saves)
- `/sessions/*` - Session management (user can only access their own sessions)
- `/game/*` - Gameplay actions
- `/streaming/*` - Streaming gameplay
- `/combat/*` - Combat actions
- `/media/*` - Asset generation

### User-Scoped Session Access

Save slots and sessions are scoped to the authenticated user:

```python
# backend/llm_rpg/api/saves.py
@router.post("", response_model=SaveSlotResponse)
def create_save_slot(
    request: SaveSlotCreateRequest,
    current_user: UserModel = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    # Save slot is automatically associated with current_user.id
    slot_data = {
        "user_id": current_user.id,
        ...
    }
```

### Player Perspective Filtering

The perspective system filters information based on the viewer's knowledge:

- **Player Perspective**: Only sees what the player has experienced
- **NPC Perspective**: Limited to NPC's known facts, beliefs, and secrets
- **Narrator Perspective**: Filters hidden information from narration output
- **World Perspective**: Sees everything (admin/world engine only)

```python
# backend/llm_rpg/core/perspective.py
def build_player_perspective(
    self,
    perspective_id: str,
    player_id: str,
    known_facts: List[str] = None,
    known_rumors: List[str] = None,
    visible_scene_ids: List[str] = None,
    discovered_locations: List[str] = None,
) -> PlayerPerspective:
    ...
```

---

## API Security

### CORS Configuration

CORS origins are configured via the `CORS_ORIGINS` environment variable:

```python
# backend/llm_rpg/main.py
DEFAULT_CORS_ORIGINS = (
    "http://localhost:3005,http://127.0.0.1:3005,"
    "http://localhost:3000,http://127.0.0.1:3000,"
    "http://localhost:8000,http://127.0.0.1:8000,"
    "https://llm.nas-1.club:18080"
)

cors_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", DEFAULT_CORS_ORIGINS).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

**Production Requirement**: Set `CORS_ORIGINS` to only include your production domain(s).

### Rate Limiting

Asset generation endpoints have rate limiting with in-memory sliding window:

| Limit Type | Default | Environment Variable |
|------------|---------|---------------------|
| User per minute | 10 | `ASSET_RATE_LIMIT_USER_PER_MINUTE` |
| User per day | 200 | `ASSET_RATE_LIMIT_USER_PER_DAY` |
| Session per minute | 20 | `ASSET_RATE_LIMIT_SESSION_PER_MINUTE` |
| Provider concurrency | 3 | `ASSET_PROVIDER_CONCURRENCY_LIMIT` |

Rate limit events are recorded to the database for audit purposes and return HTTP 429 with `Retry-After` header when exceeded.

### Input Validation

All API inputs are validated via Pydantic models:

- Type validation
- Length constraints (e.g., username 3-50 chars, password min 8 chars)
- Range constraints (e.g., save slot 1-10)
- Email format validation for optional email fields

### Admin Endpoint Protection

All admin endpoints require both:
1. Valid JWT authentication
2. `is_admin=True` on the user model

Unauthorized requests receive HTTP 401. Non-admin users receive HTTP 403.

---

## Data Protection

### Environment Variable Secrets

The following secrets must be configured via environment variables:

| Variable | Purpose | Required |
|----------|---------|----------|
| `JWT_SECRET_KEY` | JWT token signing | Yes (production) |
| `SECRET_KEY` | General secret key | Yes (production) |
| `DATABASE_URL` | PostgreSQL connection | Yes |
| `OPENAI_API_KEY` | OpenAI API access | No (uses mock if unset) |
| `SYSTEM_SETTINGS_SECRET_KEY` | Encrypt stored API keys | No (required for key storage) |
| `REDIS_URL` | Redis connection | No (optional caching) |

**Never commit secrets to version control.**

### No Hardcoded API Keys

The codebase does not contain hardcoded API keys:
- OpenAI API key is loaded from `OPENAI_API_KEY` environment variable
- Mock provider is used automatically when key is not set
- Stored API keys in system settings are encrypted

### Encrypted API Key Storage

API keys stored in the database (via admin settings API) are encrypted using Fernet symmetric encryption:

```python
# backend/llm_rpg/services/settings.py
class SecretEncryptionService:
    def encrypt(self, plaintext: str) -> str:
        if not self._fernet:
            raise MissingEncryptionKeyError("SYSTEM_SETTINGS_SECRET_KEY not configured")
        return self._fernet.encrypt(plaintext.encode()).decode()
```

Only the last 4 characters of API keys are stored for display purposes.

### Database Access Control

- SQLAlchemy ORM prevents raw SQL injection
- Foreign key constraints enforce data relationships
- User-scoped queries ensure users can only access their own data

---

## LLM-Specific Risks

### Prompt Injection Prevention

The engine does not directly expose user input to LLM prompts without sanitization:
- Input is parsed and validated before inclusion in prompts
- Prompt templates are stored in the database and versioned
- Context building filters information based on perspective

### Output Validation: NarrationLeakValidator

The `NarrationLeakValidator` prevents LLM outputs from leaking forbidden information:

```python
# backend/llm_rpg/core/validation/narration_leak_validator.py
class LeakSeverity(Enum):
    EXACT_MATCH = "EXACT_MATCH"      # Forbidden text appears verbatim
    PARTIAL_MATCH = "PARTIAL_MATCH"  # Key phrases from forbidden text appear
    SUSPICIOUS = "SUSPICIOUS"        # Word overlap detected
```

**Detection Methods**:
1. Exact substring match
2. Word-level overlap analysis (25% threshold)
3. Bigram phrase detection
4. Regex pattern matching for forbidden patterns

**Forbidden Information Sources**:
- NPC secrets (not yet revealed)
- NPC hidden identities
- Private event payloads
- Explicit forbidden info list

### Hallucination Boundaries

The narration engine has deterministic fallback when LLM fails:

```python
# backend/llm_rpg/engines/narration_engine.py
class NarrationEngine:
    """
    CRITICAL: Narration cannot invent uncommitted facts.
    Must only describe what has been committed to canonical state.
    """
```

Key constraints:
- Narration consumes committed/player-visible facts only
- LLM outputs are proposals only, never mutate state directly
- Every LLM-driven point has deterministic fallback

### Perspective-Aware Information Flow

Information is filtered based on the viewer's perspective before being included in LLM context:

- NPCs cannot know information they haven't learned
- Players cannot see NPC secrets or hidden identities
- Narrator perspective filters hidden information from output

---

## Infrastructure Security

### Network Binding

Production servers must bind to `127.0.0.1` and be exposed through a reverse proxy:

```bash
# Backend (production)
cd backend && APP_ENV=production uvicorn llm_rpg.main:app --host 127.0.0.1 --port 8000

# Frontend (production)
cd frontend && npm run build && BACKEND_API_URL=http://127.0.0.1:8000 npm run start -- -H 127.0.0.1 -p 3005
```

**Never expose development servers publicly.**

### Reverse Proxy Security (nginx)

The production deployment uses nginx as a reverse proxy:
- Public traffic to `llm.nas-1.club` is forwarded to `127.0.0.1:3005`
- Backend API is not directly exposed
- HTTPS/SSL should be configured at the nginx layer

### Database Network Isolation

PostgreSQL and Redis run in Docker containers:

```yaml
# docker-compose.yml
services:
  postgres:
    ports:
      - "5432:5432"  # Consider removing port exposure for production
  redis:
    ports:
      - "6379:6379"  # Consider removing port exposure for production
```

**Production Recommendation**: Remove port exposure and use Docker internal networking.

### Maintenance Mode

The application has a maintenance mode middleware that returns HTTP 503 for non-admin requests:

```python
# backend/llm_rpg/main.py
class MaintenanceModeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if settings.maintenance_mode:
            return JSONResponse(
                status_code=503,
                content={"detail": "System is in maintenance mode"}
            )
        return await call_next(request)
```

Admin endpoints and login remain accessible during maintenance mode.

---

## Audit Trail

### Event Sourcing Audit

All game actions are recorded as immutable events:

- `EventLogModel` stores all game events
- Events are append-only (never modified)
- Enables complete history replay and debugging

### Admin API Audit Logs

Admin audit endpoints provide visibility into system operations:

| Endpoint | Description |
|----------|-------------|
| `/admin/audit/sessions/{id}/logs` | Session event logs with pagination |
| `/admin/audit/sessions/{id}/model-calls` | LLM call history |
| `/admin/audit/sessions/{id}/context-builds` | Context build audit |
| `/admin/audit/sessions/{id}/validations` | Validation results |
| `/admin/audit/sessions/{id}/errors` | Error log |
| `/admin/audit/export` | Export session audit (JSONL format) |

**Important**: Audit exports never include API keys or raw prompts containing secrets.

### LLM Call Logging

Every LLM invocation is logged with:

```python
# backend/llm_rpg/core/audit.py
class ModelCallLog(BaseModel):
    call_id: str
    session_id: str
    turn_no: int
    provider: str
    model_name: str
    prompt_type: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_estimate: Optional[float]
    latency_ms: int
    success: bool
    error_message: Optional[str]
```

Model call logs are persisted to PostgreSQL via `ModelCallAuditLogModel`.

### Audit Data Sanitization

All audit data is sanitized to ensure no secrets are logged:
- API keys are never included in logs
- Raw prompts are not stored (only prompt type and metadata)
- Private payloads are filtered before export

---

## Security Checklist

### Before Production Deployment

- [ ] Set `JWT_SECRET_KEY` to a secure random string
- [ ] Set `SECRET_KEY` to a secure random string
- [ ] Set `SYSTEM_SETTINGS_SECRET_KEY` for encrypted key storage
- [ ] Configure `CORS_ORIGINS` to only include production domain(s)
- [ ] Remove or restrict Docker port exposures
- [ ] Configure HTTPS/SSL at reverse proxy layer
- [ ] Run database migrations: `alembic upgrade head`
- [ ] Seed content: `python -m llm_rpg.scripts.seed_content`
- [ ] Verify admin user exists with secure password
- [ ] Disable registration if not needed (via system settings)
- [ ] Review and restrict CORS origins

### Regular Security Maintenance

- [ ] Rotate `JWT_SECRET_KEY` periodically (invalidates all tokens)
- [ ] Review audit logs for suspicious activity
- [ ] Update dependencies for security patches
- [ ] Monitor rate limit events for abuse patterns
- [ ] Review admin access logs

---

## Incident Response

### Compromised JWT Secret

If `JWT_SECRET_KEY` is compromised:
1. Generate new secret key
2. Update environment variable
3. Restart backend server
4. All existing tokens become invalid (users must re-login)

### Compromised API Key

If an API key is compromised:
1. Revoke key at provider (e.g., OpenAI dashboard)
2. Generate new key
3. Update via admin settings API or environment variable
4. Audit usage logs for unauthorized access

### Data Breach

In case of data breach:
1. Identify scope via audit logs
2. Rotate all secrets
3. Force password reset for affected users
4. Review and patch vulnerability
5. Document incident and remediation
