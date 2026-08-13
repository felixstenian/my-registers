# Casos de Teste — Renderização de assistant messages (Bloco 2)

> **Rastreabilidade**: SP-115..SP-118 · Backend: `apps/api/tests/test_message_formatter.py` (18 casos) · Frontend: [Implementação não localizada] — `apps/web` sem suíte E2E/unitários.

## Cobertura alvo

- **Unitários (backend)**: `_fmt_*`, `_table`, `_daily_totals_table`, `_warnings_block`, `_has_approx_food_items`, `compose_meal`/`water`/`beverage`/`activity`. Já cobertos em `tests/test_message_formatter.py` (parte dos 226 tests do backend).
- **Unitários (frontend)**: `parseBlocks`, `splitRow`, `renderInline`, `isApproxCell`, `isPendingRowLabel`, `DayTotalsBar.collectPendingItems`. [Implementação não localizada] — sem testes JS no `apps/web`.
- **Integração**: intent → `MessageProcessor._handle_registration` → `compose_*` → conteúdo persistido; `POST /confirm` → estado atualizado + audit.
- **E2E**: jornada `/chat` → envio → poll captura assistant → cards renderizados + barra revalida.

---

## Testes Unitários (backend — já existentes)

### TC-U-001 — `_fmt_int` usa ponto de milhar pt-BR (SP-118)
- **Módulo**: `app/services/message_formatter.py`
- **Função**: `_fmt_int(1200)`
- **Saída esperada**: `"1.200"`
- **Tipo**: Happy path — `tests/test_message_formatter.py::test_fmt_int_uses_dot_thousand`

### TC-U-002 — `_fmt_dec` usa vírgula decimal pt-BR (SP-118)
- **Entrada**: `_fmt_dec(46.7, 1)`
- **Saída esperada**: `"46,7"`
- **Tipo**: Happy path — `test_fmt_dec_uses_comma_decimal`

### TC-U-003 — `_fmt_kcal` prefixa `≈` só quando approx (SP-118)
- **Entradas**: `_fmt_kcal(180, True)` → `"≈ 180 kcal"`; `_fmt_kcal(180, False)` → `"180 kcal"`
- **Tipo**: Happy path + edge — `test_fmt_kcal_prefix_only_when_approx`

### TC-U-004 — `_fmt_ml` nunca inclui `≈` (SP-118)
- **Entrada**: `_fmt_ml(500)` (mesmo com `approx=True` no caller)
- **Saída esperada**: `"500 ml"` (sem prefixo)
- **Tipo**: Edge case — `test_fmt_ml_never_approx`

### TC-U-005 — `compose_meal` usa slot pt-BR no título (SP-118)
- **Entrada**: meal com `meal_slot='breakfast'`, 1 item exato.
- **Saída esperada**: tabela "Total da refeição — Café da manhã"; cabeçalho "Registrei o café da manhã."
- **Tipo**: Happy path — `test_compose_meal_uses_meal_slot_pt_br` / `test_compose_meal_breakfast_slot`

### TC-U-006 — `compose_meal` agrega apenas itens da mensagem (SP-118)
- **Entrada**: meal com 3 items (kcal 100+200+300); snapshot diário `kcal_in=2000`.
- **Saída esperada**: tabela "Total da refeição" tem `Calorias | 600 kcal` (não 2000); tabela diária tem 2000.
- **Tipo**: Edge case — `test_compose_meal_aggregates_only_current_items`

### TC-U-007 — `compose_meal` usa `≈` quando item é estimado (SP-118)
- **Entrada**: item com `is_estimate=True`.
- **Saída esperada**: linhas nutricionais começam com `≈ `; água/volume não.
- **Tipo**: Happy path — `test_compose_meal_approx_when_item_is_estimate`

### TC-U-008 — `compose_meal` sem `≈` quando tudo exato (SP-118)
- **Entrada**: item com `is_estimate=False`, `needs_confirmation=False`, sem warnings.
- **Saída esperada**: sem `≈` em nenhuma linha.
- **Tipo**: Happy path — `test_compose_meal_no_approx_when_exact`

### TC-U-009 — `compose_meal` warnings após disclaimer (SP-118)
- **Entrada**: warnings `["needs_confirmation: feijão", "low_confidence_item: sushi ninja"]`.
- **Saída esperada**: bloco "**Confirma estes itens?** — feijão, sushi ninja" depois do disclaimer; dedup mantém ordem.
- **Tipo**: Happy path — `test_compose_meal_warnings_listed_after_disclaimer`

