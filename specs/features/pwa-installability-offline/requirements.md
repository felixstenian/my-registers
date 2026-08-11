# Requisitos — PWA — instalabilidade + shell offline (Bloco 4)

> **Rastreabilidade**: SP-128..SP-135 + INV-11 em [`specs/001-mvp-registro-diario/spec.md`](../../001-mvp-registro-diario/spec.md#313-progressive-web-app-pós-mvp-escopo-básico) · Implementação: `apps/web/src/app/{manifest.ts, layout.tsx, sw.ts, sw-update-prompt.tsx, offline/}` + `apps/web/src/app/(app)/InstallButton.tsx` · Bloco 4 (T-B401..T-B410) concluído em v1.1.0; T-B408 adiado.

## Visão geral

Transformer o `apps/web` em PWA instalável em iOS/Android/Desktop com shell offline previsível: manifest + ícones + meta tags iOS, service worker (Serwist) com estratégias por rota, página `/offline`, toast de update e botão "Instalar". **Zero** mudança no backend. **Não** cobre fila offline de mensagens (B-08), push (B-05) nem cache de dados de negócio (INV-11).

## Requisitos funcionais

| ID | Requisito | SP | Prioridade |
|---|---|---|---|
| RF-001 | `manifest.webmanifest` em `/manifest.webmanifest` com `name`, `short_name`≤12 chars, `icons` (192/512/maskable), `theme_color`, `background_color`, `display: standalone`, `start_url: /chat`, `scope: /`, `orientation: portrait`, `lang: pt-BR`. MIME `application/manifest+json` resolvido pela convenção `src/app/manifest.ts`. | SP-128 | Must Have |
| RF-002 | Meta tags iOS Safari no root layout: `apple-mobile-web-app-capable=yes`, `status-bar-style=default`, `title=my-registers`, `apple-touch-icon` 180×180, `formatDetection.telephone=false`, `viewportFit=cover`, `themeColor`. Sem essas, iOS não trata como instalável em standalone. | SP-129 | Must Have |
| RF-003 | Service worker (Serwist em `sw.ts`) com estratégias por rota: `/_next/static/*`→SWR; navegações HTML→`NetworkFirst` timeout 5s; `/api/*`→`NetworkOnly` **nunca** cachear (INV-11); ícones/manifest/fonts→cache-first (`defaultCache`). `navigationPreload` on, `clientsClaim` on, `skipWaiting` controlado por mensagem. Registro após hidratação (não bloqueia render). | SP-130, INV-11 | Must Have |
| RF-004 | Ícones em `public/icons/`: 192×192, 512×512, 512×512 maskable, 180×180 (apple-touch). PNG; fundo `#0f172a` compatível com `background_color` do manifest. | SP-131 | Must Have |
| RF-005 | Quando SW detecta versão nova (`installed` state de um novo worker + já existe `controller` ativo), exibir toast persistente "Nova versão disponível" com botão "Recarregar" que dispara `postMessage( SKIP_WAITING )` seguido de `window.location.reload()` em `controllerchange`. | SP-132 | Should Have |
| RF-006 | Botão "Instalar" no header do layout protegido: escuta `beforeinstallprompt` (preventDefault + guarda evento), chama `.prompt()`; some após `appinstalled` ou se já está em `display-mode: standalone`. Oculto em navegadores sem o evento (Safari/Firefox). | SP-133 | Should Have |
| RF-007 | Splash iOS via `apple-touch-startup-image` (3 sizes iPhone SE/8 + iPhone 15/16 Pro; iPad opcional). Sem isso, iOS mostra tela branca de ~500ms na abertura standalone. | SP-134 | Could Have |
| RF-008 | Rota carregada offline (sem cache do dia) exibe `/offline` com "Sem conexão" + descricao + aviso legal (Const. Art. VII §26) + botão "Tentar novamente" (`window.location.reload()`). | SP-135 | Must Have |

## Requisitos não funcionais

| ID | Requisito | Categoria |
|---|---|---|
| RNF-001 | INV-11 — Service worker **nunca** cacheia respostas de `/api/*` (Art. III §10 — snapshots vêm do DB). Verificado por `verify-sw.mjs` no CI. | Integridade |
| RNF-002 | SW só ativa em produção (`disable: process.env.NODE_ENV === 'development'`); em dev fica desligado pra não interferir no HMR. | DX |
| RNF-003 | Build do web usa `--webpack` (Serwist ainda não suporta Turbopack — issue serwist/serwist#54). Não trocar por Turbopack até a lib migrar. | Compatibilidade |
| RNF-004 | Registro do SW client-side; não bloqueia First Contentful Paint; `clientsClaim` para assumir abas abertas. | Performance |
| RNF-005 | `navigationPreload` habilitado paralleliza network do HTML com boot do SW. | Performance |
| RNF-006 | `SkipWaiting` é opt-in (não automático); usuário recarrega explicitamente — evita quebra de páginas abertas a meio de um fluxo. | UX |
| RNF-007 | `verify:sw` roda pós-build no CI (job `web`) — sanity estático garante INV-11 e SP-130/132/135. | Confiabilidade |
| RNF-008 | HTTPS obrigatório (PWA exige TLS) — produção em `https://myregister.felix.dev.br` via Nginx + Certbot (Fase 9). | Segurança/Infra |

## Restrições e premissas

- **SP-128..135 são pós-MVP** (`must`/`should`/`may`), já em produção v1.1.0.
- **T-B408 (SP-134 splash iOS) adiado** — depende de asset de design real (3 sizes); volta quando ícone final chegar.
- **Não inclui por design**: fila offline de mensagens (B-08), push notifications (B-05), cache offline dos totais do dia (contradiz INV-11), Background Sync API.
- **T-B409 optou por não adicionar vitest** — sanity estático via `verify-sw.mjs` + Lighthouse PWA rodado manualmente conforme `docs/pwa.md` (gate ≥ 90 pendente de rodar em prod).
- **Ícones placeholder** (script inline `sharp` a partir de SVG "mr") — substituir por assets de design real depois.

## Dependências

**Depende de:**
- **Fase 9 concluída** (app em prod com HTTPS válido — PWA exige TLS).
- `@serwist/next` ^9.5.12 + `serwist` ^9.5.12 — framework integration + runtime SW.
- `next` 16 + `react` 19 + Metadata API (`MetadataRoute.Manifest`, `Viewport`).
- `sharp` ^0.35.3 (devDep) — geração de ícones a partir do SVG.

**Requerido por:**
- Sem consumidores diretos — é infra de cliente transversal a todas as features front.