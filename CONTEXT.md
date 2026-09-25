# CONTEXT.md

Current state of the build, for the team and for AI agents. Read this before starting work in an area.
Describe **state**, not history. Update your row when you merge a PR that changes what works.

## Status by vertical

| Area | Owner | Working end to end | Stubbed / not started |
|---|---|---|---|
| `voice/` (Twilio routes, bridge, MCP adapter, injection) | Person 1 (built by Person 2 with agent help, 2026-09-25) | Inbound TwiML, Twilio<->Deepgram bridge (mulaw 8k, Flux listen, gpt-4o-mini think, Deepgram v2 speak), barge-in `clear`, function calls routed to MCP tools, KeepAlive, approval injection into live calls, outbound TwiML + `place_outbound_call()`. **Outbound reminder call verified on a real phone** (27 s: greeting, reminder read, user confirmed, agent responded). | Inbound call test, `confirm_reminder` tool (the reminder prompt tells the agent to call it but checkins.py only has a stub tool yet), morning briefing flow, prompt tuning. |
| `scheduler/` | Person 1 | APScheduler runs `run_due_reminders()` every 60 s: matches active reminders to the current minute in the user's timezone, logs to `reminder_logs`, places the call. Only starts when `PUBLIC_BASE_URL` is set. | Morning briefing job, retries, family alert when unconfirmed. |
| `mcp_servers/checkins.py` | Person 1 | Server exists with a stub `get_upcoming_appointments` so the adapter has something to call. | The real three tools. |
| `core/` (db, models, policy, pending, approvals, notify, activity, speech) | Person 2 | All modules implemented and unit tested. `db.get_client()` falls back to an in-memory fake when `SUPABASE_URL` is unset or `GARY_FAKE_DB=1`. | Phase 2 policy refinements (per-kind limits, scam scoring via Meta API). |
| `webhooks/sms.py` | Person 2 | `POST /webhooks/sms` parses YES/NO, resolves the newest pending approval for that family phone, replies with TwiML. Outbound approval request verified delivered and read on WhatsApp through the sandbox. **Inbound reply not yet tested**: needs a YES/NO from the joined phone. | Live-call injection of the result (Person 1, via `approvals.register`). |
| `mcp_servers/money.py` | Person 2 | `list_bills_due` reads the `bills` table and speaks amounts and dates. | The other five tools (Phase 2). |
| `main.py` (app, lifespan, MCP mounts) | Person 2 | All four MCP servers mounted at `/mcp/<name>` with session managers started in the lifespan; verified with an MCP client. SMS router included. `GET /health`. | Voice routes and scheduler startup (Person 1 adds to the lifespan). |
| `supabase/migrations/` | Person 2 | `0001_init.sql` defines all 15 tables. | Applied to the Supabase project (without RLS; backend uses the secret key, dashboard can use the publishable key). Seeded with the demo user. |
| `mcp_servers/orders.py` | Person 3 | Server exists with a stub `get_favorite_orders`. | The real seven tools. |
| `browser_agent/` (Muse Spark + REAL SDK) | Person 3 (built 2026-09-25) | `BrowserJobRunner` places a DashDish order from a plain-language goal end to end. After optimization (pruned tree, multi-action plans with name-based actions, learned-flow replay): first-time order **32.8 s / 5 model calls**; replay of a learned flow ("my usual") **~15 s / 0 model calls** (set `BROWSER_REPLAY_VERIFY=true` to add a model confirmation). Before: 49 to 79 s / 11 to 13 calls. `minimal` reasoning effort gave no further gain over `low`. Runner starts in the lifespan (`app.state.browser_runner`). | Udriver run not yet measured. Not yet wired to `confirm_order` / `confirm_ride` (Phase 2). |
| `web/` (mocks + dashboard) | Person 3 (dashboard pages: Person 4) | Biller and home-services mock APIs and pages; dashboard activity, approvals, and reminders pages read Supabase live; reminder form inserts rows. Food and rides mocks removed (REAL clones). TypeScript clean. | Vercel deploy. Dashboard shows a "not configured" notice until `SUPABASE_ANON_KEY` is in the root `.env`. |
| `google/` (auth, gmail, calendar, ingestion) | Person 4 | — | Everything. |
| `mcp_servers/mobility.py` | Person 4 | Server exists with a stub `get_ride_status`. | The real four tools. |

## Integration notes

Things another person needs to know to build on your work: signature changes, new env vars, return-shape changes, mount paths. Remove a note once it is reflected in AGENTS.md.

