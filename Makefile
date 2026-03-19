PROJECT=capitalos

# ---- Config ----
DB_CONTAINER=capitalos-postgres
DB_USER?=capitalos
DB_NAME?=capitalos

API_CONTAINER=capitalos-api
WEB_DIR=web

PYTHON?=python3
ORCH_MODULE=orchestration.cli
THREAD_ID?=
TASK?=
ISSUE_ID?=
SLUG?=
TITLE?=
DB_PATH?=.task-flow/langgraph.sqlite
RESTART_AT?=
STATE_FILE?=
RESUME_JSON?=

# ---- Helpers ----
define require_task
	@test -n "$(TASK)" || (echo "Usage: make $(1) TASK=tasks/issue-<id>-<slug>.md THREAD_ID=<thread-id>" && exit 2)
endef

define require_thread
	@test -n "$(THREAD_ID)" || (echo "Usage: make $(1) TASK=tasks/issue-<id>-<slug>.md THREAD_ID=<thread-id>" && exit 2)
endef

define require_resume_json
	@test -n "$(RESUME_JSON)" || (echo "Usage: make $(1) TASK=tasks/issue-<id>-<slug>.md THREAD_ID=<thread-id> RESUME_JSON='{\"decision\":\"approved\",...}'" && exit 2)
endef

define require_state_file
	@test -n "$(STATE_FILE)" || (echo "Usage: make $(1) TASK=tasks/issue-<id>-<slug>.md THREAD_ID=<thread-id> STATE_FILE=.task-flow/exports/<file>.json" && exit 2)
endef

define require_restart_at
	@test -n "$(RESTART_AT)" || (echo "Usage: make $(1) TASK=tasks/issue-<id>-<slug>.md THREAD_ID=<thread-id> STATE_FILE=<file> RESTART_AT=<stage>" && exit 2)
endef

ORCH_BASE_ARGS=--thread-id "$(THREAD_ID)" --task-file "$(TASK)" --repo-root . --db-path "$(DB_PATH)"

ORCH_INIT_ARGS=$(ORCH_BASE_ARGS) \
	$(if $(ISSUE_ID),--issue-id "$(ISSUE_ID)",) \
	$(if $(SLUG),--slug "$(SLUG)",) \
	$(if $(TITLE),--title "$(TITLE)",)

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

