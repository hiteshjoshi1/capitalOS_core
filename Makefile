PROJECT=capitalos

# ---- Config ----
GIT_REMOTE?=origin
BASE_BRANCH?=main
# Which stack this checkout drives (#44).
# - The main checkout: with the local, git-ignored docker-compose.oss-test.yml it is the
#   "OSS stack", which holds the REAL data (API :8011, Postgres :5433, project
#   capitalos-oss-test). Without it (a fresh clone) it is the base file as-is: API :8000,
#   Postgres :5432.
# - A git worktree: always an isolated instance of its own (docker-compose.isolated.yml):
#   its own project, container names, ports and database. It never reads the OSS
#   override, and explicit -p/-f beat any COMPOSE_PROJECT_NAME/COMPOSE_FILE from a
#   copied .env.
REAL_DATA_PROJECT=capitalos-oss-test
GIT_DIR_ABS:=$(abspath $(shell git rev-parse --git-dir 2>/dev/null))
GIT_COMMON_ABS:=$(abspath $(shell git rev-parse --git-common-dir 2>/dev/null))
CURRENT_BRANCH:=$(shell git branch --show-current 2>/dev/null)
ifeq ($(GIT_DIR_ABS),$(GIT_COMMON_ABS))
CHECKOUT=main
ifneq ($(wildcard docker-compose.oss-test.yml),)
COMPOSE_PROJECT=$(REAL_DATA_PROJECT)
COMPOSE=docker compose -p $(COMPOSE_PROJECT) -f docker-compose.yml -f docker-compose.oss-test.yml
API_PORT=8011
DB_CONTAINER=capitalos-oss-postgres
API_CONTAINER=capitalos-oss-test-api
else
COMPOSE_PROJECT=capitalos
COMPOSE=docker compose
API_PORT=8000
DB_CONTAINER=capitalos-postgres
API_CONTAINER=capitalos-api
endif
else
CHECKOUT=worktree
# Name and ports come from the worktree's directory, so they're stable per worktree and
# differ between worktrees. Override ISO_NAME / ISO_*_PORT to choose them.
ISO_NAME?=capitalos-wt-$(shell basename "$(CURDIR)" | tr 'A-Z' 'a-z' | tr -c 'a-z0-9\n' '-' | sed 's/-*$$//')
PORT_OFFSET:=$(shell printf '%s' "$(CURDIR)" | cksum | awk '{print 100 + $$1 % 400}')
ISO_API_PORT?=$(shell echo $$((8000 + $(PORT_OFFSET))))
ISO_PG_PORT?=$(shell echo $$((15000 + $(PORT_OFFSET))))
ISO_GRAFANA_PORT?=$(shell echo $$((13000 + $(PORT_OFFSET))))
ISO_LOKI_PORT?=$(shell echo $$((14000 + $(PORT_OFFSET))))
ISO_WEB_PORT?=$(shell echo $$((5200 + $(PORT_OFFSET))))
export ISO_NAME ISO_API_PORT ISO_PG_PORT ISO_GRAFANA_PORT ISO_LOKI_PORT
COMPOSE_PROJECT=$(ISO_NAME)
COMPOSE=COMPOSE_PROJECT_NAME= COMPOSE_FILE= docker compose -p $(COMPOSE_PROJECT) -f docker-compose.yml -f docker-compose.isolated.yml
API_PORT=$(ISO_API_PORT)
DB_CONTAINER=$(ISO_NAME)-postgres
API_CONTAINER=$(ISO_NAME)-api
endif

# Guard (#44): targets that change the stack or its data.
# - In the main checkout with the real-data stack: only on `main`. The API bind-mounts
#   ./api/app with --reload, so a feature branch checked out there would run against the
#   real data. Work in a worktree instead (make worktree ISSUE=<n> SLUG=<slug>), or pass
#   ALLOW_BRANCH=1 deliberately.
# - In a worktree: never the real-data project, containers or ports.
GUARDED_TARGETS=up down build api-up api-build api-rebuild deploy db-migrate db-reset db-restore db-adopt-migrations \
	db-seed-dummy db-clear-dummy db-seed-demo db-clear-demo ownership-reassign db-create-mcp-role user-set-password \
	observability-up observability-down observability-smoke
