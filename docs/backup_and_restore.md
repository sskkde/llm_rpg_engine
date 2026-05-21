# Backup and Restore Procedures

This document describes backup and restore procedures for the LLM RPG Engine.

## Database Backup

### Manual pg_dump

```bash
# Full database backup
docker exec llm_rpg_postgres pg_dump -U postgres -d llm_rpg > backup_$(date +%Y%m%d_%H%M%S).sql

# Compressed backup
docker exec llm_rpg_postgres pg_dump -U postgres -d llm_rpg -Fc > backup_$(date +%Y%m%d_%H%M%S).dump

# Custom format with parallel restore support
docker exec llm_rpg_postgres pg_dump -U postgres -d llm_rpg -Fd -j 4 -f backup_dir
```

### Backup Schedule Recommendation

| Type | Frequency | Retention |
|------|-----------|-----------|
| Full backup | Daily | 30 days |
| Incremental | Hourly | 7 days |
| Archive backup | Monthly | 12 months |

### Cron Job Example

```bash
# Add to crontab (crontab -e)
# Daily full backup at 2 AM
0 2 * * * docker exec llm_rpg_postgres pg_dump -U postgres -d llm_rpg | gzip > /var/backups/llm_rpg/db_$(date +\%Y\%m\%d).sql.gz

# Cleanup old backups (keep 30 days)
0 3 * * * find /var/backups/llm_rpg -name "db_*.sql.gz" -mtime +30 -delete
```

### Backup Script Example

```bash
#!/bin/bash
# /usr/local/bin/backup_llm_rpg.sh

BACKUP_DIR="/var/backups/llm_rpg"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/db_${TIMESTAMP}.sql.gz"

mkdir -p "${BACKUP_DIR}"

docker exec llm_rpg_postgres pg_dump -U postgres -d llm_rpg | gzip > "${BACKUP_FILE}"

# Verify backup
if [ -f "${BACKUP_FILE}" ] && [ -s "${BACKUP_FILE}" ]; then
    echo "Backup successful: ${BACKUP_FILE}"
    logger -t llm_rpg_backup "Backup successful: ${BACKUP_FILE}"
else
    echo "Backup FAILED"
    logger -t llm_rpg_backup "Backup FAILED"
    exit 1
fi

# Cleanup old backups
find "${BACKUP_DIR}" -name "db_*.sql.gz" -mtime +30 -delete
```

---

## Redis Backup

Redis 7 is configured with AOF (Append-Only File) persistence via `--appendonly yes`.

### RDB Snapshots

```bash
# Trigger manual RDB snapshot
docker exec llm_rpg_redis redis-cli BGSAVE

# Copy RDB file from container
docker cp llm_rpg_redis:/data/dump.rdb /var/backups/llm_rpg/redis_$(date +%Y%m%d_%H%M%S).rdb
```

### AOF Persistence

AOF is already enabled. The file is at `/data/appendonly.aof` inside the container.

```bash
# Copy AOF file
docker cp llm_rpg_redis:/data/appendonly.aof /var/backups/llm_rpg/appendonly_$(date +%Y%m%d_%H%M%S).aof

# Rewrite AOF to compact it
docker exec llm_rpg_redis redis-cli BGREWRITEAOF
```

### Redis Backup Script

```bash
#!/bin/bash
# /usr/local/bin/backup_redis.sh

BACKUP_DIR="/var/backups/llm_rpg"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

mkdir -p "${BACKUP_DIR}"

# Trigger RDB save
docker exec llm_rpg_redis redis-cli BGSAVE
sleep 5

# Copy both RDB and AOF
docker cp llm_rpg_redis:/data/dump.rdb "${BACKUP_DIR}/redis_${TIMESTAMP}.rdb"
docker cp llm_rpg_redis:/data/appendonly.aof "${BACKUP_DIR}/appendonly_${TIMESTAMP}.aof"

echo "Redis backup complete"
```

---

## Application Backup

### Environment Files

```bash
# Backup .env files (contains secrets - secure storage required)
cp backend/.env /var/backups/llm_rpg/env_backend_$(date +%Y%m%d).env
cp frontend/.env.local /var/backups/llm_rpg/env_frontend_$(date +%Y%m%d).env 2>/dev/null || true

# Production environment example
cp .env.production /var/backups/llm_rpg/env_production_$(date +%Y%m%d).env 2>/dev/null || true
```

### Content Packs

```bash
# Backup content packs directory
tar -czf /var/backups/llm_rpg/content_packs_$(date +%Y%m%d).tar.gz content_packs/
```

### Docker Volumes

```bash
# Export Docker volumes for offline backup
docker run --rm -v postgres_data:/data -v /var/backups/llm_rpg:/backup alpine tar -czf /backup/postgres_volume_$(date +%Y%m%d).tar.gz -C /data .
docker run --rm -v redis_data:/data -v /var/backups/llm_rpg:/backup alpine tar -czf /backup/redis_volume_$(date +%Y%m%d).tar.gz -C /data .
```

---

## Restore Procedures

### Database Restore

#### From SQL Dump

