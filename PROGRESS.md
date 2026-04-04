# Open Brain — Progress

**Status**: All phases + dashboard update complete (2026-04-04) — 901 tests (752 backend + 142 Vitest + 7 E2E)
**Project**: 2026-03-13 → 2026-04-04 | See [HISTORY.md](HISTORY.md) for completed phases and session notes

---

## Deployment (LIVE since 2026-03-16)

**Server**: GCP e2-small, Ubuntu 24.04, `34.118.15.81`
**Database**: Supabase (session-mode pooler, port 5432) — migrations at head (0007)
**Services**: API + Worker + Discord bot (Docker Compose)

**Cron jobs**:
- `importance` — 3 AM daily
- `synthesis` — 2 AM Sunday
- `backup` — 3:30 AM daily
- `pulse` — 7 AM daily

---

## Open Tech Debt

- **L3**: Hardcoded LIMIT 100 in search CTEs (`src/retrieval/search.py`). Revisit at 10k+ memories.
- **L4**: `merge_entities()` is 162 lines (`src/api/routes/entities.py`). Revisit if >200 lines.
- **S1**: Narrow `--forwarded-allow-ips=172.0.0.0/8` to exact Docker subnet after verifying Caddy setup.

---

## Next Up

- Deploy dashboard update: run migration 0007 (todo_labels table + label column), rebuild web container
- Clean up `dash-update-plan.md` (fully implemented)
