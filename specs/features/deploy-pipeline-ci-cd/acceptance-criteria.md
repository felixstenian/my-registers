# Critérios de Aceitação — Pipeline CI/CD (Fase 10)

> **Rastreabilidade**: ADR-012 · Contratos: [`requirements.md`](./requirements.md), [`specifications.md`](./specifications.md).

## AC-001 — CI dispara em PR (T-1001)

**Dado que** um PR é aberto contra `dev` ou `main`,
**Quando** o evento `pull_request` dispara,
**Então** `ci.yml` inicia jobs `api` e `web` em paralelo em `ubuntu-24.04`.

**Dado que** um push novo chega no mesmo PR/branch,
**Quando** o evento dispara,
**Então** `concurrency.group=ci-${{ github.ref }}` com `cancel-in-progress: true` cancela o run anterior antes de iniciar o novo.

**Notas de validação:**
- Implementação: `.github/workflows/ci.yml:5-13`.

---

## AC-002 — Job `api` em CI (T-1001)

**Dado que** o job `api` inicia,
**Quando** o Postgres 16-alpine service sobe,
**Então** healthcheck `pg_isready` (interval 5s, retries 10, timeout 3s) bloqueia steps seguintes até estar pronto.

**Dado que** Postgres está pronto,
**Quando** steps executam,
**Então** `setup-uv@v5` (cache enabled) → `uv python install 3.12` → `uv sync --frozen` → `ruff check app tests` → `ruff format --check app tests` → `pytest -q` com `PGHOST=localhost`, `PGPORT=5432`.

**Dado que** `uv.lock` mudou mas o commit não atualizou,
**Quando** `uv sync --frozen` executa,
**Então** falha (trava lock drift).

**Notas:**
- `pytest` cria DB `registers_test` via `conftest` usando a connection de admin ao DB `postgres`.

---

## AC-003 — Job `web` em CI (T-1002)

**Dado que** o job `web` inicia,
**Quando** steps executam,
**Então** `pnpm/action-setup@v4` pin 10.12.1 → `setup-node@v4` Node 20 + cache pnpm → `pnpm install --frozen-lockfile` → `pnpm --filter web typecheck` → `pnpm --filter web build` (env dummy) → `pnpm --filter web verify:sw`.

**Dado que** o `verify:sw` falhou (INV-11 quebrado em sw.ts),
**Quando** o step retorna exit 1,
**Então** CI falha; PR não pode mergear (após branch protection T-1003).

**Dado que** `pnpm-lock.yaml` mudou sem bump,
**Quando** `--frozen-lockfile` executa,
**Então** falha.

**Notas:**
- Build usa webpack (`--webpack`); Serwist ainda não suporta Turbopack.
- Env dummy `NEXT_PUBLIC_API_URL=/api`, `INTERNAL_API_URL=http://api:8000`, `NEXT_TELEMETRY_DISABLED=1` só pro compile-time; runtime real usa `.env.production`.

---

## AC-004 — Deploy dispara só pós-CI verde (T-1005)

**Dado que** o `ci.yml` completa em `main` com `conclusion: success`,
**Quando** o `workflow_run` dispara,
**Então** `deploy.yml` rode o job `deploy`.

**Dado que** `ci.yml` completa em `main` com `conclusion: failure` (ou cancelled),
**Quando** o `workflow_run` dispara,
**Então** o `if: github.event.workflow_run.conclusion == 'success'` filtra e o job `deploy` não roda.

---

## AC-005 — Deploy exclusivo e rastreável (T-1005)

**Dado que** dois merges chegam em `main` próximos,
**Quando** dois `workflow_run` disparam,
**Então** `concurrency.group=deploy-production` com `cancel-in-progress: false` serializa — só 1 deploy roda por vez.

**Dado que** deploy inicia,
**Quando** `environment: production` é declarado,
**Então** URL `https://${{ vars.DEPLOY_DOMAIN }}` aparece na aba Deployments; histórico de runs visível em `gh run list --workflow=deploy.yml`.

---

## AC-006 — SSH executa bootstrap na VPS (T-1005/T-1004)

**Dado que** o runner carrega chave `DEPLOY_SSH_KEY` via `ssh-agent`,
**Quando** `ssh-keyscan -H ${{ vars.DEPLOY_HOST }}` adiciona ao `known_hosts`,
**Então** a conexão não rejeita por host unknown.

**Dado que** o runner chama `ssh ... felix@$DEPLOY_HOST true`,
**Quando** o servidor interpreta o `command="$DEPLOY_CMD"` em `authorized_keys`,
**Então** executa `cd ~/my-registers && git pull && ./scripts/bootstrap.sh .env.production && docker compose -f docker-compose.production.yml --env-file .env.production up -d --build api web` e ignora o `true`.

**Dado que** a chave SSH é roubada e usada fora do runner,
**Quando** atacante tenta shell interativo `ssh -i deploy_only felix@vps`,
**Então** roda o comando de deploy e desconecta (sem `-t`, `no-pty`).

---

## AC-007 — Smoke test pós-deploy (T-1007)

**Dado que** o SSH disparou o bootstrap e containers rebuildando,
**Quando** smoke step executa loop 12×5s,
**Então** primeira resposta 200 em `https://$DEPLOY_DOMAIN/api/health` com `curl -fsS --max-time 5` → exit 0.

