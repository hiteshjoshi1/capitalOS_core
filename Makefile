PROJECT=capitalos

# ---- Config ----
DB_CONTAINER=capitalos-postgres
DB_USER?=capitalos
DB_NAME?=capitalos

API_CONTAINER=capitalos-api
WEB_DIR=web

# ---- Primary lifecycle ----
.PHONY: up down ps logs api-up web-up api-logs openapi

up:
	docker compose up -d

down:
	docker compose down

ps:
	docker compose ps

logs:
	docker compose logs -f

api-up:
	docker compose up -d --build api

web-up:
	cd $(WEB_DIR) && npm install && npm run dev

api-logs:
	docker logs -f $(API_CONTAINER)

openapi:
	curl -s http://localhost:8000/openapi.json > openapi.json
	@echo "Wrote openapi.json"

# ---- DB helpers ----
.PHONY: db-shell db-wait db-migrate db-reset db-seed-dummy db-clear-dummy db-query

db-shell:
	docker exec -it $(DB_CONTAINER) psql -U $(DB_USER) -d $(DB_NAME)

db-wait:
	@echo "Waiting for Postgres to be ready..."
	@until docker exec $(DB_CONTAINER) pg_isready -U $(DB_USER) -d $(DB_NAME) > /dev/null 2>&1 ; do \
		sleep 1; \
	done
	@echo "Postgres is ready."

# Runs all migrations in alphabetical order
db-migrate: db-wait
	@echo "Running migrations..."
	@for f in $$(ls -1 migrations/*.sql | sort); do \
		echo "==> $$f"; \
		docker exec -i $(DB_CONTAINER) psql -U $(DB_USER) -d $(DB_NAME) < $$f; \
	done
	@echo "Migrations complete."

# DANGER: drops the DB volume and recreates everything
db-reset:
	docker compose down -v
	docker compose up -d
	$(MAKE) db-migrate

db-seed-dummy: db-wait
	@echo "Seeding dummy demo data..."
	@docker exec -i $(DB_CONTAINER) psql -U $(DB_USER) -d $(DB_NAME) < migrations/seed_dummy.sql
	@echo "Dummy data seeded."

db-clear-dummy: db-wait
	@echo "Removing dummy demo data..."
	@docker exec -i $(DB_CONTAINER) psql -U $(DB_USER) -d $(DB_NAME) < migrations/seed_dummy_cleanup.sql
	@echo "Dummy data removed."

# Usage: make db-query QUERY="SELECT count(*) FROM accounts;"
db-query:
	@test -n "$(QUERY)" || (echo "Usage: make db-query QUERY='SELECT ...';" && exit 2)
	docker exec -i $(DB_CONTAINER) psql -U $(DB_USER) -d $(DB_NAME) -c "$(QUERY)"

# ---- Quality gates ----
.PHONY: lint typecheck test-backend test-frontend e2e verify task-prepare task-plan task-build task-review task-rework task-ship task-all

# Frontend lint + optional backend lint if ruff is installed in API image.
lint:
	cd $(WEB_DIR) && npm install && npm run lint
	docker compose run --rm api sh -lc "if command -v ruff >/dev/null 2>&1; then ruff check app tests; else echo 'ruff not installed in api image; skipping backend lint'; fi"

# Frontend TS typecheck + optional backend typecheck if mypy is installed.
typecheck:
	cd $(WEB_DIR) && npm install && npx tsc -b --pretty false
	docker compose run --rm api sh -lc "if command -v mypy >/dev/null 2>&1; then mypy app; else echo 'mypy not installed in api image; skipping backend typecheck'; fi"

test-backend:
	docker compose run --rm api pytest

test-frontend:
	cd $(WEB_DIR) && npm install && npm test -- --run

# Requires Playwright to be set up in ./web (config + @playwright/test).
e2e:
	@test -f "$(WEB_DIR)/playwright.config.ts" -o -f "$(WEB_DIR)/playwright.config.js" || (echo "Playwright is not configured in ./web yet." && exit 2)
	cd $(WEB_DIR) && npm install && npx playwright test

verify: lint typecheck test-backend test-frontend

# ---- AI task workflow ----
task-prepare:
	@test -n "$(TASK)" || (echo "Usage: make task-prepare TASK=tasks/issue-<id>-<slug>.md" && exit 2)
	./scripts/task_flow.sh prepare "$(TASK)"

task-plan:
	@test -n "$(TASK)" || (echo "Usage: make task-plan TASK=tasks/issue-<id>-<slug>.md" && exit 2)
	./scripts/task_flow.sh plan "$(TASK)"

task-build:
	@test -n "$(TASK)" || (echo "Usage: make task-build TASK=tasks/issue-<id>-<slug>.md" && exit 2)
	./scripts/task_flow.sh build "$(TASK)"

task-review:
	@test -n "$(TASK)" || (echo "Usage: make task-review TASK=tasks/issue-<id>-<slug>.md" && exit 2)
	./scripts/task_flow.sh review "$(TASK)"

task-rework:
	@test -n "$(TASK)" || (echo "Usage: make task-rework TASK=tasks/issue-<id>-<slug>.md" && exit 2)
	./scripts/task_flow.sh rework "$(TASK)"

task-ship:
	@test -n "$(TASK)" || (echo "Usage: make task-ship TASK=tasks/issue-<id>-<slug>.md" && exit 2)
	./scripts/task_flow.sh ship "$(TASK)"

task-all:
	@test -n "$(TASK)" || (echo "Usage: make task-all TASK=tasks/issue-<id>-<slug>.md" && exit 2)
	./scripts/task_flow.sh all "$(TASK)"

# ---- Existing smoke/utility targets (kept for compatibility) ----
.PHONY: api-smoke api-test api-coverage ingest-smoke crypto-smoke api-rebuild web-rebuild api-shell web-test

api-rebuild:
	docker compose build api
	docker compose up -d api

web-rebuild:
	docker compose build web
	docker compose up -d web

api-shell:
	curl -s http://localhost:8000/health && echo

web-test: test-frontend

api-smoke:
	curl -s http://localhost:8000/health
	curl -s "http://localhost:8000/dashboard/summary?month=2026-02"

api-test: test-backend

api-coverage:
	docker compose run --rm api pytest --cov=app --cov-report=term-missing

ingest-smoke:
	@echo "Running ingest smoke..."
	@ACCOUNT_ID=$$(curl -s http://localhost:8000/accounts | python3 - <<'PY'\nimport sys, json\ntry:\n    data = json.load(sys.stdin)\n    print(data[0]['id'] if data else '')\nexcept Exception:\n    print('')\nPY\n); \\
	if [ -z "$$ACCOUNT_ID" ]; then \\
		echo "No accounts found. Create an account first."; \\
		exit 1; \\
	fi; \\
	curl -s -F "file=@data/fixtures/ibkr_activity_sample.csv" "http://localhost:8000/ingest/ibkr?account_id=$$ACCOUNT_ID"; \\
	echo

crypto-smoke:
	curl -s "http://localhost:8000/crypto/summary?base_currency=USD"
