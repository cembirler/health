# Multi-stage build for apps/api (FastAPI + bundled agent loop). Build
# context is repo root so we can include the editable workspace dep
# (packages/db).

FROM python:3.11-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.5.13 /uv /uvx /usr/local/bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/apps/api/.venv

WORKDIR /app

# Copy the one editable workspace dep the API needs.
COPY packages/db ./packages/db

# Install deps first (cached layer) using only the lockfile + manifest.
COPY apps/api/pyproject.toml apps/api/uv.lock apps/api/.python-version ./apps/api/
WORKDIR /app/apps/api
RUN uv sync --frozen --no-dev --no-install-project

# Copy the rest of the API source and install the project itself.
COPY apps/api ./
RUN uv sync --frozen --no-dev


FROM python:3.11-slim

WORKDIR /app/apps/api

COPY --from=builder /app /app

ENV PATH="/app/apps/api/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8080

# Cloud Run injects $PORT (default 8080). One uvicorn worker — Cloud Run scales
# by spawning instances, not by in-process workers.
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