db-migrate: db-wait
	@echo "Running migrations..."
	@for f in $$(ls -1 migrations/*.sql | sort); do \
		echo "==> $$f"; \
		docker exec -i $(DB_CONTAINER) psql -U $(DB_USER) -d $(DB_NAME) < $$f; \
	done
	@echo "Migrations complete."

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

db-query:
	@test -n "$(QUERY)" || (echo "Usage: make db-query QUERY='SELECT ...';" && exit 2)
	docker exec -i $(DB_CONTAINER) psql -U $(DB_USER) -d $(DB_NAME) -c "$(QUERY)"

# ---- Quality gates ----
.PHONY: lint typecheck test-backend test-frontend e2e verify

lint:
	cd $(WEB_DIR) && npm install && npm run lint
	docker compose run --rm api sh -lc "if command -v ruff >/dev/null 2>&1; then ruff check app tests; else echo 'ruff not installed in api image; skipping backend lint'; fi"

typecheck:
	cd $(WEB_DIR) && npm install && npx tsc -b --pretty false
	docker compose run --rm api sh -lc "if command -v mypy >/dev/null 2>&1; then mypy app; else echo 'mypy not installed in api image; skipping backend typecheck'; fi"

test-backend:
	docker compose run --rm api pytest

test-frontend:
	cd $(WEB_DIR) && npm install && npm test -- --run

e2e:
	@test -f "$(WEB_DIR)/playwright.config.ts" -o -f "$(WEB_DIR)/playwright.config.js" || (echo "Playwright is not configured in ./web yet." && exit 2)
	cd $(WEB_DIR) && npm install && npx playwright test

verify: lint typecheck test-backend test-frontend

# ---- LangGraph task workflow ----
.PHONY: task-prepare task-plan task-build task-agent-review task-approve-plan task-human-review task-rework task-ship task-all task-resume task-export-state task-import-state task-restore-state task-state-show task-orch-smoke

task-prepare:
	$(call require_task,task-prepare)
	$(call require_thread,task-prepare)
	$(PYTHON) -m $(ORCH_MODULE) prepare $(ORCH_INIT_ARGS)

task-plan:
	$(call require_task,task-plan)
	$(call require_thread,task-plan)
	$(PYTHON) -m $(ORCH_MODULE) plan $(ORCH_INIT_ARGS)

task-build:
	$(call require_task,task-build)
	$(call require_thread,task-build)
	$(PYTHON) -m $(ORCH_MODULE) build $(ORCH_INIT_ARGS)

task-agent-review:
	$(call require_task,task-agent-review)
	$(call require_thread,task-agent-review)
	$(PYTHON) -m $(ORCH_MODULE) agent-review $(ORCH_INIT_ARGS)

task-approve-plan:
	$(call require_task,task-approve-plan)
	$(call require_thread,task-approve-plan)
	$(call require_resume_json,task-approve-plan)
	$(PYTHON) -m $(ORCH_MODULE) approve-plan $(ORCH_BASE_ARGS) --resume-json '$(RESUME_JSON)'

task-human-review:
	$(call require_task,task-human-review)
	$(call require_thread,task-human-review)
	$(call require_resume_json,task-human-review)
	$(PYTHON) -m $(ORCH_MODULE) human-review $(ORCH_BASE_ARGS) --resume-json '$(RESUME_JSON)'

task-rework:
	$(call require_task,task-rework)
	$(call require_thread,task-rework)
	$(PYTHON) -m $(ORCH_MODULE) rework $(ORCH_INIT_ARGS)

task-ship:
	$(call require_task,task-ship)
	$(call require_thread,task-ship)
	$(PYTHON) -m $(ORCH_MODULE) ship $(ORCH_INIT_ARGS)

task-all:
	$(call require_task,task-all)
	$(call require_thread,task-all)
	$(PYTHON) -m $(ORCH_MODULE) all $(ORCH_INIT_ARGS)

task-resume:
	$(call require_task,task-resume)
	$(call require_thread,task-resume)
	$(call require_resume_json,task-resume)
	$(PYTHON) -m $(ORCH_MODULE) resume $(ORCH_BASE_ARGS) --resume-json '$(RESUME_JSON)'

task-export-state:
	$(call require_task,task-export-state)
	$(call require_thread,task-export-state)
	$(PYTHON) -m $(ORCH_MODULE) export-state $(ORCH_BASE_ARGS)

task-import-state:
	$(call require_task,task-import-state)
	$(call require_thread,task-import-state)
	$(call require_state_file,task-import-state)
	$(PYTHON) -m $(ORCH_MODULE) import-state $(ORCH_BASE_ARGS) --state-file "$(STATE_FILE)"

task-restore-state:
	$(call require_task,task-restore-state)
	$(call require_thread,task-restore-state)
	$(call require_state_file,task-restore-state)
	$(call require_restart_at,task-restore-state)
	$(PYTHON) -m $(ORCH_MODULE) restore-state $(ORCH_BASE_ARGS) --state-file "$(STATE_FILE)" --restart-at "$(RESTART_AT)"

task-state-show:
	$(call require_task,task-state-show)
	$(call require_thread,task-state-show)
	@echo "Checkpoint DB: $(DB_PATH)"
	@echo "Thread ID: $(THREAD_ID)"
	@echo "Task file: $(TASK)"
	@echo "To inspect structured state:"
	@echo "  make task-export-state TASK=$(TASK) THREAD_ID=$(THREAD_ID)"

task-orch-smoke:
	@$(PYTHON) -c "import orchestration.cli, orchestration.graph, orchestration.state; print('orchestration import smoke: ok')"

# ---- Suggested structured resume examples ----
.PHONY: task-approve-plan-example task-human-review-approve-example task-human-review-fix-example

task-approve-plan-example:
	@echo 'make task-approve-plan TASK=tasks/issue-123-example.md THREAD_ID=issue-123 RESUME_JSON='\''{"gate_type":"plan_approval","decision":"approved","reviewer":"Hitesh","notes":"Looks good","questions":[],"response_requirements":[],"unresolved_comments":[]}'\'''

task-human-review-approve-example:
	@echo 'make task-human-review TASK=tasks/issue-123-example.md THREAD_ID=issue-123 RESUME_JSON='\''{"decision":"approved","reviewer":"Hitesh","notes":"Looks good","questions":[],"response_requirements":[],"unresolved_comments":[]}'\'''

task-human-review-fix-example:
	@echo 'make task-human-review TASK=tasks/issue-123-example.md THREAD_ID=issue-123 RESUME_JSON='\''{"decision":"needs_fixes","reviewer":"Hitesh","notes":"Please address the routing issue","questions":["Was the edge case covered?"],"response_requirements":["Show the exact routing fix"],"unresolved_comments":["Do not ship until corrected"]}'\'''

# ---- Cleanup helpers ----
.PHONY: task-cache-clean orch-clean

task-cache-clean:
	rm -rf .task-cache/

orch-clean:
	rm -rf .task-flow/

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
	@ACCOUNT_ID=$$(curl -s http://localhost:8000/accounts | python3 - <<'PY'\nimport sys, json\ntry:\n    data = json.load(sys.stdin)\n    print(data[0]['id'] if data else '')\nexcept Exception:\n    print('')\nPY\n); \
	if [ -z "$$ACCOUNT_ID" ]; then \
		echo "No accounts found. Create an account first."; \
		exit 1; \
	fi; \
	curl -s -F "file=@data/fixtures/ibkr_activity_sample.csv" "http://localhost:8000/ingest/ibkr?account_id=$$ACCOUNT_ID"; \
	echo

crypto-smoke:
	curl -s "http://localhost:8000/crypto/summary?base_currency=USD"