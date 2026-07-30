# Casos de Teste — Pipeline CI/CD (Fase 10)

> **Rastreabilidade**: ADR-012 · Workflows: `.github/workflows/{ci,deploy}.yml`.
> **Tests existentes**: smoke é o próprio `curl /api/health`; backend tem `apps/api/tests/test_health.py` (não específico do pipeline). Pipeline é auto-validado por cada execução do GitHub Actions.

## Cobertura alvo

- **Estáticos (existentes)**: `verify:sw` no job `web` (5 checks de `sw.ts`).
- **Integração (existentes)**: qualquer run do `ci.yml`/`deploy.yml` exercita o pipeline.
- **Smoke (existente)**: `curl -fsS https://$DEPLOY_DOMAIN/api/health` (12×5s) no `deploy.yml`.
- **Unitários/E2E (alvo)**: tipos para simular falhas específicas se adicionar `act` ou `pytest-runner-locally`.
- **Regressão**: INV-11 (`verify:sw`) bloqueante; smoke sem falso positivo.

---

## Testes de Integração (existentes no fluxo real)

### TC-I-001 — PR verde dispara CI e bloqueia merge até concluir
- **Trigger**: abrir PR contra `dev`.
- **Passos**:
  1. Workflow `ci.yml` dispara com `pull_request`.
  2. Jobs `api` e `web` em paralelo.
  3. Status checks aparecem pendentes no PR.
- **Resultado esperado**: após T-1003 (branch protection), merge bloqueado até checks verdes.

### TC-I-002 — `uv sync --frozen` falha em lock drift
- **Passos**: bumpar `pyproject.toml` dep sem `uv lock` commit.
- **Resultado esperado**: job `api` step "Sync dependencies" retorna exit 1; CI vermelho.

### TC-I-003 — `pnpm install --frozen-lockfile` falha em lock drift
- **Passos**: bumpar dep em `package.json` sem `pnpm-lock.yaml` atualizado.
- **Resultado esperado**: job `web` step "Install dependencies" retorna exit 1; CI vermelho.

### TC-I-004 — `verify:sw` falha ao remover `NetworkOnly` de /api/
- **Passos**: editar `apps/web/src/app/sw.ts`; tirar `new NetworkOnly()` da regra `/api/`.
- **Resultado esperado**: `verify-sw.mjs` exit 1; CI `web` step "Verify service worker (INV-11)" vermelho.

### TC-I-005 — Push novo cancela run antigo em mesmo PR
- **Passos**: abrir PR; esperar CI iniciar; push novo no mesmo branch.
- **Resultado esperado**: `concurrency.group=ci-...` com `cancel-in-progress: true` cancela run anterior em favor do novo.

### TC-I-006 — Merge em `main` dispara CI → deploy sequencial
- **Passos**: merge PR verde em `main`.
- **Resultado esperado**: `ci.yml` roda em `push: [main]`; ao completar `success`, `deploy.yml` dispara via `workflow_run`.

### TC-I-007 — CI fail em `main` não dispara deploy
- **Passos**: forçar CI fail em `main` (ex.: quebra espera).
- **Resultado esperado**: `workflow_run` dispara mas `if: conclusion=='success'` filtra; job `deploy` não roda.

### TC-I-008 — Deploy SSH executado com sucesso
- **Pré-condições**: T-1004 configurado; `DEPLOY_SSH_KEY` no GitHub.
- **Passos**: `deploy.yml` jobs:
  - `webfactory/ssh-agent` carrega chave.
  - `ssh-keyscan` adiciona host a `known_hosts`.
  - `ssh felix@$DEPLOY_HOST true` conecta → VPS executa `command="..."`.
  - VPS: `git pull && bootstrap.sh .env.production && docker compose up -d --build api web`.
- **Resultado esperado**: SSH exit 0; api/web rebuildados.

### TC-I-009 — Smoke test 200 em primeiro hit
- **Passos**: pós-deploy; API saudável.
- **Resultado esperado**: primeiro `curl -fsS https://$DEPLOY_DOMAIN/api/health` retorna 200 → step exit 0.

