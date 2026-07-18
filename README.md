# my-registers

Aplicação web privada de registro diário de alimentação, hidratação e atividade física por chat com IA (Anthropic Claude multimodal).

Este projeto segue **Spec-Driven Development**. Antes de escrever código, consulte na ordem:

1. [`.specify/memory/constitution.md`](./.specify/memory/constitution.md) — princípios inegociáveis.
2. [`specs/001-mvp-registro-diario/spec.md`](./specs/001-mvp-registro-diario/spec.md) — o quê (SP-01..SP-113 + invariantes).
3. [`specs/001-mvp-registro-diario/plan.md`](./specs/001-mvp-registro-diario/plan.md) — como (mapeia SPs para arquivos, gates, ordem).
4. [`specs/001-mvp-registro-diario/tasks.md`](./specs/001-mvp-registro-diario/tasks.md) — tarefas atômicas T-XXX por fase.
5. [`specs/001-mvp-registro-diario/research.md`](./specs/001-mvp-registro-diario/research.md) — ADRs.

Design técnico canônico completo em [`app_plan.md`](./app_plan.md). Navegação curta em [`docs/architecture.md`](./docs/architecture.md).

## Stack

- **Frontend:** Next.js 15 (App Router) + React 19 + TypeScript + Tailwind
- **Backend:** FastAPI + Pydantic v2 + SQLAlchemy 2.x (async) + Alembic
- **Banco:** PostgreSQL 16
- **Storage:** MinIO (S3-compatible)
- **LLM:** Anthropic Claude Sonnet 4.6 (`claude-sonnet-4-6`)

## Estrutura

```
.specify/memory/      # constituição
specs/                # spec-kit por feature (spec.md, plan.md, tasks.md, research.md)
apps/
  api/                # FastAPI
  web/                # Next.js
infra/                # Nginx, Certbot (produção)
scripts/              # Backups, bootstrap
docs/                 # navegação curta
app_plan.md           # design técnico canônico
```

## Desenvolvimento local

Recomendado em macOS: **infra em Docker, apps no host**. O bind mount do Docker Desktop em macOS costuma disparar `EDEADLK` ao importar código Python via mmap; rodar o backend no host resolve e ainda dá loop de dev mais rápido.

Pré-requisitos: `docker`, `uv` (`brew install uv`), `node` 20+, `pnpm`.

```bash
# 1) infra (Postgres + MinIO)
pnpm infra:up

# 2) backend (em outro terminal)
cd apps/api
cp .env.example .env         # ajuste ANTHROPIC_API_KEY quando começar a Fase 3
uv sync
uv run alembic -c alembic.ini upgrade head    # sem migrations ainda; roda vazio na Fase 0
uv run python -m app.cli bootstrap            # placeholder até a Fase 1
uv run uvicorn app.main:app --reload

# 3) frontend (em outro terminal)
cd apps/web
pnpm install
NEXT_PUBLIC_API_URL=http://localhost:8000 pnpm dev
```

Atalhos disponíveis a partir da raiz:

| Script              | O que faz                                       |
|---------------------|-------------------------------------------------|
| `pnpm infra:up`     | Sobe Postgres + MinIO em background             |
| `pnpm infra:down`   | Para todos os containers                        |
| `pnpm infra:reset`  | Para e apaga volumes (reset total do banco)     |
| `pnpm dev:api`      | Uvicorn com hot reload no host (após `uv sync`) |
| `pnpm dev:web`      | Next.js dev server                              |
| `pnpm db:migrate`   | `alembic upgrade head`                          |
| `pnpm db:bootstrap` | Placeholder (Fase 1 implementa)                 |

Portas locais:

| Serviço          | URL                          |
|------------------|------------------------------|
| Frontend         | http://localhost:3000        |
| Backend (docs)   | http://localhost:8000/docs   |
| Backend (health) | http://localhost:8000/health |
| MinIO S3         | http://localhost:9000        |
| MinIO Console    | http://localhost:9001        |
| Postgres         | localhost:5432               |

Credenciais de dev do MinIO: `minio_dev` / `minio_dev_secret`.
Admin default: `admin@example.com` / `adminadmin` (só ativa a partir da Fase 1).

### Modo alternativo — tudo em Docker

Se seu Docker Desktop não sofrer com o bug de bind mount:

```bash
cp .env.example .env
pnpm compose:up
```

## Roadmap

Fases de execução em [`specs/001-mvp-registro-diario/tasks.md`](./specs/001-mvp-registro-diario/tasks.md). Contexto de cada fase em [`app_plan.md`](./app_plan.md) §18.

**Estado atual:** Fase 0 concluída (commit `87b8382`). Próxima: Fase 1 (autenticação + bootstrap admin).
