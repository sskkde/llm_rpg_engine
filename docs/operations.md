# LLM RPG Engine Operations Guide

Day-to-day operations reference for running and maintaining the LLM RPG Engine. This guide covers service management, backups, monitoring, incident response, maintenance, and scaling.

For initial deployment, see `docs/deployment.md`.

---

## 1. Service Management

### 1.1 Infrastructure Services

PostgreSQL and Redis run as Docker containers managed by `docker-compose.yml`.

**Start infrastructure:**

```bash
docker-compose up -d
```

**Stop infrastructure:**

```bash
docker-compose down          # Stop containers, keep data
docker-compose down -v       # Stop containers AND delete volumes (data loss)
```

**Check status:**

```bash
docker-compose ps
```

| Service | Container | Port | Volume | Healthcheck |
|---------|-----------|------|--------|-------------|
| PostgreSQL 15 + pgvector | `llm_rpg_postgres` | 5432 | `postgres_data` | `pg_isready -U postgres` (every 5s) |
| Redis 7 | `llm_rpg_redis` | 6379 | `redis_data` | `redis-cli ping` (every 5s) |

**View infrastructure logs:**

```bash
docker-compose logs -f              # All services
docker-compose logs -f postgres     # PostgreSQL only
docker-compose logs -f redis        # Redis only
```

### 1.2 Backend Service

The backend is a FastAPI application served by uvicorn. The only supported entrypoint is `llm_rpg.main:app`.

**Development mode:**

```bash
cd backend
uvicorn llm_rpg.main:app --reload --port 8000
```

**Production mode:**

```bash
cd backend
APP_ENV=production uvicorn llm_rpg.main:app --host 127.0.0.1 --port 8000
```

The backend binds to `127.0.0.1` in production. Public traffic reaches it through the Next.js server rewrites, not by exposing port 8000 directly.

**Restart backend (production):**

```bash
# Stop the running uvicorn process, then:
cd backend
APP_ENV=production uvicorn llm_rpg.main:app --host 127.0.0.1 --port 8000
```

When restarting public services, always restart both backend and frontend in the same round so both processes load the same code version.

### 1.3 Frontend Service

The frontend is a Next.js 16 application on Node.js.

**Development mode:**

```bash
cd frontend
npm run dev              # Starts on port 3005
```

**Production mode:**

```bash
cd frontend
npm run build
BACKEND_API_URL=http://127.0.0.1:8000 npm run start -- -H 127.0.0.1 -p 3005
```

The production frontend binds to `127.0.0.1:3005`. Nginx forwards public traffic from `llm.nas-1.club` to this address.

**Restart frontend (production):**

```bash
# Stop the running Node process, then:
cd frontend
npm run build
BACKEND_API_URL=http://127.0.0.1:8000 npm run start -- -H 127.0.0.1 -p 3005
```

### 1.4 Full Service Restart (Production)

When deploying updates, restart both services together:

```bash
# 1. Stop backend and frontend processes

# 2. Start backend
cd backend
APP_ENV=production uvicorn llm_rpg.main:app --host 127.0.0.1 --port 8000 &

# 3. Build and start frontend
cd frontend
npm run build
BACKEND_API_URL=http://127.0.0.1:8000 npm run start -- -H 127.0.0.1 -p 3005 &
```

### 1.5 Health Check Endpoints

All admin endpoints require authentication with an admin-role user.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/health` | GET | System health: DB status, Redis status, provider status, uptime |
| `/admin/metrics` | GET | System metrics: API latency, LLM call stats, validator stats, turn stats, rate limits, active sessions |
| `/admin/release-readiness` | GET | Release readiness: migration status, content seed status, env vars, test gate |

**Quick health check from the command line:**

```bash
# Authenticate first
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=YOUR_PASSWORD" | jq -r '.access_token')

# Check health
curl -s http://127.0.0.1:8000/admin/health \
  -H "Authorization: Bearer $TOKEN" | jq

