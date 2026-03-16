#!/usr/bin/env bash
# Open Brain — PostgreSQL restore script
#
# Usage:
#   ./scripts/restore.sh backups/open-brain-20260315-030000.sql.gz
#   ./scripts/restore.sh backups/open-brain-20260315-030000.sql.gz postgresql://user:pass@host/testdb
#
# WARNING: This will DROP and re-create all tables in the target database.
# Always restore to a test database first to verify integrity.
#
# Environment variables:
#   SQLALCHEMY_URL   — Target Postgres URL (loaded from .env if present, or override via 2nd arg)

set -euo pipefail

# ── Load .env if present ──────────────────────────────────────────────────────
if [[ -f ".env" ]]; then
    set -a
    source .env
    set +a
fi

# ── Args ──────────────────────────────────────────────────────────────────────
BACKUP_FILE="${1:-}"
TARGET_URL="${2:-${SQLALCHEMY_URL:-}}"

if [[ -z "${BACKUP_FILE}" ]]; then
    echo "Usage: $0 <backup-file.sql.gz> [target-url]" >&2
    exit 1
fi

if [[ ! -f "${BACKUP_FILE}" ]]; then
    echo "ERROR: Backup file not found: ${BACKUP_FILE}" >&2
    exit 1
fi

if [[ -z "${TARGET_URL}" ]]; then
    echo "ERROR: No target URL provided. Set SQLALCHEMY_URL or pass as 2nd argument." >&2
    exit 1
fi

# Convert SQLAlchemy URL to psql-compatible URL
PG_URL="${TARGET_URL/+asyncpg/}"

# ── Confirm ───────────────────────────────────────────────────────────────────
echo "WARNING: This will restore ${BACKUP_FILE} to the target database."
echo "Target: ${PG_URL%%@*}@[REDACTED]"
read -rp "Type 'yes' to continue: " confirm
if [[ "${confirm}" != "yes" ]]; then
    echo "Aborted."
    exit 0
fi

# ── Restore ───────────────────────────────────────────────────────────────────
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting restore from ${BACKUP_FILE}..."
gunzip -c "${BACKUP_FILE}" | psql "${PG_URL}"
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Restore complete"

# ── Verify ────────────────────────────────────────────────────────────────────
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Verifying table counts..."
psql "${PG_URL}" -c "
SELECT schemaname, tablename, pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY tablename;
"
