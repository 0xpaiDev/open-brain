# Production Deploy Guide

Quick reference for updating the VM after pushing changes.

---

## SSH into the VM

```bash
ssh shu@<your-vm-ip>
cd /opt/open-brain
```

---

## Standard update (code changes only, no schema change)

```bash
git pull

# Rebuild and restart all running services
docker compose --profile api --profile worker --profile discord build --no-cache
docker compose --profile api --profile discord up -d
docker compose --profile worker up -d
```

> The worker is typically run via cron, not as a persistent service. Skip `worker up -d` unless you run it continuously.

---

## Update with a schema migration (new/changed DB tables)

```bash
git pull

# Run migration first, before restarting the API
docker compose --profile migrate run --rm migrate

# Then rebuild and restart services
docker compose --profile api --profile discord build --no-cache
docker compose --profile api --profile discord up -d
```

**How to tell if a migration is needed**: check if there are new files in `alembic/versions/` since the last deploy.

```bash
git log --oneline alembic/versions/
```

---

## Restart a single service (quick fix, no code change)

```bash
docker compose --profile api restart
docker compose --profile discord restart
```

---

## Check service health

```bash
# Live logs
docker logs openbrain-api --tail=50 -f
docker logs openbrain-discord --tail=50 -f

# Health endpoint
curl http://localhost:8000/health
```

---

## Emergency: stop everything

```bash
docker compose --profile api --profile discord down
```

---

## .env variables added per phase

When a new phase is deployed, check if new env vars are needed. Only `DISCORD_PULSE_USER_ID` has no default and must be set manually.

### Phase D (Morning Pulse) — add to .env if missing

```bash
# Required
DISCORD_PULSE_USER_ID=513082913521401856

# Optional — these have defaults but worth setting explicitly
MODULE_PULSE_ENABLED=true
MODULE_TODO_ENABLED=true
MODULE_RAG_CHAT_ENABLED=true
PULSE_SEND_TIME=07:00
PULSE_TIMEZONE=Europe/Vilnius   # set to your local timezone
PULSE_REPLY_WINDOW_MINUTES=240
GOOGLE_CALENDAR_CREDENTIALS_PATH=   # leave blank if not using
GOOGLE_CALENDAR_TOKEN_PATH=         # leave blank if not using
```
