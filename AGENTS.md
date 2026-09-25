# AGENTS.md

Guidance for AI coding agents (and humans) working in this repo. Read this before making changes.

For the current build status, integration notes, and blockers, read `CONTEXT.md` before starting work in an area, and update it when you merge a PR.

## Project overview

A phone-based voice assistant for older adults. The user calls a regular phone number (landline or mobile) and asks for what they need in plain language. A voice agent carries out the task. Family members stay in the loop through SMS and a web dashboard, and approve anything risky.

Features:

- **Scam Guard**: checks every payment and purchase; pauses risky ones and asks a family member to approve by SMS; flags suspicious emails.
- **Ordering Food and Essentials**: voice ordering, including "order my usual," with full read-back.
- **Bill Paying**: detects bills from Gmail, reminds the user, pays by voice after read-back.
- **Booking Home Services**: plain-language problem → provider options → booking → calendar → family notified.
- **Daily Reminders**: family-scheduled outbound calls (e.g. medication), with confirmation, retries, and family alerts. The morning call includes a briefing.
- **Booking Transportation**: ride booking with read-back, driver details, family trip alerts, rides suggested for calendar appointments.

This is a hackathon build. The biller and home-services providers are **mocks** served by `web/`. Food ordering and rides run on **REAL's web clones** (DashDish for DoorDash, Udriver for Uber) operated by a browser agent in `backend/browser_agent/` (Muse Spark on the Meta Model API deciding each step). Never integrate real payment, banking, DoorDash, or Uber APIs.

## Architecture

- **Twilio** provides the phone number, inbound/outbound calls (Media Streams), and SMS.
- **Deepgram Voice Agent API** handles speech-to-text, the conversation LLM, and text-to-speech.
- **FastAPI backend** hosts the Twilio webhooks, the Twilio↔Deepgram voice bridge, four MCP servers, the SMS webhook, and the scheduler.
- **MCP servers** (FastMCP, one per vertical) expose all user-facing tools. Deepgram does not consume MCP natively, so `voice/mcp_adapter.py` acts as the MCP client: it lists tools from all servers at call start, converts them to Deepgram function definitions, and routes Deepgram function calls to the right server.
- **Supabase (Postgres)** stores users, bills, orders, bookings, reminders, approvals, pending actions, and the activity log.
- **Gmail and Google Calendar APIs** read a seeded demo account. `google/ingestion.py` classifies emails into bills, appointments, suspected scams, and other.
- **Next.js app** (`web/`) serves the mock services and the family dashboard.

Flows:

1. **Inbound call**: Twilio → `/voice/incoming` → TwiML `<Connect><Stream>` → `voice/bridge.py` ↔ Deepgram. Function calls → `mcp_adapter` → MCP server tool → result back to Deepgram.
2. **Outbound call**: `scheduler/jobs.py` → Twilio REST API with TwiML pointing at the bridge, plus call context (reminder or morning briefing).
3. **Approval**: money tool fails `policy.check()` → `core/approvals.py` creates approval + SMS to family → family replies YES/NO → `webhooks/sms.py` → action executed or cancelled → `voice/injection.py` tells the user in the live call.
4. **Logging**: every action writes to `activity_log`, which the dashboard reads.

## Skeleton file structure

