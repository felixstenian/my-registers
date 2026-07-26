#!/usr/bin/env bash
# app_plan §14.8 — backup diário do Postgres.
#
# Uso via cron (recomendado):
#   0 3 * * * /home/felix/my-registers/scripts/backup-postgres.sh
#
# Formato `-Fc` (custom) permite restore parcial e é ~10x menor que texto.
# Retenção 14 dias local + rclone opcional (var `RCLONE_REMOTE`) para off-VPS.
set -euo pipefail

REPO_DIR="${REPO_DIR:-/home/felix/my-registers}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/pg}"
ENV_FILE="${ENV_FILE:-$REPO_DIR/.env.production}"
COMPOSE_FILE="$REPO_DIR/docker-compose.production.yml"
KEEP_DAYS="${KEEP_DAYS:-14}"

# Carrega POSTGRES_USER/DB do .env.production sem executar código dele.
POSTGRES_USER=$(grep -E '^POSTGRES_USER=' "$ENV_FILE" | cut -d= -f2-)
POSTGRES_DB=$(grep -E '^POSTGRES_DB=' "$ENV_FILE" | cut -d= -f2-)

STAMP=$(date +%Y%m%d-%H%M)
mkdir -p "$BACKUP_DIR"

OUTFILE="$BACKUP_DIR/registers-$STAMP.dump"
echo "→ Dumpando Postgres para $OUTFILE"
docker compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" exec -T postgres \
  pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$OUTFILE"

# Sanidade: falha se dump zerado
if [[ ! -s "$OUTFILE" ]]; then
  echo "ERRO: dump vazio, algo deu errado."
  rm -f "$OUTFILE"
  exit 1
fi

echo "→ Rotacionando (mantém $KEEP_DAYS dias)"
find "$BACKUP_DIR" -name 'registers-*.dump' -mtime +"$KEEP_DAYS" -delete

# Envio off-VPS opcional
if [[ -n "${RCLONE_REMOTE:-}" ]]; then
  echo "→ rclone → $RCLONE_REMOTE"
  rclone copy "$OUTFILE" "$RCLONE_REMOTE/pg/"
fi

echo "OK $(basename "$OUTFILE") ($(du -h "$OUTFILE" | cut -f1))"