ifneq ($(filter $(GUARDED_TARGETS),$(MAKECMDGOALS)),)
ifeq ($(CHECKOUT),main)
ifeq ($(COMPOSE_PROJECT),$(REAL_DATA_PROJECT))
ifneq ($(CURRENT_BRANCH),main)
ifneq ($(ALLOW_BRANCH),1)
$(error Refusing '$(filter $(GUARDED_TARGETS),$(MAKECMDGOALS))': this checkout drives the REAL-data stack but is on '$(CURRENT_BRANCH)', not main. Its API runs this checkout's code. Work in a worktree (make worktree ISSUE=<n> SLUG=<slug>), or pass ALLOW_BRANCH=1 if you really mean it)
endif
endif
endif
else
ifneq ($(filter $(REAL_DATA_PROJECT) capitalos,$(COMPOSE_PROJECT)),)
$(error Refusing: a worktree must not drive project '$(COMPOSE_PROJECT)')
endif
ifneq ($(filter capitalos-oss-% capitalos-postgres capitalos-api,$(DB_CONTAINER) $(API_CONTAINER)),)
$(error Refusing: a worktree must not use the containers '$(DB_CONTAINER)' / '$(API_CONTAINER)')
endif
ifneq ($(filter 8011 5433 8000 5432,$(ISO_API_PORT) $(ISO_PG_PORT)),)
$(error Refusing: a worktree must not use the main stack's ports ($(ISO_API_PORT)/$(ISO_PG_PORT)))
endif
endif
endif
CORE_SERVICES=postgres api
DB_USER?=capitalos
DB_NAME?=capitalos
SMOKE_USER?=demo
SMOKE_PASSWORD?=Test@1234

OBSERVABILITY_SERVICES=loki grafana alloy docker-socket-proxy
OBSERVABILITY_ENV_FILE=$(shell test -f config/observability.env && printf '%s' config/observability.env || printf '%s' config/observability.env.example)
# Same project as COMPOSE, so observability runs alongside whichever stack is active.
OBSERVABILITY_COMPOSE=$(COMPOSE) --env-file $(OBSERVABILITY_ENV_FILE)
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
COMMIT_MSG?=

ifneq ($(filter commit,$(MAKECMDGOALS)),)
  ifeq ($(strip $(COMMIT_MSG)),)
    COMMIT_MSG:=$(wordlist 2,$(words $(MAKECMDGOALS)),$(MAKECMDGOALS))
  endif
  .DEFAULT:
	@:
endif

# ---- Helpers ----
define require_task
	@test -n "$(TASK)" || (echo "Usage: make $(1) TASK=tasks/issue-<id>-<slug>.md THREAD_ID=<thread-id>" && exit 2)
	@test -f "$(TASK)" || (echo "Task file does not exist: $(TASK)" && exit 2)
endef

define require_thread
	@test -n "$(THREAD_ID)" || (echo "Usage: make $(1) TASK=tasks/issue-<id>-<slug>.md THREAD_ID=<thread-id>" && exit 2)
endef

define require_resume_json
	$(if $(strip $(RESUME_JSON)),,@echo "Usage: make $(1) TASK=tasks/issue-<id>-<slug>.md THREAD_ID=<thread-id> RESUME_JSON='{\"decision\":\"approved\",...}'" && exit 2)
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
.PHONY: build up down ps logs api-up web-up api-logs api-url openapi web-deps pr-open-if-ahead commit observability-up observability-down observability-logs observability-smoke grafana-url worktree where status instance-drop test-instance test-instance-start test-instance-status test-instance-pr test-instance-drop api-build deploy deploy-plan deploy-status observability-running

build:
	$(COMPOSE) build

up:
	$(COMPOSE) up -d $(CORE_SERVICES)

down:
	$(COMPOSE) down

ps:
	$(COMPOSE) ps

logs:
	$(COMPOSE) logs -f

api-up:
	$(COMPOSE) up -d --build api

ifeq ($(CHECKOUT),worktree)
# A worktree's web app talks only to the worktree's own API, through the Vite proxy, on
# its own port (no web/.env.local needed).
web-up: web-deps
	cd $(WEB_DIR) && VITE_API_BASE=/api VITE_API_PORT=$(API_PORT) VITE_INSTANCE_LABEL="$(or $(INSTANCE_LABEL),DEV $(CURRENT_BRANCH))" npm run dev -- --port $(ISO_WEB_PORT) --strictPort
else
web-up: web-deps
	cd $(WEB_DIR) && npm run dev
endif

api-logs:
	docker logs -f $(API_CONTAINER)

# Host URL of the API for this checkout (8011 with the local OSS override, else 8000;
# a worktree's own port).
api-url:
	@echo http://127.0.0.1:$(API_PORT)

# Where things stand (#47): board, open PRs, real stack, deploy, backups, worktrees.
# Read-only; also shown at every Claude Code session start (.claude/settings.json).
status:
	@scripts/status.sh

# Which stack this checkout drives (#44).
where:
	@echo "checkout: $(CHECKOUT) ($(CURRENT_BRANCH))"
	@echo "project:  $(COMPOSE_PROJECT)$(if $(filter $(REAL_DATA_PROJECT),$(COMPOSE_PROJECT)),  <- REAL DATA,)"
	@echo "api:      http://127.0.0.1:$(API_PORT)   db container: $(DB_CONTAINER)"
	@$(if $(filter worktree,$(CHECKOUT)),echo "web:      http://localhost:$(ISO_WEB_PORT)   postgres: 127.0.0.1:$(ISO_PG_PORT)   grafana: :$(ISO_GRAFANA_PORT)",true)

# The test instance (#45): a batch of PRs on a separate app with a copy of the real data,
# tested by Hitesh before main. Run from the main checkout. See scripts/test-instance.sh.
test-instance:
	@test -n "$(PRS)" || (echo 'Usage: make test-instance PRS="<n> <n>"' && exit 2)
	@scripts/test-instance.sh up $(PRS)

test-instance-start:
	@scripts/test-instance.sh start

test-instance-status:
	@scripts/test-instance.sh status

test-instance-pr:
	@scripts/test-instance.sh pr

test-instance-drop:
	@scripts/test-instance.sh drop

# Remove a worktree's own instance with its volumes (#44). Only in a worktree: in the main
# checkout this would delete the real data, so it refuses.
instance-drop:
ifeq ($(CHECKOUT),worktree)
	$(COMPOSE) --profile observability --profile tools down -v --remove-orphans
else
	@echo "Refusing: instance-drop only runs in a worktree (it deletes the instance's volumes)." >&2; exit 2
endif

# Start work on an issue in its own worktree (#44), so this checkout stays on main and the
# real-data stack keeps running main's code: make worktree ISSUE=44 SLUG=branch-isolation
WORKTREES_DIR?=$(abspath $(GIT_COMMON_ABS)/../../capitalOS-worktrees)
worktree:
	@test -n "$(ISSUE)" -a -n "$(SLUG)" || (echo "Usage: make worktree ISSUE=<n> SLUG=<slug>" && exit 2)
	git fetch -q $(GIT_REMOTE)
	git worktree add -b feature/issue-$(ISSUE)-$(SLUG) "$(WORKTREES_DIR)/issue-$(ISSUE)-$(SLUG)" $(GIT_REMOTE)/$(BASE_BRANCH)
	@echo "Worktree ready: cd $(WORKTREES_DIR)/issue-$(ISSUE)-$(SLUG) && make where && make up"

observability-up:
	$(OBSERVABILITY_COMPOSE) up -d $(OBSERVABILITY_SERVICES)

observability-down:
	$(OBSERVABILITY_COMPOSE) stop $(OBSERVABILITY_SERVICES)

observability-logs:
	$(OBSERVABILITY_COMPOSE) logs -f $(OBSERVABILITY_SERVICES)

observability-smoke:
	API_COMPOSE="$(COMPOSE)" API_URL=http://127.0.0.1:$(API_PORT) ./scripts/observability-smoke.sh

grafana-url:
	@echo "http://localhost:3000"

openapi:
	curl -s http://localhost:$(API_PORT)/openapi.json > openapi.json
	@echo "Wrote openapi.json"

pr-open-if-ahead:
	@branch=$$(git rev-parse --abbrev-ref HEAD); \
	if [ "$$branch" = "$(BASE_BRANCH)" ]; then \
		echo "Refusing to open a PR from base branch '$(BASE_BRANCH)'."; \
		exit 2; \
	fi; \
	git fetch $(GIT_REMOTE) $(BASE_BRANCH); \
	ahead=$$(git rev-list --count $(GIT_REMOTE)/$(BASE_BRANCH)..HEAD); \
	if [ "$$ahead" -eq 0 ]; then \
		echo "Branch '$$branch' is not ahead of $(GIT_REMOTE)/$(BASE_BRANCH); no PR created."; \
		exit 0; \
	fi; \
	if gh pr view --head "$$branch" --json url >/dev/null 2>&1; then \
		url=$$(gh pr view --head "$$branch" --json url --jq .url); \
		echo "PR already exists: $$url"; \
	else \
		git push -u $(GIT_REMOTE) "$$branch"; \
		gh pr create --base "$(BASE_BRANCH)" --head "$$branch" --fill; \
	fi

commit:
	@test -n "$(strip $(COMMIT_MSG))" || (echo 'Usage: make commit "<commit message>"' && exit 2)
	@branch=$$(git rev-parse --abbrev-ref HEAD); \
	if [ "$$branch" = "$(BASE_BRANCH)" ]; then \
		echo "Refusing to commit and push from base branch '$(BASE_BRANCH)'."; \
		exit 2; \
	fi
	git add .
	git commit -m "$(COMMIT_MSG)"
	git push

$(WEB_NODE_MODULES_STAMP): $(WEB_PACKAGE_MANIFESTS)
	cd $(WEB_DIR) && npm ci
	@touch "$(WEB_NODE_MODULES_STAMP)"

web-deps: $(WEB_NODE_MODULES_STAMP)

# ---- DB helpers ----
.PHONY: user-set-password db-shell db-wait db-migrate db-adopt-migrations db-reset db-seed-dummy db-clear-dummy db-seed-demo db-clear-demo db-query ownership-reassign db-backup db-restore db-create-mcp-role db-backup-verify backup-prune backup-status backup-schedule backup-unschedule backup-now

# Forgotten password (#72): prompts for the new one (never on the command line) and signs
# out every session of that user. In the main checkout this is the real app.
user-set-password:
	@test -n "$(USERNAME)" || { echo "Usage: make user-set-password USERNAME=<name>" >&2; exit 2; }
	$(COMPOSE) exec api python -m app.scripts.set_password "$(USERNAME)"

# Read-only role for the capitalos-postgres MCP server. Uses MCP_DB_PASSWORD from
# .env, generating one there on first run (.env is git-ignored). Idempotent.
db-create-mcp-role: db-wait
	@pw=$$(sed -n 's/^MCP_DB_PASSWORD=//p' .env 2>/dev/null | tail -1); \
	if [ -z "$$pw" ]; then \
		pw=$$(openssl rand -hex 24); \
		printf '\n# Read-only DB password for the capitalos-postgres MCP server (make db-create-mcp-role)\nMCP_DB_PASSWORD=%s\n' "$$pw" >> .env; \
		echo "Generated MCP_DB_PASSWORD in .env"; \
	fi; \
	MCP_DB_PASSWORD="$$pw" docker exec -i -e MCP_DB_PASSWORD $(DB_CONTAINER) \
		psql -q -v ON_ERROR_STOP=1 -U $(DB_USER) -d $(DB_NAME) < scripts/db-create-mcp-role.sql && \
	echo "Role capitalos_mcp_ro is ready (read-only, no access to user_credentials/auth_sessions)."

# Verified backups (#41): dump + exact snapshot counts, then a restore into a scratch DB
# that must reproduce every table's row count. See scripts/db-backup.sh.
DB_BACKUP=DB_CONTAINER=$(DB_CONTAINER) DB_USER=$(DB_USER) DB_NAME=$(DB_NAME) scripts/db-backup.sh
db-backup: db-wait
	@$(DB_BACKUP) create

db-backup-verify: db-wait
	@test -n "$(BACKUP)" || (echo "Usage: make db-backup-verify BACKUP=backups/capitalos_<timestamp>.dump" && exit 2)
	@$(DB_BACKUP) verify "$(BACKUP)"

backup-prune:
	@$(DB_BACKUP) prune $(or $(KEEP),14)

backup-status:
	@$(DB_BACKUP) status
	@scripts/backup-schedule.sh status

backup-schedule:
	@scripts/backup-schedule.sh install

backup-unschedule:
	@scripts/backup-schedule.sh uninstall

backup-now:
	@scripts/backup-schedule.sh run

db-restore:
	@test -n "$(BACKUP_FILE)" || (echo "Usage: make db-restore BACKUP_FILE=backups/capitalos_<timestamp>.dump" && exit 2)
	@test -f "$(BACKUP_FILE)" || (echo "Backup file not found: $(BACKUP_FILE)" && exit 2)
	@echo "WARNING: this overwrites the current database ($(DB_NAME)) in $(DB_CONTAINER)."
	@read -p "Type 'yes' to continue: " confirm; [ "$$confirm" = "yes" ] || (echo "Aborted." && exit 1)
	docker exec -i $(DB_CONTAINER) pg_restore -U $(DB_USER) -d $(DB_NAME) --clean --if-exists < $(BACKUP_FILE)
	@echo "Restore complete."

db-shell:
	docker exec -it $(DB_CONTAINER) psql -U $(DB_USER) -d $(DB_NAME)

# Bounded wait, so a scheduled backup fails (and logs why) instead of hanging forever
# when Docker or the database is down.
# Over TCP: on a fresh volume the entrypoint runs a temporary socket-only server for initdb
# and then restarts; a socket check passes too early and the next command hits the shutdown.
DB_WAIT_SECONDS?=120
db-wait:
	@echo "Waiting for Postgres to be ready..."
	@n=0; until docker exec $(DB_CONTAINER) pg_isready -h 127.0.0.1 -U $(DB_USER) -d $(DB_NAME) > /dev/null 2>&1 ; do \
		n=$$((n + 1)); \
		if [ $$n -ge $(DB_WAIT_SECONDS) ]; then \
			echo "Postgres ($(DB_CONTAINER)) not ready after $(DB_WAIT_SECONDS)s: is Docker running and the stack up (make up)?" >&2; exit 1; \
		fi; \
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
		{ cat "$$f"; printf "\nINSERT INTO schema_migrations (filename) VALUES ('%s');\n" "$$filename"; } | \
			docker exec -i $(DB_CONTAINER) psql -q -1 -v ON_ERROR_STOP=1 -U $(DB_USER) -d $(DB_NAME) > /dev/null || { \
			echo "Migration $$f FAILED: rolled back, not recorded; later migrations not run." >&2; exit 1; }; \
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
	@echo "DANGER: this DELETES the database volume of compose project '$(COMPOSE_PROJECT)'."
	@echo "Run 'make db-backup' first if you want to keep anything."
	@read -p "Type the project name '$(COMPOSE_PROJECT)' to continue: " confirm; [ "$$confirm" = "$(COMPOSE_PROJECT)" ] || (echo "Aborted." && exit 1)
	$(COMPOSE) down -v
	$(COMPOSE) up -d $(CORE_SERVICES)
	$(MAKE) db-migrate

db-seed-dummy: db-wait
	@echo "Seeding dummy demo data..."
	@docker exec -i $(DB_CONTAINER) psql -v ON_ERROR_STOP=1 -U $(DB_USER) -d $(DB_NAME) < migrations/seed_dummy.sql
	@echo "Dummy data seeded."

db-clear-dummy: db-wait
	@echo "Removing dummy demo data..."
	@docker exec -i $(DB_CONTAINER) psql -v ON_ERROR_STOP=1 -U $(DB_USER) -d $(DB_NAME) < migrations/seed_dummy_cleanup.sql
	@echo "Dummy data removed."

db-seed-demo: db-seed-dummy

db-clear-demo: db-clear-dummy

db-query:
	@test -n "$(QUERY)" || (echo "Usage: make db-query QUERY='SELECT ...';" && exit 2)
	docker exec -i $(DB_CONTAINER) psql -U $(DB_USER) -d $(DB_NAME) -c "$(QUERY)"

ownership-reassign:
	@test -n "$(TARGET_USER_ID)" || (echo "Usage: make ownership-reassign TARGET_USER_ID=<id> [APPLY=1]" && exit 2)
	$(COMPOSE) run --rm api python -m app.scripts.reassign_legacy_ownership --target-user-id $(TARGET_USER_ID) $(if $(APPLY),--apply,)

# ---- Quality gates ----
# ---- Python lock files (#81) ----
# requirements*.in hold our direct pins; these compile them, with every transitive package and
# its hashes, into requirements*.txt (what the image and the orchestration venv install, with
# --require-hashes). Existing pins are kept unless UPGRADE=1. Afterwards check-lock-age.py fails
# on any transitive package under 14 days old (D-1; direct pins are reviewed one by one, and can
# be security fixes). Needs network; the API lock runs in the API's own base image.
.PHONY: api-lock orch-lock
PIP_TOOLS_VERSION=7.6.2
LOCK_PIP_VERSION=26.2.2
API_PY_IMAGE=$(shell grep -m1 -o 'python:3.12-slim@sha256:[0-9a-f]*' api/Dockerfile)
PIP_COMPILE_ARGS=-q --generate-hashes --strip-extras $(if $(UPGRADE),--upgrade)

api-lock:
	docker run --rm -v "$(CURDIR)/api:/work" -w /work -e CUSTOM_COMPILE_COMMAND="make api-lock" $(API_PY_IMAGE) sh -c '\
		pip install -q --root-user-action=ignore "pip==$(LOCK_PIP_VERSION)" && \
		pip install -q --root-user-action=ignore "pip-tools==$(PIP_TOOLS_VERSION)" && \
		pip-compile $(PIP_COMPILE_ARGS) -o requirements.txt requirements.in && \
		pip-compile $(PIP_COMPILE_ARGS) -o requirements-dev.txt requirements-dev.in'
	scripts/check-lock-age.py api/requirements.txt api/requirements.in
	scripts/check-lock-age.py api/requirements-dev.txt api/requirements-dev.in api/requirements.in

# The orchestration venv runs on the host's Python ($(PYTHON)), so its lock is compiled there.
orch-lock:
	@tmp=$$(mktemp -d) && trap 'rm -r "$$tmp"' EXIT && \
	$(PYTHON) -m venv "$$tmp/venv" && \
	"$$tmp/venv/bin/pip" install -q "pip==$(LOCK_PIP_VERSION)" && \
	"$$tmp/venv/bin/pip" install -q "pip-tools==$(PIP_TOOLS_VERSION)" && \
	CUSTOM_COMPILE_COMMAND="make orch-lock" "$$tmp/venv/bin/pip-compile" $(PIP_COMPILE_ARGS) -o orchestration/requirements.txt orchestration/requirements.in
	scripts/check-lock-age.py orchestration/requirements.txt orchestration/requirements.in

.PHONY: lint typecheck test-backend contract-backend test-frontend contract-frontend e2e test test-all verify

lint: web-deps
	cd $(WEB_DIR) && npm run lint
	scripts/check-pinned-refs.sh
	scripts/test-checkout-guard.sh
	$(COMPOSE) run --rm --build --no-deps api-dev ruff check app tests

typecheck: web-deps
	cd $(WEB_DIR) && npx tsc -b --pretty false
	$(COMPOSE) run --rm --build --no-deps api-dev mypy app

test-backend:
	$(COMPOSE) run --rm --build --no-deps api-dev pytest

contract-backend:
	$(COMPOSE) run --rm --build --no-deps api-dev pytest tests/test_contracts.py -q

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
.PHONY: orch-bootstrap orch-test orch-coverage task-prepare task-plan task-build task-agent-review task-approve-plan task-human-review task-rework task-ship task-all task-resume task-respond task-export-state task-import-state task-restore-state task-salvage-plan task-state-show task-orch-smoke task-run task-status

orch-bootstrap:
	$(PYTHON) -m venv "$(ORCH_VENV)"
	"$(ORCH_PIP)" install --upgrade "pip>=26.2"
	"$(ORCH_PIP)" install --require-hashes -r orchestration/requirements.txt

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

task-run:
	$(call require_task,task-run)
	$(call require_thread,task-run)
	$(call require_orch_runtime,task-run)
	$(if $(CAFFEINATE),$(CAFFEINATE) -dimsu ,)$(ORCH_PYTHON) -m $(ORCH_MODULE) all $(ORCH_INIT_ARGS)

task-status:
	$(call require_task,task-status)
	$(call require_thread,task-status)
	$(call require_orch_runtime,task-status)
	$(ORCH_PYTHON) -m $(ORCH_MODULE) export-state $(ORCH_BASE_ARGS)

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
	@echo 'make task-approve-plan TASK=tasks/issue-123-example.md THREAD_ID=issue-123 RESUME_JSON='\''{"gate_type":"plan_approval","decision":"approved","reviewer":"YourName","notes":"Looks good","questions":[],"response_requirements":[],"unresolved_comments":[]}'\'''

task-human-review-approve-example:
	@echo 'make task-human-review TASK=tasks/issue-123-example.md THREAD_ID=issue-123 RESUME_JSON='\''{"decision":"approved","reviewer":"YourName","notes":"Looks good","questions":[],"response_requirements":[],"unresolved_comments":[]}'\'''

task-human-review-fix-example:
	@echo 'make task-human-review TASK=tasks/issue-123-example.md THREAD_ID=issue-123 RESUME_JSON='\''{"decision":"needs_fixes","reviewer":"YourName","notes":"Please address the routing issue","questions":["Was the edge case covered?"],"response_requirements":["Show the exact routing fix"],"unresolved_comments":["Do not ship until corrected"]}'\'''

# ---- Cleanup helpers ----
.PHONY: task-cache-clean orch-clean

task-cache-clean:
	rm -rf .task-cache/

orch-clean:
	rm -rf .task-flow/

# ---- Image security scan (local twin of .github/workflows/security-scan.yml) ----
# Builds the runtime API image on a freshly pulled base and fails on fixable
# HIGH/CRITICAL findings; compose images are reported but don't fail the target.
TRIVY_IMAGE?=$(shell scripts/tool-image.sh trivy)
TRIVY=docker run --rm -v /var/run/docker.sock:/var/run/docker.sock -v capitalos-trivy-cache:/root/.cache $(TRIVY_IMAGE) image --quiet --skip-version-check --table-mode detailed --scanners vuln --ignore-unfixed --severity HIGH,CRITICAL
SCAN_API_IMAGE=capitalos-api:security-scan
.PHONY: security-scan
security-scan:
	docker build --pull --target runtime -t $(SCAN_API_IMAGE) api
	$(TRIVY) --exit-code 1 $(SCAN_API_IMAGE)
	@for img in $$(docker compose -f docker-compose.yml --profile observability config --images | grep -v -- '-api') $$(scripts/tool-image.sh mcp-toolbox); do \
		echo "== $$img (report only)"; $(TRIVY) $$img | grep -E '^(Total:|[a-z].*\()' || true; \
	done

# ---- SBOMs, provenance, pruning (issue 214) ----
# Every pinned third-party image plus the tool images.
PINNED_IMAGES=$$(docker compose -f docker-compose.yml --profile observability config --images | grep -v -- '-api'; sed -n 's/^FROM \([^ ]*@sha256:[^ ]*\) AS .*/\1/p' tools/Dockerfile api/Dockerfile)
.PHONY: sbom sbom-find verify-image verify-images docker-prune
sbom:
	docker build --target runtime -t $(SCAN_API_IMAGE) api
	scripts/sbom.sh $(SCAN_API_IMAGE) $(PINNED_IMAGES)

# Which images contain a package, e.g. make sbom-find PKG=openssl (run make sbom first).
sbom-find:
	@test -n "$(PKG)" || (echo "Usage: make sbom-find PKG=<package-name>" && exit 2)
	@python3 -c 'import json,glob,sys; pkg=sys.argv[1].lower(); hits=[(f[5:-9], c.get("name"), c.get("version","")) for f in sorted(glob.glob("sbom/*.cdx.json")) for c in json.load(open(f)).get("components",[]) if pkg in (c.get("name") or "").lower()]; [print(f"{i:55} {n} {v}") for i,n,v in hits] or print("no image contains", sys.argv[1])' "$(PKG)"

# Provenance/signature check for one ref (e.g. the new ref in a Dependabot PR) or all pinned images.
verify-image:
	@test -n "$(IMAGE)" || (echo "Usage: make verify-image IMAGE=<image:tag@sha256:digest>" && exit 2)
	@scripts/verify-image.sh "$(IMAGE)"

verify-images:
	@rc=0; for ref in $(PINNED_IMAGES); do scripts/verify-image.sh "$$ref" || rc=1; done; exit $$rc

# Lists unused images of repos this project pins (and old CapitalOS builds); APPLY=1 removes them.
docker-prune:
	@COMPOSE_PROJECT=$(COMPOSE_PROJECT) APPLY=$(APPLY) scripts/docker-prune.sh

# ---- Existing smoke/utility targets (kept for compatibility) ----
.PHONY: api-smoke api-test api-coverage ingest-smoke crypto-smoke api-rebuild web-rebuild api-shell web-test

# Build the API images without restarting anything (deploy builds, migrates, then restarts).
api-build:
	$(COMPOSE) build --pull api api-dev

# Install merged main into the real-data stack (#46): backup if migrating, migrate, rebuild,
# health check. Main checkout on main only. See scripts/deploy.sh.
deploy:
	@scripts/deploy.sh $(COMMIT)

deploy-plan:
	@scripts/deploy.sh --plan $(FROM) $(TO)

deploy-status:
	@scripts/deploy.sh --status

# Exit 0 when this checkout's own observability stack (its compose project) is running.
observability-running:
	@test -n "$$($(OBSERVABILITY_COMPOSE) ps -q --status running loki 2>/dev/null)"

api-rebuild:
	# --pull refreshes python:3.12-slim so OS security patches land on every rebuild.
	$(COMPOSE) build --pull api api-dev
	$(COMPOSE) up -d api

web-rebuild:
	cd $(WEB_DIR) && npm run build

api-shell:
	$(COMPOSE) exec -T api python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/health').read().decode())"

web-test: test-frontend

api-smoke:
	$(COMPOSE) exec -T api python -c "import json, urllib.request; base='http://localhost:8000'; print(urllib.request.urlopen(base + '/health').read().decode()); login_req=urllib.request.Request(base + '/auth/login', data=json.dumps({'username':'$(SMOKE_USER)','password':'$(SMOKE_PASSWORD)'}).encode(), headers={'Content-Type':'application/json'}, method='POST'); token=json.loads(urllib.request.urlopen(login_req).read().decode())['access_token']; summary_req=urllib.request.Request(base + '/dashboard/summary?month=2026-02', headers={'Authorization': 'Bearer ' + token}); print(urllib.request.urlopen(summary_req).read().decode())"

api-test: test-backend

api-coverage:
	$(COMPOSE) run --rm --build --no-deps api-dev pytest --cov=app --cov-report=term-missing

ingest-smoke:
	@echo "Running ingest smoke..."
	@TOKEN=$$(curl -sf -X POST http://127.0.0.1:$(API_PORT)/auth/login \
		-H "Content-Type: application/json" \
		-d "{\"username\":\"$(SMOKE_USER)\",\"password\":\"$(SMOKE_PASSWORD)\"}" | \
		python3 -c 'import sys, json; print(json.load(sys.stdin)["access_token"])'); \
	ACCOUNT_ID=$$(curl -sf -H "Authorization: Bearer $$TOKEN" http://127.0.0.1:$(API_PORT)/accounts | python3 - <<'PY'\nimport sys, json\ntry:\n    data = json.load(sys.stdin)\n    print(data[0]['id'] if data else '')\nexcept Exception:\n    print('')\nPY\n); \
	if [ -z "$$ACCOUNT_ID" ]; then \
		echo "No accounts found. Create an account first."; \
		exit 1; \
	fi; \
	curl -sf -H "Authorization: Bearer $$TOKEN" -F "file=@data/fixtures/ibkr_activity_sample.csv" "http://127.0.0.1:$(API_PORT)/ingest/ibkr?account_id=$$ACCOUNT_ID"; \
	echo

crypto-smoke:
	@TOKEN=$$(curl -sf -X POST http://127.0.0.1:$(API_PORT)/auth/login \
		-H "Content-Type: application/json" \
		-d "{\"username\":\"$(SMOKE_USER)\",\"password\":\"$(SMOKE_PASSWORD)\"}" | \
		python3 -c 'import sys, json; print(json.load(sys.stdin)["access_token"])'); \
	curl -sf -H "Authorization: Bearer $$TOKEN" "http://127.0.0.1:$(API_PORT)/crypto/summary?base_currency=USD" && echo
