# CapitalOS

CapitalOS is a local-first, open-source personal capital operating system.

It provides a unified view of net worth, asset allocation, concentration risk, and spending behavior across multiple asset classes and financial accounts — designed as a foundation for building disciplined investment processes and, eventually, AI-assisted decision systems.

CapitalOS is not a budgeting app and not a trading bot.

It is infrastructure for understanding:

- where your capital is
- how it is allocated
- where risk is concentrated
- how decisions are made
- how outcomes feed back into future judgment

The project emphasizes correctness, traceability, and process over prediction.

---

## Core Principles

- **Local-first**: Runs entirely on your machine.
- **Source-of-truth driven**: Every number traces back to a file or on-chain address.
- **Judgment over automation**: Systems support decisions; they don’t replace them.
- **Process-oriented**: Investment outcomes are tracked against original intent.
- **Composable**: Each module can evolve independently.
- **Open by design**: Built for learning, experimentation, and transparency.

---

## Architecture Overview

CapitalOS is organized into five conceptual modules:

### Module A — Personal Financial Brain
Structured visibility into:
- portfolio across asset classes and geographies
- bank balances
- credit cards
- spending

Outputs:
- net worth
- asset allocation
- savings rate
- burn rate
- risk
Answers the question: What is my networth? How am I spending? What am I saving? 

---

### Module B — Market Intelligence Engine (future)
Ingests:
- earnings transcripts
- filings
- news
- product updates
- competitor announcements

Produces:
- company summaries
- competitive shifts
- risk signals
- sector trends

---

### Module C — Investment Decision System (future)

Provides structure for:
- investment memos
- checklists
- decision logs
- thesis tracking

AI assists with preparation; humans retain judgment.

---

### Module D — Feedback Loop (future)

Tracks:
- expected vs actual outcomes
- root causes
- recurring errors
- winning patterns

Designed to compound learning over time.

---

### Module E — Public Thinking Layer (optional)

Exports sanitized artifacts:
- memos
- post-mortems
- mental models
- process changes

Focus is on reasoning, not returns.

---

## Technology Stack (v1)

- Backend: FastAPI (Python)
- Frontend: React + TypeScript
- Database: PostgreSQL
- Deployment: Docker Compose

The system runs locally and is designed for straightforward migration to managed cloud services later.

---

## What CapitalOS Is Not

- Not a robo-advisor
- Not a trading platform
- Not a financial forecasting engine
- Not a consumer budgeting app

This is for people who want to know where they are heading, how are their decisions shaping their lives

---

## Getting Started

See `PRD-Module-1.md` for detailed product and technical specifications for the first module.

---

## License

MIT (or TBD)

---

## Philosophy

Good capital allocation comes from:

- clear thinking
- disciplined process
- honest feedback
- long-term perspective

CapitalOS exists to support those habits.


# Running the application

## AI Task Workflow

CapitalOS supports a local-first AI workflow with a mandatory human gate.
Detailed reference: `docs/workflows/ai-task-flow.md`.
All validation commands run locally on your machine by default.
Optional GitHub validation exists as a manual workflow (`workflow_dispatch`) and does not auto-run on PRs.
On macOS, workflow commands auto-use `caffeinate` so long-running agent steps do not sleep.

Model routing:
- Planning/architecture: `claude-opus-4.6`
- Implementation/checklist updates: Codex
- Primary review/testing: `claude-sonnet-4.6`
- Escalation review only (if Sonnet is uncertain/high-risk): `claude-opus-4.6`

Canonical task file:
- `tasks/issue-<id>-<slug>.md`

### Preflight

```bash
gh auth status -h github.com
copilot --version
codex --version
```

Optional:
- Disable sleep-prevention wrapper for a run: `ENABLE_CAFFEINATE=0 make task-build TASK=...`

### 1) Create a task from template

```bash
cp tasks/_template.md tasks/issue-123-my-feature.md
```

Add your high-level input in the task file under `## Objective`.
Example:
- "Update dashboard UI/UX for cleaner hierarchy, better risk-card readability, and improved mobile layout."

### 2) Generate plan (Opus)

```bash
make task-plan TASK=tasks/issue-123-my-feature.md
```

### 3) Human gate (required)

Review the task file and mark:

```md
- [x] Approved for implementation
```

### 4) Build and verify (Codex)

```bash
make task-build TASK=tasks/issue-123-my-feature.md
```

### 5) Review (Sonnet, Opus escalation if needed)

```bash
make task-review TASK=tasks/issue-123-my-feature.md
```

### 6) Ship branch and open PR

```bash
make task-ship TASK=tasks/issue-123-my-feature.md
```

### Optional: One command orchestration

```bash
make task-all TASK=tasks/issue-123-my-feature.md
```

`task-all` always stops for the human gate when approval is unchecked.

### E2E in this workflow

- Local definition: `Makefile` target `e2e`.
- `task-build` executes E2E only when Playwright config exists in `web/`.
- If Playwright is not configured, E2E is skipped.
- Optional manual GitHub run is available in `.github/workflows/pr-validate.yml`.


### Prerequisites
- Docker + Docker Compose
- Make

### 1) Start Postgres
From repo root:

```bash
make up
```

### 2) Create DB schema (run migrations)
```bash
make db-migrate
```


### 3) Start the API
```
make apiup 
```

### The apiup internally uses docker-compose as below
```bash
docker compose up -d --build api
```
### 4) Verify the API is running
```bsh
curl http://localhost:8000/health
```

---

## Crypto Wallet Tracking (EVM + Solana)

### Environment Variables
Set these in your `.env` (never commit secrets):

- `ALCHEMY_API_KEY` (required for EVM balances)
- `HELIUS_API_KEY` (required for Solana balances)
- `COINGECKO_API_KEY` (optional; improves rate limits)
- `CRYPTO_SIGNING_NONCE_TTL_SECONDS` (default `600`)
- `CRYPTO_REFRESH_HOUR_LOCAL` (default `0`, Asia/Singapore time)
- `CRYPTO_SCHEDULER_ENABLED` (default `1`, set `0` to disable scheduler)
- `CRYPTO_SNAPSHOT_MAX_ITEMS` (default `500`)
- `CRYPTO_ADMIN_KEY` (optional; protects `/crypto/refresh-now`)
- `CRYPTO_ADMIN_MIN_INTERVAL_SECONDS` (default `60`)
- `TZ` (default `Asia/Singapore`)

### Wallet Verification Flow (curl)
```bash
curl -X POST http://localhost:8000/crypto/wallets/init \
  -H "Content-Type: application/json" \
  -d '{"chain_type":"evm","chain":"ethereum","address":"0x...","label":"Main"}'

# Sign message with wallet, then:
curl -X POST http://localhost:8000/crypto/wallets/verify \
  -H "Content-Type: application/json" \
  -d '{"wallet_id":"<id>","address":"0x...","signature":"0x..."}'
```

### Crypto Summary (curl)
```bash
curl "http://localhost:8000/crypto/summary?base_currency=SGD"
```

### Manual Refresh (admin)
```bash
curl -X POST http://localhost:8000/crypto/refresh-now -H "X-Admin-Key: <key>"
```

### Logs
```bash
make logs
# or API only:
docker logs -f capitalos-api

###Open a DB shell
```bash
make db-shell
```

### Reset everything (DANGER: deletes DB volume)
```bash
make db-reset
```

---

## Ingestion (IBKR v1)

### Where files and reports are stored

- Raw uploads: `data/raw/<job_id>/...`
- Import reports: `data/reports/<job_id>.json`

The `api` container mounts `./data` to `/app/data` for local-first storage.

### Ingest via UI

1. Create an account (if none exist): `http://localhost:5173/accounts/new`
2. Go to `http://localhost:5173/ingest`
3. Select an account and upload an IBKR Activity Statement CSV.

### Ingest via curl

```bash
curl -s -F "file=@data/fixtures/ibkr_activity_sample.csv" "http://localhost:8000/ingest/ibkr?account_id=<ACCOUNT_ID>"
```

### Ingest smoke test

```bash
make ingest-smoke
```

### Signature and parser registry

The ingestion pipeline computes a deterministic signature from the IBKR CSV (sections + headers + delimiter).
Signatures are mapped to parser keys in `parser_registry`. Unknown signatures are marked `NEEDS_MAPPING`
so you can register a new signature for a new file format.
