# Especificações Técnicas — PWA — instalabilidade + shell offline (Bloco 4)

> **Rastreabilidade**: SP-128..SP-135 + INV-11 · Implementação: `apps/web/src/app/{manifest.ts, layout.tsx, sw.ts, sw-update-prompt.tsx, offline/}` + `apps/web/src/app/(app)/InstallButton.tsx` + `apps/web/scripts/verify-sw.mjs` + `apps/web/next.config.mjs`.

## Escopo técnico

PWA client-side puramente em `apps/web`. Nenhum endpoint do backend é tocado. Três eixos: (1) **instalabilidade** — manifest + ícones + meta tags iOS; (2) **shell offline** — service worker Serwist com estratégias por rota + fallback `/offline`; (3) **lifecycle** — toast de update + botão "Instalar" (Chromium). Verificação estática via `verify-sw.mjs` no CI.

## Interface (componentes e arquivos)

### `src/app/manifest.ts` — `MetadataRoute.Manifest` (SP-128)
```ts
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: 'my-registers', short_name: 'my-reg',
    description: 'Diário nutricional pessoal via chat...',
    start_url: '/chat', scope: '/', display: 'standalone',
    orientation: 'portrait',
    background_color: '#0f172a', theme_color: '#0f172a',
    lang: 'pt-BR', dir: 'ltr',
    icons: [
      { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
      { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
      { src: '/icons/icon-512-maskable.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
    ],
  };
}
```
Servido em `/manifest.webmanifest` com MIME `application/manifest+json` (convenção Next 16).

### `src/app/layout.tsx` — `Metadata` + `Viewport` (SP-129)
```ts
export const metadata: Metadata = {
  title: 'my-registers',
  applicationName: 'my-registers',
  appleWebApp: { capable: true, title: 'my-registers', statusBarStyle: 'default' },
  formatDetection: { telephone: false },
  icons: { icon: [...192/512], apple: [{ url: '/icons/apple-touch-icon.png', sizes: '180x180' }] },
};
export const viewport: Viewport = { themeColor: '#0f172a', width: 'device-width',
  initialScale: 1, viewportFit: 'cover' };
```
Render envolve `<html lang="pt-BR">` + `<SwUpdatePrompt />` no body.

### `src/app/sw.ts` — Service worker (SP-130 + INV-11)
```ts
const serwist = new Serwist({
  precacheEntries: self.__SW_MANIFEST,
  skipWaiting: false, clientsClaim: true, navigationPreload: true,
  runtimeCaching: [
    { matcher: /^https?:\/\/[^/]+\/api\//, handler: new NetworkOnly() },      // INV-11
    { matcher: ({ request }) => request.mode === 'navigate',
      handler: new NetworkFirst({ cacheName: 'html-cache', networkTimeoutSeconds: 5 }) },
    { matcher: /\/_next\/static\/.*/,
      handler: new StaleWhileRevalidate({ cacheName: 'next-static-cache' }) },
    ...defaultCache,                                                            // icons/manifest/fonts
  ],
  fallbacks: { entries: [{ url: '/offline',
    matcher: ({ request }) => request.destination === 'document' }] },
});
self.addEventListener('message', (e) => {
  if (e.data?.type === 'SKIP_WAITING') void self.skipWaiting();
});
serwist.addEventListeners();
```

### `src/app/sw-update-prompt.tsx` — toast de update (SP-132)
`'use client'`; `useEffect` registra `/sw.js` se `'serviceWorker' in navigator` + `NODE_ENV === 'production'`. Escuta `updatefound` → `statechange` → `installed` quando `navigator.serviceWorker.controller` existe. Toast `role="alert"` fixo no rodapé; botão "Recarregar" → `postMessage({type:'SKIP_WAITING'})`; `controllerchange` dispara `window.location.reload()`. Erros silenciosos.

### `src/app/(app)/InstallButton.tsx` — botão Install (SP-133)
`'use client'`; `useEffect` verifica `display-mode: standalone` ou `navigator.standalone` (oculta se já instalado). Escuta `beforeinstallprompt` (preventDefault + guarda evento) e `appinstalled` (reseta). Botão chama `promptEvent.prompt()` + lê `userChoice.outcome`; some se `outcome==='accepted'`.

### `src/app/offline/page.tsx` + `OfflineRetryButton.tsx` (SP-135)
Server component; `<OfflineRetryButton>` client com `window.location.reload()`. Inclui aviso legal (Const. Art. VII §26) em footer.

### `apps/web/next.config.mjs` — Serwist integration
```js
const withSerwist = withSerwistInit({
  swSrc: 'src/app/sw.ts', swDest: 'public/sw.js',
  disable: process.env.NODE_ENV === 'development',
  cacheOnNavigation: true, reloadOnOnline: true,
});
export default withSerwist({ output: 'standalone', reactStrictMode: true,
  async rewrites() { /* /api/:path* → backend */ } });
```

### `apps/web/scripts/verify-sw.mjs` — sanity estático (T-B409)
Node ESM; checagens (5):
1. Matcher `/api/` presente em `sw.ts` (INV-11).
2. `NetworkOnly` é handler da regra `/api/` (INV-11).
3. Fallback `url: '/offline'` declarado (SP-135).
4. Listener `SKIP_WAITING` + `skipWaiting()` (SP-132).
5. (pós-build) bundle `public/sw.js` contém `/api` e `/offline` — opcional se bundle ausente.

## Modelo de dados

