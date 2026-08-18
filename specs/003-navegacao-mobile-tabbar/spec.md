# Feature Specification — Navegação mobile: header sticky + bottom tab bar

**Feature ID:** 003-navegacao-mobile-tabbar
**Status:** Proposed (aguardando PR `spec:`)
**Owner:** Felix
**Constituição aplicável:** [`../../.specify/memory/constitution.md`](../../.specify/memory/constitution.md) v1.0.0
**Spec-fonte (MVP):** [`../001-mvp-registro-diario/spec.md`](../001-mvp-registro-diario/spec.md) — melhora a usabilidade mobile do layout protegido `(app)` (header + navegação) usado em `/chat`, `/day` (SP-150..SP-155), `/weekly` (SP-110..SP-113) e PWA (SP-128..SP-135).
**Plano técnico:** [`plan.md`](plan.md) — criado no PR `plan:` seguinte.
**Tarefas:** [`tasks.md`](tasks.md) — criado no PR `tasks:` seguinte.
**Decisões:** [`research.md`](research.md) — criado conforme necessário.

---

## Regras deste documento (spec-kit)

- Este arquivo descreve **o quê** e **por quê**, nunca **como** (implementação vive em `plan.md`).
- Cada requisito tem ID estável `SP-NM-XX` — nunca renumerar; para deprecar, marcar `~~SP-NM-XX~~ DEPRECATED (motivo)`.
- Cada `SP-NM-XX` deve ter pelo menos um teste (unit, integration, E2E ou manual) rastreado em `tasks.md`.
- Palavras-chave (RFC 2119): **MUST**, **MUST NOT**, **SHOULD**, **MAY**.
- Critérios no formato Given / When / Then (Dado / Quando / Então).
- Nesta spec: `must` bloqueia a entrega; `should` é importante mas negociável; `may` fica para follow-up.

---

## 1. Contexto e objetivo

**Problema.** No mobile, a navegação para os três destinos primários (Chat, Hoje, Semana) vive apenas no header — fisicamente no topo da tela e longe do polegar. Além disso, o layout do `/chat` usa `h-[calc(100vh-49px)]`: em navegadores mobile `100vh` refere-se ao **large viewport** (mais alto que a viewport visível enquanto a URL bar está aberta), fazendo a página inteira — incluindo um header **não sticky** — sair pela dobra. O usuário que está no rodapé da conversa (próximo do disclaimer) e precisa do menu precisa rolar toda a conversa de volta até o topo.

**Por que agora.** A persona acessa a aplicação diariamente em desktop **e** mobile (spec 001 §2.1). Com `/day` (Blocos 6/7) e `/weekly` entregues, navegar entre os três destinos é o principal fluxo da sessão; a fricção atual no mobile (rolar até o topo para achar o menu) é o atrito mais reportado no uso real em prod.

**Resultado observável.** Em telas estreitas (< `md`), o usuário tem o menu primário sempre ao alcance: uma barra de abas fixa no rodapé (Chat · Hoje · Semana), com a aba atual destacada. O header vira um elemento compacto e sticky (marca + ações globais), sem colapsar conteúdo nem cobrir o compositor do chat. Em desktop (≥ `md`), **nada muda** — a navegação continua no header.

---

## 2. Personas e escopo

### 2.1 Persona P1 — Felix (usuário único)
Mesma persona do MVP. Acessa diariamente via mobile (Safari iOS / Chrome Android, inclusive instalado como PWA `display: standalone`) e desktop. Opera o chat principalmente no mobile, no meio do dia.

### 2.2 Cenário-âncora
1. Mobile: usuário abre `/chat` com uma conversa longa e está no rodapé (disclaimer visível).
2. Quer o relatório semanal → toca **Semana** na barra de abas do rodapé (a menos de um dedo de onde já está).
3. Navega para `/weekly` com a aba **Semana** destacada; o header continua visível no topo com a marca e o logout.
4. Mobile: abre um `/day` longo já rolado (days passados via `DayNavigator`) → o header permanece fixo no topo; a barra de abas permite pular para o `/chat` sem rolar até o topo.
5. Desktop: nada muda — header com nav inline (Chat · Hoje · Semana), sem barra inferior.

---

## 3. Requisitos funcionais

### 3.1 Integridade do layout no mobile

