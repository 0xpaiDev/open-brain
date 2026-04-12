# Open Brain — Progress

**Status**: All phases + dashboard + training/commitments V1 complete (2026-04-12) — ~1132 tests (891 backend + 234 Vitest + 7 E2E)
**Project**: 2026-03-13 → 2026-04-12 | See [HISTORY.md](HISTORY.md) for completed phases and session notes

---

## Deployment (LIVE since 2026-03-16)

**Server**: GCP e2-medium, Ubuntu 24.04, `34.118.15.81` (static IP: `open-brain-ip`)
**Domain**: `0xpai.com` (DNS at Spaceship, A record → `34.118.15.81`)
**MCP**: `.mcp.json` → `https://0xpai.com` (routes through Caddy; port 8000 is localhost-only)
**Database**: Supabase (session-mode pooler, port 5432) — migrations at head (0010)
**Services**: API + Worker + Discord bot + Web + Caddy (Docker Compose)

**Cron jobs**:
- `importance` — 3 AM daily
- `synthesis` — 2 AM Sunday
- `backup` — 3:30 AM daily
- `pulse` — 7 AM daily
- `commitment_miss` — not yet scheduled (needs Docker cron entry)

---

## Open Tech Debt

- **L3**: Hardcoded LIMIT 100 in search CTEs (`src/retrieval/search.py`). Revisit at 10k+ memories.
- **L4**: `merge_entities()` is 162 lines (`src/api/routes/entities.py`). Revisit if >200 lines.
- **S1**: Narrow `--forwarded-allow-ips=172.0.0.0/8` to exact Docker subnet after verifying Caddy setup.
- **V1**: Voice-command classifier regex is hand-tuned to real Siri phrasings seen in prod.
- **M1**: `sync_todo_to_memory()` flips `is_superseded=True` but does NOT set `supersedes_memory_id` pointer.
- **T1**: Strava OAuth token refresh is manual (6h expiry). Automate via refresh job post-MVP.
- **T2**: Commitment miss cron not yet wired into Docker scheduler service.
- **T3**: `hybrid_search()` tag filtering (tags @> query) not yet wired — column and GIN index exist but no API surface.

---

## Next Up

- **Deploy**: Run migration 0010 on prod, restart services, schedule commitment_miss cron
- Configure Strava API app + env vars (STRAVA_CLIENT_ID/SECRET/VERIFY_TOKEN/ACCESS_TOKEN/REFRESH_TOKEN)
- Register Strava webhook subscription (`POST /api/v3/push_subscriptions`)
- Wire commitment_miss job into Docker scheduler (`src/jobs/commitment_miss.py`)
- Add tag filtering to `hybrid_search()` for training memory queries
- Settings page section for commitment creation (frontend)