# Check metrics
curl -s http://127.0.0.1:8000/admin/metrics \
  -H "Authorization: Bearer $TOKEN" | jq

# Check release readiness
curl -s http://127.0.0.1:8000/admin/release-readiness \
  -H "Authorization: Bearer $TOKEN" | jq
```

**Interpreting `/admin/health` response:**

```json
{
  "db": {"status": "ok"},
  "redis": {"status": "ok"},
  "provider": {"status": "ok", "providers": 2},
  "uptime_seconds": 86400
}
```

- `db.status`: `ok` or `error` (with error message)
- `redis.status`: `ok`, `error`, or `disabled` (if REDIS_URL not set)
- `provider.status`: `ok`, `warning` (no providers configured), or `error`

### 1.6 Log Locations

| Service | Log Location |
|---------|-------------|
| Backend (uvicorn) | stdout/stderr of the uvicorn process |
| Frontend (Next.js) | stdout/stderr of the Node process |
| PostgreSQL | `docker-compose logs postgres` |
| Redis | `docker-compose logs redis` |
| nginx | `/var/log/nginx/` (if using nginx as reverse proxy) |

**Backend log level** is controlled by the `LOG_LEVEL` environment variable (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). Default is `INFO`.

### 1.7 Interactive API Documentation

Swagger UI is available at `http://localhost:8000/docs` when the backend is running. This is useful for debugging API calls and exploring available endpoints.

---

## 2. Backup Procedures

### 2.1 Database Backup (PostgreSQL)

Use `pg_dump` from inside the Docker container or from a network-accessible host.

**Full backup:**

```bash
docker exec llm_rpg_postgres pg_dump -U postgres llm_rpg > backup_$(date +%Y%m%d_%H%M%S).sql
```

**Compressed backup:**

```bash
docker exec llm_rpg_postgres pg_dump -U postgres --format=custom llm_rpg > backup_$(date +%Y%m%d_%H%M%S).dump
```

**Restore from SQL backup:**

```bash
cat backup_20260521_120000.sql | docker exec -i llm_rpg_postgres psql -U postgres llm_rpg
```

**Restore from custom-format backup:**

```bash
docker exec -i llm_rpg_postgres pg_restore -U postgres -d llm_rpg < backup_20260521_120000.dump
```

**Recommended backup schedule:**

| Frequency | Command | Retention |
|-----------|---------|-----------|
| Daily | `pg_dump --format=custom` | Keep 7 days |
| Weekly | `pg_dump --format=custom` | Keep 4 weeks |
| Before migrations | `pg_dump --format=custom` | Keep until next major version |

### 2.2 Redis Backup

Redis is configured with AOF persistence (`appendonly yes` in docker-compose.yml). The AOF file is stored in the `redis_data` Docker volume.

**Manual RDB snapshot:**

```bash
docker exec llm_rpg_redis redis-cli BGSAVE
```

The RDB file is written to `/data/dump.rdb` inside the container.

**Copy RDB file out of the container:**

```bash
docker cp llm_rpg_redis:/data/dump.rdb redis_backup_$(date +%Y%m%d).rdb
```

**Copy AOF file out of the container:**

```bash
docker cp llm_rpg_redis:/data/appendonlydir redis_aof_backup_$(date +%Y%m%d)/
```

**Restore Redis from RDB:**

```bash
# 1. Stop Redis
docker-compose stop redis

# 2. Copy backup file into the volume
docker cp redis_backup_20260521.rdb llm_rpg_redis:/data/dump.rdb

# 3. Start Redis
docker-compose start redis
```

> Since Redis is used for caching, losing its data is not critical. The system will repopulate caches on the next requests. However, backing up Redis avoids cold-start latency after a restore.

### 2.3 Environment Configuration Backup

The `.env` file contains secrets and configuration that cannot be regenerated.

