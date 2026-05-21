# Release Checklist

Pre-release verification checklist for LLM RPG Engine deployments.

## Pre-Release Verification

Run all checks before every release. All items must pass.

### Automated Test Gates

- [ ] `make test-v1-release` passes
- [ ] `make test-p8` passes
- [ ] `cd frontend && npm run build` succeeds
- [ ] `cd frontend && npm run lint` passes
- [ ] `cd frontend && npx tsc --noEmit` passes
- [ ] CI pipeline green (all jobs in `.github/workflows/ci.yml`)

### Database Verification

- [ ] Database migrations applied: `cd backend && alembic upgrade head`
- [ ] Content seed script run: `cd backend && python -m llm_rpg.scripts.seed_content`
- [ ] pgvector extension installed (automatic in migrations)

### Service Health

- [ ] Docker services running: `docker-compose ps`
- [ ] PostgreSQL healthy: `docker exec llm_rpg_postgres pg_isready -U postgres`
- [ ] Redis healthy: `docker exec llm_rpg_redis redis-cli ping`

### API Health Checks

- [ ] Admin health endpoint responds: `curl http://127.0.0.1:8000/health`
- [ ] Admin release-readiness all green: `curl http://127.0.0.1:8000/admin/release-readiness`

### Content Validation

- [ ] Content pack valid: `cd backend && python -m llm_rpg.scripts.validate_content_pack ../content_packs/qinglan_xianxia`

---

## Deployment Steps

Follow these steps in order for production deployments.

### 1. Pre-Deployment

```bash
# Pull latest code
git fetch origin
git checkout main
git pull origin main

# Verify branch state
git status
git log -1 --oneline
```

### 2. Infrastructure Check

```bash
# Ensure Docker services are running
docker-compose ps

# Start if needed
docker-compose up -d
```

### 3. Backend Deployment

```bash
cd backend

# Install/update dependencies
pip install -r requirements.txt

# Run migrations
alembic upgrade head

# Seed content (idempotent)
python -m llm_rpg.scripts.seed_content

# Start backend (production mode)
APP_ENV=production uvicorn llm_rpg.main:app --host 127.0.0.1 --port 8000
```

### 4. Frontend Deployment

```bash
cd frontend

# Install dependencies
npm ci

# Build production bundle
npm run build

# Start production server
BACKEND_API_URL=http://127.0.0.1:8000 npm run start -- -H 127.0.0.1 -p 3005
```

### 5. Post-Deployment Verification

```bash
# Health check
curl http://127.0.0.1:8000/health

# API docs accessible
curl -s http://127.0.0.1:8000/docs | head -20

# Frontend loads
curl -s http://127.0.0.1:3005 | head -20
```

---

## Post-Deployment Verification

### API Endpoints

```bash
# Health endpoint
curl http://127.0.0.1:8000/health
# Expected: {"status": "healthy", ...}

# World summary
curl http://127.0.0.1:8000/world/summary
# Expected: JSON with world content counts

# Admin release readiness
curl -H "Authorization: Bearer <admin_token>" http://127.0.0.1:8000/admin/release-readiness
# Expected: All checks green
```

### Frontend Load

```bash
# Homepage
curl -I http://127.0.0.1:3005
# Expected: HTTP/1.1 200 OK

# Chinese locale (default)
curl -I http://127.0.0.1:3005/zh
# Expected: HTTP/1.1 200 OK

# English locale
curl -I http://127.0.0.1:3005/en
# Expected: HTTP/1.1 200 OK
```

### Admin Panel Access

```bash
# Admin panel (requires authentication)
curl -I http://127.0.0.1:3005/zh/admin
# Expected: HTTP/1.1 200 OK (or redirect to login)
```

### Database Connection

```bash
# Verify database connectivity
docker exec llm_rpg_postgres psql -U postgres -d llm_rpg -c "SELECT COUNT(*) FROM users;"
# Expected: Count of registered users

docker exec llm_rpg_postgres psql -U postgres -d llm_rpg -c "SELECT COUNT(*) FROM worlds;"
# Expected: Count of worlds (should be >= 1 after seed)
```

### Redis Connection

```bash
# Verify Redis connectivity
docker exec llm_rpg_redis redis-cli ping
# Expected: PONG

docker exec llm_rpg_redis redis-cli info server | grep redis_version
# Expected: Redis version info
```

---

## Rollback Plan

If deployment fails or critical issues are found, follow this rollback procedure.

### 1. Code Rollback

```bash
# Identify previous good commit
git log --oneline -10

# Revert to previous commit
git revert HEAD --no-edit

# Or reset to specific commit (WARNING: destroys commits)
git reset --hard <commit-hash>

# Push rollback
git push origin main --force  # Only if necessary
```

### 2. Database Restore

```bash
# Stop backend service
# (kill the uvicorn process or stop via process manager)

# Restore from backup
cat /var/backups/llm_rpg/db_YYYYMMDD.sql.gz | docker exec -i llm_rpg_postgres psql -U postgres -d llm_rpg

# Restart backend
cd backend
APP_ENV=production uvicorn llm_rpg.main:app --host 127.0.0.1 --port 8000
```

### 3. Docker Rollback

```bash
# If Docker image was updated, rollback to previous version
docker-compose down
docker-compose up -d

# If volume corruption suspected
docker-compose down -v  # WARNING: destroys data
# Restore volumes from backup
docker-compose up -d
```

### 4. Full System Rollback

```bash
# 1. Stop all services
docker-compose down

# 2. Restore volumes from backup
docker run --rm -v postgres_data:/data -v /var/backups/llm_rpg:/backup alpine tar -xzf /backup/postgres_volume_YYYYMMDD.tar.gz -C /data
docker run --rm -v redis_data:/data -v /var/backups/llm_rpg:/backup alpine tar -xzf /backup/redis_volume_YYYYMMDD.tar.gz -C /data

# 3. Checkout previous code version
git checkout <previous-commit-hash>

# 4. Reinstall dependencies
cd backend && pip install -r requirements.txt
cd frontend && npm ci && npm run build

# 5. Start services
docker-compose up -d
cd backend && APP_ENV=production uvicorn llm_rpg.main:app --host 127.0.0.1 --port 8000 &
cd frontend && BACKEND_API_URL=http://127.0.0.1:8000 npm run start -- -H 127.0.0.1 -p 3005 &

# 6. Verify rollback
curl http://127.0.0.1:8000/health
```

---

## Emergency Contacts

| Role | Contact |
|------|---------|
| Backend Lead | [TBD] |
| Frontend Lead | [TBD] |
| DevOps | [TBD] |
| On-call | [TBD] |

---

## Release Notes Template

```markdown
## Release vX.Y.Z - YYYY-MM-DD

### Summary
Brief description of release contents.

### Changes
- Feature: Description
- Fix: Description
- Refactor: Description

### Breaking Changes
- None / Description of breaking changes

### Database Migrations
- alembic revision XXXX: Description

### Configuration Changes
- New environment variables: LIST_HERE
- Deprecated variables: LIST_HERE

### Deployment Notes
- Special instructions for this release

### Rollback Instructions
1. Step 1
2. Step 2

### Verification
- [ ] Health check passes
- [ ] Frontend loads
- [ ] Admin panel accessible
```
