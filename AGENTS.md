# AGENTS.md
Project: CapitalOS
Purpose: Local-first AI-native personal finance + investing system
Architecture: Postgres + FastAPI + React (Vite) in Docker
Mode: Deterministic, verifiable, reproducible

---

# Core Principles

1. No silent breaking changes.
2. All changes must compile and run.
3. All APIs must remain OpenAPI-compatible.
4. No hardcoded IDs.
5. All logic must be testable via curl.
6. Every change must be verifiable via a Makefile command.

---

# Environment Assumptions

- Docker installed
- Docker Compose available
- Node 18+
- Python 3.12 (only inside container)
- Postgres 16 (Docker)

---

# Single Source of Truth

Backend:
- api/app/

Frontend:
- web/src/

Database:
- Postgres in Docker

---

# One-Command Lifecycle

## Start everything

make up

## Stop everything

make down

## Rebuild API

make api-rebuild

## Rebuild Web

make web-rebuild

## Reset database (DESTRUCTIVE)

make db-reset

## Run API tests (curl smoke)

make api-smoke

## Quick verify (default)
make up
make api-smoke
make web-up  


---

# Verification Rules

After ANY backend change:

1. make api-rebuild
2. curl http://localhost:8000/health
3. curl http://localhost:8000/dashboard/summary?month=YYYY-MM

After ANY frontend change:

1. make web-rebuild
2. open http://localhost:5173

---

# Snapshot Rule

- Snapshot anchor day controlled via:
  SNAPSHOT_DAY env var
- Default: 6
- Effective snapshot = max(as_of) <= anchor

Never change this logic silently.

---

# API Contract Rules

Never remove fields from responses.

You may:
- Add optional fields
- Add new endpoints

If modifying response schema:
- Update OpenAPI
- Update TypeScript types
- Update frontend rendering

---

# Coding Standards

Backend:
- SQLAlchemy ORM for models
- Raw SQL allowed only for aggregation
- No business logic in routers
- Pure functions for calculations

Frontend:
- TypeScript strict
- No any
- API types must mirror backend response
- No hardcoded month

---

# Data Rules

Transactions:
- Signed amounts
- Transfers must not affect income/expense
- Fees must reduce net

Positions:
- One snapshot per month
- Snapshot_day configurable

---

# Adding a New Feature

Steps:

1. Update DB (DDL or migration)
2. Update models
3. Update router
4. Update API types
5. Update frontend
6. make api-rebuild
7. make web-rebuild
8. Run api-smoke

No partial implementations.

---

# Future Modules (Do Not Implement Yet)

- CSV ingestion engine
- Realized P&L engine
- Valuation service
- RAG intelligence layer
- Portfolio attribution engine

These belong to later modules.

---

# OpenAPI

Spec available at:
http://localhost:8000/openapi.json

Interactive docs:
http://localhost:8000/docs

Never break these routes.

---

# Definition of Done

A change is complete only if:

- Containers start
- No import errors
- No SQL errors
- Dashboard loads
- API returns valid JSON
- Types compile

---

# Philosophy

This system is:

- Deterministic
- Auditable
- Reproducible
- Infrastructure-first
- AI-native but not AI-dependent

---

## Change budget
- Prefer minimal diffs.
- Do not reformat unrelated files.
- No repo-wide refactors unless explicitly asked.
- Touch at most N files unless task requires more.

We build instrumentation first.
Intelligence comes later.
