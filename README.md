# Gary

A phone-based voice assistant for older adults. The user calls a regular phone number and asks for what they need in plain language. A voice agent pays bills, orders food, books home services and rides, and makes daily reminder calls. Family members stay in the loop over messages and a web dashboard, and approve anything risky.

- `AGENTS.md` describes the architecture, ownership, safety rules, and conventions. Read it before changing code.
- `CONTEXT.md` describes what currently works, what is stubbed, and integration notes. Read it before starting work in an area, and update it when you merge.

## What you need

| Tool | Why |
|---|---|
| [uv](https://docs.astral.sh/uv/) | Python package manager. It installs Python 3.12 for you. |
| Node.js 20+ | The `web/` Next.js app (mock services and dashboard). |
| [ngrok](https://ngrok.com/) | Gives your laptop a public URL so Twilio can reach it. Free account required. |

Accounts: Twilio (a phone number with voice and SMS), Deepgram (API key), Supabase (a project), Meta Model API (Muse Spark key from dev.meta.ai, for the browser agent). Google credentials are optional until the Gmail and Calendar work lands.

## Setup

### macOS

```bash
brew install uv node ngrok
git clone https://github.com/aadit11/Gary.git
cd Gary
cp .env.example .env          # then fill it in, see below
cd backend && uv sync         # installs Python 3.12 and all dependencies
uv run playwright install chromium   # browser for the DashDish / Udriver agent
cd ../web && npm install
ngrok config add-authtoken <your-token>
```

### Windows (PowerShell)

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
winget install OpenJS.NodeJS.LTS
winget install ngrok.ngrok
git clone https://github.com/aadit11/Gary.git
cd Gary
Copy-Item .env.example .env   # then fill it in, see below
cd backend; uv sync
uv run playwright install chromium
cd ..\web; npm install
ngrok config add-authtoken <your-token>
```

Open a new terminal after installing so the tools are on your PATH. Everything below uses the same commands on both systems.

### Fill in `.env`

The file lives at the repo root. Both `backend/` and `web/` read it.

| Variable | Where to get it | Notes |
|---|---|---|
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` | Twilio console home page | |
| `TWILIO_PHONE_NUMBER` | Twilio console, Phone Numbers | E.164 with the plus sign, e.g. `+14155551234`. |
| `DEEPGRAM_API_KEY` | Deepgram console, API Keys | |
| `SUPABASE_URL` | Supabase, Project Settings, Data API, "Project URL" | Just `https://xxxx.supabase.co`. No `/rest/v1` on the end. |
| `SUPABASE_SERVICE_KEY` | Same page, the **secret** / service_role key | Never the publishable (anon) key. Never commit it. |
| `SUPABASE_ANON_KEY` | Same page, the **publishable** / anon key | Used only by the web dashboard in the browser. |
| `META_API_KEY` | dev.meta.ai | Muse Spark, the model that operates the DashDish and Udriver clones. |
| `BROWSER_HEADLESS` | `false` for the demo | Shows the Chromium window while the agent orders. |
| `PUBLIC_BASE_URL` | Your ngrok URL once it's running | e.g. `https://abc123.ngrok-free.dev`. Changes every ngrok restart on the free plan. |
| `MOCK_SERVICES_BASE_URL` | Where `web/` is running | `http://localhost:3000` locally. |
| `DEMO_USER_ID` | Printed by the seed script (below) | |
| `POLICY_SPENDING_LIMIT` | Your choice | Payments above this need family approval. Default 100. |
| `FAMILY_CHANNEL` | `whatsapp` or `sms` | See "Family messages" below. Use `whatsapp` for the demo. |
| `TWILIO_WHATSAPP_FROM` | `whatsapp:+14155238886` | Twilio's shared WhatsApp sandbox number. |

### Database

1. Open your Supabase project, click **SQL Editor**, then **New query**.
2. Paste the whole contents of `supabase/migrations/0001_init.sql` and click **Run**. Choose **Run without RLS** if asked. You should see "Success. No rows returned."
3. Seed the demo user:

   ```bash
   cd backend
   uv run python scripts/seed_demo_user.py
   ```

   Edit the phone numbers in that script first: the user's phone is the one that plays "Grandma," and the family contact's phone receives approval messages. The script prints `DEMO_USER_ID`. Put it in `.env`.

### Family messages: why WhatsApp

US carriers block SMS from Twilio local numbers that have not completed A2P 10DLC registration, which takes days. For the demo we send family approvals over Twilio's WhatsApp sandbox instead:

1. Every phone that should receive approvals opens WhatsApp, starts a chat with **+1 415 523 8886**, and sends the join message shown at Twilio console, Messaging, Try it out, Send a WhatsApp message (it looks like `join two-words`).
2. In the Twilio console, Messaging, Settings, WhatsApp sandbox settings, set "When a message comes in" to `<PUBLIC_BASE_URL>/webhooks/sms`, method POST.

If 10DLC registration is completed later, set `FAMILY_CHANNEL=sms` and nothing else changes.

## Running it

You need three terminals.

**1. Backend** (from `backend/`):

```bash
uv run uvicorn main:app --reload --port 8000
```

`http://localhost:8000/health` should return JSON listing the four MCP servers.

**2. Tunnel:**

```bash
ngrok http 8000
```

Copy the `https://...ngrok-free.dev` URL into `PUBLIC_BASE_URL` in `.env` and restart the backend. Then point the Twilio number at it by running this from `backend/`:

```bash
uv run python scripts/set_twilio_webhooks.py
```

Also update the WhatsApp sandbox URL in the console (step 2 in "Family messages"). Repeat both whenever ngrok gives you a new URL.

**3. Web app** (from `web/`):

```bash
npm run dev
```

Mock services and the family dashboard are at `http://localhost:3000`.

### Try it

- **Inbound**: call your Twilio number. You should hear the greeting. Ask "do I have any bills due?"
- **Outbound reminder**: from `backend/`, place a reminder call to the demo user:

  ```bash
  uv run python scripts/place_reminder_call.py
  ```

  The scheduler also places reminder calls automatically when a row in `reminders` matches the current minute in the user's timezone.
- **Family approval**: on a call, ask to send $500 to someone new. The family phone gets a WhatsApp message. Reply YES or NO and the agent tells the caller the answer in the same call.

The backend terminal prints the call transcript as it happens.

### Browser agent (food orders and rides)

Food and rides are placed on REAL's DashDish and Udriver clones by Muse Spark driving a real browser. Try one from `backend/`:

```bash
uv run python scripts/run_browser_task.py dashdish "Order one Classic Cheeseburger from Souvla for delivery and place the order." --headed
```

It prints every step, the wall-clock time, and the agent's final message. A DashDish order takes about 50 to 80 seconds. `--no-screenshot` sends only the accessibility tree and is faster.

## Testing

```bash
cd backend
uv run pytest
```

Tests run against an in-memory database and never send messages or place calls, so they work without any credentials.

To poke at MCP tools without a phone:

```bash
npx @modelcontextprotocol/inspector
# Transport: Streamable HTTP. URL: http://localhost:8000/mcp/money/mcp  (or checkins, orders, mobility)
```

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `Invalid path specified in request URL` (PGRST125) from Supabase | `SUPABASE_URL` has `/rest/v1` on the end. Use just the project URL. |
| `Could not find the table 'public.users'` (PGRST205) | The migration has not been applied. See Database above. |
| Text to family shows `undelivered`, error 30034 | Carrier blocked SMS from the unregistered number. Use `FAMILY_CHANNEL=whatsapp`. |
| WhatsApp message `failed`, error 63015 | That phone has not sent the sandbox join message yet. |
| Family reply does nothing | The WhatsApp sandbox "When a message comes in" URL is stale. Re-point it at the current ngrok URL. |
| `No module named 'mcp.server.fastmcp'` | `uv sync` picked mcp 2.x. The repo pins `mcp<2`; re-run `uv sync` from `backend/`. |
| `uv sync` complains about Python 3.14 | The project requires Python 3.12 or 3.13. `uv sync` installs 3.12 automatically; if not, run `uv python install 3.12`. |
| Call connects but there is silence | Check the backend log for a Deepgram `Error`. Usually a bad `DEEPGRAM_API_KEY` or `PUBLIC_BASE_URL` still pointing at an old ngrok URL. |
| MCP Inspector requests hang | The backend must be running; the MCP session managers start in the app lifespan. |
