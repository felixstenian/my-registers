# Casos de Teste — Edição inline de registros na página `/day`

> **Rastreabilidade**: SP-160..SP-169, INV-14 · Cobertura alvo: 90% em `correction_ops.py` e `nutrient_fact_propagation.py`.
> **Backend tests**: pytest em `apps/api/tests/` com Postgres real (INV-14 — não mockar DB).
> **Frontend tests**: ausentes no MVP (sem Vitest/Playwright em `apps/web`) — casos alvo documentados para futura configuração.

## Cobertura alvo

- **Unitários (backend)**: `correction_ops.apply_*_change` (6 funções puras), `nutrient_fact_propagation.propagate` (resolve itens, decide skip), `DailyRecomputeService` (mock-session).
- **Integração (backend)**: route → service → DB para cada um dos 4 PATCH + propagação.
- **Unitários (frontend alvo)**: `EditFoodItemForm` state machine (dirty/pristine, loading, error, success); `EditWaterForm`/`EditBeverageForm`/`EditActivityForm` similares; Server Actions chamam fetch com cookie.
- **E2E (manual na v1)**: jornadas dos cenários-âncora da spec 002 §2.2 — editar grams, editar kcal do rótulo, editar água/bebida/atividade.

---

## Testes Unitários (backend novos)

### TC-U-001 — `correction_ops.apply_water_change` atualiza volume_ml
- **Módulo**: `apps/api/app/services/correction_ops.py`
- **Função**: `apply_water_change(record, volume_ml=250)`
- **Entrada**: `WaterRecord(volume_ml=500, source='llm')`
- **Saída esperada**: `record.volume_ml == 250`; `.source == 'user_corrected'`; `{changed: {'volume_ml': (500, 250)}, warnings: []}`
- **Tipo**: Happy path

### TC-U-002 — `correction_ops.apply_water_change` sem mudança
- **Entrada**: volume_ml igual ao atual
- **Saída esperada**: `changed={}`, `warnings=[]`
- **Tipo**: Edge case

### TC-U-003 — `correction_ops.apply_beverage_change` recalcula macros via fact
- **Entrada**: `BeverageRecord(volume_ml=200, catalog_ref_id=X)`; fact X has `kcal=50 per_100ml`; novo `volume_ml=400`
- **Saída esperada**: `volume_ml=400`; `kcal=200` (50×4); `protein_g`/`carbs_g` etc atualizados; `source='user_corrected'`
- **Tipo**: Happy path

### TC-U-004 — `correction_ops.apply_beverage_change` sem fact
- **Entrada**: `BeverageRecord(catalog_ref_id=None)`; novo `volume_ml`
- **Saída esperada**: `volume_ml` atualizado; macros untouched; warning `no_catalog_hit`
- **Tipo**: Edge case

### TC-U-005 — `correction_ops.apply_activity_change` recompute via ActivityCalculator
- **Entrada**: `ActivityRecord(activity_type='cardio_run', duration_minutes=40, intensity='moderate')`; novo `duration_minutes=35`; `user.weight_kg=70`; sem `kcal_burned_reported`
- **Saída esperada**: `kcal_burned` recalculado; `calc_method` inalterado (permanece o original)
- **Tipo**: Happy path

### TC-U-006 — `correction_ops.apply_activity_change` sem peso
- **Entrada**: `user.weight_kg=None`; `duration_minutes` mudou
- **Saída esperada**: `kcal_burned` mantém valor anterior; warnings `[{'code':'weight_kg_required_for_kcal'}]`
- **Tipo**: Edge case

### TC-U-007 — `correction_ops.apply_activity_change` kcal_burned explícito
- **Entrada**: `kcal_burned=350` no payload
- **Saída esperada**: `record.kcal_burned=350`; `record.calc_method='user_manual'`; `record.met_value=None`
- **Tipo**: Happy path

### TC-U-008 — `correction_ops.apply_activity_change` intensity inválido
- **Entrada**: `intensity='extreme'`
- **Saída esperada**: Pydantic rejeita antes de chegar; se chegar direto, levanta `ValueError`/deixa inalterado
- **Tipo**: Error case

### TC-U-009 — `nutrient_fact_propagation.propagate` cenário INV-14
- **Módulo**: `apps/api/app/services/nutrient_fact_propagation.py`
- **Setup**: fact F; 3 food_items em 2 dias abertos + 1 food_item em 1 dia fechado + 2 beverage_records (1 open, 1 closed); todos com `catalog_ref_id=F.id`, `deleted_at=NULL`
- **Entrada**: `propagate(session, fact=F, user=U)` após F atualizado
- **Saída esperada**:
  - 3 food_items e 1 beverage em open: macros sobrescritos; `source='user_corrected'`; cada um com audit gravado
  - food_item + beverage em day closed: **não** mutados; listados em `propagation_skipped` com `reason='day_closed'`
  - 2 day_logs abertos: snapshot version incrementa (recompute chamado)
  - day_log fechado: snapshot **não** muda
- **Tipo**: Happy path (cobre INV-14)

