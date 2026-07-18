# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Spec-Driven Development is mandatory

Before touching code, consult in order:

1. `.specify/memory/constitution.md` — inegociável (Art. I-X). Um PR que viola um artigo é rejeitado.
2. `specs/001-mvp-registro-diario/spec.md` — WHAT (requisitos SP-01..SP-113 + invariantes INV-N).
3. `specs/001-mvp-registro-diario/plan.md` — HOW (mapeia SP-XX → arquivos, ordem, gates).
4. `specs/001-mvp-registro-diario/tasks.md` — tarefas atômicas T-XXX por fase (uma tarefa = 1 PR ≤ 1 dia).
5. `specs/001-mvp-registro-diario/research.md` — ADRs (append-only; nunca reescrever ADR aceito).
6. `app_plan.md` — design técnico canônico completo (referenciado por `plan.md`).

Fluxo canônico ao adicionar comportamento: `spec:` PR → `plan:` PR → `tasks:` PR → `feat:` PR. Ir direto para `feat:` não é permitido. Commits devem referenciar os SP-XX cobertos no corpo (ex.: `feat(fase-4): SP-20 SP-21 - registro por texto`).

Documentos SDD e commits estão em pt-BR — matenha esse padrão. Código, identificadores e comentários no código são em inglês (regra global do usuário).

**Estado atual:** Fase 0 concluída (`c29bcbc`). Próxima é Fase 1 (auth + bootstrap admin) — ver `tasks.md` T-101..T-110.

## Comandos

Do raiz (`pnpm` workspace):

| Comando | O que faz |
|--|--|
| `pnpm infra:up` | Sobe apenas Postgres + MinIO em background (`scripts/dev-infra.sh`) |
| `pnpm infra:down` / `pnpm infra:reset` | Para containers / apaga volumes |
| `pnpm dev:api` | `uv run uvicorn app.main:app --reload` em `apps/api` |
| `pnpm dev:web` | Next.js dev server (porta 3000) |
| `pnpm db:migrate` | `alembic upgrade head` |
| `pnpm db:bootstrap` | `python -m app.cli bootstrap` (placeholder até Fase 1) |
| `pnpm compose:up` | Modo alternativo: tudo em Docker (só se seu Docker Desktop não sofrer com bind mount) |

Backend (`apps/api`, gerenciado com `uv`, Python 3.12):
- Instalar deps: `uv sync`
- Rodar API: `uv run uvicorn app.main:app --reload`
- Testes: `uv run pytest` — um teste específico: `uv run pytest tests/test_health.py::test_health_ok`
- Lint/format: `uv run ruff check` / `uv run ruff format`
- Type check: `uv run mypy app`
- Nova migration: `uv run alembic -c alembic.ini revision --autogenerate -m "…"` (models precisam estar importados em `alembic/env.py` para autogenerate ver)
- CLI admin: `uv run python -m app.cli <cmd>` (bootstrap, version)

Frontend (`apps/web`, Next.js 15 + React 19 + Tailwind):
- `pnpm --filter web dev` / `build` / `start` / `lint` / `typecheck`

## Ambiente de dev (macOS)

Padrão da Constituição §31 e ADR-008: **infra em Docker, apps no host**. O bind mount do Docker Desktop dispara `EDEADLK` no `mmap` de imports Python — rodar o backend no host resolve. Use `pnpm compose:up` apenas se seu Docker não tiver esse bug.

Portas: web `3000`, api `8000` (docs em `/docs`, health em `/health`), Postgres `5432`, MinIO S3 `9000` / Console `9001`. Credenciais MinIO dev: `minio_dev` / `minio_dev_secret`. Admin default (a partir da Fase 1): `admin@example.com` / `adminadmin`.

## Arquitetura em uma tela

Monorepo pnpm (`pnpm-workspace.yaml` = `apps/*`) com dois apps:

- `apps/api` — FastAPI + Pydantic v2 + SQLAlchemy 2 async + Alembic. Camadas: `api/routes/` (HTTP) → `services/` (regras de negócio) → `repositories/` (acesso ao DB) → `models/` (SQLAlchemy). Integrações externas em `integrations/{anthropic,storage,nutrition}/`. Config via `pydantic-settings` em `app/core/config.py` (lê `.env`). Middleware global injeta `X-Request-Id`. Erros de domínio herdam de `AppError` (em `core/exceptions.py`) e são traduzidos para JSON pelo handler global em `main.py`.
- `apps/web` — Next.js 15 App Router. Só uma rota placeholder por ora; UI real chega na Fase 1+.
- `infra/` — Nginx + Certbot (produção). `docker-compose.local.yml` só para dev local.

### Princípios que afetam decisões de código

Estes vêm da Constituição e mudam como se implementa services e queries:

- **LLM interpreta, backend calcula** (Art. II). LLM só é usada para classificar intenção, extrair itens estruturados e gerar narrativa **sobre números já calculados**. Toda soma nutricional é determinística no backend. Respostas da LLM chegam via `tool_use` com JSON schema Pydantic; texto livre é descartado. Um teste deve continuar verde ao trocar o cliente Anthropic por mock que devolve lixo.
- **Snapshots recomputam do zero** (Art. III §10). Ao criar/corrigir/deletar registro, o snapshot do dia é `SELECT` completo sobre tabelas cruas (`deleted_at IS NULL`) e recomputa. Nunca aplique delta incremental.
- **Auditoria total** (Art. III §11). Toda mutação em registro de negócio grava linha em `audit_events` com `before`, `after`, `actor`, `message_id`.
- **Água ≠ outros líquidos** (Art. IV). `water_records` só é água pura (sem kcal); bebidas calóricas vão em `beverage_records`. `IntentDispatcher` valida essa separação.
- **`user_id` em toda query de repositório** (Art. V §21). Não existe query que ignore isolamento por usuário.
- **Sem endpoints HTTP de cadastro ou reset** (Art. V §18). Criação/reset de usuário é exclusivamente CLI (`app.cli create-admin`, `app.cli reset-password`) rodada por humano com SSH.
- **Bootstrap é CLI idempotente** (Art. VI §24). Runtime da API **não** roda migrations; deploy chama `alembic upgrade head` como passo explícito. Senha nunca em migration; admin default lido do ambiente pelo `app.cli bootstrap`.
- **Dia com `status='closed'` é imutável** (Art. VIII). Reabertura não existe no MVP; encerrar dia já fechado retorna snapshot atual sem regravar `closed_at`.
- **Aviso legal obrigatório** (Art. VII §26) em toda resposta de dia/semana: "As estimativas nutricionais são aproximações e não substituem acompanhamento médico ou nutricional."

### Testes

- **Invariantes `INV-N`** → integração com Postgres real, nunca mock.
- **`SP-XX must`** → unit de service + integração ponta-a-ponta (route → service → repo → DB).
- **LLM** → sempre mockar `anthropic` client; fixtures em `tests/fixtures/anthropic/*.json`.
- Cobertura mínima aceita no MVP: 80% em `app/services/`; 90% em `nutrition_calculator.py` e `activity_calculator.py`.

## Restrições operacionais fixadas por ADR

- Alembic pinado `>=1.14,<1.16` (ADR-003 em `research.md`): o auto-discovery de `pyproject.toml` no 1.16+ quebra o `alembic.ini` clássico.
- Backend em Python 3.12 (`pyproject.toml`: `>=3.12,<3.13`).
- Modelo Anthropic padrão: `claude-sonnet-4-6`; fallback: `claude-haiku-4-5-20251001`.
- Nunca commitar: `.env`, `uv.lock` de sistema divergente, `.next`, `.venv`, `node_modules`.
