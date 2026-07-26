#!/usr/bin/env bash
# app_plan §14.9 — backup diário do MinIO.
#
# Uso via cron:
#   0 4 * * * /home/felix/my-registers/scripts/backup-minio.sh
#
# `mc mirror` só copia arquivos novos (comparação por etag). Retenção 14
# dias local; se `RCLONE_REMOTE` estiver setado, também espelha off-VPS.
set -euo pipefail

REPO_DIR="${REPO_DIR:-/home/felix/my-registers}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/minio}"
ENV_FILE="${ENV_FILE:-$REPO_DIR/.env.production}"
KEEP_DAYS="${KEEP_DAYS:-14}"

MINIO_ROOT_USER=$(grep -E '^MINIO_ROOT_USER=' "$ENV_FILE" | cut -d= -f2-)
MINIO_ROOT_PASSWORD=$(grep -E '^MINIO_ROOT_PASSWORD=' "$ENV_FILE" | cut -d= -f2-)
S3_BUCKET=$(grep -E '^S3_BUCKET=' "$ENV_FILE" | cut -d= -f2-)

# Nome do bridge network gerado pelo compose. Fica `<dir-do-compose>_internal`.
NETWORK=$(basename "$REPO_DIR")_internal

STAMP=$(date +%Y%m%d)
mkdir -p "$BACKUP_DIR/$STAMP"

echo "→ Espelhando $S3_BUCKET para $BACKUP_DIR/$STAMP"
docker run --rm --network "$NETWORK" \
  -v "$BACKUP_DIR/$STAMP:/backup" \
  minio/mc sh -c "
    mc alias set src http://minio:9000 '$MINIO_ROOT_USER' '$MINIO_ROOT_PASSWORD' &&
    mc mirror --overwrite src/$S3_BUCKET /backup
  "

echo "→ Rotacionando (mantém $KEEP_DAYS dias)"
find "$BACKUP_DIR" -maxdepth 1 -mindepth 1 -type d -mtime +"$KEEP_DAYS" -exec rm -rf {} +

if [[ -n "${RCLONE_REMOTE:-}" ]]; then
  echo "→ rclone → $RCLONE_REMOTE/minio/$STAMP"
  rclone copy "$BACKUP_DIR/$STAMP" "$RCLONE_REMOTE/minio/$STAMP/"
fi

echo "OK $(du -sh "$BACKUP_DIR/$STAMP" | cut -f1)"