**SP-NM-01** (`must`) — O layout do `/chat` não estoura a viewport dinâmica no mobile.
- **Given** um navegador mobile com URL bar dinâmica (abrindo/fechando ao rolar).
- **When** o usuário navega para `/chat`.
- **Then** a altura total do layout mede a viewport **dinâmica** (`dvh`) e não a viewport grande (`vh`); o header permanece fixo no topo e o único scroll da conversa acontece dentro do contêiner interno de mensagens — a página **MUST NOT** rolar de forma que o header saia de vista.
- Critério de teste: no DevTools (iPhone/Android), com URL bar aberta e fechada, o footer/disclaimer do chat continua alcançável e o header não some.

### 3.2 Header

**SP-NM-02** (`must`) — Header sticky e colapsado no mobile.
- **Given** qualquer rota protegida (`/chat`, `/day`, `/day/[date]`, `/weekly`) em viewport `< md`.
- **When** o usuário rola o conteúdo.
- **Then**:
  1. O header é `sticky top-0` com `z-index` acima do conteúdo, permanecendo visível (SP-150..155, `/weekly` longo).
  2. A navegação horizontal (links Chat · Hoje · Semana) **MUST** estar oculta em `< md` (o destino primário vira a bottom tab bar — SP-NM-03).
  3. O e-mail do usuário é oculto em `< md`.
  4. A marca (`my-registers`), o `InstallButton` e o `LogoutButton` permanecem.
- **Then** (altura estável) a altura do header colapsado é igual à do desktop e **MUST NOT** quebrar linha nem wrap no mobile (zero CLS ao reduzir viewport).

### 3.3 Bottom tab bar

**SP-NM-03** (`must`) — Barra de navegação inferior no mobile (`< md`).
- **Given** viewport `< md` em qualquer rota protegida.
- **Then** uma barra de abas fixa no rodapé apresenta exatamente os 3 destinos primários: **Chat** (`/chat`), **Hoje** (`/day`), **Semana** (`/weekly`).
- Cada aba é um `<Link>` real (suporte a teclado/foco) com rótulo visível + ícone inline (sem dependência de lib de ícones).
- A aba correspondente à rota atual é destacada (estado ativo com contraste mínimo 3:1) e recebe `aria-current="page"`.
- Em rota fora dos 3 destinos (ex.: página futura), nenhuma aba fica ativa.
- Em viewport `≥ md` a barra **MUST NOT** ser renderizada (desktop inalterado — SP-NM-05).
- A barra respeita `safe-area-inset-bottom` (iOS home indicator / Android gesture bar) sem degradar o hit-target das abas.

**SP-NM-04** (`must`) — A barra inferior não cobre conteúdo essencial.
- **Given** a bottom tab bar visível em `/chat`.
- **When** o usuário rola até o final da conversa.
- **Then** o compositor (textarea + anexos + Enviar) e o disclaimer (Const. Art. VII §26) permanecem **totalmente visíveis e operáveis** — a área de conteúdo cede espaço à barra; a barra **MUST NOT** sobrepor nem interceptar `pointer events` do formulário (drag-and-drop SP-19).
- Critério de teste: E2E Playwright com viewport mobile confirma que o botão "Enviar" está clicável e o disclaimer legível com a barra presente.

### 3.4 Desktop e fronteiras

**SP-NM-05** (`must`) — Desktop inalterado.
- **Given** viewport `≥ md`.
- **Then** o layout, o header (com nav inline Chat · Hoje · Semana) e o `/chat` permanecem exatamente como hoje — sem bottom bar e sem ocultação de links.

**SP-NM-06** (`should`) — Toque e acessibilidade.
- Hit-target mínimo de 48×48px (área de toque) para cada aba (excluindo o padding de safe-area).
- `aria-label` na barra (ex.: "Navegação principal") e rótulos visíveis por aba.
- Foco visível (`focus-visible`) em cada aba; navegação por teclado (Tab/Enter) funcional.
- Estado ativo distinguível sem depender só de cor (ex.: cor + peso de fonte/ícone preenchido).

**SP-NM-07** (`should`) — Robusto em PWA standalone e teclado virtual.
- **Given** o app aberto como PWA em `display-mode: standalone` (iOS/Android, SP-128..135).
- **When** o teclado virtual está aberto para digitar no chat.
- **Then** a viewport dinâmica (`dvh`) mantém compositor e barra acessíveis; a barra sobe junto com o teclado sem sumir nem ficar sob o home indicator.

---

## 4. Requisitos não-funcionais

