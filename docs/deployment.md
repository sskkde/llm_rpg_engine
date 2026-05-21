# Production Deployment Guide

This guide covers deploying the LLM RPG Engine to production. Follow these steps in order for a successful deployment.

## Prerequisites

Before deploying, ensure you have the following:

### System Requirements

| Requirement | Minimum | Recommended |
|------------|---------|-------------|
| Python | 3.11+ | 3.11+ |
| Node.js | 20+ | 20+ |
| Docker | 24+ | Latest |
| PostgreSQL | 15+ with pgvector | 15+ with pgvector |
| Redis | 7+ | 7+ |
| RAM | 4GB | 8GB+ |
| Disk | 20GB | 50GB+ |

### Required Software

- **Docker** and **Docker Compose** for running PostgreSQL and Redis
- **Python 3.11+** for the backend
- **Node.js 20+** for the frontend
- **nginx** for reverse proxy and SSL termination
- **SSL certificate** for your domain (Let's Encrypt recommended)

### Domain and SSL

You need a registered domain name with SSL certificate:

```bash
# Install certbot for Let's Encrypt
sudo apt install certbot python3-certbot-nginx

# Obtain SSL certificate
sudo certbot --nginx -d yourdomain.com
```

---

## Infrastructure Setup

### 1. Docker Compose Services

The project uses Docker Compose for PostgreSQL and Redis infrastructure.

```bash
# From project root
docker-compose up -d
```

This starts:
- PostgreSQL with pgvector on port 5432
- Redis on port 6379

Verify services are healthy:

```bash
docker-compose ps

# Check PostgreSQL
docker exec llm_rpg_postgres pg_isready -U postgres

# Check Redis
docker exec llm_rpg_redis redis-cli ping
```

### 2. Environment Configuration

Copy the example environment file:

```bash
cp .env.production.example .env.production
```

Edit `.env.production` with your production values:

```bash
# Application environment
APP_ENV=production
LOG_LEVEL=INFO

# Database (use secure password!)
DATABASE_URL=postgresql://postgres:your-secure-password@postgres:5432/llm_rpg
REDIS_URL=redis://redis:6379/0

# Security (generate with: openssl rand -hex 32)
SECRET_KEY=your-generated-secret-key-minimum-32-characters
ADMIN_TOKEN=your-admin-token

# LLM Provider
OPENAI_API_KEY=your-openai-api-key
ASSET_PROVIDER=openai

# CORS (your production domain)
CORS_ORIGINS=https://yourdomain.com
```

### 3. Generate Secrets

Generate secure secrets for production:

```bash
# SECRET_KEY (JWT signing)
openssl rand -hex 32

# ADMIN_TOKEN (admin API access)
openssl rand -hex 16

# PostgreSQL password
openssl rand -hex 24
```

**Important**: Never commit real secrets to version control. Store them securely.

---

## Backend Deployment

### 1. Install Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. Run Database Migrations

```bash
cd backend
alembic upgrade head
```

This creates all required tables and installs the pgvector extension.

### 3. Seed World Content

```bash
cd backend
python -m llm_rpg.scripts.seed_content
```

This creates the default world, chapters, locations, NPCs, items, quests, and prompt templates.

### 4. Start Backend Server

For production deployment:

```bash
cd backend
APP_ENV=production uvicorn llm_rpg.main:app --host 127.0.0.1 --port 8000
```

Key points:
- Bind to `127.0.0.1` only, not `0.0.0.0`
- Use `APP_ENV=production` to disable dev endpoints
- Public traffic should reach the backend through nginx and the Next.js rewrites, not directly

### 5. Verify Backend

```bash
# Health check
curl http://127.0.0.1:8000/health

# API docs
curl -s http://127.0.0.1:8000/docs | head -20
```

---

## Frontend Deployment

### 1. Install Dependencies

```bash
cd frontend
npm ci
```

Use `npm ci` instead of `npm install` for reproducible builds.

### 2. Build Production Bundle

```bash
cd frontend
npm run build
```

This creates an optimized production build in `.next/`.

### 3. Start Production Server

```bash
cd frontend
BACKEND_API_URL=http://127.0.0.1:8000 npm run start -- -H 127.0.0.1 -p 3005
```

Key points:
- `BACKEND_API_URL` tells Next.js where to proxy API requests
- Bind to `127.0.0.1` only
- Public traffic reaches the frontend through nginx on port 443

### 4. Verify Frontend

```bash
# Homepage
curl -I http://127.0.0.1:3005

# Chinese locale (default)
curl -I http://127.0.0.1:3005/zh

# English locale
curl -I http://127.0.0.1:3005/en
```

---

## nginx Reverse Proxy

The project includes nginx configuration files in `deploy/nginx/`.

### 1. Install nginx

```bash
sudo apt install nginx
```

### 2. Copy Configuration Files

```bash
# Main nginx config
sudo cp deploy/nginx/nginx.conf /etc/nginx/nginx.conf

# SSL parameters
sudo cp deploy/nginx/ssl-params.conf /etc/nginx/ssl-params.conf

# Site configuration
sudo cp deploy/nginx/sites-available/llm-rpg /etc/nginx/sites-available/llm-rpg
sudo ln -sf /etc/nginx/sites-available/llm-rpg /etc/nginx/sites-enabled/llm-rpg

# Remove default site
sudo rm -f /etc/nginx/sites-enabled/default
```

### 3. Update Domain and SSL Paths

Edit `/etc/nginx/sites-available/llm-rpg`:

```nginx
# Replace all instances of llm.nas-1.club with your domain
server_name yourdomain.com;

# Update SSL certificate paths
ssl_certificate /etc/letsencrypt/live/yourdomain.com/fullchain.pem;
ssl_certificate_key /etc/letsencrypt/live/yourdomain.com/privkey.pem;
```

### 4. Configuration Highlights

The nginx config provides:

**Location Blocks**:
- `/` - Frontend (Next.js on port 3005)
- `/api` - Backend API (FastAPI on port 8000)
- `/streaming` - SSE streaming with longer timeouts
- `/ws` - WebSocket support
- `/health` - Health check (no rate limiting)

**SSL/TLS**:
- TLS 1.2 and 1.3 only
- Strong cipher suites
- HSTS enabled
- OCSP stapling

**Rate Limiting**:
- General: 10 requests/second
- Admin: 5 requests/second
- Streaming: 20 requests/second

**Security Headers**:
- X-Content-Type-Options: nosniff
- X-Frame-Options: SAMEORIGIN
- X-XSS-Protection: 1; mode=block
- Referrer-Policy: strict-origin-when-cross-origin

### 5. Test and Reload nginx

```bash
# Test configuration
sudo nginx -t

# Reload nginx
sudo nginx -s reload
```

---

## Verification

After deployment, verify everything works correctly.

### 1. Health Checks

```bash
# Backend health
curl https://yourdomain.com/health

# Backend admin endpoints (requires token)
curl -H "Authorization: Bearer <admin_token>" \
  https://yourdomain.com/admin/health

curl -H "Authorization: Bearer <admin_token>" \
  https://yourdomain.com/admin/release-readiness
```

### 2. Frontend Access

```bash
# Homepage
curl -I https://yourdomain.com

# Chinese locale
curl -I https://yourdomain.com/zh

# English locale
curl -I https://yourdomain.com/en
```

### 3. Database Connection

```bash
# Check database content
docker exec llm_rpg_postgres psql -U postgres -d llm_rpg -c "SELECT COUNT(*) FROM worlds;"
docker exec llm_rpg_postgres psql -U postgres -d llm_rpg -c "SELECT COUNT(*) FROM users;"
```

### 4. Redis Connection

```bash
docker exec llm_rpg_redis redis-cli ping
```

### 5. API Documentation

Visit `https://yourdomain.com/docs` for Swagger UI API documentation.

### 6. Admin Panel

Visit `https://yourdomain.com/zh/admin` for the admin panel. Requires authentication.

---

## Rollback Strategy

If deployment fails or issues are discovered, follow this rollback procedure.

### 1. Code Rollback

```bash
# Identify previous good commit
git log --oneline -10

# Revert to previous version
git checkout <previous-commit-hash>
```

### 2. Database Restore

If database changes caused issues:

```bash
# Stop backend
# (kill the uvicorn process)

# Restore from backup
zcat /var/backups/llm_rpg/db_YYYYMMDD.sql.gz | \
  docker exec -i llm_rpg_postgres psql -U postgres -d llm_rpg

# Restart backend
cd backend
APP_ENV=production uvicorn llm_rpg.main:app --host 127.0.0.1 --port 8000
```

See `docs/backup.md` for detailed backup and restore procedures.

### 3. Service Restart

Restart both backend and frontend to ensure consistency:

```bash
# Stop old processes
pkill -f "uvicorn llm_rpg.main:app"
pkill -f "next start"

# Start backend
cd backend
APP_ENV=production uvicorn llm_rpg.main:app --host 127.0.0.1 --port 8000 &

# Start frontend
cd frontend
BACKEND_API_URL=http://127.0.0.1:8000 npm run start -- -H 127.0.0.1 -p 3005 &
```

### 4. Docker Volume Restore

For complete infrastructure rollback:

```bash
# Stop services
docker-compose down

# Restore volumes
docker run --rm -v postgres_data:/data -v /var/backups/llm_rpg:/backup \
  alpine tar -xzf /backup/postgres_volume_YYYYMMDD.tar.gz -C /data

docker run --rm -v redis_data:/data -v /var/backups/llm_rpg:/backup \
  alpine tar -xzf /backup/redis_volume_YYYYMMDD.tar.gz -C /data

# Start services
docker-compose up -d
```

---

## Common Issues

### Backend Won't Start

Check environment variables:
```bash
cd backend
cat .env
```

Verify database connection:
```bash
docker exec llm_rpg_postgres psql -U postgres -d llm_rpg -c "SELECT 1;"
```

### Frontend Build Fails

Clear cache and rebuild:
```bash
cd frontend
rm -rf .next node_modules
npm ci
npm run build
```

### API Returns CORS Errors

Add your domain to `CORS_ORIGINS` in `.env.production`:
```bash
CORS_ORIGINS=https://yourdomain.com,https://www.yourdomain.com
```

Also update the backend's `DEFAULT_CORS_ORIGINS` in `llm_rpg/main.py` or set via environment.

### nginx Returns 502

Check if backend and frontend are running:
```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:3005
```

Check nginx error logs:
```bash
sudo tail -f /var/log/nginx/error.log
```

---

## Security Checklist

Before going live:

- [ ] Change all default passwords
- [ ] Generate new `SECRET_KEY` and `ADMIN_TOKEN`
- [ ] Set `APP_ENV=production`
- [ ] Configure `CORS_ORIGINS` for your domain only
- [ ] Enable HTTPS and redirect HTTP to HTTPS
- [ ] Set up database backups
- [ ] Configure firewall (allow only 80, 443, SSH)
- [ ] Review nginx security headers
- [ ] Disable debug endpoints (automatic in production mode)
- [ ] Keep secrets out of version control

---

## Monitoring

### Log Locations

| Service | Log Path |
|---------|----------|
| Backend stdout | systemd journal or process output |
| Frontend stdout | systemd journal or process output |
| nginx access | `/var/log/nginx/access.log` |
| nginx error | `/var/log/nginx/error.log` |
| PostgreSQL | `docker logs llm_rpg_postgres` |
| Redis | `docker logs llm_rpg_redis` |

### Health Check Endpoints

| Endpoint | Purpose |
|----------|---------|
| `/health` | Basic backend health |
| `/admin/health` | Detailed health check (requires auth) |
| `/admin/metrics` | Application metrics (requires auth) |
| `/admin/release-readiness` | Pre-release validation (requires auth) |

---

## Additional Resources

- [Backup and Restore Procedures](backup.md)
- [Release Checklist](release_checklist.md)
- [Project README](../README.md)
- [API Documentation](https://yourdomain.com/docs)