```bash
# Stop application services
docker-compose stop

# Restore from SQL file
cat backup.sql | docker exec -i llm_rpg_postgres psql -U postgres -d llm_rpg

# Or from compressed backup
zcat backup.sql.gz | docker exec -i llm_rpg_postgres psql -U postgres -d llm_rpg
```

#### From Custom Format Dump

```bash
# Restore from .dump file
docker cp backup.dump llm_rpg_postgres:/tmp/
docker exec llm_rpg_postgres pg_restore -U postgres -d llm_rpg -c /tmp/backup.dump

# Restore from directory format
docker cp backup_dir llm_rpg_postgres:/tmp/
docker exec llm_rpg_postgres pg_restore -U postgres -d llm_rpg -j 4 /tmp/backup_dir
```

#### Complete Database Reset and Restore

```bash
# WARNING: This destroys all data
docker exec -i llm_rpg_postgres psql -U postgres -c "DROP DATABASE IF EXISTS llm_rpg;"
docker exec -i llm_rpg_postgres psql -U postgres -c "CREATE DATABASE llm_rpg;"
docker exec -i llm_rpg_postgres psql -U postgres -d llm_rpg -c "CREATE EXTENSION IF NOT EXISTS vector;"

# Restore from backup
cat backup.sql | docker exec -i llm_rpg_postgres psql -U postgres -d llm_rpg
```

### Redis Restore

```bash
# Stop Redis
docker-compose stop redis

# Replace data files
docker cp redis_backup.rdb llm_rpg_redis:/data/dump.rdb
docker cp appendonly_backup.aof llm_rpg_redis:/data/appendonly.aof 2>/dev/null || true

# Start Redis
docker-compose start redis

# Verify
docker exec llm_rpg_redis redis-cli ping
```

### Full System Restore

1. **Stop all services**
   ```bash
   docker-compose down
   ```

2. **Restore Docker volumes**
   ```bash
   # Create volumes if needed
   docker volume create postgres_data
   docker volume create redis_data

   # Restore from backup
   docker run --rm -v postgres_data:/data -v /var/backups/llm_rpg:/backup alpine tar -xzf /backup/postgres_volume_YYYYMMDD.tar.gz -C /data
   docker run --rm -v redis_data:/data -v /var/backups/llm_rpg:/backup alpine tar -xzf /backup/redis_volume_YYYYMMDD.tar.gz -C /data
   ```

3. **Start services**
   ```bash
   docker-compose up -d
   ```

4. **Run migrations** (if needed)
   ```bash
   cd backend
   alembic upgrade head
   ```

5. **Verify restore**
   ```bash
   # Check database
   docker exec llm_rpg_postgres psql -U postgres -d llm_rpg -c "SELECT COUNT(*) FROM users;"

   # Check Redis
   docker exec llm_rpg_redis redis-cli ping
   ```

---

## Automation Ideas

### Daily Backup Cron

```bash
# /etc/cron.d/llm_rpg_backup
0 2 * * * root /usr/local/bin/backup_llm_rpg.sh >> /var/log/llm_rpg_backup.log 2>&1
30 2 * * * root /usr/local/bin/backup_redis.sh >> /var/log/llm_rpg_backup.log 2>&1
```

### Remote Backup Sync

```bash
#!/bin/bash
# Sync backups to remote storage (S3, rsync, etc.)

BACKUP_DIR="/var/backups/llm_rpg"
REMOTE="user@backup-server:/backups/llm_rpg/"

rsync -avz --delete "${BACKUP_DIR}/" "${REMOTE}"
```

### Backup Verification Script

```bash
#!/bin/bash
# Verify backup integrity

BACKUP_FILE=$1

if [ ! -f "${BACKUP_FILE}" ]; then
    echo "Backup file not found: ${BACKUP_FILE}"
    exit 1
fi

# Test SQL file
if [[ "${BACKUP_FILE}" == *.sql.gz ]]; then
    zcat "${BACKUP_FILE}" | head -100 | grep -q "PostgreSQL database dump"
    if [ $? -eq 0 ]; then
        echo "Valid PostgreSQL dump"
    else
        echo "Invalid backup file"
        exit 1
    fi
fi

echo "Backup verification passed"
```

### Monitoring and Alerts

```bash
# Add to monitoring script
BACKUP_DIR="/var/backups/llm_rpg"
MAX_AGE_HOURS=26

LATEST_BACKUP=$(find "${BACKUP_DIR}" -name "db_*.sql.gz" -type f -printf '%T@ %p\n' | sort -n | tail -1 | cut -d' ' -f2-)

if [ -z "${LATEST_BACKUP}" ]; then
    echo "CRITICAL: No database backups found"
    exit 2
fi

BACKUP_AGE=$(( ($(date +%s) - $(stat -c %Y "${LATEST_BACKUP}")) / 3600 ))

if [ ${BACKUP_AGE} -gt ${MAX_AGE_HOURS} ]; then
    echo "WARNING: Latest backup is ${BACKUP_AGE} hours old"
    exit 1
fi

echo "OK: Latest backup is ${BACKUP_AGE} hours old"
```
