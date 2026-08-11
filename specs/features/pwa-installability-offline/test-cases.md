# Casos de Teste — PWA — instalabilidade + shell offline (Bloco 4)

> **Rastreabilidade**: SP-128..SP-135 + INV-11 · Verificação estática: `apps/web/scripts/verify-sw.mjs` (T-B409) · Testes comportamentais: [Implementação não localizada] — sem vitest no `apps/web`; sem Playwright/Cypress; Lighthouse PWA rodado manualmente conforme `docs/pwa.md`.

## Cobertura alvo

- **Estáticos (existentes)**: `verify-sw.mjs` (5 checks de `sw.ts`/bundle).
- **Unitários (alvo)**: `manifest()` logica, detecção de `InstallButton` estado, `sw-update-prompt` state transitions (mockando `navigator.serviceWorker`).
- **Integração/E2E (alvo)**: Lighthouse PWA ≥ 90; fluxo de instalação em Chromium; fluxo de update; fluxo offline `/offline`.
- **Regressão**: INV-11 (matcher `/api/` + `NetworkOnly`) após qualquer mudança em `sw.ts`.

---

## Testes Estáticos (existentes — T-B409)

### TC-S-001 — `verify:sw` valida INV-11 (matcher /api/)
- **Módulo**: `apps/web/scripts/verify-sw.mjs`
- **Comando**: `pnpm --filter web verify:sw`
- **Resultado esperado**: `OK INV-11 — matcher /api/ presente em sw.ts`; `OK INV-11 — NetworkOnly usado como handler de /api/`.
- **Tipo**: Happy path (rodado no CI job `web` pós-build).

### TC-S-002 — `verify:sw` valida SP-135 (fallback /offline)
- **Resultado esperado**: `OK SP-135 — fallback /offline em sw.ts` (regex `/url:\s*['"]\/offline['"]/`).

### TC-S-003 — `verify:sw` valida SP-132 (SKIP_WAITING + skipWaiting)
- **Resultado esperada**: ambos os termos presentes em `sw.ts`.

### TC-S-004 — `verify:sw` pós-build valida bundle
- **Pré-condições**: `public/sw.js` existe (pós-build).
- **Resultado esperado**: bundle contém `/api` e `/offline`.

### TC-S-005 — `verify:sw` falha se NetworkOnly removido
- **Passos**: editar `sw.ts` tirando `new NetworkOnly()` da regra `/api/`.
- **Resultado esperado**: 1 FAIL + exit code 1 no CI.

---

## Testes Unitários (alvo pendente)

> [Implementação não localizada] — adicionar Vitest + jsdom (T-B409 explicitamente **não** adicionou vitest para 1 assertion; revisitar quando 3+ assertions justificarem). <!-- TODO: configurar Vitest -->

### TC-U-001 — `manifest()` retorna campos obrigatórios (SP-128)
- **Módulo**: `apps/web/src/app/manifest.ts`
- **Entrada**: chamar `manifest()`.
- **Saída esperada**: object com `name`, `short_name.length <= 12`, `icons` com 192/512/maskable, `display='standalone'`, `start_url='/chat'`, `orientation='portrait'`, `lang='pt-BR'`.
- **Tipo**: Happy path

### TC-U-002 — `InstallButton` oculta em `display-mode: standalone` (SP-133)
- **Pré-condições**: mock `window.matchMedia('(display-mode: standalone)').matches = true`.
- **Resultado esperado**: `installed=true`; component retorna `null`.
- **Tipo**: Edge case

### TC-U-003 — `InstallButton` captura `beforeinstallprompt` (SP-133)
- **Passos**: dispatch `window.dispatchEvent(new Event('beforeinstallprompt'))` (com `preventDefault` stubbed).
- **Resultado esperado**: botão renderiza com texto "Instalar".
- **Tipo**: Happy path

### TC-U-004 — `InstallButton` some em `appinstalled` (SP-133)
- **Pré-condições**: `promptEvent` setado.
- **Passos**: dispatch `appinstalled`.
- **Resultado esperado**: `installed=true`; botão não renderiza.
- **Tipo**: Happy path

### TC-U-005 — `SwUpdatePrompt` não registra SW em dev (RNF-002)
- **Pré-condições**: `process.env.NODE_ENV='development'`.
- **Resultado esperado**: `navigator.serviceWorker.register` **não** chamado; toast não aparece.
- **Tipo**: Edge case

### TC-U-006 — `SwUpdatePrompt` mostra toast só em update real (SP-132)
- **Pré-condições**: mock `navigator.serviceWorker.controller` setado; dispatch `updatefound` → novo worker em `state='installed'`.
- **Resultado esperado**: `waitingWorker` = novo worker; toast renderiza.
- **Tipo**: Happy path

