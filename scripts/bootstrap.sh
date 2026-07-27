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

# Seed do catálogo TBCA: idempotente (upsert por canonical_name). Precisa
# rodar em toda subida para pegar novas linhas do seed_tbca.csv adicionadas
# em releases. Sem isso, MealService.create_from_llm devolve `hit=None` para
# alimentos e persiste `food_items` com kcal=0 e catalog_ref_id=NULL, o que
# também quebra a confirmação (PATCH não consegue recompute sem catalog_ref_id).
echo "→ Seed do catálogo TBCA (idempotente)…"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" run --rm api \
  python -m app.cli seed-nutrition

echo "OK. Suba os serviços com:"
echo "  docker compose -f $COMPOSE_FILE --env-file $ENV_FILE up -d"
