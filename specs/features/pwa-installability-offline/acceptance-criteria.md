# Critérios de Aceitação — PWA — instalabilidade + shell offline (Bloco 4)

> **Rastreabilidade**: SP-128..SP-135 + INV-11 · Contratos: [`requirements.md`](./requirements.md), [`specifications.md`](./specifications.md).

## AC-001 — Manifest válido (SP-128)

**Dado que** o build de produção roda,
**Quando** `GET /manifest.webmanifest` é servido,
**Então** retorna JSON com `name`, `short_name='my-reg'` (≤12 chars), `icons` (192/512 any + 512 maskable), `theme_color='#0f172a'`, `background_color='#0f172a'`, `display='standalone'`, `start_url='/chat'`, `scope='/'`, `orientation='portrait'`, `lang='pt-BR'`.

**Dado que** o navegador requisita o manifest,
**Quando** recebe a resposta,
**Então** `Content-Type` é `application/manifest+json`.

**Notas de validação:**
- Resolvido por convenção `src/app/manifest.ts` no Next 16.

---

## AC-002 — Meta tags iOS Safari (SP-129)

**Dado que** iOS Safari carrega `/` ou qualquer rota,
**Quando** inspeciona `<head>`,
**Então** contém `apple-mobile-web-app-capable=yes`, `apple-mobile-web-app-status-bar-style=default`, `apple-mobile-web-app-title=my-registers`, `<link rel="apple-touch-icon" href="/icons/apple-touch-icon.png" sizes="180x180">`, `theme-color=#0f172a`, `viewport` com `viewport-fit=cover`, `format-detection telephone=false`.

**Dado que** o usuário adiciona à Tela de Início no iOS,
**Quando** abre standalone,
**Então** não vê barra do Safari (status bar usa estilo `default`).

---

## AC-003 — Estratégias do service worker (SP-130 + INV-11)

**Dado que** o `/sw.js` está registrado,
**Quando** um request matching `/^https?:\/\/[^/]+\/api\//` chega ao SW,
**Então** é tratado por `NetworkOnly` — **nenhuma** response de `/api/*` é cacheada.

**Dado que** navegação HTML (`request.mode === 'navigate'`) online,
**Quando chega** ao SW,
**Então** `NetworkFirst` tenta network com timeout 5s; expira → fallback `html-cache`; sem cache → `/offline`.

**Dado que** request a `/_next/static/*`,
**Quando chega** ao SW,
**Então** `StaleWhileRevalidate` responde do cache e revalida em background.

**Dado que** request a ícone/manifest/fonts,
**Quando chega** ao SW,
**Então** cache-first via `defaultCache` do Serwist.

**Notas de validação:**
- `navigationPreload` on; `clientsClaim` on.
- INV-11 verificado por `verify-sw.mjs` no CI.

---

## AC-004 — Ícones (SP-131)

**Dado que** o build de produção roda,
**Quando** o navegador busca ícones,
**Então** `public/icons/` serve `icon-192.png` (192×192), `icon-512.png` (512×512), `icon-512-maskable.png` (512×512 maskable), `apple-touch-icon.png` (180×180); todos PNG com fundo `#0f172a` compatível com `background_color`.

**Notas de validação:**
- Placeholder gerado via `sharp` a partir de `icon.svg` ('mr'); substituir por design real.

---

## AC-005 — Update flow visível (SP-132)

**Dado que** um novo `sw.js` (hash diferente) é publicado,
**Quando** o browser instala o novo SW em `installed` state **e** já existe `navigator.serviceWorker.controller`,
**Então** o `sw-update-prompt` exibe toast `role="alert"` com "Nova versão disponível" + botão "Recarregar".

**Dado que** o usuário clica "Recarregar",
**Quando** `postMessage({type:'SKIP_WAITING'})` é enviado,
**Então** o novo SW chama `self.skipWaiting()` e assumes controle; `controllerchange` dispara `window.location.reload()`.

**Dado que** um usuário entra pela primeira vez (sem controller ainda),
**Quando** o SW instala,
**Então** o toast **não** aparece (não é update, é instalação).

**Dado que** o registro do SW falha,
**Quando** o catch é disparado,
**Então** a app continua funcionando (erro silencioso).

