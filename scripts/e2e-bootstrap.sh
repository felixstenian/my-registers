#!/usr/bin/env bash
# Sobe stack E2E isolada (docker-compose.e2e.yml) e aguarda api + web
# ficarem prontas. Idempotente: rodar 2x não quebra nada; `down -v` limpa.
#
# Uso:
#   ./scripts/e2e-bootstrap.sh            # sobe + aguarda
#   ./scripts/e2e-bootstrap.sh --rebuild  # rebuild forçado das imagens
#   ./scripts/e2e-bootstrap.sh --down     # desmonta e apaga volumes
#
# Migrations, `bootstrap` (admin) e `seed-nutrition` (catálogo TBCA) já
# rodam no `command` do serviço api (docker-compose.e2e.yml), então este
# script só orquestra: sobe → aguarda healthchecks → sanity check.
set -euo pipefail
cd "$(dirname "$0")/.."

COMPOSE_FILE="docker-compose.e2e.yml"
API_URL="http://localhost:8001"
WEB_URL="http://localhost:3001"

if [[ "${1:-}" == "--down" ]]; then
  docker compose -f "$COMPOSE_FILE" down -v
  echo "Stack E2E desmontada e volumes apagados."
  exit 0
fi

echo "→ Subindo stack E2E (docker-compose.e2e.yml)…"
# Sem --wait: minio-init sai com exit 0 mas o compose reporta non-zero,
# derrubando `set -e`. Polling manual abaixo é mais controlável.
if [[ "${1:-}" == "--rebuild" ]]; then
  docker compose -f "$COMPOSE_FILE" up -d --build
else
  docker compose -f "$COMPOSE_FILE" up -d
fi

echo "→ Aguardando api em $API_URL/health…"
for i in {1..40}; do
  if curl -sfS "$API_URL/health" > /dev/null 2>&1; then
    echo "  ✓ api ok"
    break
  fi
  if (( i == 40 )); then
    echo "  ✗ api não respondeu em 80s. Ver logs:"
    echo "    docker compose -f $COMPOSE_FILE logs api"
    exit 1
  fi
  sleep 2
done

echo "→ Aguardando web em $WEB_URL/login…"
# Next dev tem cold start; damos até 60s pro primeiro compile.
for i in {1..30}; do
  # `next dev` responde qualquer status para /login (200 ou 307), o que
  # importa é o servidor estar aceitando TCP + entregando HTML.
  if curl -sf -o /dev/null "$WEB_URL/login" 2>&1; then
    echo "  ✓ web ok"
    break
  fi
  if (( i == 30 )); then
    echo "  ✗ web não respondeu em 60s. Ver logs:"
    echo "    docker compose -f $COMPOSE_FILE logs web"
    exit 1
  fi
  sleep 2
done

echo
echo "Stack E2E pronta:"
echo "  API      → $API_URL   (APP_ENV=test, /test/* ativos)"
echo "  Web      → $WEB_URL"
echo "  Postgres → localhost:5433 (db=registers_e2e)"
echo "  MinIO    → http://localhost:9010 (console :9011)"
echo
echo "Rodar E2E:      pnpm --filter web test:e2e"
echo "Desmontar:      $0 --down"
