# syntax=docker/dockerfile:1.7
# ---- base ----
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl libpq-dev \
 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir uv==0.5.*
WORKDIR /app

# ---- dev ----
# Instala tudo (dev deps também). Sem uv.lock ainda; resolve na hora e mantém
# a resolução em cache no volume nomeado `api_venv`. Bind mount de código faz
# hot reload via `uvicorn --reload`.
FROM base AS dev
COPY pyproject.toml ./
RUN uv sync --no-install-project
COPY . .
EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ---- builder (para runtime) ----
FROM base AS builder
COPY pyproject.toml ./
RUN uv sync --no-dev --no-install-project
COPY . .

# ---- runtime ----
FROM python:3.12-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl libpq5 \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd -r app && useradd -r -g app app
WORKDIR /app
COPY --from=builder /app /app
ENV PATH="/app/.venv/bin:$PATH"
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=6 \
  CMD curl -fsS http://localhost:8000/health || exit 1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
