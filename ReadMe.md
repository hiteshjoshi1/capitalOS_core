# CapitalOS

CapitalOS is a local-first, open-source personal capital operating system.

It provides a unified view of net worth, asset allocation, concentration risk, and spending behavior across multiple asset classes and financial accounts. The long-term goal is to build infrastructure for disciplined capital allocation and AI-assisted analysis, while keeping judgment, traceability, and process at the center.

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

- **Local-first**: Runs on your machine.
- **Source-of-truth driven**: Every number should trace back to a file, account, or on-chain address.
- **Judgment over automation**: Systems support decisions; they do not replace them.
- **Process-oriented**: Outcomes should be comparable against original intent.
- **Composable**: Modules can evolve independently.
- **Open by design**: Built for learning, experimentation, and transparency.

---

## What CapitalOS Is

CapitalOS is a foundation for building:

- a personal financial system of record
- portfolio visibility across multiple asset classes
- ingestion and normalization pipelines
- decision support tooling
- future AI-assisted workflows for analysis, review, and process improvement

---

## What CapitalOS Is Not

- Not a robo-advisor
- Not a trading platform
- Not a forecasting engine
- Not a consumer budgeting app
- Not a system that automates financial judgment away from the user

---

## Product Direction

CapitalOS is organized into several conceptual layers.

### Module A — Personal Financial Brain
Structured visibility into:

- portfolio across asset classes and geographies
- bank balances
- credit cards
- spending

Outputs include:

- net worth
- asset allocation
- savings rate
- burn rate
- concentration and risk visibility

This answers questions such as:

- What is my net worth?
- Where is my capital allocated?
- How am I spending?
- Where is risk concentrated?

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

### Module C — Investment Decision System (future)
Provides structure for:

- investment memos
- checklists
- decision logs
- thesis tracking

AI can assist with preparation, but humans retain judgment.

### Module D — Feedback Loop (future)
Tracks:

- expected vs actual outcomes
- root causes
- recurring errors
- winning patterns

Designed to compound learning over time.

### Module E — Public Thinking Layer (optional)
Exports sanitized artifacts such as:

- memos
- post-mortems
- mental models
- process changes

The emphasis is on reasoning, not performance signaling.

---

## Technology Stack

Current stack:

- **Backend**: FastAPI (Python)
- **Frontend**: React + TypeScript
- **Database**: PostgreSQL
- **Local runtime**: Docker Compose
- **Workflow orchestration**: LangGraph + Pydantic

The application is local-first today, but structured so it can later be migrated to managed infrastructure if needed.

---

## Repository Structure

High level:

- `app/` — backend application
- `web/` — frontend application
- `migrations/` — database migrations
- `data/` — local raw files, fixtures, and reports
- `tasks/` — human-facing issue/task markdown files
- `orchestration/` — LangGraph workflow, typed models, nodes, services, prompts, tests

---

## Getting Started

### Prerequisites

- Docker + Docker Compose
- Python 3.11+ recommended
- Node.js / npm
- Make

Optional, for AI workflow features:

- GitHub CLI (`gh`)
- Copilot CLI / builder tooling used by your orchestration services

---

## Running the Application

### 1. Start local services

```bash
make up