| ID | Requisito | Categoria |
|---|---|---|
| RNF-001 | A barra inferior é um client component leve, **sem fetch** de dados; zero impacto no LCP das rotas | Performance |
| RNF-002 | Altura do header colapsado no mobile = altura do desktop → zero CLS ao navegar/rotacionar | Estabilidade visual |
| RNF-003 | Ordem de `z-index`: header `20` < modais `50`; a bottom bar `40` nunca sobrepõe `CloseDayModal`/modais de edição | Stacking |
| RNF-004 | Nenhum cache de `/api/*` no service worker (INV-11) — a barra navega por `<Link>` sem bater na API | Conformidade |
| RNF-005 | Navegação por teclado + `aria-current` em todas as abas (WCAG 2.1) | Acessibilidade |
| RNF-006 | O disclaimer legal (Const. Art. VII §26) permanece visível no chat (coberto por SP-NM-04) | Conformidade |

---

## 5. Interfaces observáveis

### 5.1 Componentes/rotas (frontend — zero mudança de backend)

| Artefato | Tipo | Responsabilidade | SP |
|---|---|---|---|
| `apps/web/src/app/(app)/BottomNav.tsx` | client (`'use client'`) | Tab bar fixa `< md`, 3 destinos, `aria-current`, ícones SVG inline | SP-NM-03, SP-NM-06 |
| `apps/web/src/app/(app)/layout.tsx` | server | Header `sticky` + colapso `< md` (oculta nav inline e e-mail) + render `BottomNav` | SP-NM-02, SP-NM-05 |
| `apps/web/src/app/(app)/chat/page.tsx` | client | Layout usa viewport dinâmica e cede espaço à barra (compositor/disclaimer visíveis) | SP-NM-01, SP-NM-04 |
| Ícones (novo, ex.: `apps/web/src/app/(app)/nav-icons.tsx` ou inline) | server/client | Svgs Chat/Hoje/Semana sem dependência | SP-NM-03 |

### 5.2 Rotas protegidas afetadas
`/chat`, `/day`, `/day/[date]`, `/weekly` — nenhuma rota nova; os destinos já existem (middleware/proxy não muda).

### 5.3 Sem API nova
Nenhum endpoint, schema ou migration. Backend intocado.

---

## 6. Invariantes

Esta feature não introduz invariante de banco novo — é puramente de UI/navegação. Reafirma, com cobertura de teste nova (E2E mobile para NM-01/NM-04):

- **INV-11** — Service worker segue `NetworkOnly` em `/api/*`; a barra inferior não adiciona rotina de cache.
- **Art. VII §26** — O disclaimer legal permanece visível no `/chat` (SP-NM-04) e nunca é removido/duplicado.
- **Art. VIII** — A navegação não oferece edição/exclusão; dias `closed` permanecem imutáveis (a barra apenas navega).

---

## 7. Fora do escopo

- Itens globais adicionais na barra (logout, install, perfil) — permanecem no header.
- Mais de 3 abas ou abas customizáveis/persistidas.
- Gestos de swipe (ex.: deslizar para trocar de aba).
- Barra que se esconde ao rolar para baixo (hide-on-scroll) — mantém sempre visível.
- Tratamento dedicado de landscape (a barra apenas segue o layout `md`).
- Qualquer mudança no backend ou no service worker.

---

## 8. Glossário

- **Viewport dinâmica / visual (`dvh`)** — viewport do navegador ajustada à presença da URL bar / teclado virtual; `100vh` (viewport large) no mobile é maior e causa overflow do layout.
- **Safe-area inset** — área não-envasada por notch e barra de gestos (iOS/Android); aplicada como `padding-bottom: env(safe-area-inset-bottom)`.
- **Tab bar** — barra de navegação primária fixa no rodapé, um destino por aba com estado ativo.
- **`aria-current="page"`** — marcador WAI-ARIA que comunica ao screen reader qual link é o da página atual.

---

## Histórico de alterações

- **2026-08-14** — v1.0. Spec inicial. Adicionados SP-NM-01..SP-NM-07. Motivador: no mobile o menu primário vive só no topo (header) e o `/chat` com `100vh` faz o header (não sticky) sair de vista — usuário que está no rodapé da conversa precisa rolar toda a conversa para navegar. Proposta em três camadas: corrigir a viewport do `/chat` (dvh), header sticky + colapsado no `< md`, e bottom tab bar com os 3 destinos primários. Zero mudança no backend; coverage por E2E Playwright mobile.