### TC-U-010 — `_daily_totals_table` mostra `Calorias Gastas`/`Saldo` só se `kcal_out>0` (SP-118)
- **Entrada**: snapshot com `kcal_out=0` vs `kcal_out=320`.
- **Saída esperada**: sem kcal_out → sem linhas Gastas/Saldo; com kcal_out→ ambas aparecem + Saldo com sinal.
- **Tipo**: Edge case — `test_compose_meal_daily_shows_kcal_out_only_when_positive` / `..._when_activity_done`

### TC-U-011 — `compose_water` sem `≈` e cabeçalho contextual (SP-118)
- **Entrada**: hydration 500 ml.
- **Saída esperada**: "Registrei 500 ml de água."; tabela "Total do registro" com `Água | 500 ml`; sem macros.
- **Tipo**: Happy path — `test_compose_water_ptbr_header_and_table`

### TC-U-012 — `compose_beverage` com linha `Volume` e `Líquidos Totais*` (SP-118)
- **Entrada**: beverage "café" 300 ml, `other_liquids_ml=300`.
- **Saída esperada**: tabela tem linha `Volume | 300 ml`; tabela diária tem `Líquidos Totais*` + nota.
- **Tipo**: Happy path — `test_compose_beverage_table_with_volume_row`

### TC-U-013 — `compose_beverage` sem `*` quando só água (SP-118)
- **Entrada**: `other_liquids_ml=0`.
- **Saída esperada**: `Líquidos Totais` sem `*` e sem nota.
- **Tipo**: Edge case — `test_compose_beverage_no_star_when_only_water`

### TC-U-014 — `compose_activity` com `Duração` e `Calorias gastas` (SP-118)
- **Entrada**: activity 40 min, 320 kcal.
- **Saída esperada**: tabela "Total do exercício — ..." com `Duração | 40 min` e `Calorias gastas | ≈ 320 kcal`.
- **Tipo**: Happy path — `test_compose_activity_table_with_duration_and_kcal`

### TC-U-015 — `compose_activity` user_manual mostra hint "informado pelo dispositivo" (SP-118)
- **Entrada**: activity `calc_method='user_manual'`.
- **Saída esperada**: cabeçalho contém "(informado pelo dispositivo)"; linhas sem `≈`.
- **Tipo**: Edge case — `test_compose_activity_user_manual_shows_device_hint`

### TC-U-016 — Cabeçalho diário mostra data local pt-BR (SP-118)
- **Entrada**: `log_date=date(2026, 7, 30)`.
- **Saída esperada**: "Total acumulado — 30/07/2026".
- **Tipo**: Happy path — `test_daily_table_header_shows_local_date`

---

## Testes Unitários (frontend — alvo pendente)

> [Implementação não localizada] — adicionar Vitest/RTL para `apps/web`. <!-- TODO: configurar Vitest -->

### TC-U-017 — `parseBlocks` separa tabela de parágrafo
- **Módulo**: `apps/web/src/app/(app)/chat/AssistantContent.tsx`
- **Entrada**: `"**Titulo**\n\n| A | B |\n| --- | --- |\n| 1 | 2 |\n\nTexto."`
- **Saída esperada**: `[{type:'paragraph', text:'**Titulo**'}, {type:'table', rows:[['A','B'],['1','2']]}, {type:'paragraph', text:'Texto.'}]`
- **Tipo**: Happy path

### TC-U-018 — `splitRow` trima e remove bordas `|`
- **Entrada**: `"| Calorias | 180 kcal |"`
- **Saída esperada**: `["Calorias", "180 kcal"]`
- **Tipo**: Happy path

### TC-U-019 — `renderInline` converte `**x**`
- **Entrada**: `"a **b** c"`
- **Saída esperada**: `[<span>a </span>, <strong>b</strong>, <span> c</span>]`
- **Tipo**: Happy path

### TC-U-020 — `isApproxCell` detecta `≈`
- **Entrada**: `"≈ 180 kcal"` → `true`; `"180 kcal"` → `false`
- **Tipo**: Happy path + edge

### TC-U-021 — `isPendingRowLabel` detecta `*` no fim
- **Entrada**: `"Líquidos Totais*"` → `true`; `"*nota"` → `false`; `"Líquidos"` → `false`
- **Tipo**: Edge case

