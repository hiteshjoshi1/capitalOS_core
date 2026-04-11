PROJECT=capitalos

# ---- Config ----
DB_CONTAINER=capitalos-postgres
DB_USER?=capitalos
DB_NAME?=capitalos
SMOKE_USER?=demo
SMOKE_PASSWORD?=Test@1234

API_CONTAINER=capitalos-api
WEB_DIR=web
WEB_PACKAGE_MANIFESTS=$(WEB_DIR)/package.json $(WEB_DIR)/package-lock.json
WEB_NODE_MODULES_STAMP=$(WEB_DIR)/node_modules/.install-stamp

PYTHON?=python3
ORCH_VENV?=.venv-orch
ORCH_PYTHON?=$(ORCH_VENV)/bin/python
ORCH_PIP?=$(ORCH_VENV)/bin/pip
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
CAFFEINATE?=$(shell command -v caffeinate 2>/dev/null)

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

define require_orch_runtime
	@test -x "$(ORCH_PYTHON)" || (echo "Managed orchestration runtime missing at $(ORCH_PYTHON). Run: make orch-bootstrap" && exit 2)
endef

ORCH_BASE_ARGS=--thread-id "$(THREAD_ID)" --task-file "$(TASK)" --repo-root . --db-path "$(DB_PATH)"

ORCH_INIT_ARGS=$(ORCH_BASE_ARGS) \
	$(if $(ISSUE_ID),--issue-id "$(ISSUE_ID)",) \
	$(if $(SLUG),--slug "$(SLUG)",) \
	$(if $(TITLE),--title "$(TITLE)",)

define run_llm_orch
	$(call require_orch_runtime,$(1))
	$(if $(CAFFEINATE),$(CAFFEINATE) -dimsu ,)$(ORCH_PYTHON) -m $(ORCH_MODULE) $(1)
endef

# ---- Primary lifecycle ----
.PHONY: up down ps logs api-up web-up api-logs openapi web-deps

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

web-up: web-deps
	cd $(WEB_DIR) && npm run dev

api-logs:
	docker logs -f $(API_CONTAINER)

openapi:
	curl -s http://localhost:8000/openapi.json > openapi.json
	@echo "Wrote openapi.json"

$(WEB_NODE_MODULES_STAMP): $(WEB_PACKAGE_MANIFESTS)
	cd $(WEB_DIR) && npm ci
	@touch "$(WEB_NODE_MODULES_STAMP)"

web-deps: $(WEB_NODE_MODULES_STAMP)

# ---- DB helpers ----
.PHONY: db-shell db-wait db-migrate db-adopt-migrations db-reset db-seed-dummy db-clear-dummy db-seed-demo db-clear-demo db-query ownership-reassign

db-shell:
	docker exec -it $(DB_CONTAINER) psql -U $(DB_USER) -d $(DB_NAME)

db-wait:
	@echo "Waiting for Postgres to be ready..."
	@until docker exec $(DB_CONTAINER) pg_isready -U $(DB_USER) -d $(DB_NAME) > /dev/null 2>&1 ; do \
		sleep 1; \
	done
	@echo "Postgres is ready."

