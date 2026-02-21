PROJECT=capitalos
# ---- Config ----
DB_CONTAINER=capitalos-postgres
DB_USER=capitalos
DB_NAME=capitalos

# ---- Docker ----
.PHONY: up down logs ps

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f

api-rebuild:
	docker compose build api
	docker compose up -d api

web-rebuild:
	docker compose build web
	docker compose up -d web

ps:
	docker compose ps

# ---- DB helpers ----
.PHONY: db-shell db-wait db-migrate db-reset
.PHONY: db-seed-dummy db-clear-dummy

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

.PHONY: api-logs api-shell

api-logs:
	docker logs -f capitalos-api

api-shell:
	curl -s http://localhost:8000/health && echo

.PHONY: openapi

openapi:
	curl -s http://localhost:8000/openapi.json > openapi.json
	@echo "Wrote openapi.json"

.PHONY: apiup

api-up:
	docker compose up -d --build api

.PHONY: webup

web-up:
	cd web && npm install && npm run dev

.PHONY: web-test

web-test:
	cd web && npm install && npm test

api-smoke:
	curl -s http://localhost:8000/health
	curl -s "http://localhost:8000/dashboard/summary?month=2026-02"

.PHONY: api-test

api-test:
	docker compose run --rm api pytest

.PHONY: ingest-smoke

ingest-smoke:
	@echo "Running ingest smoke..."
	@ACCOUNT_ID=$$(curl -s http://localhost:8000/accounts | python3 - <<'PY'\nimport sys, json\ntry:\n    data = json.load(sys.stdin)\n    print(data[0]['id'] if data else '')\nexcept Exception:\n    print('')\nPY\n); \\\n	if [ -z \"$$ACCOUNT_ID\" ]; then \\\n		echo \"No accounts found. Create an account first.\"; \\\n		exit 1; \\\n	fi; \\\n	curl -s -F \"file=@data/fixtures/ibkr_activity_sample.csv\" \"http://localhost:8000/ingest/ibkr?account_id=$$ACCOUNT_ID\"; \\\n	echo

logs:
	docker compose logs -f
