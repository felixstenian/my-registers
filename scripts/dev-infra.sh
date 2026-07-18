#!/usr/bin/env bash
# Sobe apenas Postgres + MinIO em background para o Caminho A (dev nativo).
# Backend e frontend rodam no host, não no Docker.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose -f docker-compose.local.yml up -d postgres minio minio-init
echo
echo "Infra pronta:"
echo "  Postgres  -> localhost:5432 (user=registers_app pass=dev_password db=registers)"
echo "  MinIO S3  -> http://localhost:9000  (key=minio_dev secret=minio_dev_secret)"
echo "  MinIO UI  -> http://localhost:9001"
echo
echo "Para o backend:  cd apps/api && cp .env.example .env && uv sync && uv run uvicorn app.main:app --reload"
echo "Para o frontend: cd apps/web && pnpm install && pnpm dev"