Sem modelo de dados — feature estática (manifest, sw, ícones, componentes). Os `"dados"` envolvidos são caches do SW (Cache Storage API):
- `html-cache` — Documents HTML (`NetworkFirst` + fallback).
- `next-static-cache` — `_next/static/*` (`StaleWhileRevalidate`).
- `serwist-precache-v2` (default do Serwist) — precache de assets do build.
- Cache padrão do `defaultCache` — icons/manifest/fonts.

Não há IndexedDB; nada persiste entre sessões além do cache do SW.

## Fluxo de dados

### Instalação (Chromium)
1. BrowserQualifies (HTTPS + manifest válido + SW + ícone 192+512 + fetch handler) dispara `beforeinstallprompt`.
2. `InstallButton` captura evento (preventDefault); botão aparece no header.
3. Usuário clica → `promptEvent.prompt()` → browser mostra prompt nativo.
4. `userChoice.outcome` → `'accepted'|'dismissed'`; botão some se accepted.
5. `appinstalled` event também some o botão (caso install venha de menu do OS).

### Instalação (iOS Safari)
- Sem API `beforeinstallprompt`; usuário usa menu Share → "Adicionar à Tela de Início". Meta tags `appleWebApp` permitem standalone pós-add.
- Botão "Instalar" **não** aparece (correto — não há o que disparar).

### Update do SW (SP-132)
1. Novo build → novo `sw.js` com hash diferente.
2. Browser faz byte-for-byte check no `/sw.js`, detecta diferença, instala novo SW em `installing` → `installed` (esperando).
3. `sw-update-prompt` escuta `updatefound` + `statechange`; quando `state==='installed'` && `navigator.serviceWorker.controller` existe → exibe toast com `waitingWorker` guardado.
4. Usuário clica "Recarregar" → `waitingWorker.postMessage({type:'SKIP_WAITING'})`.
5. SW novo chama `self.skipWaiting()`; assumes controle todas as abas → dispara `controllerchange`.
6. Listener do `controllerchange` → `window.location.reload()`.

### Navegação offline (SP-135)
1. Usuário digita URL/refresh offline; SW intercepta `mode === 'navigate'`.
2. `NetworkFirst` tenta network; `networkTimeoutSeconds: 5` expira sem resposta.
3. Fallback pro `html-cache` (último HTML cached); se não há cache para a rota, `fallbacks.entries` oferece `/offline` (Document).
4. `/offline` renderiza mensagem + aviso legal + botão "Tentar novamente".
5. Click → `window.location.reload()` quando voltar online.

## Regras de negócio

1. **`/api/*` é intocável pelo cache** (INV-11). `NetworkOnly` matcher `/^https?:\/\/[^/]+\/api\//`.
2. **SkipWaiting é opt-in**: SW novo nunca assume sozinho; toast + clique explícito evita quebrar fluxos a meio.
3. **Dev sem SW** (`disable=development`) — não interfere em HMR; só ativa produção.
4. **Botão "Instalar" auto-oculta**: detecta `display-mode: standalone` no mount; some em `appinstalled`.
5. **Toast some quando não há waitingWorker**: `if (!waitingWorker) return null`.
6. **Registro do SW client-side** em `sw-update-prompt::useEffect` (não bloqueia FCP).
7. **`/offline` rota pública** (não está em `PROTECTED_PREFIXES` em `proxy.ts`) — acessível offline mesmo sem cookie.
8. **Aviso legal mandatório** no `/offline` (Art. VII §26).

## Configurações e variáveis de ambiente

| Variável | Descrição | Padrão | Obrigatória |
|---|---|---|---|
| `NEXT_PUBLIC_API_URL` | URL base para client (relativa `/api`) — proxy Next resolve `/api/*` | `/api` | Sim |
| `INTERNAL_API_URL` | URL interna para server components chamarem o backend | — | Sim (server) |
| `NODE_ENV` | Controla `disable` do Serwist (dev=desligado) | — | Sim |

Sem variáveis específicas de PWA — tudo hardcoded (cores, ícones, paths).

## Referências de implementação

- **Manifest**: `apps/web/src/app/manifest.ts`.
- **Meta tags + layout**: `apps/web/src/app/layout.tsx` (`metadata`, `viewport`, `<SwUpdatePrompt />`).
- **Service worker**: `apps/web/src/app/sw.ts` (58 linhas) — Serwist runtimeCaching/fallbacks + `SKIP_WAITING`.
- **Update toast**: `apps/web/src/app/sw-update-prompt.tsx` (80 linhas) — `updatefound`/`installed`/`controllerchange`.
- **Botão install**: `apps/web/src/app/(app)/InstallButton.tsx` (66 linhas) — `beforeinstallprompt`/`appinstalled`.
- **Página offline**: `apps/web/src/app/offline/page.tsx` + `OfflineRetryButton.tsx` (SP-135).
- **Ícones**: `apps/web/public/icons/` — `icon.svg` (source), `icon-192.png`, `icon-512.png`, `icon-512-maskable.png`, `apple-touch-icon.png` (180×180). Gerados via `sharp` (script inline).
- **Serwist integration**: `apps/web/next.config.mjs` (`withSerwistInit`).
- **Sanity check**: `apps/web/scripts/verify-sw.mjs` (T-B409) — roda via `pnpm --filter web verify:sw` no CI (job `web`).
- **Docs**: `docs/pwa.md` (instalação por plataforma, diagnóstico, arquivos-chave, Lighthouse).