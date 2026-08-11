# E2E — Playwright

Cobertura golden-path do MVP em `apps/web/e2e/` — login → registrar refeição → visão do dia → encerrar dia → semana → dia passado read-only. Suite atual: 6 specs, ~25s. Roda contra stack real (`docker-compose.e2e.yml`) com respostas da LLM enfileiradas via HTTP.

## Como rodar local

Pré-requisitos: Docker Desktop, Node 20+, pnpm 10.

```bash
# Uma unica vez: instala @playwright/test + baixa chromium
pnpm -w install
pnpm --filter web exec playwright install chromium

# Sobe stack e2e isolada em portas 5433/9010/8001/3001
./scripts/e2e-bootstrap.sh

# Roda a suite (chromium headless)
pnpm --filter web test:e2e

# Ao terminar
./scripts/e2e-bootstrap.sh --down
```

A stack e2e usa `name: registers_e2e` no compose e vive em portas separadas do dev (`docker-compose.local.yml`) — os dois podem rodar simultaneamente sem conflito. `--rebuild` força build das imagens; `--down` remove containers + volumes.

## Como debugar

- **`pnpm --filter web test:e2e:ui`** — abre o UI mode do Playwright, permite step-by-step, ver locators, e retomar spec por spec.
- **`pnpm --filter web test:e2e:debug`** — abre o Inspector com `page.pause()` implícito no start, útil pra inspecionar DOM.
- **`--headed`** — roda vendo o browser (`pnpm --filter web test:e2e -- --headed`).
- **Trace viewer**: após uma falha o zip fica em `apps/web/test-results/<spec>/trace.zip`. Abre com:
  ```bash
  pnpm --filter web exec playwright show-trace apps/web/test-results/<spec>/trace.zip
  ```
- **Logs da api**: `docker compose -f docker-compose.e2e.yml logs api | tail -100`. Cada request vem em JSON estruturado.
- **Estado do DB**: `docker compose -f docker-compose.e2e.yml exec postgres psql -U registers_app -d registers_e2e -c 'SELECT ...'`.

## Arquitetura

```
┌─ Playwright (host, node) ────────────────────┐
│  baseURL = http://localhost:3001              │
│  workers = 1  (fixtures resetam DB entre spec)│
└───────────────┬───────────────────────────────┘
                │ HTTP
┌───────────────▼───────────────────────────────┐
│  docker-compose.e2e.yml  (name=registers_e2e) │
│  ├─ postgres     :5433  (DB: registers_e2e)   │
│  ├─ minio        :9010                        │
│  ├─ api          :8001  (APP_ENV=test)        │
│  │   └─ /test/*  endpoints ativos             │
│  │   └─ AnthropicClient -> TestAnthropicClient│
│  └─ web          :3001  (next dev)            │
└───────────────────────────────────────────────┘
```

- **`APP_ENV=test`** ativa o router `test_hooks.py` (só em test) e injeta o `TestAnthropicClient` no lugar da SDK real. Zero custo com Anthropic, respostas 100% determinísticas.
- **Endpoints `/test/*`**:
  - `POST /test/reset` — DELETE das tabelas de negócio + recria admin. Preserva `nutrient_facts` (seed TBCA carregado no boot).
  - `POST /test/queue-llm-response` — enfileira envelope canned (`kind: record_intent | narrative | weekly_narrative`).
  - `GET  /test/queue-llm-status` — sizes atuais das 3 filas (debug).
- **Fixture `queueLlm`** (`e2e/support/test.ts`) — helper que POSTa em `/test/queue-llm-response`. Chamada antes de qualquer interação que dispare LLM.
- **`resetDb` + `loginAdmin`** — obrigatório no `beforeEach` de todo spec autenticado. Sem re-login o storageState do setup aponta pra user dropado e vira redirect loop.

## Padrões pra novos specs

1. **Sempre enfileirar envelope antes de disparar interação que chama LLM.** O `TestAnthropicClient` falha com `error='no_queued_result'` quando a fila está vazia — bugs de setup ficam claros.

2. **Preferir `page.request` a fetch direto** — compartilha cookies com o browser. Fixtures do `support/test.ts` já usam.

3. **Sincronizar com a persistência do worker, não com a UI.** O worker escreve `food_items`, `daily_snapshot` e `assistant message` em 1 commit. `seedLunchMeal` faz poll em `/chat/messages?after=<user_msg_id>` até assistant aparecer — depois disso o DB está consistente. Aguardar `kcal_in > 0` racena com o auto-recompute do `/days/today`.

4. **Locators semânticos** — `getByRole('button', { name: /.../ })` > `getByText` > `locator('css')`. Ancora em texto pt-BR do UI real.

5. **Cuidado com `role="alert"`**: Next 16 injeta um `<div role="alert" id="__next-route-announcer__">` vazio na página. Se precisar do erro do `LoginForm` (que é `<p role="alert">`), match por texto (`getByText`) em vez de por role.

6. **`test.use({ storageState: { cookies: [], origins: [] } })`** em qualquer spec que precise começar deslogado (ex.: `auth.spec.ts`).

7. **Não paralelizar (por ora).** `workers=1` no `playwright.config.ts` porque `resetDb` é global — TRUNCATE cross-spec quebraria. Se virar gargalo, migrar pra reset-por-transação no backend.

## Gate mínimo antes de PR

```bash
./scripts/e2e-bootstrap.sh
pnpm --filter web test:e2e
```

Todos os specs verdes localmente. O job `e2e` em `.github/workflows/ci.yml` roda a mesma stack em cada PR contra `main` ou `dev`; falhas populam `playwright-report/` e `test-results/` como artifacts do run (retenção 7 dias).

## O que não cobrimos (por design)

- Bloco 5 (upload de rótulo, discard, form manual de catálogo) — v2 sobre a base pronta.
- Mobile emulation, WebKit, Firefox — só Chromium na v1.
- Visual regression (Percy, screenshot diff) — introduz flake e custo, adia.
- PWA install prompt / offline behavior — depende de HTTPS e user gesture, complexo em headless.