### TC-U-010 — `propagate` sem itens referenciando
- **Entrada**: fact F sem nenhum food_item/beverage com `catalog_ref_id=F.id`
- **Saída esperada**: `propagated=[]`, `propagation_skipped=[]`; sem audit; sem recompute
- **Tipo**: Edge case

### TC-U-011 — `propagate` com item deletado (soft delete)
- **Entrada**: food_items com `deleted_at IS NOT NULL` referenciando F
- **Saída esperada**: excluídos da propagação (não entram em `propagated` nem `skipped`)
- **Tipo**: Edge case

### TC-U-012 — `propagate` respeita `user_id` (Art. V §21)
- **Entrada**: fact F; food_item de outro user com `catalog_ref_id=F.id`
- **Saída esperada**: item do outro user **não** é mutado (isolamento); nada em `propagated`/`skipped` que cruje user
- **Tipo**: Error case (isolation)

### TC-U-013 — `propagate` usa fact atualizado (não versão dirty)
- **Entrada**: fact F com `kcal=72` prévio; após SP-162 `F.kcal=98`
- **Saída esperada**: food_item consumido com 100g passa de 72 kcal para 98 kcal (não repetir cálculo com old 72)
- **Tipo**: Happy path

---

## Testes de Integração (backend)

### TC-I-001 — `PATCH /records/food-items/{id}` happy (SP-160, já existe)
- **Fluxo**: client (via Server Action em prod) → PATCH com `grams=220`
- **Pré-condições**: food_item vivos em day aberto, catalog hit
- **Passos**: POST auth → PATCH /records/food-items/{id}
- **Resultado esperado**: 200; food_item.grams=220, kcal recalculado; audit gravado; snapshot version incrementa
- **Teste existe**: `tests/test_log_food_flow.py` ou `test_correction.py` — estender se necessário

### TC-I-002 — `PATCH /records/food-items/{id}` dia closed
- **Resultado esperado**: 409 `conflict_closed_day`; nada mutado

### TC-I-003 — `PATCH /records/food-items/{id}` cross-user
- **Resultado esperado**: 404 `not_found` (filtro `user_id`)

### TC-I-004 — `PATCH /records/water/{id}` happy (SP-164 novo)
- **Resultado esperado**: 200; volume_ml atualizado; source='user_corrected'; audit; recompute
- **Arquivo**: `apps/api/tests/test_patch_water.py` (novo)

### TC-I-005 — `PATCH /records/water/{id}` 404/409/cross-user
- **Resultado esperado**: cobre AC-005

### TC-I-006 — `PATCH /records/beverage/{id}` happy + recompute macros (SP-165)
- **Resultado esperado**: 200; volume_ml e macros atualizados; audit; recompute
- **Arquivo**: `apps/api/tests/test_patch_beverage.py` (novo)

### TC-I-007 — `PATCH /records/activity/{id}` happy + MET recompute (SP-166)
- **Resultado esperado**: 200; kcal_burned recalculado via ActivityCalculator
- **Arquivo**: `apps/api/tests/test_patch_activity.py` (novo)

### TC-I-008 — `PATCH /records/activity/{id}` user_manual path
- **Resultado esperado**: 200; `calc_method='user_manual'`, `met_value=None`

### TC-I-009 — `PATCH /records/activity/{id}` sem peso
- **Resultado esperado**: 200; warning `weight_kg_required_for_kcal`; `kcal_burned` mantém anterior

### TC-I-010 — `PATCH /nutrient-facts/{id}` com propagação (SP-163, INV-14)
- **Fluxo**: POST cria fact + 2 food_items em 2 dias abertos + 1 em dia fechado; PATCH fact.kcal
- **Resultado esperado**: response 200 com `propagated` (3 itens) + `propagation_skipped` (1 item day_closed); 2 snapshots abertos recomputados; dia fechado inalterado; 3 audit gravados (por item propagado)
- **Arquivo**: `apps/api/tests/test_nutrient_fact_propagation.py` (novo)

### TC-I-011 — `PATCH /records/beverage/{id}` sem catalog (warning)
- **Resultado esperado**: 200; volume_ml atualizado; macros intactos; warning `no_catalog_hit`

### TC-I-012 — Refatoração `correction_ops` não regression
- **Fluxo**: rodar toda `tests/test_correction.py` (chat flow)
- **Resultado esperado**: 100% verde — EXTRAIR funções não quebra o fluxo do chat

---

## Testes Unitários (frontend alvo — pendente Vitest)

> [Implementação não localizada] — adicionar Vitest + RTL. <!-- TODO: configurar Vitest em apps/web -->

### TC-U-FE-001 — `EditFoodItemForm` estado inicial
- **Entrada**: `item={grams:150, kcal:250, ...}`, `dayOpen=true`
- **Saída esperada**: inputs com valores atuais; botão "Salvar" `disabled`

### TC-U-FE-002 — `EditFoodItemForm` dirty habilita
- **Entrada**: usuário altera `grams` para 220
- **Saída esperada**: "Salvar" `enabled`

### TC-U-FE-003 — `EditFoodItemForm` loading/spinner
- **Entrada**: click em "Salvar"
- **Saída esperada**: botão com spinner; inputs `disabled` durante o PATCH