### TC-U-007 — `SwUpdatePrompt` não mostra toast em primeira install (SP-132)
- **Pré-condições**: `navigator.serviceWorker.controller` = null.
- **Passos**: dispatch `updatefound` → `installed`.
- **Resultado esperado**: toast **não** renderiza (primeira instalação, não update).
- **Tipo**: Edge case

### TC-U-008 — `SwUpdatePrompt` toast esconde se não há waitingWorker (SP-132)
- **Resultado esperado**: `if (!waitingWorker) return null`.
- **Tipo**: Edge case

### TC-U-009 — `SwUpdatePrompt` reload em `controllerchange` (SP-132)
- **Passos**: dispatch `controllerchange`.
- **Resultado esperado**: `window.location.reload` chamado.
- **Tipo**: Happy path

### TC-U-010 — `OfflineRetryButton` chama `window.location.reload` (SP-135)
- **Passos**: render + click.
- **Resultado esperado**: `window.location.reload()` chamado.
- **Tipo**: Happy path

---

## Testes de Integração/E2E

### TC-I-001 — Lighthouse PWA ≥ 90 (gate Bloco 4)
- **Comando**: `npx lighthouse https://myregister.felix.dev.br --only-categories=pwa --view`.
- **Pré-condições**: prod up + HTTPS + manifest + SW + ícones.
- **Resultado esperado**: score ≥ 90; categories "Installable" + "PWA Optimized" aprovadas.
- **Notas**: Pendente de rodar em prod (T-B409). Tooling offline/lab local.

### TC-E-001 — Instalar em Chromium Desktop (SP-133)
- **Persona**: Felix (Chrome/Edge desktop).
- **Passos**: abrir `/chat`; esperar "Instalar" aparecer no header; clicar; prompt nativo; aceitar.
- **Resultado esperado**: atalho criado; app abre em janela standalone.

### TC-E-002 — Instalar em Chrome Android (SP-128/133)
- **Passos**: abrir `https://myregister.felix.dev.br` no Chrome Android; "Adicionar à tela inicial" pelo menu ou banner.
- **Resultado esperado**: ícone na home; abre standalone.

### TC-E-003 — Adicionar à Tela de Início no iOS Safari (SP-129)
- **Passos**: Safari iOS → Share → "Adicionar à Tela de Início".
- **Resultado esperado**: ícone na home; abre sem barra Safari (status-bar-style default).

### TC-E-004 — Fluxo offline cai em /offline (SP-135)
- **Passos**: carregar `/chat` online (para precache); DevTools → Network → Offline; reload.
- **Resultado esperado**: SW serve `/offline` (não tela branca); botão "Tentar novamente" funciona; volte online → reload navega.

### TC-E-005 — `/api/*` nunca é cacheado (INV-11)
- **Passos**: carregar dados; DevTools → Application → Cache Storage.
- **Resultado esperado**: nenhuma entrada contém `/api/`. Cache `_next/static/` e HTML apenas.

### TC-E-006 — Update flow e2e (SP-132)
- **Passos**: abrir app (SW v1 instalado); fazer deploy de v2; reload da puppet página.
- **Resultado esperado**: SW v2 instala em waiting; toast "Nova versão disponível" aparece; clique em "Recarregar" → app assume v2.

### TC-E-007 — Fall-back sem cache-html para rota não-cacheada
- **Passos**: novo usuario abre o app offline sem `/chat` ainda cached.
- **Resultado esperado**: SW usa `fallbacks.entries` → `/offline`.

---

## Testes de Regressão

Casos críticos a manter a cada release PWA:

- **R-001** (INV-11): `verify:sw` verde em cada PR do web.
- **R-002** (SP-130): matcher `/api/` + `NetworkOnly` preservados (qualquer mudança em `runtimeCaching` deve mantê-los).
- **R-003** (SP-135): `fallbacks.entries` com `url: '/offline'` + `destination === 'document'`.
- **R-004** (SP-132): listener `SKIP_WAITING` em `sw.ts`; `skipWaiting: false` na config do Serwist.
- **R-005** (SP-128): `manifest()` em `src/app/manifest.ts` com todos campos obrigatórios.
- **R-006** (SP-129): meta tags `appleWebApp` + `viewportFit=cover` no root layout.
- **R-007** (SP-133): `InstallButton` oculta em `display-mode: standalone`.
- **R-008** (Const. Art. VII §26): disclaimer em `/offline`.
- **R-009** (RNF-003): build web usa `--webpack` (não Turbopack).
- **R-010** (RNF-002): SW `disable=true` em dev.