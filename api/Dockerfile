# Two targets share one base:
#   runtime (default) - what `make up` runs: app code and runtime deps only,
#                       non-root, no pip, no test/lint tooling.
#   dev               - adds pytest/ruff/mypy and tests/ for the `api-dev`
#                       compose service (make test-backend / lint / typecheck).
FROM python:3.12-slim@sha256:aa943ce411423c7582288f18707ff66eddcbaeb510502d747a72aeb34f30d159 AS base

WORKDIR /app
ENV PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1

# Fixed uid/gid so bind-mounted ./data ownership is predictable; override per
# host with CAPITALOS_UID / CAPITALOS_GID in .env (see docker-compose.yml).
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --no-create-home --shell /usr/sbin/nologin app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade "pip>=26.2" \
    && pip install --no-cache-dir -r /app/requirements.txt


FROM base AS dev

COPY requirements-dev.txt /app/requirements-dev.txt
RUN pip install --no-cache-dir -r /app/requirements-dev.txt \
    && pip uninstall -y pip

COPY app /app/app
COPY tests /app/tests
COPY pytest.ini /app/pytest.ini
COPY pyproject.toml /app/pyproject.toml
# Tools write caches (.mypy_cache, .ruff_cache, .pytest_cache) under /app.
RUN chown app:app /app

USER app


FROM base AS runtime

# pip (and the urllib3/msgpack/setuptools copies vendored inside it) is only
# needed to build the image.
RUN pip uninstall -y pip

COPY app /app/app

USER app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host=0.0.0.0", "--port=8000"]