**Notas de validação:**
- `skipWaiting` é opt-in (config `skipWaiting: false` no `Serwist`).
- Toast some automaticamente no reload seguinte (waitingWorker reset).

---

## AC-006 — Botão "Instalar" (SP-133)

**Dado que** o browser dispara `beforeinstallprompt` (Chromium Android/desktop),
**Quando** `InstallButton` captura o evento com `preventDefault`,
**Então** botão "Instalar" aparece no header do layout protegido.

**Dado que** o usuário clica "Instalar",
**Quando** `promptEvent.prompt()` resolve,
**Então** browser mostra prompt nativo; lê `userChoice.outcome`; se `accepted`, botão some.

**Dado que** `appinstalled` dispara (instalação via menu OS, por ex.),
**Quando** `InstallButton` reage,
**Então** botão some.

**Dado que** a app já está em `display-mode: standalone` (ou `navigator.standalone=true` no iOS),
**Quando** o componente monta,
**Então** botão não renderiza.

**Dado que** o browser é Safari/Firefox (sem `beforeinstallprompt`),
**Quando** o componente monta,
**Então** botão nunca aparece.

---

## AC-007 — Splash iOS (SP-134) — ADIADO

**Dado que** um iPhone SE/8 ou 15/16 Pro abre a app standalone,
**Quando** iOS mostra a splash,
**Então** usa `apple-touch-startup-image` (3 sizes) — em vez de tela branca de ~500ms.

> **Status: adiado (T-B408)** — depende de asset de design real; volta quando ícone final chegar. Discrepância documentada em [`tasks.md`](../../001-mvp-registro-diario/tasks.md).

---

## AC-008 — Página offline previsível (SP-135)

**Dado que** o usuário está offline e uma navegação falha (sem cache HTML),
**Quando** o SW cai no `fallbacks.entries` com `destination='document'`,
**Então** serve `/offline`.

**Dado que** `/offline` renderiza,
**Quando** o usuário vê,
**Então** encontra "Sem conexão" + descricao "Algumas ações do my-registers ficam indisponíveis até você reconectar." + botão "Tentar novamente" + aviso legal (Art. VII §26) em footer.

**Dado que** o usuário clica "Tentar novamente",
**Quando** o client reloada,
**Então** `window.location.reload()` é chamado; se online, navegação normal.

**Notas de validação:**
- `/offline` **não** está em `PROTECTED_PREFIXES` em `proxy.ts` — acessível sem cookie.

---

## Cenários de Borda

| Cenário | Comportamento Esperado |
|---|---|
| Dev mode (`NODE_ENV='development'`) | Serwist `disable=true`; `/sw.js` não é injetado; HMR funciona normalmente. |
| Browser sem SW support | `sw-update-prompt.tsx` retorna cedo (`!('serviceWorker' in navigator)`); sem erro. |
| `beforeinstallprompt` nunca dispara (iOS) | `InstallButton` state `promptEvent=null`; component retorna `null`. |
| Usuário recarrega no meio do toast | Toast some naturalmente (waitingWorker reset no novo mount); SW ainda espera skipWaiting. |
| `/offline` acessada online (URL direta) | Renderiza normalmente — não é rota offline-only por si; é usada como fallback. |
| Múltiplas abas abertas | `controllerchange` em 1 aba; cada aba precisa recarregar para pegar novo SW; `clientsClaim` faz o novo SW controlar todas mas reload ainda manual. |
| NetworkFirst timeout 5s sem cache | Pagina cai em `/offline`. |
| Request a `/api/*` offline | Falha (NetworkOnly) — não cacheia; corolário do INV-11 — app mostra erro de fetch específico da feature (não `/offline`). |

## Critérios de Não-Funcionalidade

| Critério | Threshold |
|---|---|
| Lighthouse PWA score | ≥ 90 (rodar em prod — pendente) |
| `verify:sw` no CI | 5/5 checks OK mandatório antes de merge |
| `/api/*` no cache | 0 entradas (INV-11) |
| First Contentful Paint | Não é bloqueado por SW (registro client-side pós-hidratação) |
| SW register | Só em produção (dev desligado) |
| Build | `--webpack` (não Turbopack) |
| Bundle size | Sem markdown lib; SW runtime é Serwist (~20 KB) |