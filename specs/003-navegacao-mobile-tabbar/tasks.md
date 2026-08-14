# Tasks — Navegação mobile: header sticky + bottom tab bar

**Feature ID:** 003-navegacao-mobile-tabbar
**Depende de:** [`spec.md`](spec.md), [`plan.md`](plan.md), [`../../.specify/memory/constitution.md`](../../.specify/memory/constitution.md)

---

## Regras deste documento

- Cada tarefa tem ID `T-NM-XXX` estável.
- Uma tarefa é **atômica**: entrega em ≤ 1 dia, em 1 PR pequeno.
- Cada tarefa referencia: os `SP-NM-XX` que atende, arquivos-chave a criar/modificar, dependências (`blocked_by`), e critério de aceite.
- Status: `todo` · `in_progress` · `done` · `blocked` · `deferred`.
- Tamanho: **S** (≤ 2h) · **M** (½ dia) · **L** (1 dia).

---

## Fase 0 — Layout: header sticky + colapso mobile ⬜

Status: **todo**. Destrava a barra inferior sem duplicar markup; muda o esqueleto compartilhado por `/chat`, `/day` e `/weekly`.

- [ ] **T-NM-01** — Header sticky + colapso `< md` em `layout.tsx`. (S) — SP-NM-02, SP-NM-05.
  - Arquivos: `apps/web/src/app/(app)/layout.tsx:36-69`.
  - Header vira `sticky top-0 z-20` (permanece visível quando `/day`/`/weekly` rolam — SP-NM-02).
  - No `< md`: `<nav>` inline (Chat · Hoje · Semana) e o `{me.email}` ocultos via Tailwind (`hidden md:flex` / `hidden md:block`); a marca, `InstallButton` e `LogoutButton` permanecem. Altura do header colapsado = altura do desktop (sem wrap — zero CLS).
  - A constante `NAV_ITEMS` (Chat/Hoje/Semana) passa a viver em `BottomNav.tsx` (client) e é **importada** pelo layout — single source of truth (plan §1).
  - `blocked_by`: nenhum.
  - **Aceite:** `pnpm --filter web typecheck` + `lint` verdes; no DevTools 375px o header mostra marca + ícones (sem links inline); desktop (≥ 768px) com nav inline intacta.

---

## Fase 1 — BottomNav (client) ⬜

Status: **todo**. Coração da feature — o menu no alcance do polegar.

- [ ] **T-NM-02** — `BottomNav.tsx` client + render no layout. (M) — SP-NM-03, SP-NM-06.
  - Arquivos: novo `apps/web/src/app/(app)/BottomNav.tsx`; `layout.tsx` (render após `<div className="flex-1">`).
  - `'use client'` com `usePathname()`; exporta `NAV_ITEMS` (`{href,label}` para `/chat`, `/day`, `/weekly`).
  - `<nav aria-label="Navegação principal">` fixo `bottom-0 inset-x-0 z-40 md:hidden`, fundo + `border-t`, `padding-bottom: env(safe-area-inset-bottom)`.
  - Cada aba: `<Link>` com ícone SVG inline + rótulo, hit-target ≥ 48×48px; estado ativo (rota atual → `aria-current="page"` + destaque com contraste ≥ 3:1, não só por cor); rota desconhecida → nenhum ativo.
  - Foco visível (`focus-visible`) em cada aba.
  - `blocked_by`: T-NM-01.
  - **Aceite:** `pnpm typecheck`/`lint` verdes; no DevTools 375px a barra aparece com 3 abas e segue a rota ativa navegando Chat→Hoje→Semana; ≥ 768px não renderiza; teclado (Tab/Enter) navega as abas.

---

## Fase 2 — `/chat`: viewport dinâmica + espaço p/ a barra ⬜

Status: **todo**. Corrige a causa raiz (100vh) e garante SP-NM-04/07.

- [ ] **T-NM-03** — `main` do `/chat` usa `100dvh` + reserva de espaço `< md`. (M) — SP-NM-01, SP-NM-04, SP-NM-07.
  - Arquivos: `apps/web/src/app/(app)/chat/page.tsx:399` (`h-[calc(100vh-49px)]` → `100dvh`).
  - No `< md`, adiciona `padding-bottom` = altura da barra + safe-area (`env(safe-area-inset-bottom)`), de forma que compositor (textarea + anexos + Enviar) e disclaimer (Art. VII §26) fiquem **acima** da barra — a barra nunca sobrepõe nem intercepta `pointer events` do formulário (drag-and-drop SP-19).
  - Sem mudança no polling (`POLL_CAP_MS`), no fetch nem no SW.
  - `blocked_by`: T-NM-02.
  - **Aceite:** com URL bar aberta/fechada no DevTools mobile, o header não sai de vista e o scroll da conversa é só interno; botão "Enviar" clicável com a barra visível; disclaimer legível.

---

## Fase 3 — `/day` e `/weekly`: espaço p/ a barra ⬜

Status: **todo**. Páginas com scroll de página não podem ter conteúdo oculto atrás da barra fixa.

- [ ] **T-NM-04** — `padding-bottom` `< md` nos wrappers. (S) — SP-NM-04.
  - Arquivos: `apps/web/src/app/(app)/day/page.tsx`, `apps/web/src/app/(app)/day/[date]/page.tsx`, `apps/web/src/app/(app)/weekly/page.tsx` (wrappers `<main className="...p-4">`).
  - Adiciona `pb` reservando barra + safe-area no mobile; desktop inalterado.
  - `blocked_by`: T-NM-02.
  - **Aceite:** em 375px, o último elemento de `/day` e `/weekly` não fica oculto atrás da barra; ≥ 768px sem diferença.

---

## Fase 4 — E2E Playwright + gates ⬜

Status: **todo**. Prova dos critérios de aceite do spec via viewports.

- [ ] **T-NM-05** — `navigation-mobile.spec.ts`. (M) — cobertura SP-NM-01/03/04/05/06/07.
  - Arquivos: novo `apps/web/e2e/navigation-mobile.spec.ts`.
  - Viewport mobile (ex.: 390×844): (1) barra visível em `/chat` com conversa carregada; "Enviar" clicável + disclaimer legível ao rolar até o fim; (2) tab ativa segue Chat→Hoje→Semana com `aria-current`; (3) `/day` rolado mantém header no topo (bounding box inalterado); (4) hit-target das abas ≥ 48px.
  - Viewport desktop (1280×800): barra ausente; nav inline visível no header (SP-NM-05).
  - `blocked_by`: T-NM-03, T-NM-04.
  - **Aceite:** `pnpm --filter web exec playwright test navigation-mobile` verde (e job `e2e` do CI); `verify:sw` verde.

**Gate da feature — cumprido:** SP-NM-01..07 cobertos; `typecheck`/`lint`/`build --webpack`/`verify:sw`/E2E verdes; checklist de conformidade do `plan.md` §4 assinalado.

---

## Histórico

- **2026-08-14** — v1.0. Tarefas atômicas por fase (T-NM-01..05) derivadas do `plan.md` §2.