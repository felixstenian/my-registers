#!/usr/bin/env bash
# Restore de dump `-Fc` do Postgres. Destrói o schema atual e recria.
#
# **DESTRUTIVO** — só rode em VPS/staging depois de confirmar o dump.
# Faça sempre `pg_dump` antes do restore para ter um snapshot pre-restore.
#
# Uso:
#   ./scripts/restore-postgres.sh /var/backups/pg/registers-20260719-0300.dump
#
# Ou em dry-run (mostra o SQL sem executar):
#   DRY_RUN=1 ./scripts/restore-postgres.sh /var/backups/pg/registers-20260719-0300.dump
set -euo pipefail

DUMP_FILE="${1:-}"
if [[ -z "$DUMP_FILE" || ! -f "$DUMP_FILE" ]]; then
  echo "Uso: $0 <path-para-dump>"
  echo "Ex.:  $0 /var/backups/pg/registers-20260719-0300.dump"
  exit 1
fi

REPO_DIR="${REPO_DIR:-/home/felix/my-registers}"
ENV_FILE="${ENV_FILE:-$REPO_DIR/.env.production}"
COMPOSE_FILE="$REPO_DIR/docker-compose.production.yml"

POSTGRES_USER=$(grep -E '^POSTGRES_USER=' "$ENV_FILE" | cut -d= -f2-)
POSTGRES_DB=$(grep -E '^POSTGRES_DB=' "$ENV_FILE" | cut -d= -f2-)

if [[ "${DRY_RUN:-0}" == "1" ]]; then
  echo "→ DRY-RUN. Mostrando conteúdo do dump (SQL) sem restaurar…"
  docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" run --rm -T postgres \
    pg_restore --list < "$DUMP_FILE"
  exit 0
fi

echo "!!! ATENÇÃO: vai DROP+RECREATE '$POSTGRES_DB'. Ctrl-C em 5s para abortar."
sleep 5

echo "→ Parando API pra evitar conexões durante restore"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" stop api web

echo "→ Terminating other backends do $POSTGRES_DB"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T postgres \
  psql -U "$POSTGRES_USER" -d postgres -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity \
   WHERE datname='$POSTGRES_DB' AND pid <> pg_backend_pid();"

echo "→ Recriando o database"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T postgres \
  psql -U "$POSTGRES_USER" -d postgres -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\";"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T postgres \
  psql -U "$POSTGRES_USER" -d postgres -c "CREATE DATABASE \"$POSTGRES_DB\";"

echo "→ Restaurando dump"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T postgres \
  pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --clean --if-exists < "$DUMP_FILE"

echo "→ Subindo API/web de volta"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" start api web

echo "OK. Restore concluído. Confira /health e alguns dados manualmente."
