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

api-smoke:
	curl -s http://localhost:8000/health
	curl -s "http://localhost:8000/dashboard/summary?month=2026-02"

.PHONY: api-test

api-test:
	docker compose run --rm api pytest

logs:
	docker compose logs -f
