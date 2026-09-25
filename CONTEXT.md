# CONTEXT.md

Current state of the build, for the team and for AI agents. Read this before starting work in an area.
Describe **state**, not history. Update your row when you merge a PR that changes what works.

## Status by vertical

| Area | Owner | Working end to end | Stubbed / not started |
|---|---|---|---|
| `voice/` (Twilio routes, bridge, MCP adapter, injection) | Person 1 | — | Everything. Files hold docstrings only. |
| `scheduler/` | Person 1 | — | Everything. |
| `mcp_servers/checkins.py` | Person 1 | — | All three tools. |
| `core/` (db, models, policy, pending, approvals, notify, activity, speech) | Person 2 | — | Everything. `speak()`, `policy.check()`, `pending` not yet implemented. |
| `webhooks/sms.py` | Person 2 | — | Everything. |
| `mcp_servers/money.py` | Person 2 | — | All six tools. |
| `main.py` (app, lifespan, MCP mounts) | Person 2 | Empty FastAPI app starts. | MCP server mounting, lifespan, routers. |
| `supabase/migrations/` | Person 2 | — | `0001_init.sql` is a comment listing the tables. No schema. |
| `mcp_servers/orders.py` | Person 3 | — | All seven tools. |
| `web/` mocks (biller, food, services, rides) | Person 3 | — | Routes return `{}`. Mock-data JSON files are empty arrays. |
| `google/` (auth, gmail, calendar, ingestion) | Person 4 | — | Everything. |
| `mcp_servers/mobility.py` | Person 4 | — | All four tools. |
| `web/app/dashboard/` | Person 4 | — | Pages render a heading only. |

## Integration notes

Things another person needs to know to build on your work: signature changes, new env vars, return-shape changes, mount paths. Remove a note once it is reflected in AGENTS.md.

- `mcp_servers/__init__.py` exports an empty `SERVERS` dict. Register your FastMCP instance there once it exists.
- `backend/pyproject.toml` lists dependencies by name without pins. Run `uv sync` once and commit the lockfile.
- `web/package.json` uses `latest` for all packages. Run `npm install` once and commit the lockfile.

## Known issues and blockers

- None yet.

## Changelog

One line per merged PR, newest first. Keep it to what changed, not how.

- 2026-09-24: Scaffolded the skeleton file structure from AGENTS.md. All files are stubs.
