# Production Deploy Guide

Quick reference for updating the VM after pushing changes.

---

## SSH into the VM

```bash
ssh shu@<your-vm-ip>
cd ~/open-brain
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
