#!/usr/bin/env bash
# app_plan §14.7 / Const. §24 — Deploy bootstrap.
#
# Roda migrations Alembic e cria/atualiza o admin default. Idempotente:
# pode ser rodado em toda subida sem risco.
#
# Uso:
#   ./scripts/bootstrap.sh [.env.production]
#
# Const. §6 (INV-6): a API em runtime NUNCA roda migrations — é
# responsabilidade deste script rodar antes do `up -d`.
set -euo pipefail

ENV_FILE="${1:-.env.production}"
COMPOSE_FILE="docker-compose.production.yml"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "ERRO: $ENV_FILE não existe. Copie de .env.production.example."
  exit 1
fi

echo "→ Aplicando migrations…"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" run --rm api \
  alembic upgrade head

echo "→ Bootstrap do admin default (idempotente)…"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" run --rm api \
  python -m app.cli bootstrap

echo "OK. Suba os serviços com:"
echo "  docker compose -f $COMPOSE_FILE --env-file $ENV_FILE up -d"
