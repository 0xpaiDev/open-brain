# Open Brain — Progress

**Status**: All phases + dashboard update + project tagging + chat + voice + todo sync + mobile UI fixes complete (2026-04-08) — 1017 tests (823 backend + 185 Vitest + 7 E2E + 2 pre-existing skip)
**Project**: 2026-03-13 → 2026-04-08 | See [HISTORY.md](HISTORY.md) for completed phases and session notes

---

## Deployment (LIVE since 2026-03-16)

**Server**: GCP e2-medium, Ubuntu 24.04, `34.118.55.10` (static IP: `open-brain-ip`)
**Domain**: `0xpai.com` (DNS at Spaceship → needs A record update to `34.118.55.10`)
**Database**: Supabase (session-mode pooler, port 5432) — migrations at head (0009)
**Services**: API + Worker + Discord bot + Web + Caddy (Docker Compose)

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

- Update DNS A record at Spaceship: `0xpai.com` → `34.118.55.10`
- Fix pre-existing task-list test failure (`web/__tests__/components/task-list.test.tsx:716` — done section grouped collapsibles)
- Clean up obsolete plan docs (`dash-update-plan.md`, `docs/chat-implementation-plan.md`)
- Narrow `--forwarded-allow-ips` to exact Docker subnet (S1 tech debt)
