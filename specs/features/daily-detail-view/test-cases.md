# Casos de Teste — Visão detalhada do dia (Bloco 6)

> **Rastreabilidade**: SP-150..SP-155 · Backend parcial: `apps/api/tests/test_day_close_report.py`.
> **Tests前端**: [Implementação não localizada] — sem Vitest/Playwright em `apps/web`.

## Cobertura alvo

- **Unitários (frontend alvo)**: `format.ts` (data arithmetic + formatters), `DayNavigator` state (visibilidade prev/next/Hoje), `ConfirmItemButton` state machine, `groupBySlot` em `DayView`, `EmptyState` branches.
- **Integração (frontend)**: page server component com `fetch` mocked; render tree completa.
- **E2E**: jornada `/day` em desktop + mobile; `/day/[date]` com 404; data futura bloqueada; navegação temporal.

---

## Testes Unitários (backend — alguns existentes)

### TC-U-001 — `_load_food` retorna micros (SP-152)
- **Módulo**: `apps/api/app/services/day_query.py`
- **Função**: `_load_food(day_log_id)`
- **Saída esperada**: por FoodItem, dict contém `sodium_mg`/`calcium_mg`/`iron_mg`/`potassium_mg` + `confidence`/`has_catalog`/`is_estimate`/`needs_confirmation`/`source`.
- **Tipo**: Happy path — parcial [Implementação não localizada]-dedicado, cobertura em `test_day_close_report.py`.

---

## Testes Unitários (frontend — alvo pendente)

> [Implementação não localizada] — adicionar Vitest + RTL. <!-- TODO: configurar Vitest -->

### TC-U-002 — `fmtDateFull` formata em pt-BR (SP-150)
- **Módulo**: `apps/web/src/app/(app)/day/format.ts`
- **Entrada**: `'2026-07-29'`
- **Saída esperada**: `"quarta-feira, 29 de julho de 2026"` (`capitalize` aplicado no `<h1>`).
- **Tipo**: Happy path

### TC-U-003 — `fmtAmount` escolhe grams/ml/quantity (SP-151)
- **Entradas**: (a) `{grams:150, ml:null, quantity:null, unit:null}` → `"150 g"`; (b) `{grams:null, ml:200, ...}` → `"200 ml"`; (c) `{grams:null, ml:null, quantity:2, unit:'concha'}` → `"2 concha"`; (d) tudo null → `"—"`.
- **Tipo**: Happy path + edge

### TC-U-004 — `fmtInt`/`fmtKcal`/`fmtMg` retornam `—` para null/0 (SP-152)
- **Entradas**: `fmtInt(0)` → `"—"`; `fmtMg(null)` → `"—"`; `fmtKcal(undefined)` → `"—"`.
- **Tipo**: Edge case

### TC-U-005 — `addDaysISO` usa UTC (RNF-006)
- **Entrada**: `addDaysISO('2026-03-15', -1)` (pré-DST BR)
- **Saída esperada**: `"2026-03-14"` (sem drift).
- **Tipo**: Happy path

### TC-U-006 — `todayLocalISO` respeita fuso browser
- **Entrada**: mock `Date` com timezone fixo.
- **Saída esperada**: `YYYY-MM-DD` do dia local do browser.
- **Tipo**: Happy path

### TC-U-007 — `compareISO` lexicográfico
- **Entradas**: `('2026-07-29', '2026-07-30')` → -1; `('2026-07-30', '2026-07-30')` → 0; `('2026-08-01', '2026-07-30')` → 1.
- **Tipo**: Happy path

### TC-U-008 — `groupBySlot` ordena e bucketiza desconhecidos (SP-151)
- **Módulo**: `apps/web/src/app/(app)/day/DayView.tsx`
- **Entrada**: `[{meal_slot:'lunch', occurred_at:'12:30'}, {meal_slot:'lunch', occurred_at:'12:00'}, {meal_slot:'brunch', occurred_at:'10:00'}]`
- **Saída esperada**: `lunch` ordenado ASC `[12:00, 12:30]`; slot `brunch` cai em `unspecified`.
- **Tipo**: Edge case

### TC-U-009 — `DayNavigator` esconde botões no dia atual (SP-155)
- **Entrada**: `date === todayLocalISO()`.
- **Saída esperada**: "Hoje" não renderizado; "Próximo dia →" não renderizado; "← Dia anterior" presente; date picker `max=today` e `value=today`.
- **Tipo**: Edge case

### TC-U-010 — `DayNavigator` mostra "Próximo dia →" apenas se `nextDate <= today`
- **Entradas**: (a) date=ontem → próximo é hoje → mostra; (b) date=anteontem → próximo é ontem → mostra; (c) date=hoje → esconde.
- **Tipo**: Edge case

### TC-U-011 — `goToPicked` bloqueia futuro client-side (SP-155)
- **Entrada**: `picked = '2026-12-31'` (futuro), `today = '2026-07-30'`.
- **Saída esperada**: `router.push` **não** chamado (early return).
- **Tipo**: Edge case

### TC-U-012 — `ConfirmItemButton` fluxo happy (SP-151)
- **Passos**: render com `itemId='x'`; click; mock `api()` retorna `{ok:true}`.
- **Saída esperada**: state `'confirming'` → `'done'`; `router.refresh()` chamado; component retorna `null`.
- **Tipo**: Happy path

### TC-U-013 — `ConfirmItemButton` falha mantém idle (SP-151)
- **Passos**: mock `api()` retorna `{ok:false}`.
- **Saída esperada**: state volta a `'idle'`; botão permanece.
- **Tipo**: Error case