```
.
├── AGENTS.md
├── CONTEXT.md                       # current build status per area; update on every merged PR
├── README.md
├── .env.example
├── supabase/
│   └── migrations/
│       └── 0001_init.sql            # all tables (see Data model)
├── backend/
│   ├── pyproject.toml
│   ├── main.py                      # FastAPI app; mounts MCP servers; routers; lifespan (MCP session managers, scheduler, adapter)
│   ├── config.py                    # env loading (pydantic-settings)
│   ├── voice/                       # OWNER: Person 1
│   │   ├── __init__.py
│   │   ├── twilio_routes.py         # /voice/incoming, /voice/outbound-twiml, /voice/stream (WebSocket)
│   │   ├── bridge.py                # VoiceAgentSession: Twilio <-> Deepgram audio + events
│   │   ├── mcp_adapter.py           # MCP client sessions, MCP->Deepgram schema conversion, call routing
│   │   ├── agent_settings.py        # Deepgram listen/think/speak config, turn-taking settings
│   │   ├── injection.py             # push messages into a live call (approval results)
│   │   └── prompts/
│   │       ├── base.md              # persona + elder-friendly speaking rules
│   │       ├── morning_checkin.md   # outbound briefing call
│   │       └── reminder.md          # outbound reminder call
│   ├── core/                        # OWNER: Person 2 (shared library, NOT MCP tools)
│   │   ├── __init__.py
│   │   ├── db.py                    # Supabase client
│   │   ├── models.py                # pydantic models for tables
│   │   ├── policy.py                # policy.check(): limits, known payees, scam patterns
│   │   ├── pending.py               # prepare/confirm pending-action helper
│   │   ├── approvals.py             # create approval, resolve approval
│   │   ├── notify.py                # notify_family(), sms helpers (Twilio)
│   │   ├── activity.py              # log_event()
│   │   └── speech.py                # speak() response helper; money/date formatting for TTS
│   ├── google/                      # OWNER: Person 4
│   │   ├── __init__.py
│   │   ├── auth.py                  # OAuth credentials for the demo account
│   │   ├── gmail.py
│   │   ├── calendar.py              # read events, create events
│   │   └── ingestion.py             # classify emails -> bills / appointments / scams / other
│   ├── mcp_servers/
│   │   ├── __init__.py              # SERVERS registry used by main.py and mcp_adapter
│   │   ├── checkins.py              # Vertical 1 (Person 1)
│   │   ├── money.py                 # Vertical 2 (Person 2)
│   │   ├── orders.py                # Vertical 3 (Person 3)
│   │   └── mobility.py              # Vertical 4 (Person 4)
│   ├── clients/
│   │   └── mock_services.py         # HTTP client for web/ mock APIs (owners add their own functions)
│   ├── browser_agent/               # Muse Spark + REAL SDK: drives DashDish / Udriver in the background
│   │   ├── muse.py                  # Meta Model API client (OpenAI-compatible, reasoning_effort)
│   │   ├── agent.py                 # observation -> next action (axtree + screenshot prompt)
│   │   ├── tasks.py                 # FreeformCloneTask: any goal on a REAL clone; per-site flow hints
│   │   └── runner.py                # BrowserJobRunner: one worker thread, submit()/run_now()
│   ├── scheduler/                   # OWNER: Person 1
│   │   ├── __init__.py
│   │   └── jobs.py                  # due reminders, morning briefings, retries
│   ├── webhooks/                    # OWNER: Person 2
│   │   ├── __init__.py
│   │   └── sms.py                   # inbound SMS (YES/NO approvals)
│   ├── scripts/
│   │   ├── seed_demo_user.py        # demo user, family contact, favorites, known payees
│   │   └── seed_gmail.py            # optional: send seed emails to demo inbox
│   └── tests/
│       ├── conftest.py
│       ├── test_policy.py
│       ├── test_pending.py
│       ├── test_checkins_tools.py
│       ├── test_money_tools.py
│       ├── test_orders_tools.py
│       └── test_mobility_tools.py
└── web/                             # OWNER: Person 3 (dashboard pages: Person 4)
    ├── package.json
    ├── app/
    │   ├── layout.tsx
    │   ├── page.tsx                 # landing / links
    │   ├── dashboard/
    │   │   ├── page.tsx             # activity log
    │   │   ├── reminders/page.tsx   # schedule reminders
    │   │   └── approvals/page.tsx   # approval history
    │   ├── mock/
    │   │   ├── biller/page.tsx
    │   │   └── services/page.tsx
    │   └── api/mock/
    │       ├── biller/{bills,pay}/route.ts
    │       └── services/{search,bookings}/route.ts
    └── lib/
        ├── supabase.ts
        └── mock-data/               # static JSON: bills, providers
```

## Ownership

| Area | Owner |
|---|---|
| `voice/`, `scheduler/`, `mcp_servers/checkins.py` | Person 1 |
| `core/`, `webhooks/`, `mcp_servers/money.py`, `main.py`, migrations | Person 2 |
| `web/` (mocks), `mcp_servers/orders.py` | Person 3 |
| `google/`, `mcp_servers/mobility.py`, `web/app/dashboard/` | Person 4 |

Agents: only edit files in the area you were asked to work on. Changes to shared files (`core/`, `main.py`, `supabase/migrations/`, `mcp_servers/__init__.py`) must be small, backwards-compatible, and called out in the PR description.

## Safety invariants (never break these)