### TC-I-010 — Smoke test falha após 60s sem resposta
- **Passos**: API não responde; `curl` falha em todas 12 tentativas.
- **Resultado esperado**: step exit 1; run vermelho; **containers permanecem de pé** (rollback manual).

### TC-I-011 — Concorrência exclusiva deploy
- **Passos**: abrir dois merges simultâneos em `main`.
- **Resultado esperado**: `concurrency.group=deploy-production` serializa; segundo run espera o primeiro concluir.

### TC-I-012 — Deploymentation URL aparece
- **Passos**: deploy sucesso.
- **Resultado esperado**: `gh run list --workflow=deploy.yml` mostra `production` environment; URL `https://$DEPLOY_DOMAIN` linkeble.

---

## Testes de Regressão Manuais (docs runbook)

### TC-M-001 — Rollback via `git revert` (§14.4)
- **Passos**:
  1. `git revert <hash-que-quebrou> && git push origin main`.
  2. CI roda no revert; deploy dispara.
- **Resultado esperado**: produção volta ao estado pré-hash; smoke verde.

### TC-M-002 — Rollback com migration destrutiva (§14.4)
- **Passos**:
  1. Na VPS: `cd ~/my-registers && uv run alembic downgrade -1`.
  2. `git revert + push`.
- **Resultado esperado**: `alembic` desfez schema, deploy reverte sem crash de migration.

### TC-M-003 — Deploy manual em GitHub outage (§14.5)
- **Passos**: com Actions fora do ar, SSH na VPS e rodar manualmente `git pull && ./scripts/bootstrap.sh .env.production && docker compose -f docker-compose.production.yml --env-file .env.production up -d --build api web`.
- **Resultado esperado**: produção atualizada; `bootstrap.sh` idêntico ao rodado pelo Actions.

### TC-M-004 — Chave SSH deploy-only só faz deploy
- **Passos**: `ssh -i ~/.ssh/deploy_myregisters felix@$DEPLOY_HOST` interativamente.
- **Resultado esperado**: roda o `command="..."`, faz deploy, desconecta (sem prompt shell).

### TC-M-005 — Debug de deploy fail (§14.3)
- **Passos**: `gh run list --workflow=deploy.yml --limit 10` + `gh run view --log`.
- **Resultado esperado**: logs mostram qual step falhou (SSH ou smoke); `curl -sSI` e `docker compose ps` complementam.

---

## Testes Unitários (backend — existentes)

### TC-U-001 — `/api/health` retorna OK
- **Módulo**: `apps/api/app/api/routes/health.py`
- **Entrada**: `GET /health`
- **Saída esperada**: `{ status: "ok", service: "my-registers-api", version: "0.0.0" }` (200).
- **Tipo**: Happy path — `apps/api/tests/test_health.py::test_health_ok`.

---

## Testes de Regressão (a manter a cada release do pipeline)

- **R-001** (ADR-012): `DEPLOY_SSH_KEY` é única secret; `ANTHROPIC_API_KEY`/`POSTGRES_PASSWORD` não aparecem em logs.
- **R-002** (T-1001): `concurrency` `ci-${{ github.ref }}` + `cancel-in-progress: true` em CI.
- **R-003** (T-1005): `concurrency` `deploy-production` + `cancel-in-progress: false` em deploy.
- **R-004** (T-1007): smoke 12×5s em HTTPS público `/api/health`; falha não derruba containers.
- **R-005** (INV-11): `verify:sw` no job `web` (5 checks) sempre roda e pode quebrar CI.
- **R-006** (RNF-001): `deploy.yml` nunca edita/lê `.env.production`.
- **R-007** (T-1004): public key com `command="...",no-port-forwarding,no-x11-forwarding,no-agent-forwarding,no-pty` em `authorized_keys`.
- **R-008** (T-1005): `workflow_run` com `if: conclusion == 'success'` (CI fail não dispara deploy).
- **R-009** (T-1001/T-1002): `uv sync --frozen` e `pnpm install --frozen-lockfile` travam lock drift.
- **R-010** (T-1001): Postgres 16-alpine service com healthcheck `pg_isready` antes de `pytest`.
- **R-011** (T-1002): build em `--webpack` (não Turbopack; serwist#54).