### TC-U-014 — `ConfirmItemButton.stopPropagation` impede toggle do `<details>`
- **Passos**: click no botão dentro do `<summary>`; verificar `event.preventDefault()` e `event.stopPropagation()` chamados.
- **Tipo**: Edge case

### TC-U-015 — `RefreshOnFocus` mount refresh (RNF)
- **Módulo**: `apps/web/src/app/(app)/day/RefreshOnFocus.tsx`
- **Passos**: render; useEffect no mount.
- **Saída esperada**: `router.refresh()` chamado 1x no mount.

### TC-U-016 — `RefreshOnFocus` debounce visibility (RNF)
- **Passos**: dispatch `visibilitychange` com `visible` duas vezes <2s.
- **Saída esperada**: `router.refresh()` **não** chamado na 2ª (debounce).

---

## Testes de Integração

### TC-I-001 — `/day` renderiza com snapshot completo (SP-150..153)
- **Fluxo**: page server → `GET /days/today` mockado → `DayView` render tree → componentes.
- **Pré-condições**: cookie válido; mock fetch server-side.
- **Passos**: render HTML; selecionar `main`, `h1` (data pt-BR), badge, seções.
- **Resultado esperado**: todos elementos presentes; disclaimer ao final; ordem dos slots correta.

### TC-I-002 — `/day/[date]` 404 (SP-154)
- **Fluxo**: page server → `GET /days/2026-01-01` mockado 404.
- **Resultado esperado**: ErrorPanel "Nenhum registro encontrado nesta data."; link "Voltar para hoje".

### TC-I-003 — `/day/[date]` futuro bloqueado (SP-155)
- **Fluxo**: page server → `compareISO(date, today) > 0` sem fetch.
- **Resultado esperado**: ErrorPanel "Não é possível ver o futuro"; **fetch não chamado**.

### TC-I-004 — `POST /confirm` botão reflui (SP-151)
- **Fluxo**: client `ConfirmItemButton` → `api()` → reload server.
- **Resultado esperado**: badge some após refresh.

### TC-I-005 — `/day/[date]` com `status='open'` mostra botão encerrar (SP-154 revisitado)
- **Passos**: render com data passada; `result.status='open'`.
- **Resultado esperado**: `CloseDayButton` visível; click dispara `router.refresh()` pós-fechamento.

---

## Testes E2E

### TC-E-001 — Jornada /day em desktop (SP-150..154)
- **Persona**: Felix (desktop Chrome).
- **Passos**: logar; navegar `/day`; validar header/data/badge; ver seções; expandir um item; ver micros; ver disclaimer.
- **Resultado esperado**: layout completo; `<details>` expande; formatting pt-BR.

### TC-E-002 — Jornada mobile compacta (SP-150)
- **Passos**: viewport 375px; abrir `/day`.
- **Resultado esperado**: grids colapsam; readable; sem overflow horizontal.

### TC-E-003 — Navegação temporal (SP-155)
- **Passos**: `/day`; click "← Dia anterior"; validar URL `/day/2026-07-29`; click "Hoje"; voltar a `/day`; preencher date picker → "Ir".
- **Resultado esperado**: navegação correta; botões de visibilidade respeitam regras.

### TC-E-004 — Saltar de /weekly → /day/[date] (SP-155)
- **Passos**: `/weekly`; click coluna "Dia" de uma linha; URL fica `/day/<row.date>`.
- **Resultado esperado**: rota válida; snapshot correto.

### TC-E-005 — Confirmar item sem sair do /day (SP-151)
- **Passos**: `/day` com item pendente; click "confirmar"; esperar refresh.
- **Resultado esperado**: badge some; outros elementos permanecem.

### TC-E-006 — Encerrar dia retroativo (SP-154 revisitado)
- **Passos**: `/day/2026-07-28` (passado, status='open'); click "Encerrar dia"; confirmar modal; refresh.
- **Resultado esperado**: status vira `closed`; narrativa aparece.

### TC-E-007 — Não ver futuro (SP-155)
- **Passos**: digitar URL `/day/2099-12-31`.
- **Resultado esperado**: "Não é possível ver o futuro" + link; sem chamada backend.

---

## Testes de Regressão

Casos críticos a manter a cada release do Bloco 6:

- **R-001** (SP-151): ordem dos slots `breakfast → lunch → snack → dinner → unspecified`; slots vazios some.
- **R-002** (SP-152): valores `null/0` renderizam `—`.
- **R-003** (SP-152): `<details>` expande sem JS extra.
- **R-004** (SP-155): "Próximo dia →" escondido no dia atual; futuro bloqueado client/server.
- **R-005** (SP-154): `/day/[date]` 404 amigável; path traversal rejeitado.
- **R-006** (SP-154 revisitado): `allowClose=true` em dia passado `open`.
- **R-007** (INV-5): botão "Encerrar" some em `status='closed'`; `POST /confirm` rejeitado no backend.
- **R-008** (Const. Art. VII §26): disclaimer presente em todas as renderizações.
- **R-009** (RNF-002): `force-dynamic` mantido em ambas rotas.
- **R-010** (RNF-008): `/day` e `/day/:path*` em `PROTECTED_PREFIXES` do `proxy.ts`.
- **R-011** (RNF-006): `addDaysISO` não tem DST drift.
- **R-012** (SP-155): coluna "Dia" do `/weekly` é link.