- **Python 3.12 and `mcp<2`.** `mcp` 2.x renamed FastMCP; the repo pins 1.x so `from mcp.server.fastmcp import FastMCP` works as documented. `uv sync` picks 3.12 automatically (3.14 is too new for some deps).
- **Every tool takes `user_id: str` as its first parameter.** The voice adapter (Person 1) should inject the caller's user id into every function call, so the LLM never has to know it. `DEMO_USER_ID` in `.env` is that id for the demo.
- **MCP mount paths** are `/mcp/checkins/mcp`, `/mcp/money/mcp`, `/mcp/orders/mcp`, `/mcp/mobility/mcp` (streamable HTTP). `mcp_servers.streamable_http_url(base, name)` builds them. `SERVERS` in `mcp_servers/__init__.py` is the registry.
- **Tool results are `speak()` JSON strings**: `{"say": ..., "action_id"?: ..., "data"?: {...}}`. The adapter should hand the whole string to Deepgram; the prompt tells the agent to speak only `say` and pass `action_id` to `confirm_*`.
- **Pending actions**: `pending.create(action_type, user_id, **payload)` in `prepare_*`; `pending.consume(action_id, action_type, user_id)` in `confirm_*`. `consume` raises `PendingActionError` with a speakable `.say`; catch it and `speak(err.say)`.
- **Policy**: `policy.check(kind, payee, amount, user_id, message_text=None)` returns `Decision(needs_approval, reason, family_name)`. Call it inside every money-moving tool.
- **Approvals**: `approvals.request(user_id, action, payload, reason, summary=None)` texts the approver. When the family replies, `webhooks/sms.py` resolves it and runs `ACTION_EXECUTORS[action]` (register yours: `ACTION_EXECUTORS["pay_bill"] = fn`). `approvals.register(callback)` is where Person 1 hooks `voice/injection.py` to tell the live call the outcome.
- **Family messaging channel**: `notify.send_sms(to, body)` sends on `FAMILY_CHANNEL` (`whatsapp` for the demo, `sms` once 10DLC clears). Inbound WhatsApp replies arrive at the same `/webhooks/sms` route; `From` comes in as `whatsapp:+1...` and `normalize_phone` handles it.
- **Voice call parameters**: TwiML `<Stream>` carries `user_id`, `reason` (`inbound` | `reminder` | `morning_briefing`), and `reminder_text`. `voice/agent_settings.py` picks the prompt, greeting, and which MCP servers to expose per reason (`SERVERS_BY_REASON`).
- **MCP adapter transport**: `MCPAdapter()` defaults to in-process sessions over the same FastMCP objects (no loopback HTTP; uvicorn isn't listening yet during lifespan startup). `MCPAdapter(transport="http")` uses real streamable-HTTP sessions. Schemas are identical either way.
- **Live-call injection**: `voice.bridge.ACTIVE_SESSIONS[user_id]` is the live session; `voice/injection.py` is registered with `approvals.register()` and speaks the family's decision with `InjectAgentMessage` (`behavior: interrupt`).
- **Outbound calls**: `voice.twilio_routes.place_outbound_call(user_id, reason, reminder_id=None)`. Twilio fetches `/voice/outbound-twiml?...` which returns the same stream TwiML.
- **Twilio number webhooks** (run `uv run python scripts/set_twilio_webhooks.py` after every ngrok restart): voice -> `PUBLIC_BASE_URL/voice/incoming`, SMS -> `PUBLIC_BASE_URL/webhooks/sms`. WhatsApp sandbox inbound URL is set in the console.
- **Browser agent**: `from browser_agent.runner import BrowserJobRunner`; `app.state.browser_runner.submit(site, goal, user_id=..., flow_key=..., on_done=fn)` where site is `dashdish` or `udriver`. Pass `flow_key` (e.g. the favorite's id) to learn the flow on first success and replay it next time (`backend/data/flows/<site>/<key>.json`, committed). The model emits multi-step plans; `click_named(role, regex)` etc. act on elements not yet on the page. `on_done` runs on the worker thread; use `asyncio.run_coroutine_threadsafe` to touch the call loop (see `voice/injection.py`). Goals are plain English; `browser_agent/tasks.py` appends a short per-site flow hint. `MUSE_REASONING_EFFORT=low` (a reasoning model; `minimal` is faster but sloppier). `BROWSER_USE_SCREENSHOT=false` is ~25% faster.
- **REAL clone facts**: DashDish checkout uses the clone's own saved address and card (Foster City, Visa ...5097); do not ask the agent to change them. Udriver only accepts pickup/dropoff from its own place list (substring search); pick places that exist there.
- **Web env**: `web/next.config.mjs` reads the repo-root `.env` and exposes `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `DEMO_USER_ID` as `NEXT_PUBLIC_*`. On Vercel set the `NEXT_PUBLIC_*` vars directly.
- **Fake database for tests**: `tests/conftest.py` forces `GARY_FAKE_DB=1` and provides a `demo` fixture with a user, approver, known payees, and bills. Write your tool tests against it; no network needed.
- `backend/pyproject.toml` lists dependencies by name without pins. Run `uv sync` once and commit the lockfile.
- `web/package.json` uses `latest` for all packages. Run `npm install` once and commit the lockfile.

## Known issues and blockers

- `SUPABASE_ANON_KEY` (publishable key) is not yet in the root `.env`, so dashboard pages render an empty-state notice.
- The browser agent's DashDish total varied between runs ($21.77 vs $23.37) because it sometimes picks a different size option; the read-back should quote the item, not a precise total, until the agent reports it.
- **SMS is blocked on our Twilio number** (carrier error 30034: local 10DLC number without A2P registration; registration takes days). Family messages go over the **Twilio WhatsApp sandbox** instead (`FAMILY_CHANNEL=whatsapp`). Any phone that should receive approvals must first send `join halfway-rate` on WhatsApp to +1 415 523 8886. Current demo family phone: +1 315 480 4465.
- The ngrok URL changes on every restart (free plan). When it does: update `PUBLIC_BASE_URL` in `.env`, restart the backend, run `scripts/set_twilio_webhooks.py`, and update the WhatsApp sandbox "When a message comes in" URL in the Twilio console (no API for that one).

## Changelog

One line per merged PR, newest first. Keep it to what changed, not how.

- 2026-09-25: Browser agent sped up: pruned accessibility tree, multi-action plans with name-based actions, learned-flow replay. First order 32.8 s, replay ~24 s.
- 2026-09-25: Browser agent (Muse Spark on Meta Model API + REAL SDK) places a DashDish order end to end; 3/3 runs, 49 to 79 s. Web app reduced to biller + services mocks and a live dashboard.
- 2026-09-25: README rewritten (macOS/Windows setup, run, test, troubleshooting); helper scripts `set_twilio_webhooks.py` and `place_reminder_call.py`.
- 2026-09-25: Outbound reminder call verified on a real phone end to end (Twilio -> bridge -> Deepgram -> speech both ways).
- 2026-09-25: Voice bridge, MCP adapter, prompts, turn-taking settings, injection, outbound calls, minimal scheduler. 49 tests.
- 2026-09-25: Family approval request delivered live over WhatsApp sandbox; reply loop pending a real YES/NO. SMS blocked by carrier registration; `FAMILY_CHANNEL` switch added.
- 2026-09-25: Schema applied to Supabase and demo user seeded; `DEMO_USER_ID` set in Person 2's .env.
- 2026-09-25: Person 2 Phase 1: core library, schema, four mounted MCP servers with one stub tool each, SMS approval webhook, seed script, 23 tests.
- 2026-09-24: Scaffolded the skeleton file structure from AGENTS.md. All files are stubs.

## Experiment: jev-ultrafast (branch `jev-ultrafast`, 2026-09-25)

Goal: see whether Browser Use's jev-ultrafast loop beats our Muse Spark runner on a first-time DashDish order. TypeSafe API keys were paused, so an LLM decider (`browser_agent/jev_llm.py`) reproduces TypeSafe's operation+target contract over the library's own element table; Muse Spark writes typed text. Benchmarks in `backend/data/benchmarks/`.

| Agent | Loop | Decider | Runs | Orders confirmed | Median time | Median decisions |
|---|---|---|---|---|---|---|
| muse | ours (REAL SDK, Playwright) | Muse Spark | 3 | **3/3** | 37.3 s | 5 |
| jev-muse | jev-ultrafast | Muse Spark | 3 | 0/3 | 26.1 s (failed) | 3 to 4 |
| jev-openrouter | jev-ultrafast | Mercury 2.5 | 3 | 0/3 | 29.1 s (blocked) | 10 |

Why the jev loop fails on DashDish: after typing "Souvla" the text is in the box and the DOM has the four suggestion nodes, but the library's snapshot only lists standard HTML/ARIA controls, so DashDish's div-based result cards (and the restaurant cards on the home page) never appear as clickable elements, and its visible-text reader omits the dropdown. Every decider therefore loops on the search box. Its README lists arbitrary widgets as out of scope. Fixing it means patching the library's `snapshot.js`; not worth it before the demo.

What did transfer: per-decision latency of ~0.4 s (Mercury) to ~1.7 s (Muse, minimal reasoning) on a compact element table, versus ~3 s on our pruned accessibility tree. If we want more speed later, the element-table observation and a constrained one-line decision format are the parts to port into our runner, keeping the REAL SDK's DOM access that does see the cards.

Decision: stay on the Muse Spark runner on `main` (37 s first order, 15 s replay). Branch kept for reference.
