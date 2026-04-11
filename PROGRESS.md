# Open Brain — Progress

**Status**: All phases + dashboard + chat + todo/pulse sync + UI polish + voice command endpoint + web voice unification complete (2026-04-11) — ~1098 tests (883 backend + 208 Vitest + 7 E2E)
**Project**: 2026-03-13 → 2026-04-11 | See [HISTORY.md](HISTORY.md) for completed phases and session notes

---

## Deployment (LIVE since 2026-03-16)

**Server**: GCP e2-medium, Ubuntu 24.04, `34.118.15.81` (static IP: `open-brain-ip`)
**Domain**: `0xpai.com` (DNS at Spaceship, A record → `34.118.15.81`)
**MCP**: `.mcp.json` → `https://0xpai.com` (routes through Caddy; port 8000 is localhost-only)
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
- **V1**: Voice-command classifier regex is hand-tuned to real Siri phrasings seen in prod. Expand as new phrasings slip through (watch `voice_command_intent intent=memory` log lines for legitimate create/complete dictations falling to memory).

---

## Next Up

- Clean up obsolete plan docs (`dash-update-plan.md`, `docs/chat-implementation-plan.md`)
- Narrow `--forwarded-allow-ips` to exact Docker subnet (S1 tech debt)
- Fix the stray todo from 2026-04-11 testing where Haiku returned `due_date=2025-04-09` (bad row still in DB)
- Monitor voice endpoint intent-classification accuracy; extend regex as new Siri phrasings emerge