```bash
cp backend/.env backend/.env.backup_$(date +%Y%m%d)
```

Store backups of `.env` files in a secure, encrypted location. Never commit them to version control.

Key files to back up:

| File | Location | Contents |
|------|----------|----------|
| `.env` | `backend/` | Database URL, Redis URL, API keys, JWT secret, CORS origins |
| `.env.production.example` | Project root | Production environment template |
| `alembic.ini` | `backend/` | Alembic migration configuration |

### 2.4 Content Pack Backup

Content packs are YAML-based and stored in version control, but you can also back them up explicitly:

```bash
tar czf content_packs_backup_$(date +%Y%m%d).tar.gz content_packs/
```

To validate a content pack before use:

```bash
cd backend
python -m llm_rpg.scripts.validate_content_pack ../content_packs/qinglan_xianxia
```

---

## 3. Monitoring

### 3.1 Admin API Monitoring

Use the admin endpoints for programmatic monitoring. All require admin authentication.

**`GET /admin/health`** - Component-level health checks:

| Field | What to Watch |
|-------|---------------|
| `db.status` | Should be `ok`. If `error`, database is unreachable |
| `redis.status` | `ok` is normal. `disabled` means Redis is not configured (caching off). `error` means Redis is down |
| `provider.status` | `ok` means providers available. `warning` means no providers configured (asset generation won't work) |
| `uptime_seconds` | Sudden reset indicates unexpected restart |

**`GET /admin/metrics`** - Operational metrics:

| Field | What to Watch |
|-------|---------------|
| `llm_calls.failure_rate` | Should stay below 5%. Above 10% indicates OpenAI API issues |
| `llm_calls.failure_count` | Rising count signals persistent API problems |
| `sessions.active_count` | Normal baseline for capacity planning |
| `validator.rejection_count` | High rejection rate means LLM output quality is degrading |
| `rate_limit.hit_count` | Non-zero means users are hitting rate limits |
| `turns.failure_count` | Non-zero means turn execution failures |

**`GET /admin/release-readiness`** - Deployment readiness:

| Field | What to Watch |
|-------|---------------|
| `migrations.up_to_date` | Must be `true`. `false` means pending migrations |
| `content.seeded` | Must be `true`. `false` means no game content |
| `env_vars.DATABASE_URL` | Must be `true` |
| `env_vars.SECRET_KEY` | Must be `true` |
| `env_vars.OPENAI_API_KEY` | `false` means system runs on mock provider |

### 3.2 Log Monitoring

**Backend logs to watch:**

```bash
# Filter errors
cd backend && uvicorn logs 2>&1 | grep -i error

# Watch LLM API issues
cd backend && uvicorn logs 2>&1 | grep -i "openai\|provider\|llm"

# Watch database connection issues
cd backend && uvicorn logs 2>&1 | grep -i "database\|connection\|sqlalchemy"
```

**Infrastructure logs:**

```bash
# PostgreSQL slow queries and errors
docker-compose logs postgres | grep -i "error\|fatal\|slow"

# Redis issues
docker-compose logs redis | grep -i "error\|warning"
```

### 3.3 Key Metrics to Watch

| Metric | Normal Range | Action If Abnormal |
|--------|-------------|-------------------|
| LLM call failure rate | < 2% | Check OpenAI status, verify API key, consider fallback to mock |
| LLM call latency (p95) | < 5s | Check network, OpenAI status; consider model downgrade |
| Active sessions | Baseline dependent | Scale backend if approaching resource limits |
| DB connection pool usage | < 80% of pool_size | Increase pool_size or add read replicas |
| Validator rejection rate | < 10% | Investigate prompt quality, check model performance |
| Rate limit hits | 0 per normal period | Review user behavior, adjust rate limits |
| Backend uptime | Continuous | Investigate restart causes, check OOM or crash logs |
| Disk usage (Docker volumes) | < 80% | Plan for disk expansion or data cleanup |

### 3.4 Simple Monitoring Script

A basic cron-based check you can adapt:

```bash
#!/bin/bash
# health_check.sh - Run via cron every 5 minutes

TOKEN=$(curl -s -X POST http://127.0.0.1:8000/auth/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=$ADMIN_PASSWORD" | jq -r '.access_token')

HEALTH=$(curl -s http://127.0.0.1:8000/admin/health \
  -H "Authorization: Bearer $TOKEN")

DB_STATUS=$(echo "$HEALTH" | jq -r '.db.status')
REDIS_STATUS=$(echo "$HEALTH" | jq -r '.redis.status')

if [ "$DB_STATUS" != "ok" ]; then
  echo "ALERT: Database status is $DB_STATUS" >&2
  # Send notification
fi

if [ "$REDIS_STATUS" = "error" ]; then
  echo "ALERT: Redis status is $REDIS_STATUS" >&2
  # Send notification
fi
```

---

## 4. Incident Response

### 4.1 Service Down

**Symptoms:** Frontend returns 502/503, backend is unreachable.

**Steps:**

1. **Check if the backend process is running:**
   ```bash
   ps aux | grep uvicorn
   ```

2. **Check if the frontend process is running:**
   ```bash
   ps aux | grep next
   ```

3. **Check infrastructure:**
   ```bash
   docker-compose ps
   ```
   If PostgreSQL or Redis shows as unhealthy, restart them:
   ```bash
   docker-compose restart postgres
   docker-compose restart redis
   ```

4. **Check recent logs for the crashed service:**
   ```bash
   # Backend
   journalctl -u llm-rpg-backend --since "1 hour ago" 2>/dev/null || check process output

   # Frontend
   journalctl -u llm-rpg-frontend --since "1 hour ago" 2>/dev/null || check process output
   ```

5. **Restart the affected service:**
   ```bash
   # Backend
   cd backend
   APP_ENV=production uvicorn llm_rpg.main:app --host 127.0.0.1 --port 8000 &

   # Frontend
   cd frontend
   npm run build
   BACKEND_API_URL=http://127.0.0.1:8000 npm run start -- -H 127.0.0.1 -p 3005 &
   ```

6. **Verify recovery:**
   ```bash
   curl -s http://127.0.0.1:8000/admin/health -H "Authorization: Bearer $TOKEN" | jq
   ```

### 4.2 LLM API Failure

**Symptoms:** Game turns return errors, narration fails, 500 errors on `/game/sessions/*/turn`.

**Steps:**

1. **Check OpenAI API status:**
   - Visit [status.openai.com](https://status.openai.com)
   - Check `OPENAI_API_KEY` is still valid

2. **Verify provider health via admin API:**
   ```bash
   curl -s http://127.0.0.1:8000/admin/health -H "Authorization: Bearer $TOKEN" | jq '.provider'
   ```

3. **Check metrics for failure rate:**
   ```bash
   curl -s http://127.0.0.1:8000/admin/metrics -H "Authorization: Bearer $TOKEN" | jq '.llm_calls'
   ```

4. **Short-term mitigation** - the system automatically falls back to MockLLMProvider when:
   - `OPENAI_API_KEY` is not set
   - Rate limits are exceeded
   - The API key is invalid

   To intentionally switch to mock provider:
   ```bash
   # Temporarily unset the API key to force mock fallback
   # Edit .env and comment out OPENAI_API_KEY, then restart backend
   ```

5. **If the issue is rate limiting**, wait for the rate limit window to reset (typically 1 minute for OpenAI). You can also:
   - Reduce `OPENAI_MODEL` to a cheaper/faster model
   - Implement request queuing to smooth out traffic

6. **Verify recovery** by making a test game turn once the API is available.

### 4.3 Database Corruption

**Symptoms:** SQLAlchemy errors, 500 errors on database-dependent endpoints, `pg_isready` passes but queries fail.

**Steps:**

1. **Assess the damage:**
   ```bash
   docker exec llm_rpg_postgres psql -U postgres -c "SELECT count(*) FROM alembic_version;"
   docker exec llm_rpg_postgres psql -U postgres -c "SELECT count(*) FROM worlds;"
   ```

2. **If data is partially corrupted but PostgreSQL is running:**
   ```bash
   # Backup whatever is readable
   docker exec llm_rpg_postgres pg_dump -U postgres llm_rpg > emergency_backup.sql

   # Try to repair specific tables
   docker exec llm_rpg_postgres psql -U postgres -c "REINDEX DATABASE llm_rpg;"
   ```

3. **If PostgreSQL won't start or data is severely corrupted:**
   ```bash
   # Stop the database
   docker-compose stop postgres

   # Remove the corrupted volume
   docker-compose down -v  # WARNING: removes ALL volumes including Redis

   # Or selectively remove just the postgres volume
   docker volume rm llm_rpg_engine_postgres_data

   # Start fresh
   docker-compose up -d

   # Apply migrations
   cd backend && alembic upgrade head

   # Re-seed content
   cd backend && python -m llm_rpg.scripts.seed_content
   ```

4. **Restore from backup (if available):**
   ```bash
   cat backup_20260521_120000.sql | docker exec -i llm_rpg_postgres psql -U postgres llm_rpg
   ```

### 4.4 Disk Full

**Symptoms:** Write errors in logs, PostgreSQL cannot write WAL, Redis cannot persist, 500 errors.

**Steps:**

1. **Check disk usage:**
   ```bash
   df -h
   du -sh /var/lib/docker/volumes/llm_rpg_engine_*
   ```

2. **Identify the largest consumers:**
   ```bash
   docker system df                  # Docker disk usage
   docker exec llm_rpg_postgres psql -U postgres -c "SELECT pg_size_pretty(pg_database_size('llm_rpg'));"
   ```

3. **Immediate cleanup options:**

   ```bash
   # Remove unused Docker resources
   docker system prune -f

   # Remove old Docker images
   docker image prune -a -f

   # Truncate old application logs (if logging to disk)
   find /var/log/ -name "*.log" -mtime +7 -delete

   # Vacuum PostgreSQL to reclaim space
   docker exec llm_rpg_postgres psql -U postgres -c "VACUUM FULL;"
   ```

4. **Long-term prevention:**
   - Set up log rotation (see Section 5.4)
   - Monitor disk usage with alerts at 70% and 85%
   - Archive old game session data periodically

### 4.5 Maintenance Mode

The backend supports a maintenance mode that returns 503 for all non-admin requests. This is useful during planned maintenance.

Enable or disable maintenance mode through the system settings (admin API). When enabled, only `/admin/*`, `/auth/login`, `/auth/me`, and documentation endpoints remain accessible.

---

## 5. Regular Maintenance

### 5.1 Database Migrations

Always back up the database before applying migrations.

**Check current migration status:**

```bash
cd backend
alembic current
```

**Apply pending migrations:**

```bash
cd backend
alembic upgrade head
```

**Rollback one migration:**

```bash
cd backend
alembic downgrade -1
```

**Create a new migration (after model changes):**

```bash
cd backend
alembic revision --autogenerate -m "description of change"
```

**Verify migration status via admin API:**

```bash
curl -s http://127.0.0.1:8000/admin/release-readiness \
  -H "Authorization: Bearer $TOKEN" | jq '.migrations'
```

The response shows `current` revision, `head` revision, and whether they match (`up_to_date: true`).

### 5.2 Content Pack Updates

Content packs define game worlds, NPCs, locations, quests, and more. They live in `content_packs/` as structured YAML directories.

**Validate a content pack before importing:**

```bash
cd backend
python -m llm_rpg.scripts.validate_content_pack ../content_packs/qinglan_xianxia
```

**Preview import (dry run):**

```bash
cd backend
python -m llm_rpg.scripts.import_content_pack ../content_packs/qinglan_xianxia --dry-run
```

**Import a content pack:**

```bash
cd backend
python -m llm_rpg.scripts.import_content_pack ../content_packs/qinglan_xianxia
```

**Re-seed content (idempotent):**

```bash
cd backend
python -m llm_rpg.scripts.seed_content
```

The seed script creates: 1 world, 3 chapters, 10 locations, 6 NPCs, 7 items, 4 quests, 6 event templates, 5 prompt templates, and 3 endings.

**Verify content status:**

```bash
curl -s http://127.0.0.1:8000/admin/release-readiness \
  -H "Authorization: Bearer $TOKEN" | jq '.content'
```

### 5.3 Cache Clearing

Redis is used for caching. Clearing it is safe; the system repopulates caches as needed.

**Flush all Redis data:**

```bash
docker exec llm_rpg_redis redis-cli FLUSHALL
```

**Flush a specific database (default is 0):**

```bash
docker exec llm_rpg_redis redis-cli -n 0 FLUSHDB
```

**Check Redis memory usage:**

```bash
docker exec llm_rpg_redis redis-cli INFO memory
```

**When to clear the cache:**
- After content pack imports
- After database migrations that change schema
- When stale data is suspected
- During troubleshooting of inconsistent game state

### 5.4 Log Rotation

Backend and frontend logs go to stdout/stderr. If you redirect them to files, set up logrotate.

**Example logrotate config** (`/etc/logrotate.d/llm-rpg`):

```
/var/log/llm-rpg/backend.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}

/var/log/llm-rpg/frontend.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
```

### 5.5 Database Maintenance

**Routine PostgreSQL maintenance:**

```bash
# Analyze tables for query planner optimization
docker exec llm_rpg_postgres psql -U postgres -c "ANALYZE;"

# Vacuum to reclaim space (non-blocking)
docker exec llm_rpg_postgres psql -U postgres -c "VACUUM;"

# Full vacuum for significant space reclamation (locks tables)
docker exec llm_rpg_postgres psql -U postgres -c "VACUUM FULL;"

# Check table sizes
docker exec llm_rpg_postgres psql -U postgres -c "
  SELECT relname, pg_size_pretty(pg_total_relation_size(relid))
  FROM pg_catalog.pg_statio_user_tables
  ORDER BY pg_total_relation_size(relid) DESC
  LIMIT 10;
"
```

**Recommended schedule:**

| Task | Frequency | Impact |
|------|-----------|--------|
| `ANALYZE` | Weekly | None (non-blocking) |
| `VACUUM` | Weekly | Minimal (non-blocking) |
| `VACUUM FULL` | Monthly or on demand | Locks tables, run during low traffic |
| `REINDEX` | On demand | Locks individual indexes |

---

## 6. Scaling Considerations

### 6.1 When to Add Resources

Consider scaling when you observe:

- Backend CPU consistently above 70%
- Memory usage approaching limits (watch for OOM kills)
- Database connection pool exhaustion (errors like "QueuePool limit of size X reached")
- LLM API latency causing slow user experience
- Active session count growing beyond comfortable single-process handling

### 6.2 Backend Scaling

The simplest path is running multiple uvicorn workers:

```bash
# Multiple workers on the same machine
cd backend
APP_ENV=production uvicorn llm_rpg.main:app \
  --host 127.0.0.1 --port 8000 \
  --workers 4
```

For multi-machine scaling, put backend instances behind a load balancer. Make sure:
- All instances share the same PostgreSQL database
- All instances share the same Redis instance
- JWT secrets (`SECRET_KEY`, `JWT_SECRET_KEY`) are identical across instances
- `CORS_ORIGINS` includes all frontend origins

### 6.3 Database Connection Pooling

SQLAlchemy manages a connection pool. Tune it via the `DATABASE_URL` or SQLAlchemy configuration.

Default pool settings (adjust as needed):

| Parameter | Default | When to Increase |
|-----------|---------|-----------------|
| `pool_size` | 5 | When you see "QueuePool limit" errors |
| `max_overflow` | 10 | When pool_size isn't enough for burst traffic |
| `pool_timeout` | 30s | When connections take longer to acquire |
| `pool_recycle` | 3600s | If PostgreSQL drops idle connections |

**Rule of thumb:** Total connections available = `pool_size + max_overflow`. Set this to at least 2x your expected concurrent requests.

### 6.4 Read Replicas

For read-heavy workloads (world state queries, content browsing), consider adding PostgreSQL read replicas:

1. **Set up streaming replication** on PostgreSQL
2. **Configure a read-only DATABASE_URL** for read-only queries
3. **Route write operations** to the primary and read operations to the replica

Read-heavy endpoints that benefit from replicas:
- `GET /world/state`, `GET /world/summary`
- `GET /world/chapters/*`, `GET /world/locations/*`
- `GET /admin/worlds`, `GET /admin/npc-templates` (admin content browsing)

Write endpoints that must use the primary:
- `POST /game/sessions/*/turn`
- `POST /auth/register`, `POST /auth/login`
- All `POST` and `PATCH` admin content endpoints

### 6.5 Redis Scaling

Redis is currently used for caching. Scaling options:

- **Single instance**: Sufficient for most workloads
- **Redis Cluster**: For datasets that exceed single-node memory
- **Read replicas**: Add replica instances for read-heavy cache patterns

Since Redis data is ephemeral in this system (all state lives in PostgreSQL), losing Redis only causes a temporary performance hit from cache misses.

### 6.6 Frontend Scaling

Next.js supports standalone output mode for containerized deployment:

1. Build once, deploy the `.next/standalone` output
2. Run multiple frontend instances behind a load balancer
3. Ensure `BACKEND_API_URL` points to a shared backend or backend load balancer

### 6.7 LLM API Rate Limit Awareness

OpenAI enforces rate limits per API key. If you scale to multiple backend instances sharing one key, the combined request rate might exceed limits.

**Mitigations:**
- Use separate API keys for different backend instances
- Implement request queuing to smooth traffic
- Cache LLM responses where possible (repeated similar prompts)
- Consider using cheaper models for less critical calls

---

## Quick Reference Card

| Task | Command |
|------|---------|
| Start infrastructure | `docker-compose up -d` |
| Stop infrastructure | `docker-compose down` |
| Start backend (dev) | `cd backend && uvicorn llm_rpg.main:app --reload --port 8000` |
| Start backend (prod) | `cd backend && APP_ENV=production uvicorn llm_rpg.main:app --host 127.0.0.1 --port 8000` |
| Start frontend (dev) | `cd frontend && npm run dev` |
| Start frontend (prod) | `cd frontend && npm run build && BACKEND_API_URL=http://127.0.0.1:8000 npm run start -- -H 127.0.0.1 -p 3005` |
| Apply migrations | `cd backend && alembic upgrade head` |
| Seed content | `cd backend && python -m llm_rpg.scripts.seed_content` |
| Validate content pack | `cd backend && python -m llm_rpg.scripts.validate_content_pack ../content_packs/qinglan_xianxia` |
| Backup database | `docker exec llm_rpg_postgres pg_dump -U postgres --format=custom llm_rpg > backup.dump` |
| Clear Redis cache | `docker exec llm_rpg_redis redis-cli FLUSHALL` |
| Check health | `curl -s http://127.0.0.1:8000/admin/health -H "Authorization: Bearer $TOKEN" \| jq` |
| Run backend tests | `cd backend && pytest -q` |
| Run frontend checks | `cd frontend && npm run lint && npx tsc --noEmit` |