**Dado que** API não responde em 60s,
**Quando** o loop esgota,
**Então** exit 1 → run fail; containers permanecem de pé (sem derrubar produção).

**Notas:**
- Smoke é em HTTPS público (não healthcheck interno do compose) — evita falso positivo.
- `/api/health` retorna `{ status: 'ok', service: 'my-registers-api', version: '0.0.0' }`.

---

## AC-008 — Branch protection em `main` (T-1003) — pendente

**Dado que** T-1003 está configurado via UI,
**Quando** um PR direto tentar push em `main`,
**Então** rejeitado (require PR, no direct pushes).

**Dado que** um PR tenta merge sem status checks verdes,
**Quando** `api (ruff + pytest)` e `web (typecheck + build)` estão pendentes ou vermelhos,
**Então** GitHub bloqueia merge (after T-1003 setup).

**Dado que** PR está verde,
**Quando** branch não está up-to-date com `main`,
**Então** GitHub obriga rebase/update antes de merge (require linear history opcional).

> **Status**: T-1003 aguarda config manual na UI → [NÃO IMPLEMENTADO até operador acionar].

---

## AC-009 — Chave SSH deploy-only (T-1004) — pendente

**Dado que** T-1004 está configurado na VPS,
**Quando** `cat ~/.ssh/authorized_keys` mostra a linha da public key,
**Então** inicia com `command="cd ~/my-registers && git pull && ... up -d --build api web",no-port-forwarding,no-x11-forwarding,no-agent-forwarding,no-pty`.

**Dado que** secret `DEPLOY_SSH_KEY` no GitHub coincide com a private key par da public na VPS,
**Quando** runner conecta,
**Então** SSH aceita (sem password prompt).

> **Status**: T-1004 aguarda setup na VPS → [NÃO IMPLEMENTADO até operador acionar].

---

## AC-010 — Zero secret de negócio no GitHub (RNF-001)

**Dado que** repositório tem apenas 1 secret configurada,
**Quando** `gh secret list` roda,
**Então** retorna `DEPLOY_SSH_KEY` (única).

**Dado que** deploy dispara,
**Quando** o job executa,
**Então** em nenhum passo o `.env.production` da VPS é editado ou lido pelo runner.

---

## AC-011 — Rollback via `git revert` (T-1006 docs)

**Dado que** deploy em `main` quebrou produção (smoke fail ou bug em prod),
**Quando** `git revert <hash> && git push origin main` é executado,
**Então** `deploy.yml` roda de novo com o commit anterior; produção volta ao hash pré-bug.

**Dado que** bug envolveu migration destrutiva,
**Quando** rollback tenta rodar,
**Então** operador precisa `alembic downgrade -1` na VPS ANTES do `git revert`.

---

## AC-012 — Fallback manual (T-1006 docs §14.5)

**Dado que** GitHub Actions está fora do ar,
**Quando** Felix SSH na VPS manualmente,
**Então** executa `cd ~/my-registers && git pull && ./scripts/bootstrap.sh .env.production && docker compose -f docker-compose.production.yml --env-file .env.production up -d --build api web`; `scripts/bootstrap.sh` é idêntico ao rodado pelo Actions.

---

## Cenários de Borda

| Cenário | Comportamento Esperado |
|---|---|
| PR não atualiza `uv.lock` após dep bump | `uv sync --frozen` falha → CI vermelho |
| `pnpm-lock.yaml` divergir | `pnpm install --frozen-lockfile` falha |
| Postgres service não sobe em 30s | Job `api` fail (service healthcheck esgotado); PR bloqueado |
| `verify:sw` falha | CI vermelho; PR bloqueado; INV-11 garantido |
| `workflow_run` dispara com CI cancelled | `if` filtra; deploy não roda |
| 2 deploys simultâneos tentados | `deploy-production` group serializa |
| Smoke fail 60s | Run vermelho; containers permanecem de pé; rollback manual |
| Branch protection não configurado (T-1003 pendente) | Merge sem CI verde é possível — gap até operador configurar |
| Key SSH deploy-only comprometida | Atacante só força deploy do estado HEAD do `main`; não tem shell |
| `cd ~/my-registers` falha (dir movido) | SSH command falha → deploy fail |
| `bootstrap.sh` falha (migration quebra) | Deploy fail antes de `docker compose up`; containers antigos permanecem |
| `DEPLOY_DOMAIN` DNS ainda não propagou | `curl /api/health` falha mesmo API OK; smoke fail — operador ajusta `DEPLOY_DOMAIN` variable |

## Critérios de Não-Funcionalidade

| Critério | Threshold |
|---|---|
| Duração CI `api` job | < 15 min (timeout) — real ~3 min |
| Duração CI `web` job | < 15 min (timeout) — real ~3 min |
| Duração deploy run | < 10 min (timeout) — real ~2 min |
| Smoke timeout | 60s (12 × 5s) |
| Concorrência deploy | 1 simultâneo |
| CI `cancel-in-progress` | true (economia minutes) |
| Actions minutes/mês | < 2000 (free tier private) |
| Secrets no repo | 1 (`DEPLOY_SSH_KEY`) |
| Hostages após deploy fail | Containers antigos intactos |