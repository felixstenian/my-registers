# Requisitos — Pipeline CI/CD (Fase 10)

> **Rastreabilidade**: ADR-012 em [`specs/001-mvp-registro-diario/research.md`](../../001-mvp-registro-diario/research.md) · Implementação: `.github/workflows/{ci,deploy}.yml`, `docs/deploy.md` §14, `scripts/bootstrap.sh`, `apps/api/app/api/routes/health.py`. Fase 10 (T-1001..T-1007) — workflows e docs concluídos (PR #34); T-1003/T-1004 pendentes como config manual UI/VPS.

## Visão geral

CI/CD com GitHub Actions em dois workflows: `ci.yml` valida cada PR (jobs paralelos `api` Postgres 16 + ruff + pytest; `web` typecheck + build + `verify:sw` INV-11) e `deploy.yml` dispara SSH deploy pós-CI verde em `main`, com smoke test em `/api/health`. Estratégia **zero secret**: `ANTHROPIC_API_KEY` nunca sai da VPS; GitHub só recebe a chave SSH `deploy-only` restrita via `command="..."` no `authorized_keys`.

## Requisitos funcionais

| ID | Requisito | Tarefa | Prioridade |
|---|---|---|---|
| RF-001 | `ci.yml` dispara em `pull_request` para `dev`/`main` e em `push` para `main`. `concurrency.group=ci-${{ github.ref }}` com `cancel-in-progress: true` (cancela runs antigos ao push novo). | T-1001 | Must Have |
| RF-002 | Job `api` (ubuntu-24.04, timeout 15min): Postgres 16-alpine service (`POSTGRES_USER=registers_app`, `POSTGRES_PASSWORD=dev_password`); steps `setup-uv@v5` (cache enabled), `uv python install 3.12`, `uv sync --frozen`, `uv run ruff check app tests`, `uv run ruff format --check app tests`, `uv run pytest -q` com `PGHOST=localhost`/`PGPORT=5432`. | T-1001 | Must Have |
| RF-003 | Job `web` (ubuntu-24.04, timeout 15min) em paralelo: `pnpm/action-setup@v4` pin 10.12.1, `setup-node@v4` Node 20 + cache pnpm, `pnpm install --frozen-lockfile`, `pnpm --filter web typecheck`, `pnpm --filter web build` (webpack) com env dummy (`NEXT_PUBLIC_API_URL=/api`, `INTERNAL_API_URL=http://api:8000`, `NEXT_TELEMETRY_DISABLED=1`), `pnpm --filter web verify:sw`. | T-1002 | Must Have |
| RF-004 | `deploy.yml` dispara via `workflow_run` em `ci` types `[completed]` branches `[main]`. Filtra `github.event.workflow_run.conclusion == 'success'` (workflow_run dispara mesmo se ci falhou). | T-1005 | Must Have |
| RF-005 | Job `deploy` (ubuntu-24.04, timeout 10min): `concurrency.group=deploy-production` com `cancel-in-progress: false` (um deploy por vez); `environment: production` com `url: https://${{ vars.DEPLOY_DOMAIN }}` (deploys aparecem na aba Deployments). | T-1005 | Must Have |
| RF-006 | Steps do deploy: `webfactory/ssh-agent@v0.9.0` com `secrets.DEPLOY_SSH_KEY`, `ssh-keyscan -H ${{ vars.DEPLOY_HOST }} >> ~/.ssh/known_hosts`, `ssh -o BatchMode=yes -o ConnectTimeout=30 felix@${{ vars.DEPLOY_HOST }} true` (dispara `command="..."` restringido na VPS). | T-1005 | Must Have |
| RF-007 | Smoke test: loop de 12 tentativas × 5s (`curl -fsS --max-time 5`) em `https://${{ vars.DEPLOY_DOMAIN }}/api/health`; 0 no primeiro 200, 1 após 60s. Containers permanecem de pé mesmo em falha — rollback é manual. | T-1007 | Must Have |
| RF-008 | Branch protection em `main` (T-1003): require PR, status checks `api (ruff + pytest)` + `web (typecheck + build)`, require branches up-to-date, no direct pushes. **Config manual via GitHub UI**. | T-1003 | Must Have |
| RF-009 | Chave SSH `deploy-only` (T-1004): `ed25519` sem passphrase, prepend `command="$DEPLOY_CMD",no-port-forwarding,no-x11-forwarding,no-agent-forwarding,no-pty` em `authorized_keys` na VPS; private key como GitHub Secret `DEPLOY_SSH_KEY`. **Config manual na VPS**. | T-1004 | Must Have |
| RF-010 | Comando `DEPLOY_CMD` na VPS: `cd ~/my-registers && git pull && ./scripts/bootstrap.sh .env.production && docker compose -f docker-compose.production.yml --env-file .env.production up -d --build api web`. | T-1004 | Must Have |
| RF-011 | `/api/health` retorna `{ status: 'ok', service: 'my-registers-api', version: '0.0.0' }` (sem auth) — usado pelo smoke. | [Inferido do código] | Must Have |
| RF-012 | `docs/deploy.md` §14 documenta: fluxo feature→PR→CI→merge→deploy; setup chave deploy-only + `authorized_keys`; secrets/variables no GitHub; branch protection passo-a-passo; debug (`gh run list/view`); rollback via `git revert`; quando pausar o CD. | T-1006 | Should Have |

## Requisitos não funcionais

| ID | Requisito | Categoria |
|---|---|---|
| RNF-001 | Zero segredo de negócio no GitHub: `ANTHROPIC_API_KEY`, `POSTGRES_PASSWORD`, etc. ficam só em `.env.production` na VPS; `deploy.yml` nunca edita `.env.production`. ADR-012 mandate. | Segurança |
| RNF-002 | Chave SSH `deploy-only` restrita via `command="..."` (não shell interativo): mesmo se vazada, só rola deploy fixo, sem acesso arbitrário. `no-port-forwarding`, `no-x11-forwarding`, `no-agent-forwarding`, `no-pty`. | Segurança |
| RNF-003 | Cache de deps: uv `enable-cache: true`; Node pnpm cache; reduz 1-2 min por run. | Performance |
| RNF-004 | Cancel in-progress CI (em push novo) evita desperdício de Actions minutes. | Custo |
| RNF-005 | Concorrência exclusiva em deploy (`cancel-in-progress: false`) — garante 1 deploy por vez. | Corretude |
| RNF-006 | Postgres 16-alpine service com healthcheck `pg_isready` (interval 5s, retries 10) — disponível antes de pytest iniciar. | Corretude |
| RNF-007 | Runtime identidade dev/prod: `uv` para Python 3.12, `pnpm` 10.12.1 + Node 20; reproduzível. | Reprodutibilidade |
| RNF-008 | Branch protection + linear history evitam merge commits noise. | Governança |
| RNF-009 | Rollback via `git` (`git revert + push`) — sem workflow dedicado; pipeline reroda com o hash anterior. | Recuperação |
| RNF-010 | Deploy fallback manual (`scripts/bootstrap.sh` é o mesmo script rodado pelo Actions) — sobrevive a GitHub outages. | Resiliência |

## Restrições e premissas

- **Fase 10 concluída (parcial)** via PR #34 — código e docs prontos; **T-1003/T-1004 aguardam config manual no GitHub UI e na VPS** (não é possível fazer via commit).
- **ADR-012 aceita** — ADR é append-only; não reescrever.
- **Sem E2E (Playwright) no CI** — ADR-012 explicitamente não inclui; unit + integration cobrem invariantes críticos; custo/manutenção de Playwright não justificado para 1 dev.
- **Sem preview environments por PR** — infra dedicada complexa, fora do escopo.
- **Sem cache de imagens Docker no GHCR** — otimização; build de 2 min é aceitável.
- **Sem signed commits gate** — Felix é único committer.
- **Repo privado eventual**: GitHub Actions grátis 2000 min/mês — nosso build ~2-3 min, cabe folgado.

## Dependências

**Depende de:**
- ADR-012 (`research.md`) — escolha registrada (GitHub Actions vs Webhook/Watchtower/ArgoCD/Compose pull/leave-as-is).
- `apps/api` — código de testes (`apps/api/tests`) + `health.py` endpoint.
- `apps/web` — `verify:sw` script (INV-11) + `next build --webpack`.
- `scripts/bootstrap.sh` — script runbook que o `command="..."` chama (mesmo usado em deploy manual).
- `docker-compose.production.yml` — services `api`/`web` alvos do `--build`.
- Fase 9 (Nginx + Certbot) — TLS do smoke test em `https://$DEPLOY_DOMAIN`.

**Requerido por:**
- Todos os PRs pós-Fase 10 (gate blocking).
- Deploy pós-merge em `main` (CD automatic).