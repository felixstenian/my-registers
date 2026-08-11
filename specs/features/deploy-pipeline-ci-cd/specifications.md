# Especificações Técnicas — Pipeline CI/CD (Fase 10)

> **Rastreabilidade**: ADR-012 · Implementação: `.github/workflows/{ci,deploy}.yml`, `docs/deploy.md` §14, `scripts/bootstrap.sh`, `apps/api/app/api/routes/health.py`.

## Escopo técnico

Dois workflows GitHub Actions (.github/workflows/) + runbook de operação (`docs/deploy.md` §14) + endpoint de health (`/api/health`) + script de bootstrap (`scripts/bootstrap.sh`). Pipeline é **gated em `main`** (branch protection) e **trigger** de deploy via `workflow_run` em CI sucesso — separação total entre validar pré-merge (CI) e deployar pós-merge (CD). Sem publish de imagem em registry; build roda na VPS via `docker compose --build`.

## Triggers e workflows

### `ci.yml` — validação pré-merge

```yaml
name: ci
on:
  pull_request:
    branches: [main, dev]
  push:
    branches: [main]
concurrency:
  group: ci-${{ github.ref }}
  cancel-in-progress: true

jobs:
  api:   # Postgres 16 service + uv + ruff + pytest
  web:   # pnpm + typecheck + build + verify:sw
```

### `deploy.yml` — deploy pós-CI verde em `main`

```yaml
name: deploy
on:
  workflow_run:
    workflows: [ci]
    types: [completed]
    branches: [main]
concurrency:
  group: deploy-production
  cancel-in-progress: false
jobs:
  deploy:
    if: ${{ github.event.workflow_run.conclusion == 'success' }}
    environment:
      name: production
      url: https://${{ vars.DEPLOY_DOMAIN }}
```

Fluxo:
```
feature branch → PR pra dev → ci.yml (bloqueante) → merge
release:      dev → PR pra main → ci.yml → merge → deploy.yml → prod
```

## Interface (passo a passo) — Job `api`

```yaml
api:
  runs-on: ubuntu-24.04
  timeout-minutes: 15
  services:
    postgres:
      image: postgres:16-alpine
      env: { POSTGRES_USER: registers_app, POSTGRES_PASSWORD: dev_password, POSTGRES_DB: postgres }
      ports: ['5432:5432']
      options: >-
        --health-cmd pg_isready
        --health-interval 5s --health-timeout 3s --health-retries 10
  defaults: { run: { working-directory: apps/api } }
  steps:
    - uses: actions/checkout@v4
    - uses: astral-sh/setup-uv@v5
      with: { enable-cache: true }
    - run: uv python install 3.12
    - run: uv sync --frozen
    - run: uv run ruff check app tests
    - run: uv run ruff format --check app tests
    - run: uv run pytest -q
      env: { PGHOST: localhost, PGPORT: "5432" }
```

## Interface — Job `web`

```yaml
web:
  runs-on: ubuntu-24.04
  timeout-minutes: 15
  steps:
    - uses: actions/checkout@v4
    - uses: pnpm/action-setup@v4
      with: { version: 10.12.1 }
    - uses: actions/setup-node@v4
      with: { node-version: "20", cache: "pnpm" }
    - run: pnpm install --frozen-lockfile
    - run: pnpm --filter web typecheck
    - run: pnpm --filter web build
      env:
        NEXT_PUBLIC_API_URL: /api
        INTERNAL_API_URL: http://api:8000
        NEXT_TELEMETRY_DISABLED: "1"
    - run: pnpm --filter web verify:sw
```

## Interface — Job `deploy`

```yaml
deploy:
  runs-on: ubuntu-24.04
  timeout-minutes: 10
  if: ${{ github.event.workflow_run.conclusion == 'success' }}
  environment: { name: production, url: https://${{ vars.DEPLOY_DOMAIN }} }
  steps:
    - uses: webfactory/ssh-agent@v0.9.0
      with: { ssh-private-key: ${{ secrets.DEPLOY_SSH_KEY }} }
    - name: Add VPS to known_hosts
      run: |
        mkdir -p ~/.ssh
        ssh-keyscan -H "${{ vars.DEPLOY_HOST }}" >> ~/.ssh/known_hosts
    - name: Deploy via restricted SSH command
      run: |
        ssh -o BatchMode=yes -o ConnectTimeout=30 \
          "felix@${{ vars.DEPLOY_HOST }}" true
    - name: Smoke test — /api/health
      run: |
        set -euo pipefail
        url="https://${{ vars.DEPLOY_DOMAIN }}/api/health"
        for i in $(seq 1 12); do
          if curl -fsS --max-time 5 "$url" >/dev/null; then exit 0; fi
          sleep 5
        done
        exit 1
```

## Endpoint de health (smoke)

```python
# apps/api/app/api/routes/health.py
class HealthResponse(BaseModel):
    status: str
    service: str
    version: str

@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok", service="my-registers-api", version="0.0.0")
```
Sem auth; servido em `/health` (proxy Next não envolve `/health`, exposto direto pelo nginx em `/api/health`).

## Comando restrito na VPS (T-1004 setup)

```bash
DEPLOY_CMD='cd ~/my-registers && git pull && ./scripts/bootstrap.sh .env.production && docker compose -f docker-compose.production.yml --env-file .env.production up -d --build api web'

# Em ~/.ssh/authorized_keys do usuário felix:
echo "command=\"$DEPLOY_CMD\",no-port-forwarding,no-x11-forwarding,no-agent-forwarding,no-pty $(cat ~/.ssh/deploy_myregisters.pub)" >> ~/.ssh/authorized_keys
```

##modelo de dados (secrets/variables GitHub)