1. **Safety checks are never MCP tools.** `policy.check()` is called *inside* every money-moving tool (bills, person-to-person payments, orders, service bookings, rides). The LLM must have no path around it.
2. **Read-back is enforced in code.** Every action is split into `prepare_*` (returns details to read back, creates a pending action) and `confirm_*` (executes only a valid, unexpired, unused pending-action ID for the same user and action type). `confirm_*` must reject anything else.
3. **Approvals are required** when `policy.check()` says so. A tool must never execute an action that is awaiting approval.
4. **No real money or real services.** Only call the mock APIs in `web/`.
5. **No secrets in code or logs.** Use env vars. Don't log full email bodies or OAuth tokens.

## MCP tool conventions

- One FastMCP server per vertical, defined in its own file and registered in `mcp_servers/__init__.py`.
- Tool names are globally unique (Deepgram sees one flat list) and use `snake_case` verbs: `prepare_order`, `confirm_order`.
- Docstring = one clear sentence describing when to use the tool. The LLM chooses tools from these descriptions.
- Fully type-hinted parameters. Keep parameters few and simple (strings, numbers, IDs).
- Return via `core.speech.speak()`, which produces a JSON string:
  ```json
  {"say": "One or two sentences for the agent to speak.", "action_id": "optional", "data": {}}
  ```
  The agent speaks only `say`. Never put IDs, JSON, or markdown in `say`.
- Every executed action calls `activity.log_event()` and, where relevant, `notify.notify_family()`.
- Tools must be fast (target < 1.5s). Anything slower runs in the background and confirms by SMS.
- Handle errors by returning a friendly `say` ("I couldn't reach the store just now, want me to try again?"), never a stack trace.

Example:

```python
from mcp.server.fastmcp import FastMCP
from core import policy, pending, approvals, activity
from core.speech import speak, money_str, date_str

money = FastMCP("money")

@money.tool()
def prepare_bill_payment(bill_id: str) -> str:
    """Prepare to pay one of the user's detected bills and return details to read back."""
    bill = get_bill(bill_id)
    decision = policy.check(kind="bill", payee=bill.payee, amount=bill.amount)
    if decision.needs_approval:
        approvals.request(action="pay_bill", payload={"bill_id": bill_id}, reason=decision.reason)
        return speak(f"I'd like to check with {decision.family_name} before paying this one.")
    action_id = pending.create("pay_bill", bill_id=bill_id)
    return speak(
        f"That's {money_str(bill.amount)} to {bill.payee}, due {date_str(bill.due_date)}. Should I pay it?",
        action_id=action_id,
    )
```

## Tool catalog

| Server | Tools |
|---|---|
| checkins | `get_daily_briefing`, `get_upcoming_appointments`, `confirm_reminder` |
| money | `list_bills_due`, `prepare_bill_payment`, `confirm_bill_payment`, `prepare_payment_to_person`, `check_message_for_scam`, `list_suspicious_emails` |
| orders | `get_favorite_orders`, `search_food_and_groceries`, `prepare_order`, `confirm_order`, `find_home_service`, `prepare_service_booking`, `confirm_service_booking` |
| mobility | `prepare_ride`, `confirm_ride`, `get_ride_status`, `suggest_ride_for_appointment` |

Adding a tool:

1. Add it to your vertical's server file following the conventions above.
2. Add a unit test in `backend/tests/`.
3. Test it in the MCP Inspector.
4. Test it over a real phone call.
5. Update the tool catalog in this file.

## Voice and prompt rules

The users are older adults on a phone call. All spoken text (prompts and `say` strings) must:

- Be short: one or two sentences per turn; never list more than three items at once.
- Use plain words; no jargon, acronyms, or markdown.
- Read back every purchase, payment, and booking in full (what, how much, when, to whom) and wait for a clear "yes" before calling `confirm_*`.
- Say what it's doing before slow operations ("Let me check your email").
- Be warm and patient; handle "what?" and "say that again" by repeating more simply.
- Never scold or embarrass the user, especially when Scam Guard holds a payment.
- Format money as "$84.20" and dates as "Friday, September 25 at 2 PM" (use `core/speech.py` helpers), never ISO timestamps.

Turn-taking is tuned in `voice/agent_settings.py` to tolerate long pauses. Don't make it more aggressive without testing with slow speech.

## Data model (Supabase)