db-migrate: db-wait
	@docker exec -i $(DB_CONTAINER) psql -v ON_ERROR_STOP=1 -U $(DB_USER) -d $(DB_NAME) -c "CREATE TABLE IF NOT EXISTS schema_migrations (filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW());" > /dev/null
	@tracked_count=$$(docker exec -i $(DB_CONTAINER) psql -At -U $(DB_USER) -d $(DB_NAME) -c "SELECT COUNT(*) FROM schema_migrations;"); \
	public_table_count=$$(docker exec -i $(DB_CONTAINER) psql -At -U $(DB_USER) -d $(DB_NAME) -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name <> 'schema_migrations';"); \
	if [ "$$tracked_count" = "0" ] && [ "$$public_table_count" -gt 0 ]; then \
		echo "Legacy database detected without migration tracking."; \
		echo "Run 'make db-adopt-migrations' once to mark existing numbered migrations as applied without replaying them."; \
		exit 2; \
	fi
	@echo "Running migrations..."
	@for f in $$(ls -1 migrations/[0-9][0-9][0-9]_*.sql | sort); do \
		filename=$$(basename "$$f"); \
		applied=$$(docker exec -i $(DB_CONTAINER) psql -At -U $(DB_USER) -d $(DB_NAME) -c "SELECT 1 FROM schema_migrations WHERE filename = '$$filename' LIMIT 1;"); \
		if [ "$$applied" = "1" ]; then \
			echo "==> $$f (already applied)"; \
			continue; \
		fi; \
		echo "==> $$f"; \
		docker exec -i $(DB_CONTAINER) psql -v ON_ERROR_STOP=1 -U $(DB_USER) -d $(DB_NAME) < $$f; \
		docker exec -i $(DB_CONTAINER) psql -v ON_ERROR_STOP=1 -U $(DB_USER) -d $(DB_NAME) -c "INSERT INTO schema_migrations (filename) VALUES ('$$filename');" > /dev/null; \
	done
	@echo "Migrations complete."

db-adopt-migrations: db-wait
	@docker exec -i $(DB_CONTAINER) psql -v ON_ERROR_STOP=1 -U $(DB_USER) -d $(DB_NAME) -c "CREATE TABLE IF NOT EXISTS schema_migrations (filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW());" > /dev/null
	@public_table_count=$$(docker exec -i $(DB_CONTAINER) psql -At -U $(DB_USER) -d $(DB_NAME) -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public' AND table_name <> 'schema_migrations';"); \
	if [ "$$public_table_count" = "0" ]; then \
		echo "Database is empty; nothing to adopt. Run 'make db-migrate' instead."; \
		exit 2; \
	fi
	@echo "Adopting existing numbered migrations without executing SQL..."
	@for f in $$(ls -1 migrations/[0-9][0-9][0-9]_*.sql | sort); do \
		filename=$$(basename "$$f"); \
		echo "==> $$f"; \
		docker exec -i $(DB_CONTAINER) psql -v ON_ERROR_STOP=1 -U $(DB_USER) -d $(DB_NAME) -c "INSERT INTO schema_migrations (filename) VALUES ('$$filename') ON CONFLICT (filename) DO NOTHING;" > /dev/null; \
	done
	@echo "Migration adoption complete."

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

db-seed-demo: db-seed-dummy

db-clear-demo: db-clear-dummy

db-query:
	@test -n "$(QUERY)" || (echo "Usage: make db-query QUERY='SELECT ...';" && exit 2)
	docker exec -i $(DB_CONTAINER) psql -U $(DB_USER) -d $(DB_NAME) -c "$(QUERY)"

ownership-reassign:
	@test -n "$(TARGET_USER_ID)" || (echo "Usage: make ownership-reassign TARGET_USER_ID=<id> [APPLY=1]" && exit 2)
	docker compose run --rm api python -m app.scripts.reassign_legacy_ownership --target-user-id $(TARGET_USER_ID) $(if $(APPLY),--apply,)

# ---- Quality gates ----
.PHONY: lint typecheck test-backend contract-backend test-frontend contract-frontend e2e test test-all verify

lint: web-deps
	cd $(WEB_DIR) && npm run lint
	docker compose run --rm api sh -lc "if command -v ruff >/dev/null 2>&1; then ruff check app tests; else echo 'ruff not installed in api image; skipping backend lint'; fi"

typecheck: web-deps
	cd $(WEB_DIR) && npx tsc -b --pretty false
	docker compose run --rm api sh -lc "if command -v mypy >/dev/null 2>&1; then mypy app; else echo 'mypy not installed in api image; skipping backend typecheck'; fi"

test-backend:
	docker compose run --rm api pytest

contract-backend:
	docker compose run --rm api pytest tests/test_contracts.py -q

test-frontend: web-deps
	cd $(WEB_DIR) && npm test -- --run

contract-frontend: web-deps
	cd $(WEB_DIR) && npm test -- --run src/__tests__/contracts.test.tsx

e2e: web-deps
	@test -f "$(WEB_DIR)/playwright.config.ts" -o -f "$(WEB_DIR)/playwright.config.js" || (echo "Playwright is not configured in ./web yet." && exit 2)
	cd $(WEB_DIR) && npx playwright test

test-all: test-backend contract-backend test-frontend contract-frontend orch-test e2e

test: test-all

verify: lint typecheck test-backend test-frontend

# ---- LangGraph task workflow ----
.PHONY: orch-bootstrap orch-test orch-coverage task-prepare task-plan task-build task-agent-review task-approve-plan task-human-review task-rework task-ship task-all task-resume task-respond task-export-state task-import-state task-restore-state task-salvage-plan task-state-show task-orch-smoke task-v3-run task-v3-resume task-v3-status

orch-bootstrap:
	$(PYTHON) -m venv "$(ORCH_VENV)"
	"$(ORCH_PIP)" install -r orchestration/requirements.txt

orch-test:
	$(call require_orch_runtime,orch-test)
	"$(ORCH_PYTHON)" -m pytest orchestration/tests -q

orch-coverage:
	$(call require_orch_runtime,orch-coverage)
	@mkdir -p .task-flow/coverage
	"$(ORCH_PYTHON)" -m pytest orchestration/tests \
		--cov=orchestration \
		--cov-config=.coveragerc \
		--cov-report=term-missing \
		--cov-report=xml:.task-flow/coverage/orchestration-coverage.xml \
		--cov-report=json:.task-flow/coverage/orchestration-coverage.json \
		-q

task-prepare:
	$(call require_task,task-prepare)
	$(call require_thread,task-prepare)
	$(call require_orch_runtime,task-prepare)
	$(ORCH_PYTHON) -m $(ORCH_MODULE) prepare $(ORCH_INIT_ARGS)

task-plan:
	$(call require_task,task-plan)
	$(call require_thread,task-plan)
	$(call run_llm_orch,plan $(ORCH_INIT_ARGS))

task-build:
	$(call require_task,task-build)
	$(call require_thread,task-build)
	$(call run_llm_orch,build $(ORCH_INIT_ARGS))

task-agent-review:
	$(call require_task,task-agent-review)
	$(call require_thread,task-agent-review)
	$(call run_llm_orch,agent-review $(ORCH_INIT_ARGS))

task-approve-plan:
	$(call require_task,task-approve-plan)
	$(call require_thread,task-approve-plan)
	$(call require_resume_json,task-approve-plan)
	$(call run_llm_orch,approve-plan $(ORCH_BASE_ARGS) --resume-json '$(RESUME_JSON)')

task-human-review:
	$(call require_task,task-human-review)
	$(call require_thread,task-human-review)
	$(call require_resume_json,task-human-review)
	$(call run_llm_orch,human-review $(ORCH_BASE_ARGS) --resume-json '$(RESUME_JSON)')

task-rework:
	$(call require_task,task-rework)
	$(call require_thread,task-rework)
	$(call run_llm_orch,rework $(ORCH_INIT_ARGS))

task-ship:
	$(call require_task,task-ship)
	$(call require_thread,task-ship)
	$(call require_orch_runtime,task-ship)
	$(ORCH_PYTHON) -m $(ORCH_MODULE) ship $(ORCH_INIT_ARGS)

task-all:
	$(call require_task,task-all)
	$(call require_thread,task-all)
	$(call run_llm_orch,all $(ORCH_INIT_ARGS))

task-v3-run:
	$(call require_task,task-v3-run)
	$(call require_thread,task-v3-run)
	$(call require_orch_runtime,task-v3-run)
	PIPELINE_VERSION=v3 $(if $(CAFFEINATE),$(CAFFEINATE) -dimsu ,)$(ORCH_PYTHON) -m $(ORCH_MODULE) all $(ORCH_INIT_ARGS)

task-v3-resume:
	$(call require_task,task-v3-resume)
	$(call require_thread,task-v3-resume)
	$(call require_resume_json,task-v3-resume)
	$(call require_orch_runtime,task-v3-resume)
	PIPELINE_VERSION=v3 $(if $(CAFFEINATE),$(CAFFEINATE) -dimsu ,)$(ORCH_PYTHON) -m $(ORCH_MODULE) resume $(ORCH_BASE_ARGS) --resume-json '$(RESUME_JSON)'

task-v3-status:
	$(call require_task,task-v3-status)
	$(call require_thread,task-v3-status)
	$(call require_orch_runtime,task-v3-status)
	PIPELINE_VERSION=v3 $(ORCH_PYTHON) -m $(ORCH_MODULE) export-state $(ORCH_BASE_ARGS)

task-resume:
	$(call require_task,task-resume)
	$(call require_thread,task-resume)
	$(call require_resume_json,task-resume)
	$(call run_llm_orch,resume $(ORCH_BASE_ARGS) --resume-json '$(RESUME_JSON)')

task-respond:
	$(call require_task,task-respond)
	$(call require_thread,task-respond)
	$(call run_llm_orch,respond $(ORCH_BASE_ARGS))

task-export-state:
	$(call require_task,task-export-state)
	$(call require_thread,task-export-state)
	$(call require_orch_runtime,task-export-state)
	$(ORCH_PYTHON) -m $(ORCH_MODULE) export-state $(ORCH_BASE_ARGS)

task-import-state:
	$(call require_task,task-import-state)
	$(call require_thread,task-import-state)
	$(call require_state_file,task-import-state)
	$(call require_orch_runtime,task-import-state)
	$(ORCH_PYTHON) -m $(ORCH_MODULE) import-state $(ORCH_BASE_ARGS) --state-file "$(STATE_FILE)"

task-restore-state:
	$(call require_task,task-restore-state)
	$(call require_thread,task-restore-state)
	$(call require_state_file,task-restore-state)
	$(call require_restart_at,task-restore-state)
	$(call require_orch_runtime,task-restore-state)
	$(ORCH_PYTHON) -m $(ORCH_MODULE) restore-state $(ORCH_BASE_ARGS) --state-file "$(STATE_FILE)" --restart-at "$(RESTART_AT)"

task-salvage-plan:
	$(call require_task,task-salvage-plan)
	$(call require_thread,task-salvage-plan)
	$(call require_orch_runtime,task-salvage-plan)
	$(ORCH_PYTHON) -m $(ORCH_MODULE) salvage-plan $(ORCH_INIT_ARGS)

task-state-show:
	$(call require_task,task-state-show)
	$(call require_thread,task-state-show)
	@echo "Checkpoint DB: $(DB_PATH)"
	@echo "Thread ID: $(THREAD_ID)"
	@echo "Task file: $(TASK)"
	@echo "To inspect structured state:"
	@echo "  make task-export-state TASK=$(TASK) THREAD_ID=$(THREAD_ID)"

task-orch-smoke:
	@$(call require_orch_runtime,task-orch-smoke)
	@"$(ORCH_PYTHON)" -c "import orchestration.cli, orchestration.graph, orchestration.state; from orchestration.services.persistence import get_checkpointer; get_checkpointer('.task-flow/langgraph.sqlite'); print('orchestration import smoke: ok')"

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
	docker compose exec -T api python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/health').read().decode())"

web-test: test-frontend

api-smoke:
	docker compose exec -T api python -c "import json, urllib.request; base='http://localhost:8000'; print(urllib.request.urlopen(base + '/health').read().decode()); login_req=urllib.request.Request(base + '/auth/login', data=json.dumps({'username':'$(SMOKE_USER)','password':'$(SMOKE_PASSWORD)'}).encode(), headers={'Content-Type':'application/json'}, method='POST'); token=json.loads(urllib.request.urlopen(login_req).read().decode())['access_token']; summary_req=urllib.request.Request(base + '/dashboard/summary?month=2026-02', headers={'Authorization': 'Bearer ' + token}); print(urllib.request.urlopen(summary_req).read().decode())"

api-test: test-backend

api-coverage:
	docker compose run --rm api pytest --cov=app --cov-report=term-missing

ingest-smoke:
	@echo "Running ingest smoke..."
	@TOKEN=$$(curl -sf -X POST http://127.0.0.1:8000/auth/login \
		-H "Content-Type: application/json" \
		-d "{\"username\":\"$(SMOKE_USER)\",\"password\":\"$(SMOKE_PASSWORD)\"}" | \
		python3 -c 'import sys, json; print(json.load(sys.stdin)["access_token"])'); \
	ACCOUNT_ID=$$(curl -sf -H "Authorization: Bearer $$TOKEN" http://127.0.0.1:8000/accounts | python3 - <<'PY'\nimport sys, json\ntry:\n    data = json.load(sys.stdin)\n    print(data[0]['id'] if data else '')\nexcept Exception:\n    print('')\nPY\n); \
	if [ -z "$$ACCOUNT_ID" ]; then \
		echo "No accounts found. Create an account first."; \
		exit 1; \
	fi; \
	curl -sf -H "Authorization: Bearer $$TOKEN" -F "file=@data/fixtures/ibkr_activity_sample.csv" "http://127.0.0.1:8000/ingest/ibkr?account_id=$$ACCOUNT_ID"; \
	echo

crypto-smoke:
	@TOKEN=$$(curl -sf -X POST http://127.0.0.1:8000/auth/login \
		-H "Content-Type: application/json" \
		-d "{\"username\":\"$(SMOKE_USER)\",\"password\":\"$(SMOKE_PASSWORD)\"}" | \
		python3 -c 'import sys, json; print(json.load(sys.stdin)["access_token"])'); \
	curl -sf -H "Authorization: Bearer $$TOKEN" "http://127.0.0.1:8000/crypto/summary?base_currency=USD" && echo