| Tipo | Nome | Conteúdo | Visível em logs |
|---|---|---|---|
| Secret | `DEPLOY_SSH_KEY` | Private key ed25519 (conteúdo do arquivo `deploy_myregisters`) | Não (criptografado) |
| Variable | `DEPLOY_HOST` | `myregister.felix.dev.br` (ou IP se DNS ainda não propagou) | Sim |
| Variable | `DEPLOY_DOMAIN` | `myregister.felix.dev.br` (usado no smoke HTTPS) | Sim |

`ANTHROPIC_API_KEY`, `POSTGRES_PASSWORD`, MinIO creds, JWT secret etc. **não** vão no GitHub — apenas `.env.production` na VPS.

## Fluxo de dados

### CI (PR para dev/main)
1. Novo PR/push → trigger `pull_request`/`push`.
2. `concurrency` cancela runs antigos do mesmo `github.ref`.
3. Jobs `api` e `web` em paralelo (ubuntu-24.04 runner).
4. `api`: Postgres service sobe com healthcheck → uv install Python 3.12 → `uv sync --frozen` (cache `~/.cache/uv`) → `ruff check` + `ruff format --check` → `pytest -q` com `PGHOST=localhost`.
5. `web`: pnpm install (cache) → `typecheck` → `build` com env dummy → `verify:sw` (5 checks INV-11/SP-130/132/135).
6. Ambos passam → status checks verdes → branch protection permite merge.

### Deploy (push/merge em main)
1. `ci.yml` roda em `push: [main]` (mesmo workflow) → conclui em `success`.
2. `deploy.yml` dispara via `workflow_run` types `[completed]`.
3. `if: conclusion == 'success'` filtra rodar só se CI passou (workflow_run dispara mesmo em fail).
4. `ssh-agent` carrega a chave `DEPLOY_SSH_KEY`.
5. `ssh-keyscan` add `DEPLOY_HOST` ao `known_hosts` runner (weak check sem TOFU rigoroso).
6. `ssh ... true` conecta — VPS executa `command="$DEPLOY_CMD"` (ignora o `true` que enviamos).
7. Na VPS: `git pull` (atualiza `~/my-registers`) → `bootstrap.sh .env.production` (migrations + alembic upgrade + idempotente setup) → `docker compose up -d --build api web` (rebuild apenas api e web; postgres/minio/nginx/certbot intactos).
8. Runner executa smoke: loop 12×5s no `https://$DEPLOY_DOMAIN/api/health` `curl -fsS`.
9. 200 → run verde; deployment aparece na aba Deployments.
10. Timeout 60s sem 200 → run fail; containers ficam de pé; operador decide rollback manual.

## Regras de negócio

1. **CI é gate bloqueante** (após T-1003); sem CI verde, sem merge em `main`.
2. **CD é automático pós-merge em `main`** — sem approval/trigger manual.
3. **`workflow_run` filtra `ci` sucesso** via `if` explícito (GitHub dispara evento mesmo em CI fail).
4. **1 deploy por vez** (`cancel-in-progress: false` em deploy; `true` em CI).
5. **Zero reset de `.env.production`** — o deploy nunca edita o arquivo; rotação de segredo é manual SSH.
6. **`ANTHROPIC_API_KEY` nunca no GitHub** — ADR-012 explicita.
7. **Chave SSH só faz uma coisa** (via `command="..."`) — não é shell interativo mesmo se vazada.
8. **Rollback via `git revert + push`** — pipeline reroda com hash anterior; não há workflow dedicado.
9. **Build local na VPS** (`--build api web`), não em registry (ADR-012 descarta Watchtower/GHCR pra MVP).
10. **Smoke em HTTPS público** — não é health interno do compose (evita falso positivo).
11. **Falha no smoke não derruba containers** — rollback é operador.
12. **Branch protection inclui `require linear history`** (opcional; evita merge commits).

## Configurações e variáveis de ambiente

GitHub repo → Settings:
| Item | Tipo | Valor |
|---|---|---|
| `DEPLOY_SSH_KEY` | Secret | Private key deploy-only |
| `DEPLOY_HOST` | Variable | hostname/IP VPS |
| `DEPLOY_DOMAIN` | Variable | domínio HTTPS público |

VPS `.env.production` (não gerenciado pelo Actions): `ANTHROPIC_API_KEY`, `POSTGRES_PASSWORD`, `JWT_SECRET_KEY`, `JWT_REFRESH_SECRET_KEY`, MinIO creds, `TZ`, etc.

## Referências de implementação

- **Workflows**: `.github/workflows/ci.yml` (~80 linhas), `.github/workflows/deploy.yml` (~60 linhas).
- **Smoke endpoint**: `apps/api/app/api/routes/health.py` (14 linhas) + `apps/api/app/main.py` (import + `X-Request-Id` middleware).
- **Bootstrap script**: `scripts/bootstrap.sh` (roda migrations `alembic upgrade head` + setup idempotente) — reusado em deploy manual.
- **Compose prod**: `docker-compose.production.yml` — services `nginx`, `certbot`, `postgres`, `minio`, `minio-init`, `api`, `web` + volumes.
- **Docs**: `docs/deploy.md` §14 (seções 14.1-14.5: fluxo, setup VPS, debug, rollback, pausar CD).
- **ADR**: `specs/001-mvp-registro-diario/research.md` ADR-012 (accepted 2026-07-26).
- **Tasks**: `specs/001-mvp-registro-diario/tasks.md` Fase 10 (T-1001..T-1007).
- **Tests**: smoke é próprio `curl /api/health`; CI do backend tem `apps/api/tests/test_health.py` já (não específico deste pipeline).