| Table | Purpose |
|---|---|
| `users` | Demo user profile: name, phone, address, timezone |
| `family_contacts` | Family members, phone numbers, approval rights |
| `known_payees` | Trusted billers/recipients |
| `emails` | Ingested emails with classification (`bill`, `appointment`, `scam`, `other`) and extracted fields |
| `bills` | Payee, amount, due date, status, source email |
| `favorites` | Saved "usual" orders |
| `orders` | Food/grocery orders |
| `service_bookings` | Home service bookings |
| `rides` | Ride bookings and status |
| `reminders` | Family-scheduled reminders (time, message, recurrence) |
| `reminder_logs` | Each reminder call: answered, confirmed, retries |
| `pending_actions` | Prepared actions awaiting confirmation (type, payload, expires_at, used) |
| `approvals` | Family approval requests and outcomes |
| `activity_log` | Every action, for the dashboard |
| `calls` | Call records: direction, reason, Twilio call SID |

## Mock service APIs (`web/app/api/mock/`)

Mocks are simple and mostly stateless; the backend database is the source of truth.

| Service | Endpoints |
|---|---|
| Biller | `GET /api/mock/biller/bills`, `POST /api/mock/biller/pay` → `{confirmation_id}` |
| Food | **REAL DashDish clone** via `browser_agent` (no API; see below) |
| Services | `GET /api/mock/services/search?category=` (or `?q=my sink is leaking`), `POST /api/mock/services/bookings` → `{booking_id, provider, time}` |
| Rides | **REAL Udriver clone** via `browser_agent` (no API; see below) |

## Browser agent (food and rides)

REAL's clones have no API, so orders and rides are placed by a browser agent: `BrowserJobRunner.submit(site, goal, user_id, on_done)` runs Muse Spark against the clone on a background thread and calls back with a `BrowserJob` (status, result_text like "DONE: Ordered ..., total $21.77", steps, seconds). A DashDish order takes about 50 to 80 seconds, so tools must never wait on it: `confirm_*` says "I'm placing that now" and the callback texts the family and injects the result into the live call. Measure with `uv run python scripts/run_browser_task.py dashdish "..."`.

## Environment variables (`.env.example`)

```
# Twilio
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_PHONE_NUMBER=

# Deepgram
DEEPGRAM_API_KEY=

# Supabase
SUPABASE_URL=
SUPABASE_SERVICE_KEY=

# Google (demo account)
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REFRESH_TOKEN=

# Meta Model API (Muse Spark) for the browser agent
META_API_KEY=
BROWSER_HEADLESS=false      # show the Chromium window during the demo

# App
PUBLIC_BASE_URL=            # public backend URL (ngrok or host) for Twilio webhooks
MOCK_SERVICES_BASE_URL=     # web/ deployment URL
DEMO_USER_ID=
POLICY_SPENDING_LIMIT=100
```

## Commands

Backend (from `backend/`):

```bash
uv sync
uv run uvicorn main:app --reload --port 8000
ngrok http 8000                      # set PUBLIC_BASE_URL and Twilio webhooks to this URL
uv run pytest
uv run python scripts/seed_demo_user.py
```

MCP Inspector (test tools without a phone call):

```bash
npx @modelcontextprotocol/inspector
# connect via Streamable HTTP to http://localhost:8000/mcp/<server>/mcp
# (FastMCP serves streamable HTTP at /mcp under its mount path)
```

Web (from `web/`):

```bash
npm install
npm run dev
```

## Implementation notes

- FastMCP servers are mounted in `main.py` over streamable HTTP. Their session managers **must** be started in FastAPI's lifespan handler, or requests will fail. The MCP adapter's client sessions are also opened in the lifespan so calls have no connection overhead.
- The backend needs long-running WebSockets, so deploy it to Railway, Render, or Fly, not Vercel.
- Check Deepgram's Voice Agent function-calling docs for exact message shapes before changing `mcp_adapter.py` or `bridge.py`.
- For outbound calls, pass call context (reason, reminder text) so `agent_settings.py` can choose the right prompt and, if needed, expose only the relevant MCP servers.

## Git workflow

- Branch per vertical: `v1-checkins`, `v2-money`, `v3-orders`, `v4-mobility`; infra branches as needed.
- Small PRs, merged often. Run `uv run pytest` before merging.
- Feature freeze: **Sunday 12:00 PM**. After that, only bug fixes on the demo path.