### TC-U-022 — `collectPendingItems` filtra `needs_confirmation`
- **Entrada**: `day.records.food=[{items:[{needs_confirmation:true},{needs_confirmation:false},{needs_confirmation:true}]}]`
- **Saída esperada**: 2 items
- **Tipo**: Happy path

---

## Testes de Integração

### TC-I-001 — Intent → compose → conteúdo persistido (SP-118)
- **Fluxo**: `IntentDispatcher` → `MealService` → `MessageProcessor._handle_registration` → `compose_meal` → `session.add(assistant_message)`.
- **Pré-condições**: usuário autenticado; `local_today` mocked.
- **Passos**: dispatch `log_food` com 3 items; ler assistant message criada.
- **Resultado esperado**: `content` contém 2 tabelas, disclaimer, slot correto no título; nomes dos items aparecem em warnings se `needs_confirmation`.

### TC-I-002 — `POST /records/food-items/{id}/confirm` → estado + audit (SP-117)
- **Fluxo**: route → `CorrectionService` → repo → `audit_events`.
- **Pré-condições**: item `needs_confirmation=True` em dia aberto.
- **Resultado esperado**: 200 `{already_confirmed: false}`; item com `needs_confirmation=False`; `audit_events.action='confirm'`; `DayTotalsBar` revalida e badge some.

### TC-I-003 — `DELETE /records/food-items/{id}` → soft delete + recompute (SP-117)
- **Resultado esperado**: 200 `DeletionOut`; `deleted_at` setado; snapshot recompute do zero (INV-4); audit (INV-10); dia fechado bloqueia (INV-5).

### TC-I-004 — Confirmação idempotente (SP-117)
- **Passos**: chamar `POST /confirm` no mesmo item 2x.
- **Resultado esperado**: 1ª `{already_confirmed:false}`; 2ª `{already_confirmed:true}`.

---

## Testes E2E

### TC-E-001 — Jornada: envio → cards renderizados → barra atualiza (SP-115/116/118)
- **Persona**: Felix (desktop).
- **Passos**:
  1. `/chat` → barra mostra estado vazio (ou totais anteriores).
  2. Enviar "150 g de arroz, 90 g de feijão".
  3. Poll captura assistant message.
  4. Verificar: 2 cards (refeição + acumulado) renderizados com header destacado; disclaimer visível.
  5. Verificar: barra atualiza kcal_in/macros; data pt-BR no título "Total acumulado — ...".
- **Resultado esperado**: fluxo completo, feedback visual correto.

### TC-E-002 — Modal de pendentes completa fluxo (SP-117)
- **Passos**:
  1. Enviar mensagem ambígua que gere `needs_confirmation=true` (ex.: "1 concha de feijão" com catálogo incerto).
  2. Verificar badge "1 item precisa de confirmação" aparece na barra.
  3. Clicar badge; modal abre com item listado.
  4. Clicar "Confirmar".
  5. Verificar: modal fecha se não há mais pendentes; badge desaparece; barra não mostra mais o item.

### TC-E-003 — Descartar item remove da barra (SP-117)
- **Passos**:
  1. Trigger item pendente (como TC-E-002).
  2. Abrir modal; clicar "Descartar".
- **Resultado esperado**: item some; recompute reflete (kcal_in diminui); badge atualiza.

### TC-E-004 — Render mobile colapsa horizontalmente (SP-116)
- **Passos**: viewport 375px → a barra fica rolável horizontalmente; `Cal. in` visível sem scroll lateral inicial.
- **Resultado esperado**: layout responsivo.

---

## Testes de Regressão

Casos críticos a manter a cada release do bloco:

- **R-001** (SP-118): tabelas geradas em ordem correta; disclaimer sempre presente; warnings deduplicados preservando ordem.
- **R-002** (SP-118): `≈` condicional em estimativas; água/volume nunca.
- **R-003** (SP-118): `Calorias Gastas`/`Saldo` só aparecem quando `kcal_out>0`.
- **R-004** (SP-118): `Líquidos Totais*` + nota quando `other_liquids_ml>0`.
- **R-005** (SP-115): parser lê markdown conhecido sem biblioteca externa.
- **R-006** (SP-116): `revalidateKey` dispara re-fetch; estado vazio/`closed` corretos.
- **R-007** (SP-117): confirm idempotente; discard recompute + audit; dia fechado bloqueia (INV-5).
- **R-008** (Const. Art. VII §26): disclaimer em toda assistant message.