### TC-U-FE-004 — `EditFoodItemForm` erro 409
- **Entrada**: mock Server Action retorna `{ok:false, error:'conflict_closed_day'}`
- **Saída esperada**: região `aria-live` exibe "Dia encerrado é imutável"; inputs permanecem editáveis

### TC-U-FE-005 — `EditFoodItemForm` sucesso
- **Entrada**: mock retorna `{ok:true}`
- **Saída esperada**: `<details>` recolhe (ou toast de sucesso); Server Action chama `revalidatePath`

### TC-U-FE-006 — `EditFoodItemForm` fact TBCA não editável
- **Entrada**: `item.has_catalog=true, source='TBCA_2023'`
- **Saída esperada**: inputs per-100g **não** renderizam; mostra "Catálogo canônico — não editável"; inputs de quantidade permitem

### TC-U-FE-007 — `EditFoodItemForm` dia closed
- **Entrada**: `dayOpen=false`
- **Saída esperada**: todos inputs `disabled` + dica

### TC-U-FE-008 — `EditFoodItemForm` cancelar
- **Entrada**: altera `grams` → clica "Cancelar"
- **Saída esperada**: inputs revertem ao estado inicial; `<details>` permanece aberto

### TC-U-FE-009 — `EditActivityForm` select intensity
- **Entrada**: expande; altera `intensity` de `'moderate'` para `'vigorous'`
- **Saída esperada**: botão habilita; PATCH envia `{intensity:'vigorous'}`

### TC-U-FE-010 — Lazy mount do form
- **Entrada**: página com 10 itens; `<details>` de 1 item aberto
- **Saída esperada**: apenas 1 `EditFoodItemForm` montado (9 outros não hidratam JS do form)

---

## Testes E2E (manuais na v1)

### TC-E-001 — Editar quantidade de alimento
- **Persona**: Felix (desktop Chrome)
- **Passos**: logar → `/day` → expandir item → alterar `grams` → "Salvar"
- **Resultado esperado**: totais do dia atualizam; item mostra novo kcal; sem reload manual

### TC-E-002 — Editar kcal do rótulo + propagação
- **Passos**: setup 2 days abertos com mesmo iogurte (fact compartilhado) → editar `kcal` per-100g no `/day` atual
- **Resultado esperado**: ambos os dias com item atualizado; toast/página mostra propagation; se um estiver fechado → `propagation_skipped`

### TC-E-003 — Editar água
- **Passos**: `/day` → expandir em Hidratação → alterar `volume_ml` → salvar
- **Resultado esperado**: Água total atualiza

### TC-E-004 — Editar atividade
- **Passos**: `/day` → expandir em Atividade → alterar `duration_minutes` → salvar
- **Resultado esperado**: Calorias gastas atualizam

### TC-E-005 — Dia encerrado bloqueia
- **Passos**: `/day/[date]` com `status='closed'` → expandir item
- **Resultado esperado**: inputs disabled + dica

### TC-E-006 — Fact canônico não editável
- **Passos**: expandir item com `source='TBCA_2023'`
- **Resultado esperado**: inputs per-100g não aparecem

### TC-E-007 — Cross-day propagation com toast
- **Passos**: editar fact afetando 2 dias abertos (1 atual + 1 ontem)
- **Resultado esperado**: `/day` atual atualiza; toast "Itens de outro dia também atualizados" + link a `/day/2026-08-11`

### TC-E-008 — A11y: foco no primeiro input
- **Passos**: navegar por teclado; expandir linha via Enter
- **Resultado esperado**: foco move ao primeiro input

### TC-E-009 — Aviso legal persiste
- **Passos**: editar qualquer item; observar rodapé
- **Resultado esperado**: `<Disclaimer/>` continua

---

## Testes de Regressão

Casos críticos a cada release desta feature:

- **R-001** (INV-14): propagação recalcula todos os itens vivos em dias abertos; pula em closed.
- **R-002** (INV-5): PATCH em dia closed → 409 em todos os 4 tipos.
- **R-003** (INV-4): `DailyRecomputeService.recompute` chamado ao fim de cada PATCH com mudança real.
- **R-004** (INV-10): audit gravado antes do commit em toda mutação (incluindo propagação por item).
- **R-005** (INV-1, Art. II): nenhuma soma via LLM — `NutritionCalculator`/`ActivityCalculator` exclusivos.
- **R-006** (Art. V §21): PATCH cross-user retorna 404.
- **R-007** (SP-74/INV-10): audit `action='correct'` com `actor='user'` via REST; `actor='llm'` via chat unchanged.
- **R-008** (Art. VII §26): disclaimer permanece na UI pós-edição.
- **R-009** (SP-72 chat): `CorrectionService` do chat continua 100% verde após refactor `correction_ops`.
- **R-010** (SP-33): `PATCH /nutrient-facts/{id}` sem `promote_food_item_id` continua funcionando (sem regression).
- **R-011**: `pnpm --filter web verify:sw` verde pós-build (INV-11 — SW não afetado).
- **R-012**: `uv run ruff check` + `uv run mypy app` + `uv run pytest` verde no CI.