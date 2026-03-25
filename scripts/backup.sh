#!/usr/bin/env bash
# Open Brain — PostgreSQL backup script
#
# Usage:
#   ./scripts/backup.sh
#   BACKUP_DIR=/path/to/backups ./scripts/backup.sh
#
# Scheduled via host cron — example: daily at 3 AM
#   0 3 * * * cd /opt/open-brain && ./scripts/backup.sh >> /var/log/openbrain-backup.log 2>&1
#
# Environment variables:
#   SQLALCHEMY_URL   — Postgres connection string (required, loaded from .env if present)
#   BACKUP_DIR       — Output directory for backup files (default: ./backups)
#   RETENTION_DAYS   — Days to keep backups (default: 30)

set -euo pipefail

# ── Load .env if present ──────────────────────────────────────────────────────
if [[ -f ".env" ]]; then
    set -a
    source .env
    set +a
fi

# ── Config ────────────────────────────────────────────────────────────────────
BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
DATE=$(date +%Y%m%d-%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/open-brain-${DATE}.sql.gz"

if [[ -z "${SQLALCHEMY_URL:-}" ]]; then
    echo "ERROR: SQLALCHEMY_URL is not set" >&2
    exit 1
fi

# Convert SQLAlchemy URL to psql-compatible URL (strip driver prefix)
# e.g. postgresql+asyncpg://user:pass@host/db  →  postgresql://user:pass@host/db
PG_URL="${SQLALCHEMY_URL/+asyncpg/}"

# Validate that the URL conversion succeeded
if [[ ! "$PG_URL" == postgresql://* ]]; then
    echo "ERROR: unexpected database URL format after conversion: $PG_URL" >&2
    exit 1
fi

# ── Backup ────────────────────────────────────────────────────────────────────
mkdir -p "${BACKUP_DIR}"
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting backup → ${BACKUP_FILE}"

pg_dump "${PG_URL}" | gzip > "${BACKUP_FILE}"

BACKUP_SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Backup complete (${BACKUP_SIZE}) → ${BACKUP_FILE}"

# ── Prune old backups ─────────────────────────────────────────────────────────
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Pruning backups older than ${RETENTION_DAYS} days..."
find "${BACKUP_DIR}" -name "open-brain-*.sql.gz" -mtime "+${RETENTION_DAYS}" -delete
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Pruning complete"
