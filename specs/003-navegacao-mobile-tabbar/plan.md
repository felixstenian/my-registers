# Implementation Plan — Navegação mobile: header sticky + bottom tab bar

**Feature ID:** 003-navegacao-mobile-tabbar
**Owner:** Felix
**Depende de:** [`spec.md`](spec.md) v1.0, [`../../.specify/memory/constitution.md`](../../.specify/memory/constitution.md) v1.0.0
**Referencia:** [`../001-mvp-registro-diario/plan.md`](../001-mvp-registro-diario/plan.md) — fases de frontend e PWA já entregues (`(app)/layout.tsx`, `/chat` SP-116, `/day` SP-150..155, `/weekly` SP-110..113, Serwist SP-128..135). Feature 100% frontend; nenhum arquivo de `apps/api` é tocado.

---

## Regras deste documento

- Descreve **como** implementar o que está em `spec.md`, sem duplicar decisões da spec.
- Não duplica `app_plan.md` (fonte canônica de arquitetura) — apenas mapeia SP-NM → arquivos/ordem/gates.
- Alterações neste arquivo requerem PR próprio (`plan:`).

---

## 1. Mapa SP-NM → arquivos

| SP | Área | Arquivos-chave | Status |
|----|------|----------------|--------|
| SP-NM-01 | Viewport dinâmica no `/chat` | `apps/web/src/app/(app)/chat/page.tsx:399` (main `h-[calc(100vh-49px)]` → `100dvh` + reserva p/ barra) | ❌ novo |
| SP-NM-02 | Header sticky + colapso `< md` | `apps/web/src/app/(app)/layout.tsx:36-69` (header + wrapper) | ❌ novo |
| SP-NM-03 | Bottom tab bar mobile | novo `apps/web/src/app/(app)/BottomNav.tsx` (client, `usePathname`), renderizado em `layout.tsx` | ❌ novo |
| SP-NM-04 | Não cobrir compositor/disclaimer | `chat/page.tsx:399-564` (padding inferior reserva espaço da barra) | ❌ novo |
| SP-NM-05 | Desktop inalterado | `layout.tsx` (nav inline só `≥ md`), `BottomNav.tsx` (`hidden md:flex` inverso → `md:hidden`) | ❌ novo |
| SP-NM-06 | Toque + a11y | `BottomNav.tsx` (hit-target 48px, `aria-current`, `aria-label`, foco visível) | ❌ novo |
| SP-NM-07 | PWA standalone + teclado | `chat/page.tsx` (`100dvh`), `BottomNav.tsx` (safe-area) | ❌ novo |
| E2E | Verificação visual | novo `apps/web/e2e/navigation-mobile.spec.ts` (viewport mobile + desktop) | ❌ novo |

**Nenhum arquivo de backend é alterado.** Nenhuma rota, endpoint, schema ou migration nova.

### Decisão de arquitetura (fronteira client)

- `layout.tsx` permanece **server component** (faz `fetchMe` + `redirect`). O header continua server (links puros).
- `BottomNav.tsx` é o **único** novo `'use client'`: precisa de `usePathname()` para o estado ativo. É a folha — o layout não é marcado client.
- Ícones Chat/Hoje/Semana como **SVG inline dentro de `BottomNav.tsx`** (um único consumidor — DRY com juízo: não extrair `nav-icons.tsx` na primeira repetição).

### Single source of truth dos destinos

A constante `NAV_ITEMS = [{ href:'/chat', label:'Chat' }, { href:'/day', label:'Hoje' }, { href:'/weekly', label:'Semana' }]` vive em `BottomNav.tsx` e é **exportada** para o header do layout consumir no modo desktop (evita os dois lugares divergirem). Exportar de client para server component é seguro (é só um array estático sericizável).

---

## 2. Ordem de execução (Fases)

| Fase | Nome | Estim. | Entrega os SPs |
|------|------|--------|----------------|
| 0 | Layout: header sticky + colapso `< md` + wrapper para a barra | ½d | SP-NM-02, SP-NM-05 (parcial) |
| 1 | `BottomNav.tsx` (client) + integração no layout | ½d | SP-NM-03, SP-NM-06 |
| 2 | `/chat`: `100dvh` + reserva de espaço p/ a barra + safe-area | ½d | SP-NM-01, SP-NM-04, SP-NM-07 |
| 3 | E2E `navigation-mobile.spec.ts` (must + regressão desktop) | ½d | proved de SP-NM-01/03/04/05/06/07 |

Total: ~2 dias úteis. (Feature pura de UI; sem interação com banco/LLM.)

---

## 3. Gates de fase

Cada fase é **entregue** quando:

1. Todos os SP-NM `must` da fase têm verificação (E2E mobile para SP-NM-01/04; manual + E2E para 02/03/05) — rastreada em `tasks.md`.
2. Nenhuma violação da Constituição (checklist §4).
3. Nenhuma alteração de spec sem PR próprio.
4. `git log` do PR referencia os SPs cobertos (ex.: `feat(nav-mobile): SP-NM-01 SP-NM-03 SP-NM-04 - header sticky + bottom bar`).
5. `pnpm --filter web typecheck` + `pnpm --filter web lint` + `pnpm --filter web build --webpack` + `pnpm --filter web verify:sw` verdes; job `e2e` do CI verde.

---

## 4. Checklist de conformidade constitucional

Feature de UI pura — os itens de negócio do MVP (Art. II §5, Art. III §10/§11, Art. IV, Art. V §21) são **N/A** (nenhum dado é calculado/mutado). O que se aplica:

- [ ] `INV-11` — SW segue `NetworkOnly` em `/api/*`; nenhuma mudança em `sw.ts`/`next.config.mjs`; `verify:sw` verde.
- [ ] Art. VII §26 — disclaimer do `/chat` permanece visível com a barra presente (SP-NM-04).
- [ ] Art. VIII — a barra apenas **navega**; não oferece edição/exclusão; dia `closed` imutável na UI.
- [ ] Só `api-client` como cliente HTTP — a barra não faz fetch (links puros); o `/chat` não recebe fetch novo.
- [ ] Client boundary mínimo — apenas `BottomNav.tsx` ganha `'use client'`; `layout.tsx`/`page.tsx` não são marcados client por comodidade.
- [ ] Sem dependência nova (SVGs inline; Tailwind existente).

---

## 5. Decisões técnicas SDD-específicas

### 5.1 Modelo de layout (integridade de scroll)

- Raiz do `(app)` continua `flex min-h-dvh flex-col`; header vira `sticky top-0 z-20`.
- A barra inferior é `fixed bottom-0 inset-x-0 z-40 md:hidden` com `padding-bottom: env(safe-area-inset-bottom)`.
- Como é `fixed` (não `absolute`/`flow`), **cada página cede espaço** para não esconder conteúdo:
  - `/chat`: `main` vira `h-[calc(100dvh-49px)]` (substitui o `100vh` — corrige a viewport large no mobile, SP-NM-01/07) + no `< md` adiciona `padding-bottom` equivalente a `nav-height + safe-area` (SP-NM-04) — o compositor e o disclaimer ficam acima da barra sem overlay.
  - `/day` e `/weekly`: adicionam `padding-bottom` `< md` no wrapper (o conteúdo rola por cima, mas o último elemento não fica oculto).
- Ordem de `z-index` (evita que a barra cubra modais): header `20` < bottom bar `40` < modais existentes `50` (`CloseDayModal`/edição).

### 5.2 Stacking e estados da barra

- Estados: `active` (rota atual → `aria-current="page"` + estilo destacado) e `idle`.
- `usePathname()` compara o pathname com `NAV_ITEMS[].href`; rota desconhecida → nenhum ativo.
- Rótulo + ícone em cada aba; hit-target mínimo 48×48px (área de toque, fora do safe-area padding).

### 5.3 E2E Playwright (novo spec)

Banco de viewport por `test.describe`:
- `{ viewport: phones }` (ex.: `Pixel 7` 412×915 ou iPhone 14 390×844) → asserts de SP-NM-01/03/04/06/07.
- `test.use({ viewport: { width: 1280, height: 800 } })` → registra SP-NM-05 (sem barra, nav inline visível).

Cenários-chave (rastrear em `tasks.md` como aceite de SP-NM):
1. `/chat` em mobile com conversa carregada → barra visível; botão "Enviar" clicável e disclaimer legível (a página rola o suficiente para o fim e a barra não oculta o formulário).
2. Tab ativa segue a navegação Chat → Hoje → Semana (e `aria-current` presente).
3. Desktop: sem barra; header com links Chat/Hoje/Semana visíveis.
4. Rota desconhecida (se houver no teste) → nenhuma tab ativa.
5. `/day` mobile rolado → header sticky permanece no topo (bounding box do header não muda ao scroll).

### 5.4 PWA / Service Worker

Não toca `sw.ts`/`next.config.mjs`. `verify:sw` deve continuar verde; a barra é um client component estático (sem rotas novas de runtime). SP-130 (shell offline) intocado.

### 5.5 Server Components vs Client

- `layout.tsx` (server) renderiza `<BottomNav />` — client na folha, sem propagação `'use client'` para cima.
- O header (server) continua com links `next/link` puros; no `< md` o `<nav>` some via Tailwind (`hidden md:flex` já implícito no par `hidden`/`md:flex`), mantendo acessibilidade no desktop.